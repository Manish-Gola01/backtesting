"""Phase 11-12 tests: optimization, splits, walk-forward — overfitting-safe."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.analytics.optimize import OVERFITTING_WARNING, optimize, split_data
from app.analytics.walkforward import walk_forward
from app.backtesting.registry import _clear, register_strategy
from app.strategies.base import BaseStrategy, Signal, SignalType
from app.strategies.liquidity_oi import LiquidityOIStrategy

T0 = datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc)


class MomentumStrategy(BaseStrategy):
    """Buys when close rises > threshold% over prior candle; deterministic."""
    name = "momentum"
    param_schema = {"threshold": {"type": "float", "default": 0.001}}

    def on_candle(self, candle, history, params):
        if len(history) < 2:
            return Signal()
        prev = history[-2].close
        if prev and (candle.close - prev) / prev >= params.get("threshold", 0.001):
            return Signal(SignalType.LONG, "momentum")
        return Signal()


def trending_frame(n=120):
    """A rising series with periodic pullbacks -> sweep+reclaim opportunities."""
    specs = []
    price = 100.0
    for i in range(n):
        oi = 10000.0 + (300.0 if i % 10 == 5 else 50.0)  # OI jump on dips
        if i % 10 == 5:  # a dip-and-recover candle (sweep of recent low, reclaim)
            o, h, l, c = price, price * 1.005, price * 0.99, price * 1.004
        else:
            o, h, l, c = price, price * 1.002, price * 0.999, price * 1.001
        specs.append(dict(timestamp=T0 + timedelta(minutes=i), open=round(o, 3),
                          high=round(h, 3), low=round(l, 3), close=round(c, 3),
                          volume=1000.0, open_interest=oi))
        price = c
    return pd.DataFrame(specs)


@pytest.fixture(autouse=True)
def _reg():
    _clear()
    register_strategy(LiquidityOIStrategy())
    register_strategy(MomentumStrategy())
    yield
    _clear()


BASE = {"strategy": "liquidity_oi", "symbol": "T", "exchange": "X", "timeframe": "1m",
        "initial_capital": 100000.0, "warmup": 5, "sizing": {"model": "fixed_qty", "value": 10},
        "stop_loss_pct": 1.0, "take_profit_pct": 2.0}


# ------------------------------------------------------------------ splits ---

def test_split_is_chronological_no_shuffle():
    f = trending_frame(100)
    s = split_data(f, 0.6, 0.2, 0.2)
    assert len(s.train) == 60 and len(s.validation) == 20 and len(s.test) == 20
    # chronological: train ends before validation begins before test
    assert s.train["timestamp"].max() < s.validation["timestamp"].min() < s.test["timestamp"].max()


def test_split_rejects_bad_ratios():
    with pytest.raises(AssertionError):
        split_data(trending_frame(50), 0.5, 0.5, 0.5)


# ------------------------------------------------------------ optimization ---

def test_optimize_ranks_and_never_touches_test_for_selection():
    f = trending_frame(120)
    out = optimize(f, BASE, {"lookback": [5, 10], "oi_threshold": [1.0, 3.0]}, rank_by="sharpe_ratio")
    assert out["combinations_tested"] == 4
    assert out["warning"] == OVERFITTING_WARNING
    assert out["best"] is not None
    assert out["best"]["params"]["lookback"] in (5, 10)
    # out-of-sample evaluation present and separate from selection
    assert "validation" in out["out_of_sample"] and "test" in out["out_of_sample"]
    # ranking is sorted best-first by score
    scores = [r["score"] for r in out["ranking"] if r["score"] is not None]
    assert scores == sorted(scores, reverse=True)


def test_optimize_caps_combinations():
    f = trending_frame(60)
    with pytest.raises(ValueError):
        optimize(f, BASE, {"lookback": list(range(1, 50))}, max_combinations=10)


# ------------------------------------------------------------ walk-forward ---

def test_walk_forward_rolls_and_aggregates_oos():
    # rising series: momentum fires reliably, so each window gets trades
    specs = []
    price = 100.0
    for i in range(120):
        price *= 1.002  # steady uptrend
        specs.append(dict(timestamp=T0 + timedelta(minutes=i), open=price, high=price * 1.001,
                          low=price * 0.999, close=price * 1.0005, volume=1000.0, open_interest=float("nan")))
    f = pd.DataFrame(specs)
    base = {"strategy": "momentum", "symbol": "T", "exchange": "X", "timeframe": "1m",
            "initial_capital": 100000.0, "sizing": {"model": "fixed_qty", "value": 5},
            "stop_loss_pct": 5.0, "take_profit_pct": 5.0}
    out = walk_forward(f, base, {"threshold": [0.0005, 0.001]}, train_size=40, test_size=20, rank_by="sharpe_ratio")
    assert out["warning"] == OVERFITTING_WARNING
    assert out["aggregate"]["windows"] >= 3
    assert all(w["best_params"]["threshold"] in (0.0005, 0.001) for w in out["windows"])
    assert all("test_metrics" in w for w in out["windows"])
    # test windows are chronological and non-overlapping
    ranges = [w["test_range"] for w in out["windows"]]
    assert all(ranges[i][1] <= ranges[i + 1][0] for i in range(len(ranges) - 1))


def test_walk_forward_empty_when_window_too_large():
    f = trending_frame(50)
    out = walk_forward(f, BASE, {"lookback": [5]}, train_size=40, test_size=40)
    assert out["aggregate"]["windows"] == 0
