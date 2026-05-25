"""Jupiter v6 quote + swap client.

Docs: https://station.jup.ag/docs/apis/swap-api

Flow:
  1. GET /quote   -> route + expected out
  2. POST /swap   -> serialized transaction
  3. sign + send  -> tx signature

The client returns at step (2) — actually signing/sending lives in
executor/wallet.py so this stays testable without a wallet.
"""

from typing import Any

from app.clients.http import HTTPClient
from app.config import get_settings


class JupiterClient:
    def __init__(self) -> None:
        s = get_settings()
        self._quote = HTTPClient(base_url="https://quote-api.jup.ag")
        self._slippage_bps = s.slippage_bps
        self._priority_fee = s.priority_fee_microlamports

    async def quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int | None = None,
        only_direct_routes: bool = False,
    ) -> dict[str, Any]:
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": slippage_bps if slippage_bps is not None else self._slippage_bps,
            "onlyDirectRoutes": str(only_direct_routes).lower(),
        }
        r = await self._quote.get("/v6/quote", params=params)
        return r.json()

    async def build_swap_tx(self, quote: dict[str, Any], user_pubkey: str) -> str:
        """Returns base64-encoded versioned tx ready to sign."""
        body = {
            "quoteResponse": quote,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": self._priority_fee,
        }
        r = await self._quote.post("/v6/swap", json=body)
        return r.json()["swapTransaction"]

    async def aclose(self) -> None:
        await self._quote.aclose()
