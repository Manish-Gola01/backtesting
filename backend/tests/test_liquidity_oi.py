"""Hand-verified signal tests for the Liquidity Sweep + OI strategy.

Each scenario builds a small candle history by hand, computes the expected
signal independently, and asserts the strategy produces exactly it — and that
it never sees the future.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.strategies.base import Candle, SignalType
from app.strategies.liquidity_oi import LiquidityOIStrategy

T0 = datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc)


def c(i, o, h, l, cl, oi=None):
    return Candle(timestamp=T0 + timedelta(minutes=i), open=o, high=h, low=l, close=cl,
                  volume=1000.0, open_interest=oi)


def strat(**params):
    s = LiquidityOIStrategy()
    return s, s.validate_params(params)


def run(s, candles, params):
    """Feed candles one by one (history grows), return list of (idx, Signal)."""
    out = []
    for i in range(len(candles)):
        sig = s.on_candle(candles[i], candles[: i + 1], params)
        # contract: never sees the future
        assert candles[: i + 1][-1].timestamp == candles[i].timestamp
        out.append((i, sig))
    return out


# ------------------------------------------------------------ bullish setup ---

def test_bullish_sweep_reclaim_with_oi_fires_long():
    # 5-candle lookback. Prior lows all 100; candle 5 dips to 99 (sweep), closes 100.5 (reclaim), OI +3%
    hist = [
        c(0, 100, 100.5, 100, 100.2, oi=10000),
        c(1, 100, 100.5, 100, 100.1, oi=10000),
        c(2, 100, 100.5, 100, 100.3, oi=10000),
        c(3, 100, 100.5, 100, 100.2, oi=10000),
        c(4, 100, 100.5, 100, 100.1, oi=10000),
        c(5, 100, 100.2, 99.0, 100.5, oi=10300),  # sweep low 99 < 100, reclaim close 100.5 > 100, OI +3%
    ]
    s, p = strat(lookback=5, oi_threshold=2.5)
    sigs = run(s, hist, p)
    assert sigs[5][1].type is SignalType.LONG
    assert sigs[5][1].stop_loss == 99.0  # SL below sweep wick


def test_bullish_no_oi_confirmation_no_signal():
    # same sweep+reclaim but OI change below threshold
    hist = [
        c(0, 100, 100.5, 100, 100.2, oi=10000),
        c(1, 100, 100.5, 100, 100.1, oi=10000),
        c(2, 100, 100.5, 100, 100.3, oi=10000),
        c(3, 100, 100.5, 100, 100.2, oi=10000),
        c(4, 100, 100.5, 100, 100.1, oi=10000),
        c(5, 100, 100.2, 99.0, 100.5, oi=10100),  # OI +1% < 2.5%
    ]
    s, p = strat(lookback=5, oi_threshold=2.5)
    assert run(s, hist, p)[5][1].type is SignalType.NONE


def test_sweep_without_reclaim_no_signal():
    # dips below low but closes below the level (no reclaim)
    hist = [c(i, 100, 100.5, 100, 100.1, oi=10000) for i in range(5)] + \
           [c(5, 100, 100.2, 99.0, 99.2, oi=10300)]  # close 99.2 < level 100
    s, p = strat(lookback=5)
    assert run(s, hist, p)[5][1].type is SignalType.NONE


# ------------------------------------------------------------ bearish setup ---

def test_bearish_sweep_reject_with_oi_fires_short():
    # prior highs all 101, prior lows all 100. Candle 5 sweeps the HIGH (102>101)
    # and rejects (close 100.2 < 101) but its low (100.1) stays ABOVE the prior
    # low (100) so it is NOT also a bullish sweep. OI +3%.
    hist = [c(i, 100.5, 101, 100, 100.4, oi=10000) for i in range(5)] + \
           [c(5, 100.8, 102.0, 100.1, 100.2, oi=10300)]
    s, p = strat(lookback=5, oi_threshold=2.5)
    sig = run(s, hist, p)[5][1]
    assert sig.type is SignalType.SHORT
    assert sig.stop_loss == 102.0  # SL above sweep wick


def test_bearish_falling_oi_confirms_when_configured():
    # oi_direction=falling_confirms: a 3% OI drop should confirm; low stays > prior low
    hist = [c(i, 100.5, 101, 100, 100.4, oi=10000) for i in range(5)] + \
           [c(5, 100.8, 102.0, 100.1, 100.2, oi=9700)]
    s, p = strat(lookback=5, oi_threshold=2.5, oi_direction="falling_confirms")
    assert run(s, hist, p)[5][1].type is SignalType.SHORT


# ------------------------------------------------------------- OI handling ---

def test_missing_oi_blocks_signal_when_required():
    hist = [c(i, 100, 100.5, 100, 100.2) for i in range(5)] + [c(5, 100, 100.2, 99.0, 100.5)]
    s, p = strat(lookback=5, oi_required=True)
    assert run(s, hist, p)[5][1].type is SignalType.NONE


def test_missing_oi_allows_signal_when_not_required():
    hist = [c(i, 100, 100.5, 100, 100.2) for i in range(5)] + [c(5, 100, 100.2, 99.0, 100.5)]
    s, p = strat(lookback=5, oi_required=False)
    assert run(s, hist, p)[5][1].type is SignalType.LONG


# ------------------------------------------------------- lookback boundary ---

def test_level_excludes_current_candle():
    # current candle's own low must NOT count toward the level
    # (if it did, the sweep could never trigger because level == current low)
    hist = [c(i, 100, 100.5, 100, 100.2, oi=10000) for i in range(5)] + \
           [c(5, 100, 100.2, 99.0, 100.5, oi=10300)]
    s, p = strat(lookback=5)
    assert run(s, hist, p)[5][1].type is SignalType.LONG  # only fires if level=100 (prior), not 99


def test_insufficient_history_no_signal():
    hist = [c(i, 100, 100.5, 100, 100.2, oi=10000) for i in range(3)]  # < lookback+1
    s, p = strat(lookback=5)
    assert all(sig.type is SignalType.NONE for _, sig in run(s, hist, p))


# ------------------------------------------------------------ multi-candle ---

def test_sweep_lookahead_two_candles():
    # sweep on candle 4, reclaim on candle 5 (sweep_lookahead=2)
    # lookback=3 -> level from candles 0..2 (lows 100); sweep window = candles 4,5
    hist = [c(i, 100, 100.5, 100, 100.2, oi=10000) for i in range(3)] + [
        c(3, 100, 100.4, 100, 100.1, oi=10000),    # idx 3: still inside level window (history[-(3+2):-2])
        c(4, 100, 100.3, 99.0, 99.5, oi=10000),   # idx 4: sweep below 100, no reclaim yet
        c(5, 99.5, 100.6, 99.4, 100.5, oi=10300),  # idx 5: reclaim above 100, OI +3%
    ]
    s1, p1 = strat(lookback=3, sweep_lookahead=1)
    assert run(s1, hist, p1)[5][1].type is SignalType.NONE  # too late with lookahead=1
    s2, p2 = strat(lookback=3, sweep_lookahead=2)
    assert run(s2, hist, p2)[5][1].type is SignalType.LONG  # fires with lookahead=2


# ------------------------------------------------------------- validation ---

def test_param_validation_rejects_bad_values():
    s = LiquidityOIStrategy()
    with pytest.raises(ValueError):
        s.validate_params({"lookback": 0})
    with pytest.raises(ValueError):
        s.validate_params({"oi_direction": "bogus"})
    with pytest.raises(ValueError):
        s.validate_params({"reclaim_mode": "bogus"})
