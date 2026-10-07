"""Request/response schemas for backtest + strategy APIs."""
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---- nested config ----
class SizingIn(BaseModel):
    model: str = "risk_pct"
    value: float = 1.0
    lot_size: Optional[float] = None
    compounding: bool = True


class CostsIn(BaseModel):
    brokerage_per_trade: float = 0.0
    brokerage_pct: float = 0.0
    exchange_fee_pct: float = 0.0
    other_charges_pct: float = 0.0
    slippage_pct: float = 0.0


class RiskIn(BaseModel):
    max_position_size: Optional[float] = None
    max_open_positions: int = 1
    daily_loss_limit: Optional[float] = None
    max_drawdown_limit: Optional[float] = None


# ---- requests ----
class BacktestRequest(BaseModel):
    strategy: str
    symbol: str
    exchange: str
    timeframe: str
    initial_capital: float = Field(gt=0)
    params: dict[str, Any] = Field(default_factory=dict)
    sizing: SizingIn = Field(default_factory=SizingIn)
    costs: CostsIn = Field(default_factory=CostsIn)
    risk: RiskIn = Field(default_factory=RiskIn)
    execution_model: str = "next_open"
    intrabar_policy: str = "conservative"
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    risk_reward: Optional[float] = None
    risk_free_rate: float = 0.0


# ---- responses ----
class BacktestCreated(BaseModel):
    id: str
    status: str


class BacktestStatusOut(BaseModel):
    id: str
    status: str
    error: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class TradeOut(BaseModel):
    trade_seq: int
    symbol: str
    strategy: str
    side: str
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    quantity: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    gross_pnl: float
    brokerage: float
    slippage_cost: float
    other_costs: float
    net_pnl: float
    pnl_pct: float
    exit_reason: str
    holding_seconds: int


class MetricsOut(BaseModel):
    metrics: dict[str, Any]


class EquityPointOut(BaseModel):
    timestamp: str
    equity: float
    drawdown: float


class StrategyOut(BaseModel):
    name: str
    description: str
    param_schema: dict[str, Any]
