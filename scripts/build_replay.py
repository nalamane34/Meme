"""Build the offline RL replay dataset from logged signals.

For each `signals` row that produced (or *could have* produced) a buy
decision, we:

  1. Snapshot the historical price from Birdeye N minutes after the signal.
  2. Apply the same stop-loss / take-profit / trailing-stop rules used live
     to compute the outcome %.
  3. Emit one parquet row: features + outcome_pct + mint.

Usage:
    python scripts/build_replay.py --out data/replay.parquet --horizon-min 240
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clients.birdeye import BirdeyeClient
from app.config import get_settings
from app.db.models import Signal


def _simulate_outcome(prices: list[float], stop_loss: float, take_profit: float, trail: float) -> float:
    if not prices:
        return 0.0
    entry = prices[0]
    peak = entry
    for p in prices[1:]:
        peak = max(peak, p)
        if p <= entry * (1 - stop_loss):
            return (p / entry) - 1.0
        if p >= entry * (1 + take_profit):
            return (p / entry) - 1.0
        if p <= peak * (1 - trail):
            return (p / entry) - 1.0
    return (prices[-1] / entry) - 1.0


async def run(out_path: str, horizon_min: int) -> None:
    s = get_settings()
    engine = create_async_engine(s.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    birdeye = BirdeyeClient()

    rows: list[dict] = []
    async with Session() as session:
        q = select(Signal).where(Signal.features.is_not(None), Signal.side == "buy")
        signals = (await session.execute(q)).scalars().all()
        for sig in signals:
            ts_from = int(sig.received_at.timestamp())
            ts_to = int((sig.received_at + timedelta(minutes=horizon_min)).timestamp())
            history = await birdeye.history_price(sig.mint, ts_from, ts_to)
            prices = [float(h.get("value") or 0) for h in history if h.get("value")]
            outcome = _simulate_outcome(prices, s.stop_loss_pct, s.take_profit_pct, s.trailing_stop_pct)

            meta = sig.features or {}
            # Re-derive numeric vector from `meta` keys used in features.py
            # (kept stable). Order MUST match FEATURE_DIM layout there.
            from math import log1p
            import numpy as np
            f = [
                log1p(meta.get("age_min", 0)),
                log1p(meta.get("liquidity_usd", 0)),
                log1p(meta.get("fdv_usd", 0)),
                log1p(meta.get("vol_5m_usd", 0)),
                log1p(meta.get("vol_1h_usd", 0)),
                meta.get("price_change_5m", 0),
                meta.get("price_change_1h", 0),
                meta.get("buy_ratio", 0.5),
                meta.get("smart_wallets_1h", 0),
                float(np.sign(meta.get("smart_buy_pressure_usd", 0)) * np.log1p(abs(meta.get("smart_buy_pressure_usd", 0)))),
                (meta.get("rugcheck_score") or 50) / 100.0,
                log1p(meta.get("holders", 0)),
                log1p(meta.get("signal_amount_usd") or 0),
            ]
            row = {f"f{i}": v for i, v in enumerate(f)}
            row["mint"] = sig.mint
            row["outcome_pct"] = outcome
            rows.append(row)

    df = pd.DataFrame(rows)
    df.to_parquet(out_path, index=False)
    print(f"wrote {len(df)} rows to {out_path}")
    await birdeye.aclose()
    await engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/replay.parquet")
    p.add_argument("--horizon-min", type=int, default=240)
    args = p.parse_args()
    asyncio.run(run(args.out, args.horizon_min))
