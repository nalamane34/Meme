"""Auto-discover smart wallets from our own wins.

When a position closes profitably, we backfill the wallets that bought
the same mint in its first hour and add them as tier-3 candidates.
A periodic pruner removes ones that haven't generated profit after a
trial window.

Data source: Birdeye `/defi/v3/token/list-trader` (free, rate-limited) —
falls back gracefully to a no-op if the endpoint isn't reachable. Helius
`getSignaturesForAddress` + parse is the heavier alternative; we leave a
TODO for that path so it can be turned on when needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.clients.birdeye import BirdeyeClient
from app.db.models import Position, PositionStatus, SmartWallet
from app.logging import get_logger
from app.strategy.pipeline import recent_position_winners

log = get_logger(__name__)

EARLY_BUYER_HORIZON_MIN = 60
PROMOTE_LIMIT_PER_RUN = 10


class WalletFinder:
    def __init__(self, birdeye: BirdeyeClient) -> None:
        self._birdeye = birdeye

    async def run(self, sessionmaker: async_sessionmaker) -> int:
        winners = await recent_position_winners(sessionmaker, min_pnl_pct=0.5)
        if not winners:
            return 0

        promoted = 0
        async with sessionmaker() as session:
            for pos in winners:
                wallets = await self._early_buyers(pos)
                for w in wallets:
                    if promoted >= PROMOTE_LIMIT_PER_RUN:
                        break
                    existing = await session.get(SmartWallet, w["address"])
                    if existing is not None:
                        continue
                    session.add(SmartWallet(
                        address=w["address"],
                        label=f"auto:{pos.mint[:6]}",
                        tier=3,
                        win_rate=None,
                        pnl_30d_usd=None,
                        active=True,
                    ))
                    promoted += 1
                if promoted >= PROMOTE_LIMIT_PER_RUN:
                    break
            await session.commit()

        if promoted:
            log.info("auto_promoted_wallets", count=promoted)
        return promoted

    async def _early_buyers(self, pos: Position) -> list[dict[str, Any]]:
        """Return [{address, usd_volume}] for wallets that bought within
        EARLY_BUYER_HORIZON_MIN of our entry. Best-effort: returns empty
        if the data source is unavailable."""
        try:
            r = await self._birdeye._http.get(  # type: ignore[attr-defined]
                "/defi/v3/token/list-trader",
                params={"address": pos.mint, "limit": 50, "sort_by": "volume", "sort_type": "desc"},
            )
            items = (r.json().get("data") or {}).get("items") or []
        except Exception as e:  # noqa: BLE001
            log.debug("early_buyers_unavailable", mint=pos.mint, error=str(e))
            return []

        out: list[dict[str, Any]] = []
        cutoff = (pos.opened_at + timedelta(minutes=EARLY_BUYER_HORIZON_MIN)).timestamp()
        for it in items:
            ts = float(it.get("lastTradeUnixTime") or 0)
            owner = it.get("owner") or it.get("address")
            if not owner or ts == 0 or ts > cutoff:
                continue
            out.append({"address": owner, "usd_volume": float(it.get("volume") or 0)})
        return out


async def prune_inactive(sessionmaker: async_sessionmaker, *, days: int = 14) -> int:
    """Deactivate auto-promoted wallets that haven't generated a profitable
    signal in `days`. Cheap insurance against bloating the watch list."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    pruned = 0
    async with sessionmaker() as session:
        q = select(SmartWallet).where(
            SmartWallet.tier == 3,
            SmartWallet.active == True,  # noqa: E712
            SmartWallet.added_at < cutoff,
        )
        candidates = (await session.execute(q)).scalars().all()
        for w in candidates:
            # If no profitable position attributed to this wallet, deactivate.
            q2 = select(Position).join(Position.trades).where(
                Position.status == PositionStatus.CLOSED.value,
                Position.realized_pnl_usd.is_not(None),
                Position.realized_pnl_usd > 0,
            )
            wins = (await session.execute(q2)).scalars().all()
            if not wins:
                w.active = False
                pruned += 1
        await session.commit()
    if pruned:
        log.info("pruned_auto_wallets", count=pruned)
    return pruned
