"""Solana wallet helpers.

Private key is read from the env (WALLET_PRIVATE_KEY, base58-encoded
64-byte secret) and only ever lives in memory. Sign + send is the only
operation here — everything else is read-only.
"""

from __future__ import annotations

import base58
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from app.config import get_settings


class Wallet:
    def __init__(self) -> None:
        s = get_settings()
        if not s.wallet_private_key:
            self._keypair: Keypair | None = None
        else:
            self._keypair = Keypair.from_bytes(base58.b58decode(s.wallet_private_key))
        self._rpc = AsyncClient(s.solana_rpc_url)

    @property
    def pubkey(self) -> str:
        if self._keypair is None:
            raise RuntimeError("wallet not configured (WALLET_PRIVATE_KEY missing)")
        return str(self._keypair.pubkey())

    async def sign_and_send(self, swap_tx_b64: str) -> str:
        """Signs a Jupiter-built versioned tx and submits it.

        Returns the tx signature. Caller is responsible for polling
        confirmation if it needs finality (most meme paths don't — by the
        time you'd have finality, the price has already moved).
        """
        if self._keypair is None:
            raise RuntimeError("wallet not configured")
        import base64

        raw = base64.b64decode(swap_tx_b64)
        unsigned = VersionedTransaction.from_bytes(raw)
        signed = VersionedTransaction(unsigned.message, [self._keypair])
        resp = await self._rpc.send_raw_transaction(
            bytes(signed),
            opts=TxOpts(skip_preflight=True, max_retries=2),
        )
        return str(resp.value)

    async def aclose(self) -> None:
        await self._rpc.close()
