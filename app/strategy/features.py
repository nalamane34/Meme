"""Build the RL state vector for a candidate trade.

Keep this deterministic and side-effect free: it's called from both the
live path (decision-time) and the offline trainer (replay). Anything that
needs IO goes through the passed-in clients.

State vector layout (kept stable — append-only, never reorder):

    0  age_minutes_log         log1p(minutes since token first seen)
    1  liquidity_usd_log       log1p(USD)
    2  fdv_usd_log             log1p(FDV in USD)
    3  vol_5m_usd_log          log1p(5-minute USD volume)
    4  vol_1h_usd_log          log1p(1-hour USD volume)
    5  price_change_5m         fraction (e.g. 0.12 = +12%)
    6  price_change_1h         fraction
    7  txns_5m_buy_ratio       buys / (buys+sells) over 5m, 0.5 default
    8  smart_wallet_count      number of *watched* wallets in this token in the last hour
    9  smart_buy_pressure      net (buys-sells) usd from watched wallets in 1h, signed log1p
   10  rugcheck_score_norm     rugcheck score / 100, clipped
   11  holder_count_log        log1p(holders)
   12  signal_amount_usd_log   log1p(this signal's USD size)
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import log1p
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.birdeye import BirdeyeClient
from app.clients.dexscreener import DexScreenerClient
from app.db.models import Signal, Token

FEATURE_DIM = 13


@dataclass
class FeatureSnapshot:
    vector: np.ndarray
    meta: dict[str, Any]  # human-readable values for logging/debugging


def _signed_log1p(x: float) -> float:
    return float(np.sign(x) * np.log1p(abs(x)))


async def build_features(
    *,
    session: AsyncSession,
    mint: str,
    signal_amount_usd: float | None,
    birdeye: BirdeyeClient,
    dexscreener: DexScreenerClient,
    rugcheck_score: int | None,
) -> FeatureSnapshot:
    now = datetime.utcnow()

    token = await session.get(Token, mint)
    first_seen = token.first_seen_at if token else now
    age_min = max(0.0, (now - first_seen).total_seconds() / 60.0)

    overview = await birdeye.token_overview(mint) or {}
    pair = await dexscreener.best_pair(mint) or {}

    liquidity_usd = float((pair.get("liquidity") or {}).get("usd") or overview.get("liquidity") or 0)
    fdv_usd = float(pair.get("fdv") or overview.get("fdv") or 0)
    vol_5m_usd = float((pair.get("volume") or {}).get("m5") or 0)
    vol_1h_usd = float((pair.get("volume") or {}).get("h1") or 0)
    price_change_5m = float((pair.get("priceChange") or {}).get("m5") or 0) / 100.0
    price_change_1h = float((pair.get("priceChange") or {}).get("h1") or 0) / 100.0

    txns_5m = pair.get("txns", {}).get("m5") or {}
    buys = float(txns_5m.get("buys") or 0)
    sells = float(txns_5m.get("sells") or 0)
    buy_ratio = buys / (buys + sells) if (buys + sells) > 0 else 0.5

    holders = int(overview.get("holder") or overview.get("holders") or 0)

    # Smart-wallet activity in the last hour for this mint
    one_hour_ago = now - timedelta(hours=1)
    q = select(Signal).where(Signal.mint == mint, Signal.received_at >= one_hour_ago)
    recent_signals = (await session.execute(q)).scalars().all()
    wallets_seen = {s.wallet for s in recent_signals if s.wallet}
    buy_pressure = sum(
        (s.amount_usd or 0) * (1 if s.side == "buy" else -1) for s in recent_signals
    )

    rc_norm = float(rugcheck_score) / 100.0 if rugcheck_score is not None else 0.5

    vec = np.array(
        [
            log1p(age_min),
            log1p(liquidity_usd),
            log1p(fdv_usd),
            log1p(vol_5m_usd),
            log1p(vol_1h_usd),
            price_change_5m,
            price_change_1h,
            buy_ratio,
            float(len(wallets_seen)),
            _signed_log1p(buy_pressure),
            min(max(rc_norm, 0.0), 1.0),
            log1p(holders),
            log1p(signal_amount_usd or 0.0),
        ],
        dtype=np.float32,
    )
    assert vec.shape == (FEATURE_DIM,)

    return FeatureSnapshot(
        vector=vec,
        meta={
            "age_min": age_min,
            "liquidity_usd": liquidity_usd,
            "fdv_usd": fdv_usd,
            "vol_5m_usd": vol_5m_usd,
            "vol_1h_usd": vol_1h_usd,
            "price_change_5m": price_change_5m,
            "price_change_1h": price_change_1h,
            "buy_ratio": buy_ratio,
            "smart_wallets_1h": len(wallets_seen),
            "smart_buy_pressure_usd": buy_pressure,
            "rugcheck_score": rugcheck_score,
            "holders": holders,
            "signal_amount_usd": signal_amount_usd,
        },
    )
