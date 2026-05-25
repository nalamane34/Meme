"""Birdeye free-tier price/liquidity client.

Docs: https://docs.birdeye.so/

Free tier: requires header `X-API-KEY` (still free, just register).
We only hit endpoints available on the public tier.
"""

from typing import Any

from app.clients.http import HTTPClient
from app.config import get_settings


class BirdeyeClient:
    def __init__(self) -> None:
        s = get_settings()
        headers = {"x-chain": "solana"}
        if s.birdeye_api_key:
            headers["X-API-KEY"] = s.birdeye_api_key
        self._http = HTTPClient(base_url=s.birdeye_base_url, headers=headers)

    async def token_overview(self, mint: str) -> dict[str, Any] | None:
        try:
            r = await self._http.get("/defi/token_overview", params={"address": mint})
            return r.json().get("data")
        except Exception:
            return None

    async def price(self, mint: str) -> float | None:
        try:
            r = await self._http.get("/defi/price", params={"address": mint})
            data = r.json().get("data") or {}
            v = data.get("value")
            return float(v) if v is not None else None
        except Exception:
            return None

    async def history_price(
        self, mint: str, ts_from: int, ts_to: int, address_type: str = "token", type_: str = "5m"
    ) -> list[dict[str, Any]]:
        try:
            r = await self._http.get(
                "/defi/history_price",
                params={
                    "address": mint,
                    "address_type": address_type,
                    "type": type_,
                    "time_from": ts_from,
                    "time_to": ts_to,
                },
            )
            return (r.json().get("data") or {}).get("items") or []
        except Exception:
            return []

    async def aclose(self) -> None:
        await self._http.aclose()
