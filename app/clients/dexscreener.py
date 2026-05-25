"""DexScreener free API client.

Docs: https://docs.dexscreener.com/api/reference

No key required. Good for cross-checking Birdeye price + getting
liquidity / 24h volume per pair.
"""

from typing import Any

from app.clients.http import HTTPClient
from app.config import get_settings


class DexScreenerClient:
    def __init__(self) -> None:
        s = get_settings()
        self._http = HTTPClient(base_url=s.dexscreener_base_url)

    async def pairs_for_token(self, mint: str) -> list[dict[str, Any]]:
        try:
            r = await self._http.get(f"/latest/dex/tokens/{mint}")
            return r.json().get("pairs") or []
        except Exception:
            return []

    async def best_pair(self, mint: str) -> dict[str, Any] | None:
        """Highest-liquidity pair for this mint."""
        pairs = await self.pairs_for_token(mint)
        if not pairs:
            return None
        return max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))

    async def aclose(self) -> None:
        await self._http.aclose()
