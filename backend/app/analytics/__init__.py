"""Performance analytics — pure functions over a BacktestResult.

Every metric is derived from the closed-trade list and the mark-to-market
equity curve produced by the engine. No re-simulation, no future data.

Conventions (documented, reproducible):
- Period returns come from the equity curve (realized + unrealized MTM).
- Trade statistics use NET P&L (after costs) — the honest measure.
- Sharpe/Sortino use per-bar equity returns, annualized from detected bar
  spacing; risk-free rate is a parameter (default 0).
- Ratio metrics return None on insufficient data (never fake zeros).
"""
from app.analytics.metrics import compute_metrics
from app.analytics.returns import period_returns
from app.analytics.risk import max_drawdown, sharpe_ratio, sortino_ratio

__all__ = ["compute_metrics", "period_returns", "max_drawdown", "sharpe_ratio", "sortino_ratio"]
