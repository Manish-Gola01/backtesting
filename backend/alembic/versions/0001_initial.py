"""Initial schema: users, instruments, strategies, historical_data,
backtests, backtest_trades, backtest_metrics, backtest_equity.

Revision ID: 0001_initial
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

instrument_type = sa.Enum("index", "stock", "future", "option", name="instrumenttype")
backtest_status = sa.Enum("QUEUED", "RUNNING", "COMPLETED", "FAILED", name="backteststatus")
direction = sa.Enum("LONG", "SHORT", name="direction")
exit_reason = sa.Enum("STOP_LOSS", "TAKE_PROFIT", "SIGNAL_EXIT", "END_OF_DATA", name="exitreason")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("instrument_type", instrument_type, nullable=False),
        sa.Column("tick_size", sa.Double, nullable=True),
        sa.Column("lot_size", sa.Double, nullable=True),
        sa.Column("has_oi", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("uq_instruments_identity", "instruments", ["symbol", "exchange", "instrument_type"], unique=True)

    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("version", sa.String(16), server_default="1.0.0"),
        sa.Column("param_schema", sa.JSON, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "historical_data",
        sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("timeframe", sa.String(8), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("open", sa.Double, nullable=False),
        sa.Column("high", sa.Double, nullable=False),
        sa.Column("low", sa.Double, nullable=False),
        sa.Column("close", sa.Double, nullable=False),
        sa.Column("volume", sa.Double, nullable=False),
        sa.Column("open_interest", sa.Double, nullable=True),
    )
    op.create_index("ix_hd_lookup_desc", "historical_data", ["instrument_id", "timeframe", "timestamp"])

    op.create_table(
        "backtests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("strategy_name", sa.String(64), nullable=False),
        sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("config", sa.JSON, nullable=False),
        sa.Column("status", backtest_status, nullable=False, server_default="QUEUED"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger, nullable=True),
    )
    op.create_index("ix_backtests_status", "backtests", ["status"])
    op.create_index("ix_backtests_created", "backtests", ["created_at"])

    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("backtest_id", sa.String(36), sa.ForeignKey("backtests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trade_seq", sa.Integer, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("strategy", sa.String(64), nullable=False),
        sa.Column("direction", direction, nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Double, nullable=False),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_price", sa.Double, nullable=False),
        sa.Column("quantity", sa.Double, nullable=False),
        sa.Column("stop_loss", sa.Double, nullable=True),
        sa.Column("take_profit", sa.Double, nullable=True),
        sa.Column("gross_pnl", sa.Double, nullable=False),
        sa.Column("brokerage", sa.Double, nullable=False, server_default="0"),
        sa.Column("slippage_cost", sa.Double, nullable=False, server_default="0"),
        sa.Column("other_costs", sa.Double, nullable=False, server_default="0"),
        sa.Column("net_pnl", sa.Double, nullable=False),
        sa.Column("pnl_pct", sa.Double, nullable=False),
        sa.Column("exit_reason", exit_reason, nullable=False),
        sa.Column("holding_seconds", sa.BigInteger, nullable=False),
    )
    op.create_index("ix_bt_trades_bt_seq", "backtest_trades", ["backtest_id", "trade_seq"])

    op.create_table(
        "backtest_metrics",
        sa.Column("backtest_id", sa.String(36), sa.ForeignKey("backtests.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("net_profit", sa.Double, nullable=True),
        sa.Column("net_profit_pct", sa.Double, nullable=True),
        sa.Column("total_trades", sa.Integer, nullable=True),
        sa.Column("win_rate", sa.Double, nullable=True),
        sa.Column("profit_factor", sa.Double, nullable=True),
        sa.Column("max_drawdown", sa.Double, nullable=True),
        sa.Column("max_drawdown_pct", sa.Double, nullable=True),
        sa.Column("sharpe_ratio", sa.Double, nullable=True),
        sa.Column("sortino_ratio", sa.Double, nullable=True),
        sa.Column("expectancy", sa.Double, nullable=True),
        sa.Column("metrics", sa.JSON, server_default="{}"),
    )

    op.create_table(
        "backtest_equity",
        sa.Column("backtest_id", sa.String(36), sa.ForeignKey("backtests.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("equity", sa.Double, nullable=False),
        sa.Column("drawdown", sa.Double, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("backtest_equity")
    op.drop_table("backtest_metrics")
    op.drop_index("ix_bt_trades_bt_seq", table_name="backtest_trades")
    op.drop_table("backtest_trades")
    op.drop_index("ix_backtests_created", table_name="backtests")
    op.drop_index("ix_backtests_status", table_name="backtests")
    op.drop_table("backtests")
    op.drop_index("ix_hd_lookup_desc", table_name="historical_data")
    op.drop_table("historical_data")
    op.drop_table("strategies")
    op.drop_index("uq_instruments_identity", table_name="instruments")
    op.drop_table("instruments")
    op.drop_table("users")
    for e in (instrument_type, backtest_status, direction, exit_reason):
        e.drop(op.get_bind(), checkfirst=True)
