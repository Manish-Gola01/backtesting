"""Phase 10: anti-look-ahead bias + golden backtest + intrabar verification.

These are the tests that PROVE the engine can't cheat.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

import pandas as pd
import pytest

from app.backtesting import BacktestConfig, CostModel, ExecutionModel, SizingModel, SizingSpec, run_backtest
from app.strategies.base import BaseStrategy, Candle, Signal, SignalType

T0 = datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc)


def frame(specs):
    return pd.DataFrame([dict(timestamp=T0 + timedelta(minutes=i), open=o, high=h, low=l, close=c,
                              volume=1000.0, open_interest=float("nan"))
                         for i, (o, h, l, c) in enumerate(specs)])


# ---- A strategy that tries to cheat by reading history beyond current -------
class FuturePeekStrategy(BaseStrategy):
    name = "peek"
    """Attempts to detect a future price spike and buy before it. If the engine
    leaks future candles, this strategy would produce a signal early."""

    def __init__(self):
        self.spike_detected_at = None

    def on_candle(self, candle: Candle, history: Sequence[Candle], params: Mapping[str, Any]) -> Signal:
        # Look at the LAST candle in history — it MUST be `candle` itself.
        last = history[-1]
        assert last.timestamp == candle.timestamp, "engine leaked a future candle!"
        # try to find a spike in the data we're given
        for h in history:
            if h.close > 200:  # a spike exists
                self.spike_detected_at = candle.timestamp
                return Signal(SignalType.LONG, reason="saw spike")
        return Signal()


def test_no_look_ahead_spike_invisible_until_it_happens():
    # spike happens at index 5 (close 300). Before that, no candle >200.
    specs = [(100, 101, 99, 100)] * 5 + [(100, 305, 100, 300)] + [(300, 301, 299, 300)]
    s = FuturePeekStrategy()
    cfg = BacktestConfig(strategy="peek", symbol="T", timeframe="1m", initial_capital=10000,
                         sizing=SizingSpec(SizingModel.FIXED_QTY, 1))
    run_backtest(frame(specs), s, cfg)
    # the strategy must only "see" the spike at index 5 (its own candle), not before
    assert s.spike_detected_at == T0 + timedelta(minutes=5)


def test_history_length_equals_index_plus_one():
    """The strategy receives exactly i+1 candles at step i — never more."""
    seen_lengths = []

    class LenStrategy(BaseStrategy):
        name = "len"
        def on_candle(self, candle, history, params):
            seen_lengths.append(len(history))
            return Signal()

    specs = [(100, 101, 99, 100)] * 8
    cfg = BacktestConfig(strategy="len", symbol="T", timeframe="1m", initial_capital=10000,
                         sizing=SizingSpec(SizingModel.FIXED_QTY, 1))
    run_backtest(frame(specs), LenStrategy(), cfg)
    # NEXT_OPEN signals on idx 0..n-2 => lengths 1..n-1
    assert seen_lengths == list(range(1, 8))


# ---- golden backtest: fully hand-computed -----------------------------------

def test_golden_backtest_hand_computed():
    """One known trade, every number verified by hand.

    Signal LONG at idx0 (close 100). NEXT_OPEN -> entry idx1 open=100.
    qty=10 fixed. SL 5% -> 95; TP none. Exit at idx2 close 99 via END_OF_DATA
    ... actually we engineer a TP: idx2 high hits 110 (TP 10% -> 110).
    Costs: brokerage 5/side, slippage 0.
    """
    specs = [(100, 101, 99, 100),   # 0 signal
             (100, 102, 100, 101),  # 1 entry @100 (next open)
             (101, 110, 100, 109)]  # 2 high 110 hits TP(110) -> exit @110
    class Buy0(BaseStrategy):
        name = "buy0"
        def on_candle(self, candle, history, params):
            return Signal(SignalType.LONG, "buy") if len(history) == 1 else Signal()

    cfg = BacktestConfig(strategy="buy0", symbol="T", timeframe="1m", initial_capital=2000,
                         sizing=SizingSpec(SizingModel.FIXED_QTY, 10),
                         take_profit_pct=10.0, stop_loss_pct=5.0,
                         costs=CostModel(brokerage_per_trade=5.0),
                         execution_model=ExecutionModel.NEXT_OPEN)
    r = run_backtest(frame(specs), Buy0(), cfg)
    assert len(r.trades) == 1
    t = r.trades[0]
    assert t.entry_price == 100.0          # next candle open, slippage 0
    assert t.exit_price == 110.0           # TP = 100 * 1.10
    assert t.exit_reason.value == "TAKE_PROFIT"
    assert t.gross_pnl == pytest.approx((110 - 100) * 10)   # 100
    assert t.brokerage == pytest.approx(10.0)               # 5 entry + 5 exit
    assert t.net_pnl == pytest.approx(90.0)                 # 100 - 10
    assert t.pnl_pct == pytest.approx(90.0 / 1000 * 100)    # net / entry notional
    assert t.quantity == 10


def test_equity_curve_monotonic_timestamps_and_length():
    specs = [(100, 101, 99, 100)] * 6
    class Noop(BaseStrategy):
        name = "noop"
        def on_candle(self, c, h, p): return Signal()
    cfg = BacktestConfig(strategy="noop", symbol="T", timeframe="1m", initial_capital=1000,
                         sizing=SizingSpec(SizingModel.FIXED_QTY, 1))
    r = run_backtest(frame(specs), Noop(), cfg)
    ts = [p.timestamp for p in r.equity_curve]
    assert ts == sorted(ts)                      # ascending
    assert len(r.equity_curve) == len(specs) + 1 # one per candle + final mark
    assert all(p.equity == 1000 for p in r.equity_curve)  # no trades -> flat
