"""The full metric set (spec §9) — one entry point: compute_metrics()."""
from __future__ import annotations

from typing import Optional

from app.analytics.returns import period_returns
from app.analytics.risk import max_drawdown, sharpe_ratio, sortino_ratio
from app.backtesting.engine import BacktestResult
from app.backtesting.types import Trade


def _mean(xs: list[float]) -> Optional[float]:
    return (sum(xs) / len(xs)) if xs else None


def _streaks(trades: list[Trade]) -> tuple[int, int]:
    """(max consecutive wins, max consecutive losses) by net P&L sign."""
    max_w = max_l = cur_w = cur_l = 0
    for t in trades:
        if t.net_pnl > 0:
            cur_w += 1; cur_l = 0
        elif t.net_pnl < 0:
            cur_l += 1; cur_w = 0
        else:
            cur_w = cur_l = 0
        max_w = max(max_w, cur_w); max_l = max(max_l, cur_l)
    return max_w, max_l


def compute_metrics(result: BacktestResult, *, risk_free_rate: float = 0.0) -> dict:
    """Compute every metric from a BacktestResult. Returns a flat dict with
    nested period-return maps. Ratio fields are None when undefined.
    """
    trades = result.trades
    eq = result.equity_curve
    initial = result.initial_capital
    final = result.final_equity

    nets = [t.net_pnl for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)  # positive magnitude

    total = len(trades)
    n_win = len(wins)
    n_loss = len(losses)
    win_rate = (n_win / total * 100.0) if total else None
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (None if gross_profit == 0 else float("inf"))
    expectancy = _mean(nets)  # average net per trade == expectancy

    mdd, mdd_pct = max_drawdown(eq)
    sharpe = sharpe_ratio(eq, risk_free_rate)
    sortino = sortino_ratio(eq, risk_free_rate)

    cons_w, cons_l = _streaks(trades)
    hold = [t.holding_seconds for t in trades]

    net_profit = final - initial
    return {
        # capital
        "initial_capital": initial,
        "final_capital": final,
        "net_profit": net_profit,
        "net_profit_pct": (net_profit / initial * 100.0) if initial else None,
        # trade counts
        "total_trades": total,
        "winning_trades": n_win,
        "losing_trades": n_loss,
        "win_rate": win_rate,
        # averages
        "avg_winning_trade": _mean(wins),
        "avg_losing_trade": _mean(losses),
        "largest_winner": max(wins) if wins else None,
        "largest_loser": min(losses) if losses else None,
        "avg_trade": _mean(nets),
        # ratios
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        # risk
        "max_drawdown": mdd,
        "max_drawdown_pct": mdd_pct,
        # behaviour
        "avg_holding_seconds": _mean(hold),
        "max_consecutive_wins": cons_w,
        "max_consecutive_losses": cons_l,
        # period returns
        "daily_returns": period_returns(eq, "daily"),
        "weekly_returns": period_returns(eq, "weekly"),
        "monthly_returns": period_returns(eq, "monthly"),
        "yearly_returns": period_returns(eq, "yearly"),
        # meta
        "candles": result.candles,
        "halted": result.halted,
        "halt_reason": result.halt_reason,
    }
