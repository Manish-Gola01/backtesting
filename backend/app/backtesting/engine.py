"""The deterministic backtesting engine.

Single chronological pass (docs/ARCHITECTURE.md §5). Guarantees:
- A strategy only ever sees candles <= the just-closed candle (look-ahead
  impossible by construction).
- Signals are generated at a candle's close; execution follows the configured
  model (default: next candle open).
- Intrabar SL/TP ambiguity resolved by the configured policy.
- Fully deterministic: same (candles, strategy, config) => identical result.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Sequence

from app.backtesting.config import BacktestConfig, ExecutionModel, IntrabarPolicy
from app.backtesting.costs import apply_slippage, side_charges, slippage_cost
from app.backtesting.portfolio import Portfolio
from app.backtesting.sizing import compute_quantity
from app.backtesting.types import EquityPoint, ExitReason, Position, PositionSide, Trade
from app.strategies.base import BaseStrategy, Candle, Signal, SignalType

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    config: dict
    symbol: str
    timeframe: str
    strategy: str
    candles: int
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    initial_capital: float = 0.0
    final_equity: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)


def _candle(row) -> Candle:
    oi = row.open_interest
    return Candle(
        timestamp=row.timestamp.to_pydatetime(),
        open=row.open, high=row.high, low=row.low, close=row.close,
        volume=row.volume,
        open_interest=None if oi != oi else oi,  # NaN -> None
    )


def _levels(cfg: BacktestConfig, side: PositionSide, entry: float, sig: Signal):
    """Resolve stop/target: strategy-provided levels take precedence, else pct / RR model."""
    sl = sig.stop_loss
    tp = sig.take_profit
    if sl is None and cfg.stop_loss_pct is not None:
        sl = entry * (1 - cfg.stop_loss_pct / 100) if side is PositionSide.LONG else entry * (1 + cfg.stop_loss_pct / 100)
    if tp is None:
        if cfg.risk_reward is not None and sl is not None:
            r = abs(entry - sl) * cfg.risk_reward
            tp = entry + r if side is PositionSide.LONG else entry - r
        elif cfg.take_profit_pct is not None:
            tp = entry * (1 + cfg.take_profit_pct / 100) if side is PositionSide.LONG else entry * (1 - cfg.take_profit_pct / 100)
    # Round to kill float noise (e.g. 100*1.1 -> 110.00000000000001) so an exact
    # touch of the level registers as a hit.
    return (round(sl, 10) if sl is not None else None, round(tp, 10) if tp is not None else None)


def _intrabar_exit(cfg: BacktestConfig, pos: Position, candle: Candle):
    """Return (exit_price, reason) if this candle hits SL/TP, else None.

    Both-hit ambiguity is resolved by cfg.intrabar_policy.
    """
    sl, tp = pos.stop_loss, pos.take_profit
    if sl is None and tp is None:
        return None
    if pos.side is PositionSide.LONG:
        sl_hit = sl is not None and candle.low <= sl
        tp_hit = tp is not None and candle.high >= tp
    else:
        sl_hit = sl is not None and candle.high >= sl
        tp_hit = tp is not None and candle.low <= tp

    if sl_hit and tp_hit:
        policy = cfg.intrabar_policy
        if policy is IntrabarPolicy.OPTIMISTIC:
            return tp, ExitReason.TAKE_PROFIT
        # CONSERVATIVE and LOWER_TIMEFRAME-without-finer-data both assume SL first
        return sl, ExitReason.STOP_LOSS
    if sl_hit:
        return sl, ExitReason.STOP_LOSS
    if tp_hit:
        return tp, ExitReason.TAKE_PROFIT
    return None


def run_backtest(
    frame,
    strategy: BaseStrategy,
    config: BacktestConfig,
) -> BacktestResult:
    """Run a deterministic backtest over a validated candle frame.

    `frame` must be the ParsedDataSet frame: ascending tz-aware timestamps,
    canonical columns. A copy is NOT made; we iterate rows directly.
    """
    t0 = time.perf_counter()
    warnings: list[str] = []

    rows = list(frame.itertuples(index=False))  # materialize once, ascending
    n = len(rows)
    candles = [_candle(r) for r in rows]

    port = Portfolio(config.initial_capital, config.costs, config.risk)
    params = strategy.validate_params(config.params)
    warmup = max(config.warmup, 0)

    if config.intrabar_policy is IntrabarPolicy.LOWER_TIMEFRAME:
        warnings.append(
            "intrabar_policy=lower_timeframe requested but no lower-timeframe data "
            "supplied; falling back to conservative same-candle resolution."
        )

    seq = 0
    skipped_insufficient_cash = 0
    # last index we can both signal on (i) and fill on (i+1) for NEXT_OPEN
    last_i = n - 1 if config.execution_model is ExecutionModel.SIGNAL_CLOSE else n - 2

    for i in range(0, n):
        candle = candles[i]

        # 1. manage open positions using ONLY this candle's OHLC -------------
        for pos in list(port.positions):
            if candle.timestamp <= pos.entry_time and config.execution_model is ExecutionModel.NEXT_OPEN:
                continue  # can't exit on the entry candle for next-open model
            hit = _intrabar_exit(config, pos, candle)
            if hit is not None:
                price, reason = hit
                exit_price = apply_slippage(price, pos.side, is_entry=False, slippage_pct=config.costs.slippage_pct)
                notional = pos.quantity * exit_price
                charges = side_charges(notional, config.costs)
                exit_cost = charges["brokerage"] + charges["exchange"] + charges["other"]
                seq += 1
                port.close_position(pos, exit_price=exit_price, exit_time=candle.timestamp,
                                    exit_cost=exit_cost, exit_reason=reason,
                                    trade_seq=seq, symbol=config.symbol, strategy=config.strategy)

        # 2. risk gate --------------------------------------------------------
        if port.halted:
            port.record_equity(candle.timestamp, candle.close)
            continue

        # 3. strategy signal (only past+current candles visible) -------------
        if i >= warmup and i <= last_i:
            history = candles[: i + 1]
            sig = strategy.on_candle(candle, history, params)
        else:
            sig = Signal()

        # 4. execution ---------------------------------------------------------
        if sig.type in (SignalType.LONG, SignalType.SHORT) and port.can_open(candle.timestamp):
            side = PositionSide.LONG if sig.type is SignalType.LONG else PositionSide.SHORT

            if config.execution_model is ExecutionModel.NEXT_OPEN:
                fill_bar = candles[i + 1]                 # strictly the next candle
                ref_price = fill_bar.open
                fill_time = fill_bar.timestamp
            else:  # SIGNAL_CLOSE (aggressive; same-candle)
                ref_price = candle.close
                fill_time = candle.timestamp

            entry_price = apply_slippage(ref_price, side, is_entry=True, slippage_pct=config.costs.slippage_pct)
            sl, tp = _levels(config, side, entry_price, sig)
            qty = compute_quantity(
                config.sizing, equity=port.equity(candle.close),
                initial_capital=config.initial_capital,
                entry_price=entry_price, stop_loss=sl,
                max_position_size=config.risk.max_position_size,
            )
            if qty > 0:
                notional = qty * entry_price
                charges = side_charges(notional, config.costs)
                entry_cost = charges["brokerage"] + charges["exchange"] + charges["other"]
                if notional + entry_cost <= port.cash:
                    pos = Position(side=side, quantity=qty, entry_price=entry_price,
                                   entry_time=fill_time, stop_loss=sl, take_profit=tp)
                    port.open_position(pos, entry_notional=notional, entry_cost=entry_cost)
                else:
                    skipped_insufficient_cash += 1
                    logger.debug(
                        "skip entry @%s: notional %.2f + cost %.2f > cash %.2f",
                        fill_time, notional, entry_cost, port.cash,
                    )

        # 5. mark-to-market ----------------------------------------------------
        port.record_equity(candle.timestamp, candle.close)

    # force-close any position still open at end of data ----------------------
    if candles:
        last = candles[-1]
        for pos in list(port.positions):
            exit_price = apply_slippage(last.close, pos.side, is_entry=False, slippage_pct=config.costs.slippage_pct)
            notional = pos.quantity * exit_price
            charges = side_charges(notional, config.costs)
            exit_cost = charges["brokerage"] + charges["exchange"] + charges["other"]
            seq += 1
            port.close_position(pos, exit_price=exit_price, exit_time=last.timestamp,
                                exit_cost=exit_cost, exit_reason=ExitReason.END_OF_DATA,
                                trade_seq=seq, symbol=config.symbol, strategy=config.strategy)
        port.record_equity(last.timestamp, last.close)

    final_eq = port.equity_curve[-1].equity if port.equity_curve else config.initial_capital
    duration_ms = int((time.perf_counter() - t0) * 1000)

    if skipped_insufficient_cash:
        warnings.append(
            f"{skipped_insufficient_cash} signal(s) skipped: required notional exceeded "
            f"available cash (no leverage). Consider smaller sizing or more capital."
        )

    logger.info(
        "backtest done: %s %s %s | candles=%d trades=%d final=%.2f halted=%s | %dms",
        config.strategy, config.symbol, config.timeframe, n, len(port.closed_trades),
        final_eq, port.halted, duration_ms,
    )

    return BacktestResult(
        config=config.snapshot(), symbol=config.symbol, timeframe=config.timeframe,
        strategy=config.strategy, candles=n, trades=port.closed_trades,
        equity_curve=port.equity_curve, initial_capital=config.initial_capital,
        final_equity=final_eq, halted=port.halted, halt_reason=port.halt_reason,
        duration_ms=duration_ms, warnings=warnings,
    )
