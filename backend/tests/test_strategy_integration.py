"""End-to-end: LiquidityOIStrategy driving the real engine over synthetic data."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.backtesting import BacktestConfig, CostModel, ExecutionModel, SizingModel, SizingSpec, run_backtest
from app.backtesting.registry import get_strategy, register_strategy, _clear
from app.strategies.liquidity_oi import LiquidityOIStrategy

T0 = datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc)


def frame_from(specs):
    rows = [dict(timestamp=T0 + timedelta(minutes=i), open=o, high=h, low=l, close=c,
                 volume=1000.0, open_interest=oi)
            for i, (o, h, l, c, oi) in enumerate(specs)]
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def _registry():
    _clear()
    register_strategy(LiquidityOIStrategy())
    yield
    _clear()


def _bullish_frame():
    # 20 flat candles (lows 100), then a sweep+reclaim with OI jump, then drift up
    specs = [(100, 100.5, 100, 100.2, 10000.0) for _ in range(20)]
    specs.append((100, 100.3, 99.0, 100.5, 10300.0))   # idx 20: sweep+reclaim, OI+3%
    specs.append((100.5, 101.0, 100.4, 100.9, 10300.0))  # idx 21: entry (next open 100.5)
    specs.append((100.9, 102.0, 100.8, 101.8, 10300.0))  # idx 22: TP region (TP ~ 100.5*1.01=101.5)
    specs.append((101.8, 102.2, 101.5, 102.0, 10300.0))  # idx 23
    return frame_from(specs)


def test_registry_resolves_strategy():
    assert get_strategy("liquidity_oi").name == "liquidity_oi"
    with pytest.raises(KeyError):
        get_strategy("nope")


def test_end_to_end_bullish_trade():
    frame = _bullish_frame()
    strat = get_strategy("liquidity_oi")
    cfg = BacktestConfig(
        strategy="liquidity_oi", symbol="TEST", timeframe="1m", initial_capital=100_000.0,
        params={"lookback": 20, "oi_threshold": 2.5},
        sizing=SizingSpec(SizingModel.FIXED_QTY, 10.0),
        costs=CostModel(brokerage_per_trade=0.0, slippage_pct=0.0),
        execution_model=ExecutionModel.NEXT_OPEN,
        warmup=20,
        stop_loss_pct=1.0, take_profit_pct=1.0,  # engine-derived TP/SL from entry
    )
    r = run_backtest(frame, strat, cfg)
    assert len(r.trades) == 1
    t = r.trades[0]
    assert t.side.value == "LONG"
    # entry at next candle (idx 21) open = 100.5
    assert t.entry_price == pytest.approx(100.5)
    assert t.exit_reason.value in ("TAKE_PROFIT", "STOP_LOSS", "END_OF_DATA")
    assert r.candles == 24
    assert r.final_equity != r.initial_capital  # P&L realized


def test_no_signal_without_oi_data_when_required():
    # same bullish pattern but OI all None -> strategy must not fire (oi_required default True)
    specs = [(100, 100.5, 100, 100.2, None) for _ in range(20)]
    specs.append((100, 100.3, 99.0, 100.5, None))
    specs.append((100.5, 101.0, 100.4, 100.9, None))
    frame = frame_from(specs)
    strat = get_strategy("liquidity_oi")
    cfg = BacktestConfig(
        strategy="liquidity_oi", symbol="TEST", timeframe="1m", initial_capital=100_000.0,
        params={"lookback": 20, "oi_required": True},
        sizing=SizingSpec(SizingModel.FIXED_QTY, 10.0),
        execution_model=ExecutionModel.NEXT_OPEN, warmup=20,
    )
    r = run_backtest(frame, strat, cfg)
    assert len(r.trades) == 0
