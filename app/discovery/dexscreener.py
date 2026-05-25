"""DexScreener-driven discovery.

Two free public endpoints:
  - /token-boosts/latest/v1  -> tokens whose owners just paid for a boost
  - /token-boosts/top/v1     -> all-time-top-boosted tokens
Both are heavily abused by paid promo, so we use them only as a *candidate
funnel* — the safety gate and policy filter the noise.

We also scan /token-profiles/latest/v1 for fresh listings.

All Solana-only.
"""

from __future__ import annotations

from typing import Any

from app.clients.http import HTTPClient
from app.config import get_settings
from app.logging import get_logger
from app.strategy.pipeline import Candidate

log = get_logger(__name__)


class DexScreenerDiscovery:
    def __init__(self) -> None:
        s = get_settings()
        self._http = HTTPClient(base_url=s.dexscreener_base_url)

    async def latest_boosts(self) -> list[Candidate]:
        return await self._fetch("/token-boosts/latest/v1", "discovery_dex_boosts_latest")

    async def top_boosts(self) -> list[Candidate]:
        return await self._fetch("/token-boosts/top/v1", "discovery_dex_boosts_top")

    async def latest_profiles(self) -> list[Candidate]:
        return await self._fetch("/token-profiles/latest/v1", "discovery_dex_profiles_latest")

    async def _fetch(self, path: str, source: str) -> list[Candidate]:
        try:
            r = await self._http.get(path)
            items = r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("dexscreener_discovery_failed", path=path, error=str(e))
            return []
        if not isinstance(items, list):
            return []
        out: list[Candidate] = []
        for item in items:
            if (item.get("chainId") or "").lower() != "solana":
                continue
            mint = item.get("tokenAddress")
            if not mint:
                continue
            out.append(Candidate(
                source=source,
                mint=mint,
                raw={k: item.get(k) for k in ("chainId", "tokenAddress", "url", "description")},
            ))
        return out

    async def aclose(self) -> None:
        await self._http.aclose()
