"""Engine tests: determinism, no-look-ahead, SL/TP, sizing, costs, intrabar policy.

Uses a scripted stub strategy so we control exactly when signals fire, and
synthetic candle frames engineered to hit specific engine branches.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

import pandas as pd
import pytest

from app.backtesting import (
    BacktestConfig, CostModel, ExecutionModel, IntrabarPolicy,
    RiskLimits, SizingModel, SizingSpec, run_backtest,
)
from app.backtesting.config import BacktestConfig as Cfg
from app.strategies.base import BaseStrategy, Candle, Signal, SignalType

T0 = datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc)


def mk_candles(specs):
    """specs: list of (o,h,l,c) — 1-minute bars from T0."""
    rows = []
    for i, (o, h, l, c) in enumerate(specs):
        rows.append(dict(timestamp=T0 + timedelta(minutes=i), open=o, high=h, low=l, close=c,
                         volume=1000.0, open_interest=float("nan")))
    return pd.DataFrame(rows)


class ScriptStrategy(BaseStrategy):
    """Fires pre-scripted signals on specific candle indices."""
    name = "script"
    param_schema = {}

    def __init__(self, plan: dict[int, SignalType]):
        self.plan = plan
        self.seen_max_index = -1  # for look-ahead assertions

    def on_candle(self, candle: Candle, history: Sequence[Candle], params: Mapping[str, Any]) -> Signal:
        # anti-look-ahead invariant: history's last element IS the current candle
        assert history[-1].timestamp == candle.timestamp, "history must end at current candle"
        assert all(h.timestamp <= candle.timestamp for h in history), "future candle leaked!"
        idx = len(history) - 1
        self.seen_max_index = max(self.seen_max_index, idx)
        t = self.plan.get(idx, SignalType.NONE)
        return Signal(t, reason=f"idx{idx}")


def cfg(**kw):
    base = dict(strategy="script", symbol="TEST", timeframe="1m", initial_capital=100_000.0)
    base.update(kw)
    return BacktestConfig(**base)


# ------------------------------------------------------------ determinism ---

def test_determinism_identical_inputs_identical_outputs():
    frame = mk_candles([(100,101,99,100)]*10 + [(100,101,99,100.5)]*5)
    plan = {2: SignalType.LONG}
    c = cfg(stop_loss_pct=1.0, take_profit_pct=2.0)
    r1 = run_backtest(frame, ScriptStrategy(plan), c)
    r2 = run_backtest(frame, ScriptStrategy(plan), c)
    assert [ (t.entry_price, t.exit_price, t.net_pnl) for t in r1.trades ] == \
           [ (t.entry_price, t.exit_price, t.net_pnl) for t in r2.trades ]
    assert [ (e.equity) for e in r1.equity_curve ] == [ (e.equity) for e in r2.equity_curve ]


def test_no_lookahead_history_never_exceeds_current():
    frame = mk_candles([(100,101,99,100)]*6)
    s = ScriptStrategy({})
    run_backtest(frame, s, cfg())
    # NEXT_OPEN model signals on indices 0..n-2 (index 4 here): the last candle
    # has no following candle to fill on, so it's never signaled. Correct.
    assert s.seen_max_index == 4


def test_no_lookahead_signal_close_sees_all_candles():
    frame = mk_candles([(100,101,99,100)]*6)
    s = ScriptStrategy({})
    run_backtest(frame, s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE))
    assert s.seen_max_index == 5  # signal-close can act on the final candle


# ----------------------------------------------------------- entry model ---

def test_next_open_entry_uses_following_candle_open():
    # signal at idx 0 (close 100), next candle opens at 102 -> entry = 102
    frame = mk_candles([(100,101,99,100), (102,103,101.5,102), (102,102.5,98,99)])
    s = ScriptStrategy({0: SignalType.LONG})
    r = run_backtest(frame, s, cfg(sizing=SizingSpec(SizingModel.FIXED_QTY, 10)))
    assert len(r.trades) == 1
    assert r.trades[0].entry_price == 102.0


def test_signal_close_entry_uses_signal_candle_close():
    frame = mk_candles([(100,101,99,100), (102,103,101.5,102)])
    s = ScriptStrategy({0: SignalType.LONG})
    r = run_backtest(frame, s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
                                   sizing=SizingSpec(SizingModel.FIXED_QTY, 10)))
    assert r.trades[0].entry_price == 100.0  # the signal candle's close


# ------------------------------------------------------------------ SL/TP ---

def test_stop_loss_hit_long():
    # enter 100, SL 1% => 99; next candle dips to 98.5 -> SL exit at 99
    frame = mk_candles([(100,101,99.5,100), (100,100.2,98.5,99)])
    s = ScriptStrategy({0: SignalType.LONG})
    r = run_backtest(frame, s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
                                   stop_loss_pct=1.0, take_profit_pct=5.0,
                                   sizing=SizingSpec(SizingModel.FIXED_QTY, 10)))
    t = r.trades[0]
    assert t.exit_reason.value == "STOP_LOSS"
    assert t.exit_price == 99.0
    assert t.net_pnl == pytest.approx((99.0-100.0)*10)


def test_take_profit_hit_long():
    frame = mk_candles([(100,101,99.5,100), (100,103,100,102.5)])
    s = ScriptStrategy({0: SignalType.LONG})
    r = run_backtest(frame, s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
                                   stop_loss_pct=1.0, take_profit_pct=2.0,
                                   sizing=SizingSpec(SizingModel.FIXED_QTY, 10)))
    t = r.trades[0]
    assert t.exit_reason.value == "TAKE_PROFIT"
    assert t.exit_price == 102.0
    assert t.net_pnl == pytest.approx((102.0-100.0)*10)


def test_short_stop_and_target_mirror():
    # short at 100; SL 1% => 101, TP 2% => 98
    sl_frame = mk_candles([(100,101,99.5,100), (100,101.5,100,101)])
    s = ScriptStrategy({0: SignalType.SHORT})
    r = run_backtest(sl_frame, s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
                                      stop_loss_pct=1.0, take_profit_pct=2.0,
                                      sizing=SizingSpec(SizingModel.FIXED_QTY, 10)))
    t = r.trades[0]
    assert t.exit_reason.value == "STOP_LOSS"
    assert t.exit_price == 101.0
    assert t.net_pnl == pytest.approx((100.0-101.0)*10)  # short loses when price rises


# -------------------------------------------------- same-candle SL/TP ---

def _both_hit_frame():
    # one candle dips to 98 (SL for 1%) AND spikes to 103 (TP for 2%) after a 100 entry
    return mk_candles([(100,101,99.5,100), (100,103,98,101)])


def test_intrabar_conservative_assumes_sl_first():
    s = ScriptStrategy({0: SignalType.LONG})
    r = run_backtest(_both_hit_frame(), s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
                       stop_loss_pct=1.0, take_profit_pct=2.0,
                       intrabar_policy=IntrabarPolicy.CONSERVATIVE,
                       sizing=SizingSpec(SizingModel.FIXED_QTY, 10)))
    assert r.trades[0].exit_reason.value == "STOP_LOSS"


def test_intrabar_optimistic_assumes_tp_first():
    s = ScriptStrategy({0: SignalType.LONG})
    r = run_backtest(_both_hit_frame(), s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
                       stop_loss_pct=1.0, take_profit_pct=2.0,
                       intrabar_policy=IntrabarPolicy.OPTIMISTIC,
                       sizing=SizingSpec(SizingModel.FIXED_QTY, 10)))
    assert r.trades[0].exit_reason.value == "TAKE_PROFIT"


def test_intrabar_lower_timeframe_without_data_falls_back_conservative():
    s = ScriptStrategy({0: SignalType.LONG})
    r = run_backtest(_both_hit_frame(), s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
                       stop_loss_pct=1.0, take_profit_pct=2.0,
                       intrabar_policy=IntrabarPolicy.LOWER_TIMEFRAME,
                       sizing=SizingSpec(SizingModel.FIXED_QTY, 10)))
    assert r.trades[0].exit_reason.value == "STOP_LOSS"
    assert any("lower_timeframe" in w for w in r.warnings)


# ----------------------------------------------------------------- sizing ---

def test_risk_pct_sizing():
    # equity 100k, risk 1% => risk 1000; stop distance 1 => qty 1000
    frame = mk_candles([(100,101,99.5,100), (100,100.5,99,100)])
    s = ScriptStrategy({0: SignalType.LONG})
    r = run_backtest(frame, s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
                                   stop_loss_pct=1.0,
                                   sizing=SizingSpec(SizingModel.RISK_PCT, 1.0)))
    assert r.trades[0].quantity == pytest.approx(1000.0)


def test_fixed_amount_sizing():
    frame = mk_candles([(100,101,99.5,100), (100,100.5,99,100)])
    s = ScriptStrategy({0: SignalType.LONG})
    r = run_backtest(frame, s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
                                   sizing=SizingSpec(SizingModel.FIXED_AMOUNT, 5000.0)))
    assert r.trades[0].quantity == pytest.approx(50.0)


def test_max_position_size_caps_qty():
    frame = mk_candles([(100,101,99.5,100), (100,100.5,99,100)])
    s = ScriptStrategy({0: SignalType.LONG})
    r = run_backtest(frame, s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
                                   sizing=SizingSpec(SizingModel.FIXED_QTY, 500.0),
                                   risk=RiskLimits(max_position_size=100.0)))
    assert r.trades[0].quantity == 100.0


# ------------------------------------------------------------------ costs ---

def test_brokerage_and_slippage_applied_and_separated():
    # entry close 100 * (1+0.1%) = 100.1 ; qty 100 ; brokerage 10/side
    frame = mk_candles([(100,101,99.5,100), (100,100.5,99.5,100)])
    s = ScriptStrategy({0: SignalType.LONG})
    c = cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
            sizing=SizingSpec(SizingModel.FIXED_QTY, 100.0),
            costs=CostModel(brokerage_per_trade=10.0, slippage_pct=0.1))
    r = run_backtest(frame, s, c)
    t = r.trades[0]
    assert t.entry_price == pytest.approx(100.1)
    assert t.brokerage == pytest.approx(20.0)   # entry + exit
    # gross uses entry 100.1, exit 100*(1-0.1%)=99.9
    assert t.gross_pnl == pytest.approx((99.9-100.1)*100)
    assert t.net_pnl == pytest.approx(t.gross_pnl - 20.0)


# -------------------------------------------------------------- risk gates ---

def test_insufficient_cash_skips_and_warns():
    # risk-based sizing yields a leveraged position exceeding cash -> skipped + warning
    frame = mk_candles([(100,101,99.5,100), (100,100.5,99,100)])
    s = ScriptStrategy({0: SignalType.LONG})
    r = run_backtest(frame, s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
                                   stop_loss_pct=0.5,
                                   sizing=SizingSpec(SizingModel.RISK_PCT, 1.0)))
    assert len(r.trades) == 0
    assert any("notional exceeded" in w for w in r.warnings)


def test_max_open_positions_blocks_second_entry():
    # signal long on idx 0 and 1, but max_open_positions=1 -> only one trade
    frame = mk_candles([(100,101,99.5,100)]*3)
    s = ScriptStrategy({0: SignalType.LONG, 1: SignalType.LONG})
    r = run_backtest(frame, s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
                                   sizing=SizingSpec(SizingModel.FIXED_QTY, 10),
                                   risk=RiskLimits(max_open_positions=1)))
    assert len(r.trades) == 1


def test_max_drawdown_limit_halts_new_entries():
    # big loser then more signals that must be blocked after DD breach
    frame = mk_candles([
        (100,101,99.5,100),      # 0: long signal
        (100,100.3,90,90.5),     # 1: huge drop -> SL (1%) small loss... use big SL
        (90,91,89,90),           # 2
        (90,91,89,90),           # 3
    ])
    s = ScriptStrategy({0: SignalType.LONG, 2: SignalType.LONG, 3: SignalType.LONG})
    r = run_backtest(frame, s, cfg(execution_model=ExecutionModel.SIGNAL_CLOSE,
                                   stop_loss_pct=20.0,   # wide stop so the drop realizes a big loss
                                   sizing=SizingSpec(SizingModel.FIXED_QTY, 1000.0),
                                   risk=RiskLimits(max_drawdown_limit=5000.0)))
    # first trade realized a large loss; later signals must be suppressed
    assert r.halted
    assert len(r.trades) == 1
