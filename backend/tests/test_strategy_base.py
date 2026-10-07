"""Strategy plugin contract tests.

These pin the interface the Phase 4 engine will rely on; the anti-look-ahead
contract itself is enforced by engine tests in Phase 10.
"""
from datetime import datetime, timezone

import pytest

from app.strategies.base import BaseStrategy, Candle, Signal, SignalType


def test_base_strategy_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseStrategy()  # type: ignore[abstract]


class _DummyStrategy(BaseStrategy):
    name = "dummy"

    def on_candle(self, candle, history, params):
        return Signal(SignalType.NONE, reason="no setup")


def test_minimal_substrategy_works():
    strategy = _DummyStrategy()
    signal = strategy.on_candle(None, [], {})  # type: ignore[arg-type]
    assert signal.type is SignalType.NONE
    assert signal.reason == "no setup"
    assert strategy.validate_params({"lookback": 20}) == {"lookback": 20}


def test_candle_open_interest_is_optional_and_never_fabricated():
    candle = Candle(
        timestamp=datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc),
        open=100.0,
        high=101.0,
        low=99.5,
        close=100.5,
        volume=1_000.0,
    )
    assert candle.open_interest is None


def test_signal_defaults_are_inert():
    signal = Signal()
    assert signal.type is SignalType.NONE
    assert signal.stop_loss is None
    assert signal.take_profit is None
