"""High-level trade execution: opens and closes positions.

The trader owns the global risk gates (kill-switch, daily-loss circuit,
max open positions, max position size). The policy never bypasses these.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as redis_async

from app.clients.birdeye import BirdeyeClient
from app.clients.jupiter import JupiterClient
from app.config import get_settings
from app.db.models import Position, PositionStatus, Trade
from app.executor.wallet import Wallet
from app.logging import get_logger

log = get_logger(__name__)


@dataclass
class TradeResult:
    ok: bool
    reason: str
    position_id: int | None = None
    tx_sig: str | None = None


class Trader:
    def __init__(
        self,
        *,
        jupiter: JupiterClient,
        birdeye: BirdeyeClient,
        wallet: Wallet | None,
        redis: redis_async.Redis,
    ) -> None:
        self._jup = jupiter
        self._birdeye = birdeye
        self._wallet = wallet
        self._redis = redis
        self._settings = get_settings()

    # --- gates ----------------------------------------------------------

    async def _halted(self) -> bool:
        v = await self._redis.get(self._settings.halt_flag_key)
        return v is not None

    async def _daily_loss_breached(self, session: AsyncSession) -> bool:
        since = datetime.utcnow() - timedelta(days=1)
        q = select(Position).where(
            Position.closed_at.is_not(None),
            Position.closed_at >= since,
        )
        rows = (await session.execute(q)).scalars().all()
        pnl_24h = sum(r.realized_pnl_usd or 0 for r in rows)
        return pnl_24h <= -self._settings.max_daily_loss_usd

    async def _open_position_count(self, session: AsyncSession) -> int:
        q = select(Position).where(Position.status == PositionStatus.OPEN.value)
        return len((await session.execute(q)).scalars().all())

    # --- buy ------------------------------------------------------------

    async def buy(
        self,
        *,
        session: AsyncSession,
        mint: str,
        size_multiplier: float,
        entry_signal_id: int | None,
    ) -> TradeResult:
        if await self._halted():
            return TradeResult(False, "halted")
        if await self._daily_loss_breached(session):
            return TradeResult(False, "daily_loss_breached")
        if await self._open_position_count(session) >= self._settings.max_open_positions:
            return TradeResult(False, "max_open_positions")

        size_usd = self._settings.max_position_usd * size_multiplier
        if size_usd <= 0:
            return TradeResult(False, "zero_size")

        # USDC has 6 decimals
        amount_in = int(size_usd * 1_000_000)
        quote = await self._jup.quote(
            input_mint=self._settings.usdc_mint, output_mint=mint, amount=amount_in
        )
        expected_out = float(quote.get("outAmount") or 0)
        price_usd = (size_usd / (expected_out / 1e9)) if expected_out else 0.0

        tx_sig: str | None = None
        if not self._settings.dry_run and self._wallet is not None:
            swap_b64 = await self._jup.build_swap_tx(quote, self._wallet.pubkey)
            tx_sig = await self._wallet.sign_and_send(swap_b64)
            log.info("buy_sent", mint=mint, size_usd=size_usd, tx_sig=tx_sig)
        else:
            log.info("buy_dry_run", mint=mint, size_usd=size_usd, expected_out=expected_out)

        position = Position(
            mint=mint,
            status=PositionStatus.OPEN.value,
            entry_signal_id=entry_signal_id,
            entry_price_usd=price_usd,
            entry_amount_usd=size_usd,
            entry_amount_tokens=expected_out / 1e9,
            entry_tx_sig=tx_sig,
            peak_price_usd=price_usd,
        )
        session.add(position)
        await session.flush()
        session.add(
            Trade(
                position_id=position.id,
                side="buy",
                mint=mint,
                tx_sig=tx_sig,
                amount_in=size_usd,
                amount_out=expected_out / 1e9,
                price_usd=price_usd,
                slippage_bps=self._settings.slippage_bps,
                priority_fee_lamports=self._settings.priority_fee_microlamports * 200,
                dry_run=self._settings.dry_run,
            )
        )
        await session.commit()
        return TradeResult(True, "ok", position_id=position.id, tx_sig=tx_sig)

    # --- sell -----------------------------------------------------------

    async def sell(self, *, session: AsyncSession, position: Position, reason: str) -> TradeResult:
        amount_tokens = position.entry_amount_tokens
        # Convert token amount with 9 decimals — this is a simplification;
        # real tokens have varying decimals. TODO: fetch from mint info.
        amount_in = int(amount_tokens * 1e9)
        quote = await self._jup.quote(
            input_mint=position.mint, output_mint=self._settings.usdc_mint, amount=amount_in
        )
        expected_out_usdc = float(quote.get("outAmount") or 0) / 1e6
        exit_price = expected_out_usdc / amount_tokens if amount_tokens else 0.0

        tx_sig: str | None = None
        if not self._settings.dry_run and self._wallet is not None:
            swap_b64 = await self._jup.build_swap_tx(quote, self._wallet.pubkey)
            tx_sig = await self._wallet.sign_and_send(swap_b64)
            log.info("sell_sent", mint=position.mint, reason=reason, tx_sig=tx_sig)
        else:
            log.info(
                "sell_dry_run",
                mint=position.mint,
                reason=reason,
                expected_out_usdc=expected_out_usdc,
            )

        position.status = PositionStatus.CLOSED.value
        position.exit_price_usd = exit_price
        position.exit_amount_usd = expected_out_usdc
        position.exit_tx_sig = tx_sig
        position.exit_reason = reason
        position.closed_at = datetime.utcnow()
        position.realized_pnl_usd = expected_out_usdc - position.entry_amount_usd

        session.add(
            Trade(
                position_id=position.id,
                side="sell",
                mint=position.mint,
                tx_sig=tx_sig,
                amount_in=amount_tokens,
                amount_out=expected_out_usdc,
                price_usd=exit_price,
                slippage_bps=self._settings.slippage_bps,
                priority_fee_lamports=self._settings.priority_fee_microlamports * 200,
                dry_run=self._settings.dry_run,
            )
        )
        await session.commit()
        return TradeResult(True, "ok", position_id=position.id, tx_sig=tx_sig)
