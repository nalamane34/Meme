"""Smoke test for the shared discovery/webhook pipeline.

Uses an in-memory SQLite DB and fake clients so we can exercise the full
candidate→safety→features→policy→trade path without network or wallet.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, Position, PositionStatus, Signal
from app.strategy.pipeline import Candidate, process_candidate


class FakeRedis:
    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    async def set(self, k, v, ex=None, nx=False):
        if nx and k in self._d:
            return None
        self._d[k] = v
        return True

    async def get(self, k):
        return self._d.get(k)

    async def delete(self, k):
        self._d.pop(k, None)


@dataclass
class FakeVerdict:
    safe: bool
    score: int | None
    reasons: list[str]
    liquidity_usd: float | None
    rugcheck: dict | None


@pytest.fixture
async def engine_and_sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    yield engine, sm
    await engine.dispose()


@pytest.fixture
def fake_policy():
    from app.strategy.policy import ACTION_BUY_FULL, Decision

    class P:
        def decide(self, snapshot):
            return Decision(ACTION_BUY_FULL, 1.0, "test_force_buy")

    return P()


@pytest.fixture
def skip_policy():
    from app.strategy.policy import ACTION_SKIP, Decision

    class P:
        def decide(self, snapshot):
            return Decision(ACTION_SKIP, 0.0, "test_force_skip")

    return P()


def _fake_features():
    from app.strategy.features import FEATURE_DIM, FeatureSnapshot
    import numpy as np

    return FeatureSnapshot(
        vector=np.zeros(FEATURE_DIM, dtype=np.float32),
        meta={"liquidity_usd": 80_000, "smart_wallets_1h": 0},
    )


async def _fake_build_features(**kwargs):
    return _fake_features()


@pytest.mark.asyncio
async def test_unsafe_candidate_is_skipped(engine_and_sessionmaker, fake_policy, monkeypatch):
    _, sm = engine_and_sessionmaker
    redis = FakeRedis()

    rugcheck = AsyncMock()
    birdeye = AsyncMock()
    dex = AsyncMock()

    async def unsafe_assess(*a, **k):
        return FakeVerdict(False, 90, ["liquidity_$0<min_$15000"], 0, None)

    monkeypatch.setattr("app.strategy.pipeline.assess", unsafe_assess)
    monkeypatch.setattr("app.strategy.pipeline.build_features", _fake_build_features)

    trader = AsyncMock()
    trader.buy = AsyncMock()

    candidate = Candidate(source="discovery_birdeye_trending", mint="M1")
    await process_candidate(
        candidate, sessionmaker=sm, redis=redis, rugcheck=rugcheck,
        birdeye=birdeye, dexscreener=dex, policy=fake_policy, trader=trader,
    )

    trader.buy.assert_not_called()
    async with sm() as s:
        from sqlalchemy import select
        sigs = (await s.execute(select(Signal))).scalars().all()
        assert len(sigs) == 1
        assert sigs[0].decision == "skip"
        assert "unsafe" in (sigs[0].decision_reason or "")


@pytest.mark.asyncio
async def test_safe_candidate_triggers_buy(engine_and_sessionmaker, fake_policy, monkeypatch):
    _, sm = engine_and_sessionmaker
    redis = FakeRedis()

    async def safe_assess(*a, **k):
        return FakeVerdict(True, 20, [], 80_000, {"score": 20})

    monkeypatch.setattr("app.strategy.pipeline.assess", safe_assess)
    monkeypatch.setattr("app.strategy.pipeline.build_features", _fake_build_features)

    trader = AsyncMock()
    trader.buy = AsyncMock(return_value=None)

    candidate = Candidate(source="discovery_dex_boosts_latest", mint="M2")
    await process_candidate(
        candidate, sessionmaker=sm, redis=redis, rugcheck=AsyncMock(),
        birdeye=AsyncMock(), dexscreener=AsyncMock(), policy=fake_policy, trader=trader,
    )

    trader.buy.assert_called_once()
    kwargs = trader.buy.call_args.kwargs
    assert kwargs["mint"] == "M2"
    assert kwargs["size_multiplier"] == 1.0


@pytest.mark.asyncio
async def test_dedupe_within_window(engine_and_sessionmaker, fake_policy, monkeypatch):
    _, sm = engine_and_sessionmaker
    redis = FakeRedis()

    async def safe_assess(*a, **k):
        return FakeVerdict(True, 20, [], 80_000, {})

    monkeypatch.setattr("app.strategy.pipeline.assess", safe_assess)
    monkeypatch.setattr("app.strategy.pipeline.build_features", _fake_build_features)

    trader = AsyncMock()
    trader.buy = AsyncMock(return_value=None)

    candidate = Candidate(source="discovery_birdeye_trending", mint="M3")
    args = dict(
        sessionmaker=sm, redis=redis, rugcheck=AsyncMock(),
        birdeye=AsyncMock(), dexscreener=AsyncMock(), policy=fake_policy, trader=trader,
    )
    await process_candidate(candidate, **args)
    await process_candidate(candidate, **args)  # should be deduped

    assert trader.buy.call_count == 1


@pytest.mark.asyncio
async def test_open_position_blocks_new_buy(engine_and_sessionmaker, fake_policy, monkeypatch):
    _, sm = engine_and_sessionmaker
    redis = FakeRedis()

    # Pre-create an open position on the same mint.
    async with sm() as session:
        session.add(Position(
            mint="M4",
            status=PositionStatus.OPEN.value,
            entry_price_usd=1.0,
            entry_amount_usd=50,
            entry_amount_tokens=50,
            peak_price_usd=1.0,
            opened_at=datetime.utcnow(),
        ))
        await session.commit()

    async def safe_assess(*a, **k):
        return FakeVerdict(True, 20, [], 80_000, {})

    monkeypatch.setattr("app.strategy.pipeline.assess", safe_assess)
    monkeypatch.setattr("app.strategy.pipeline.build_features", _fake_build_features)

    trader = AsyncMock()
    trader.buy = AsyncMock(return_value=None)

    await process_candidate(
        Candidate(source="discovery_birdeye_trending", mint="M4"),
        sessionmaker=sm, redis=redis, rugcheck=AsyncMock(),
        birdeye=AsyncMock(), dexscreener=AsyncMock(), policy=fake_policy, trader=trader,
    )
    trader.buy.assert_not_called()
