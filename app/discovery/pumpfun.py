"""pump.fun discovery.

Most Solana meme launches start on pump.fun's bonding curve. The 0.1% that
graduate to Raydium are where the big runs happen — and the first wallets
that bought near launch are reliably profitable.

Free data sources (community-maintained — these can change):
  - https://frontend-api.pump.fun/coins?sort=created_timestamp&order=DESC
      Recent launches.
  - https://frontend-api.pump.fun/coins?sort=market_cap&order=DESC&offset=0&limit=50
      Top-by-mcap, used to find tokens about to graduate (mcap > ~$69k).

We focus on the "about to graduate" cohort: if a token is ~80%+ of the way
through the bonding curve with steady volume, it's a high-conviction
candidate. Pre-graduation sniping is also valuable but much riskier.
"""

from __future__ import annotations

from typing import Any

from app.clients.http import HTTPClient
from app.logging import get_logger
from app.strategy.pipeline import Candidate

log = get_logger(__name__)

PUMPFUN_API = "https://frontend-api.pump.fun"

# Pump.fun bonding curves graduate at ~$69k market cap. Anything in
# (NEAR_GRAD_MIN, GRAD_THRESHOLD) is "about to migrate" — high-EV window.
GRAD_THRESHOLD_USD = 69_000
NEAR_GRAD_MIN_USD = 55_000


class PumpFunDiscovery:
    def __init__(self) -> None:
        self._http = HTTPClient(base_url=PUMPFUN_API, timeout=10.0)

    async def near_graduation(self, limit: int = 50) -> list[Candidate]:
        items = await self._coins(sort="market_cap", order="DESC", limit=limit)
        out: list[Candidate] = []
        for c in items:
            mcap = float(c.get("usd_market_cap") or 0)
            if NEAR_GRAD_MIN_USD <= mcap <= GRAD_THRESHOLD_USD and not c.get("complete"):
                mint = c.get("mint")
                if not mint:
                    continue
                out.append(Candidate(
                    source="discovery_pumpfun_near_grad",
                    mint=mint,
                    raw={k: c.get(k) for k in ("mint", "name", "symbol", "usd_market_cap", "complete")},
                ))
        return out

    async def just_graduated(self, limit: int = 50) -> list[Candidate]:
        """Tokens that just migrated to Raydium — first 30m post-grad is
        often the rip leg."""
        items = await self._coins(sort="last_trade_timestamp", order="DESC", limit=limit)
        out: list[Candidate] = []
        for c in items:
            if not c.get("complete"):
                continue
            mint = c.get("mint")
            if not mint:
                continue
            out.append(Candidate(
                source="discovery_pumpfun_graduated",
                mint=mint,
                raw={k: c.get(k) for k in ("mint", "name", "symbol", "usd_market_cap")},
            ))
        return out

    async def _coins(self, sort: str, order: str, limit: int) -> list[dict[str, Any]]:
        try:
            r = await self._http.get(
                "/coins",
                params={"sort": sort, "order": order, "limit": limit, "offset": 0},
            )
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception as e:  # noqa: BLE001
            log.warning("pumpfun_fetch_failed", error=str(e))
            return []

    async def aclose(self) -> None:
        await self._http.aclose()
