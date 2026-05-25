"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "smart_wallets",
        sa.Column("address", sa.String(64), primary_key=True),
        sa.Column("label", sa.String(128)),
        sa.Column("tier", sa.Integer, nullable=False, server_default="1"),
        sa.Column("win_rate", sa.Float),
        sa.Column("pnl_30d_usd", sa.Float),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("added_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "tokens",
        sa.Column("mint", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(32)),
        sa.Column("name", sa.String(128)),
        sa.Column("decimals", sa.Integer, nullable=False, server_default="9"),
        sa.Column("first_seen_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("rugcheck_score", sa.Integer),
        sa.Column("rugcheck_payload", sa.JSON),
        sa.Column("blacklisted", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("wallet", sa.String(64)),
        sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("amount_usd", sa.Float),
        sa.Column("tx_sig", sa.String(128)),
        sa.Column("raw", sa.JSON, nullable=False),
        sa.Column("received_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("features", sa.JSON),
        sa.Column("decision", sa.String(16)),
        sa.Column("decision_reason", sa.String(256)),
    )
    op.create_index("ix_signals_mint", "signals", ["mint"])
    op.create_index("ix_signals_received_at", "signals", ["received_at"])
    op.create_index("ix_signals_mint_received", "signals", ["mint", "received_at"])

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("entry_signal_id", sa.Integer, sa.ForeignKey("signals.id")),
        sa.Column("entry_price_usd", sa.Float, nullable=False),
        sa.Column("entry_amount_usd", sa.Float, nullable=False),
        sa.Column("entry_amount_tokens", sa.Float, nullable=False),
        sa.Column("entry_tx_sig", sa.String(128)),
        sa.Column("opened_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("peak_price_usd", sa.Float, nullable=False),
        sa.Column("exit_price_usd", sa.Float),
        sa.Column("exit_amount_usd", sa.Float),
        sa.Column("exit_tx_sig", sa.String(128)),
        sa.Column("exit_reason", sa.String(64)),
        sa.Column("closed_at", sa.DateTime),
        sa.Column("realized_pnl_usd", sa.Float),
    )
    op.create_index("ix_positions_mint", "positions", ["mint"])

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("position_id", sa.Integer, sa.ForeignKey("positions.id"), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("mint", sa.String(64), nullable=False),
        sa.Column("tx_sig", sa.String(128)),
        sa.Column("amount_in", sa.Float, nullable=False),
        sa.Column("amount_out", sa.Float, nullable=False),
        sa.Column("price_usd", sa.Float, nullable=False),
        sa.Column("slippage_bps", sa.Integer, nullable=False),
        sa.Column("priority_fee_lamports", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("dry_run", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_trades_position_id", "trades", ["position_id"])


def downgrade() -> None:
    op.drop_table("trades")
    op.drop_table("positions")
    op.drop_table("signals")
    op.drop_table("tokens")
    op.drop_table("smart_wallets")
