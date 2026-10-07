"""Portfolio: cash, open positions, realized equity, and risk-limit gates.

Accounting model (documented):
- Cash is reduced by entry notional + entry costs, increased by exit proceeds
  net of exit costs. Equity = cash + market value of open positions.
- Compounding: sizing reads current equity unless config disables it.
- Risk limits halt NEW entries only (open positions still managed to exit).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from app.backtesting.config import CostModel, RiskLimits
from app.backtesting.types import EquityPoint, Position, PositionSide, Trade


class Portfolio:
    def __init__(self, initial_capital: float, costs: CostModel, risk: RiskLimits) -> None:
        self.initial_capital = initial_capital
        self.costs = costs
        self.risk = risk
        self.cash: float = initial_capital
        self.positions: list[Position] = []
        self.closed_trades: list[Trade] = []
        self.equity_curve: list[EquityPoint] = []
        self._peak: float = initial_capital
        self._realized_today: float = 0.0
        self._today: Optional[date] = None
        self.halted: bool = False
        self.halt_reason: str = ""

    # --- equity / drawdown -------------------------------------------------
    def equity(self, mark_price: float) -> float:
        # Cash already carries the entry notional; add open unrealized P&L.
        return self.cash + sum(p.unrealized_pnl(mark_price) for p in self.positions)

    def _roll_day(self, ts: datetime) -> None:
        d = ts.date()
        if self._today != d:
            self._today = d
            self._realized_today = 0.0

    def can_open(self, ts: datetime) -> bool:
        self._roll_day(ts)
        if self.halted:
            return False
        if len(self.positions) >= self.risk.max_open_positions:
            return False
        if self.risk.daily_loss_limit is not None and self._realized_today <= -abs(self.risk.daily_loss_limit):
            return False
        if self.risk.max_drawdown_limit is not None:
            dd = self._peak - self.cash
            if dd >= self.risk.max_drawdown_limit:
                return False
        return True

    # --- position lifecycle -------------------------------------------------
    def open_position(self, pos: Position, *, entry_notional: float, entry_cost: float) -> None:
        pos.entry_cost = entry_cost
        self.cash -= entry_notional + entry_cost
        self.positions.append(pos)

    def close_position(self, pos: Position, *, exit_price: float, exit_time: datetime,
                       exit_cost: float, exit_reason, trade_seq: int, symbol: str, strategy: str) -> Trade:
        self.positions.remove(pos)
        sign = pos.side.sign
        gross = sign * pos.quantity * (exit_price - pos.entry_price)
        # cash: return entry notional + gross pnl, minus exit costs
        self.cash += pos.quantity * pos.entry_price + gross - exit_cost

        entry_notional = pos.quantity * pos.entry_price
        brokerage = pos.entry_cost + exit_cost  # entry_cost holds entry-side charges
        slippage = 0.0  # slippage already embedded in fill prices; reported via config separately
        net = gross - brokerage
        pnl_pct = (net / entry_notional * 100.0) if entry_notional else 0.0
        holding = int((exit_time - pos.entry_time).total_seconds())

        trade = Trade(
            trade_seq=trade_seq, symbol=symbol, strategy=strategy, side=pos.side,
            entry_time=pos.entry_time, entry_price=pos.entry_price,
            exit_time=exit_time, exit_price=exit_price, quantity=pos.quantity,
            stop_loss=pos.stop_loss, take_profit=pos.take_profit,
            gross_pnl=gross, brokerage=brokerage, slippage_cost=slippage,
            other_costs=0.0, net_pnl=net, pnl_pct=pnl_pct,
            exit_reason=exit_reason, holding_seconds=holding,
        )
        self.closed_trades.append(trade)
        self._realized_today += net
        return trade

    # --- mark-to-market ------------------------------------------------------
    def record_equity(self, ts: datetime, price: float) -> None:
        self._roll_day(ts)
        eq = self.equity(price)
        self._peak = max(self._peak, eq)
        dd = self._peak - eq
        self.equity_curve.append(EquityPoint(timestamp=ts, equity=eq, drawdown=dd))
        # persistent halt once max drawdown breached
        if self.risk.max_drawdown_limit is not None and dd >= self.risk.max_drawdown_limit:
            self.halted = True
            self.halt_reason = f"max drawdown {dd:.2f} >= limit {self.risk.max_drawdown_limit}"
