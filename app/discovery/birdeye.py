"""Birdeye trending discovery.

Endpoints used (free tier with key):
  /defi/token_trending?sort_by=rank&sort_type=asc&offset=0&limit=20
  /defi/v2/tokens/new_listing

The trending list is the closest free-tier proxy for "this token's volume
is exploding right now" — exactly what we want to feed the policy.
"""

from __future__ import annotations

from app.clients.birdeye import BirdeyeClient
from app.logging import get_logger
from app.strategy.pipeline import Candidate

log = get_logger(__name__)


class BirdeyeDiscovery:
    def __init__(self, client: BirdeyeClient | None = None) -> None:
        self._client = client or BirdeyeClient()
        self._owns_client = client is None

    async def trending(self, limit: int = 20) -> list[Candidate]:
        try:
            r = await self._client._http.get(  # type: ignore[attr-defined]
                "/defi/token_trending",
                params={"sort_by": "rank", "sort_type": "asc", "offset": 0, "limit": limit},
            )
            items = (r.json().get("data") or {}).get("tokens") or []
        except Exception as e:  # noqa: BLE001
            log.warning("birdeye_trending_failed", error=str(e))
            return []

        out: list[Candidate] = []
        for it in items:
            mint = it.get("address")
            if not mint:
                continue
            out.append(Candidate(
                source="discovery_birdeye_trending",
                mint=mint,
                raw={k: it.get(k) for k in ("rank", "symbol", "name", "liquidity", "volume24hUSD")},
            ))
        return out

    async def new_listings(self, limit: int = 20) -> list[Candidate]:
        try:
            r = await self._client._http.get(  # type: ignore[attr-defined]
                "/defi/v2/tokens/new_listing", params={"limit": limit}
            )
            items = (r.json().get("data") or {}).get("items") or []
        except Exception as e:  # noqa: BLE001
            log.warning("birdeye_new_listings_failed", error=str(e))
            return []

        out: list[Candidate] = []
        for it in items:
            mint = it.get("address")
            if not mint:
                continue
            out.append(Candidate(
                source="discovery_birdeye_new",
                mint=mint,
                raw={k: it.get(k) for k in ("symbol", "name", "liquidityAddedAt")},
            ))
        return out

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
