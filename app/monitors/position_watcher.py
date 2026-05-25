"""Background loop that polls open positions and exits them on:
    - stop loss        (entry * (1 - STOP_LOSS_PCT) hit)
    - take profit      (entry * (1 + TAKE_PROFIT_PCT) hit)
    - trailing stop    (peak  * (1 - TRAILING_STOP_PCT) hit)

This intentionally lives OUTSIDE the RL policy. The agent decides entries.
Exits are deterministic — that's the cheapest way to bound the loss the
agent can cause us.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.clients.birdeye import BirdeyeClient
from app.config import get_settings
from app.db.models import Position, PositionStatus
from app.executor.trader import Trader
from app.logging import get_logger

log = get_logger(__name__)


async def watch_loop(
    *,
    sessionmaker: async_sessionmaker,
    trader: Trader,
    birdeye: BirdeyeClient,
    interval_sec: float = 5.0,
) -> None:
    s = get_settings()
    while True:
        try:
            async with sessionmaker() as session:
                q = select(Position).where(Position.status == PositionStatus.OPEN.value)
                positions = (await session.execute(q)).scalars().all()

                for pos in positions:
                    price = await birdeye.price(pos.mint)
                    if price is None:
                        continue

                    if price > pos.peak_price_usd:
                        pos.peak_price_usd = price
                        await session.commit()

                    if price <= pos.entry_price_usd * (1 - s.stop_loss_pct):
                        await trader.sell(session=session, position=pos, reason="stop_loss")
                        continue
                    if price >= pos.entry_price_usd * (1 + s.take_profit_pct):
                        await trader.sell(session=session, position=pos, reason="take_profit")
                        continue
                    if price <= pos.peak_price_usd * (1 - s.trailing_stop_pct):
                        await trader.sell(session=session, position=pos, reason="trailing_stop")
                        continue

        except Exception as e:  # noqa: BLE001
            log.error("position_watcher_error", error=str(e))

        await asyncio.sleep(interval_sec)
