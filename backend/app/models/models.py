"""SQLAlchemy ORM models — mirrors docs/ARCHITECTURE.md §4 exactly.

Design guarantees:
- historical_data composite PK (instrument_id, timeframe, timestamp) makes
  duplicate candles impossible at the DB level — idempotent re-uploads.
- open_interest NULL == "no data" — never fabricated.
- backtests.config is an immutable JSONB snapshot → reproducibility.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Double,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


# ----- enums ---------------------------------------------------------------

class InstrumentType(str, enum.Enum):
    INDEX = "index"
    STOCK = "stock"
    FUTURE = "future"
    OPTION = "option"


class BacktestStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Direction(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class ExitReason(str, enum.Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    SIGNAL_EXIT = "SIGNAL_EXIT"
    END_OF_DATA = "END_OF_DATA"


# ----- tables ---------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        # one logical instrument per symbol/exchange/type
        Index("uq_instruments_identity", "symbol", "exchange", "instrument_type", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    instrument_type: Mapped[InstrumentType] = mapped_column(Enum(InstrumentType), nullable=False)
    tick_size: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    lot_size: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    has_oi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    candles: Mapped[list["HistoricalData"]] = relationship(back_populates="instrument", cascade="all, delete-orphan")


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(16), default="1.0.0")
    param_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HistoricalData(Base):
    __tablename__ = "historical_data"
    __table_args__ = (
        Index("ix_hd_lookup_desc", "instrument_id", "timeframe", "timestamp"),
    )

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    open: Mapped[float] = mapped_column(Double, nullable=False)
    high: Mapped[float] = mapped_column(Double, nullable=False)
    low: Mapped[float] = mapped_column(Double, nullable=False)
    close: Mapped[float] = mapped_column(Double, nullable=False)
    volume: Mapped[float] = mapped_column(Double, nullable=False)
    open_interest: Mapped[Optional[float]] = mapped_column(Double, nullable=True)  # NULL = no data

    instrument: Mapped[Instrument] = relationship(back_populates="candles")


class Backtest(Base):
    __tablename__ = "backtests"
    __table_args__ = (
        Index("ix_backtests_status", "status"),
        Index("ix_backtests_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)  # immutable snapshot
    status: Mapped[BacktestStatus] = mapped_column(Enum(BacktestStatus), nullable=False, default=BacktestStatus.QUEUED)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    trades: Mapped[list["BacktestTrade"]] = relationship(back_populates="backtest", cascade="all, delete-orphan")
    metrics: Mapped[Optional["BacktestMetric"]] = relationship(back_populates="backtest", cascade="all, delete-orphan", uselist=False)
    equity: Mapped[list["BacktestEquity"]] = relationship(back_populates="backtest", cascade="all, delete-orphan")


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"
    __table_args__ = (Index("ix_bt_trades_bt_seq", "backtest_id", "trade_seq"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    backtest_id: Mapped[str] = mapped_column(ForeignKey("backtests.id", ondelete="CASCADE"), nullable=False)
    trade_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[Direction] = mapped_column(Enum(Direction), nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[float] = mapped_column(Double, nullable=False)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_price: Mapped[float] = mapped_column(Double, nullable=False)
    quantity: Mapped[float] = mapped_column(Double, nullable=False)
    stop_loss: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    gross_pnl: Mapped[float] = mapped_column(Double, nullable=False)
    brokerage: Mapped[float] = mapped_column(Double, nullable=False, default=0.0)
    slippage_cost: Mapped[float] = mapped_column(Double, nullable=False, default=0.0)
    other_costs: Mapped[float] = mapped_column(Double, nullable=False, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Double, nullable=False)
    pnl_pct: Mapped[float] = mapped_column(Double, nullable=False)
    exit_reason: Mapped[ExitReason] = mapped_column(Enum(ExitReason), nullable=False)
    holding_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False)

    backtest: Mapped[Backtest] = relationship(back_populates="trades")


class BacktestMetric(Base):
    __tablename__ = "backtest_metrics"

    backtest_id: Mapped[str] = mapped_column(ForeignKey("backtests.id", ondelete="CASCADE"), primary_key=True)
    # headline columns for cheap listing/comparison
    net_profit: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_profit_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    total_trades: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    win_rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    profit_factor: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    max_drawdown: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    max_drawdown_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sharpe_ratio: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sortino_ratio: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    expectancy: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    # full detailed metric set (consecutive streaks, holding times, period returns)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)

    backtest: Mapped[Backtest] = relationship(back_populates="metrics")


class BacktestEquity(Base):
    __tablename__ = "backtest_equity"

    backtest_id: Mapped[str] = mapped_column(ForeignKey("backtests.id", ondelete="CASCADE"), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    equity: Mapped[float] = mapped_column(Double, nullable=False)
    drawdown: Mapped[float] = mapped_column(Double, nullable=False, default=0.0)

    backtest: Mapped[Backtest] = relationship(back_populates="equity")
