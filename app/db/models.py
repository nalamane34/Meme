from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    FAILED = "failed"


class SmartWallet(Base):
    __tablename__ = "smart_wallets"

    address: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str | None] = mapped_column(String(128))
    tier: Mapped[int] = mapped_column(Integer, default=1)
    win_rate: Mapped[float | None] = mapped_column(Float)
    pnl_30d_usd: Mapped[float | None] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Token(Base):
    __tablename__ = "tokens"

    mint: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(128))
    decimals: Mapped[int] = mapped_column(Integer, default=9)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    rugcheck_score: Mapped[int | None] = mapped_column(Integer)
    rugcheck_payload: Mapped[dict | None] = mapped_column(JSON)
    blacklisted: Mapped[bool] = mapped_column(default=False)


class Signal(Base):
    """One inbound signal from a watched wallet (or other source).

    Every signal — even ones we don't act on — gets logged. This is the
    raw data that feeds the offline RL trainer.
    """

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32))  # "helius_webhook" | "manual" | etc
    wallet: Mapped[str | None] = mapped_column(String(64))
    mint: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))  # buy/sell of the *watched* wallet
    amount_usd: Mapped[float | None] = mapped_column(Float)
    tx_sig: Mapped[str | None] = mapped_column(String(128))
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    features: Mapped[dict | None] = mapped_column(JSON)  # snapshotted state vector
    decision: Mapped[str | None] = mapped_column(String(16))  # buy/skip/sell
    decision_reason: Mapped[str | None] = mapped_column(String(256))

    __table_args__ = (Index("ix_signals_mint_received", "mint", "received_at"),)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default=PositionStatus.OPEN.value)

    entry_signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))
    entry_price_usd: Mapped[float] = mapped_column(Float)
    entry_amount_usd: Mapped[float] = mapped_column(Float)
    entry_amount_tokens: Mapped[float] = mapped_column(Float)
    entry_tx_sig: Mapped[str | None] = mapped_column(String(128))
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    peak_price_usd: Mapped[float] = mapped_column(Float)  # for trailing stop

    exit_price_usd: Mapped[float | None] = mapped_column(Float)
    exit_amount_usd: Mapped[float | None] = mapped_column(Float)
    exit_tx_sig: Mapped[str | None] = mapped_column(String(128))
    exit_reason: Mapped[str | None] = mapped_column(String(64))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)

    realized_pnl_usd: Mapped[float | None] = mapped_column(Float)

    trades: Mapped[list["Trade"]] = relationship(back_populates="position")


class Trade(Base):
    """Atomic swap record (one Jupiter swap)."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"), index=True)
    side: Mapped[str] = mapped_column(String(8))
    mint: Mapped[str] = mapped_column(String(64))
    tx_sig: Mapped[str | None] = mapped_column(String(128))
    amount_in: Mapped[float] = mapped_column(Float)
    amount_out: Mapped[float] = mapped_column(Float)
    price_usd: Mapped[float] = mapped_column(Float)
    slippage_bps: Mapped[int] = mapped_column(Integer)
    priority_fee_lamports: Mapped[int] = mapped_column(BigInteger, default=0)
    dry_run: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    position: Mapped[Position] = relationship(back_populates="trades")
