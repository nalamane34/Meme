"""Shared candidate processing pipeline.

Both the Helius webhook (smart-wallet copy signal) and the discovery
scanners (autonomous trending detection) funnel into this same code path:

    candidate → dedupe → safety gate → features → policy → trade → log

Keeping it in one place means the RL agent always sees the same shape of
state vector regardless of where the candidate came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import redis.asyncio as redis_async
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.birdeye import BirdeyeClient
from app.clients.dexscreener import DexScreenerClient
from app.clients.rugcheck import RugCheckClient
from app.db.models import Position, PositionStatus, Signal, Token
from app.executor.trader import Trader
from app.logging import get_logger
from app.strategy.features import build_features
from app.strategy.policy import ACTION_SKIP, Policy
from app.strategy.safety import assess

log = get_logger(__name__)

DEDUPE_WINDOW_MIN = 30  # don't process the same mint from the same source twice in 30m


@dataclass
class Candidate:
    source: str                          # "helius_webhook" | "discovery_dexscreener" | ...
    mint: str
    side: str = "buy"                    # discovery is always "buy" (entry candidate)
    wallet: str | None = None
    amount_usd: float | None = None
    tx_sig: str | None = None
    raw: dict[str, Any] | None = None


async def _is_duplicate(session: AsyncSession, redis: redis_async.Redis, c: Candidate) -> bool:
    key = f"dedupe:{c.source}:{c.mint}"
    if await redis.set(key, "1", ex=DEDUPE_WINDOW_MIN * 60, nx=True) is None:
        return True
    return False


async def _has_open_position(session: AsyncSession, mint: str) -> bool:
    q = select(Position).where(
        Position.mint == mint,
        Position.status == PositionStatus.OPEN.value,
    )
    return (await session.execute(q)).scalar_one_or_none() is not None


async def process_candidate(
    candidate: Candidate,
    *,
    sessionmaker: async_sessionmaker,
    redis: redis_async.Redis,
    rugcheck: RugCheckClient,
    birdeye: BirdeyeClient,
    dexscreener: DexScreenerClient,
    policy: Policy,
    trader: Trader,
) -> None:
    async with sessionmaker() as session:
        if await _is_duplicate(session, redis, candidate):
            return
        if await _has_open_position(session, candidate.mint):
            log.debug("already_open", mint=candidate.mint, source=candidate.source)
            return

        token = await session.get(Token, candidate.mint)
        if token is None:
            token = Token(mint=candidate.mint)
            session.add(token)
            await session.commit()
        elif token.blacklisted:
            log.debug("blacklisted_token", mint=candidate.mint)
            return

        # Smart-wallet sells from the webhook source: log and bail; entries
        # only — never auto-mirror sells (positions exit via the watcher).
        if candidate.side == "sell":
            session.add(Signal(
                source=candidate.source,
                wallet=candidate.wallet,
                mint=candidate.mint,
                side="sell",
                amount_usd=candidate.amount_usd,
                tx_sig=candidate.tx_sig,
                raw=candidate.raw or {},
                decision="observe_sell",
                decision_reason="watched_wallet_sold",
            ))
            await session.commit()
            return

        verdict = await assess(candidate.mint, rugcheck, dexscreener)
        token.rugcheck_score = verdict.score
        token.rugcheck_payload = verdict.rugcheck

        if not verdict.safe:
            session.add(Signal(
                source=candidate.source,
                wallet=candidate.wallet,
                mint=candidate.mint,
                side="buy",
                amount_usd=candidate.amount_usd,
                tx_sig=candidate.tx_sig,
                raw=candidate.raw or {},
                decision="skip",
                decision_reason="unsafe:" + ",".join(verdict.reasons)[:220],
            ))
            token.blacklisted = token.blacklisted or any("critical_risk" in r for r in verdict.reasons)
            await session.commit()
            return

        snapshot = await build_features(
            session=session,
            mint=candidate.mint,
            signal_amount_usd=candidate.amount_usd,
            birdeye=birdeye,
            dexscreener=dexscreener,
            rugcheck_score=verdict.score,
        )
        decision = policy.decide(snapshot)

        signal = Signal(
            source=candidate.source,
            wallet=candidate.wallet,
            mint=candidate.mint,
            side="buy",
            amount_usd=candidate.amount_usd,
            tx_sig=candidate.tx_sig,
            raw=candidate.raw or {},
            features=snapshot.meta,
            decision=("buy" if decision.action != ACTION_SKIP else "skip"),
            decision_reason=decision.reason,
        )
        session.add(signal)
        await session.commit()

        if decision.action == ACTION_SKIP:
            return

        await trader.buy(
            session=session,
            mint=candidate.mint,
            size_multiplier=decision.size_multiplier,
            entry_signal_id=signal.id,
        )


async def recent_position_winners(
    sessionmaker: async_sessionmaker,
    *,
    min_pnl_pct: float = 0.5,
    window: timedelta = timedelta(days=7),
) -> list[Position]:
    """Used by the wallet-finder to identify which positions are worth
    mining for co-buyers."""
    cutoff = datetime.utcnow() - window
    async with sessionmaker() as session:
        q = select(Position).where(
            Position.status == PositionStatus.CLOSED.value,
            Position.closed_at >= cutoff,
            Position.realized_pnl_usd.is_not(None),
        )
        rows = (await session.execute(q)).scalars().all()
        return [
            r for r in rows
            if r.entry_amount_usd and (r.realized_pnl_usd / r.entry_amount_usd) >= min_pnl_pct
        ]
