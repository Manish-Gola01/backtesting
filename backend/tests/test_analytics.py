"""Analytics tests — every metric verified against hand-computed values."""
from datetime import datetime, timedelta, timezone

import pytest

from app.analytics import compute_metrics, max_drawdown, period_returns, sharpe_ratio, sortino_ratio
from app.backtesting.engine import BacktestResult
from app.backtesting.types import EquityPoint, ExitReason, PositionSide, Trade

T0 = datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc)


def eq(vals, start=T0, step_min=1):
    return [EquityPoint(timestamp=start + timedelta(minutes=step_min * i), equity=v) for i, v in enumerate(vals)]


def trade(net, hold=60, i=0):
    return Trade(
        trade_seq=i, symbol="T", strategy="s", side=PositionSide.LONG,
        entry_time=T0, entry_price=100.0, exit_time=T0 + timedelta(seconds=hold),
        exit_price=101.0, quantity=10.0, stop_loss=99.0, take_profit=102.0,
        gross_pnl=net + 0.0, brokerage=0.0, slippage_cost=0.0, other_costs=0.0,
        net_pnl=net, pnl_pct=net / 1000 * 100, exit_reason=ExitReason.TAKE_PROFIT,
        holding_seconds=hold,
    )


def result(trades, equity_vals, initial=100000.0):
    final = equity_vals[-1] if equity_vals else initial
    return BacktestResult(config={}, symbol="T", timeframe="1m", strategy="s",
                          candles=len(equity_vals), trades=trades, equity_curve=eq(equity_vals),
                          initial_capital=initial, final_equity=final)


# ------------------------------------------------------------- trade stats ---

def test_win_rate_and_counts():
    trades = [trade(100), trade(200), trade(-50), trade(-50), trade(150)]
    m = compute_metrics(result(trades, [100000, 100100, 100300, 100250, 100200, 100350]))
    assert m["total_trades"] == 5
    assert m["winning_trades"] == 3
    assert m["losing_trades"] == 2
    assert m["win_rate"] == pytest.approx(60.0)


def test_avg_winner_loser_and_extremes():
    trades = [trade(100), trade(300), trade(-50), trade(-150)]
    m = compute_metrics(result(trades, [100000, 100050]))
    assert m["avg_winning_trade"] == pytest.approx(200.0)
    assert m["avg_losing_trade"] == pytest.approx(-100.0)
    assert m["largest_winner"] == 300
    assert m["largest_loser"] == -150


def test_profit_factor_and_expectancy():
    trades = [trade(300), trade(-100), trade(200), trade(-100)]  # GP=500, GL=200
    m = compute_metrics(result(trades, [100000, 100300]))
    assert m["profit_factor"] == pytest.approx(2.5)
    assert m["expectancy"] == pytest.approx(75.0)  # mean net = (300-100+200-100)/4


def test_consecutive_streaks():
    trades = [trade(10), trade(20), trade(-5), trade(30), trade(40), trade(50), trade(-1)]
    m = compute_metrics(result(trades, [100000, 100149]))
    assert m["max_consecutive_wins"] == 3
    assert m["max_consecutive_losses"] == 1


def test_avg_holding_time():
    trades = [trade(10, hold=60), trade(20, hold=180)]
    m = compute_metrics(result(trades, [100000, 100030]))
    assert m["avg_holding_seconds"] == pytest.approx(120.0)


def test_empty_trades_ratio_fields_none_not_zero():
    m = compute_metrics(result([], [100000, 100000]))
    assert m["total_trades"] == 0
    assert m["win_rate"] is None
    assert m["profit_factor"] is None
    assert m["expectancy"] is None


def test_all_winners_profit_factor_infinite():
    m = compute_metrics(result([trade(100), trade(50)], [100000, 100150]))
    assert m["profit_factor"] == float("inf")


# ------------------------------------------------------------------ capital ---

def test_net_profit_and_pct():
    m = compute_metrics(result([trade(5000)], [100000, 105000], initial=100000.0))
    assert m["net_profit"] == pytest.approx(5000.0)
    assert m["net_profit_pct"] == pytest.approx(5.0)
    assert m["final_capital"] == 105000.0


# ------------------------------------------------------------------ drawdown ---

def test_max_drawdown_absolute_and_pct():
    # peak 110000, trough 99000 -> dd 11000, ~10% of peak
    e = eq([100000, 110000, 99000, 105000])
    mdd, mdd_pct = max_drawdown(e)
    assert mdd == pytest.approx(11000.0)
    assert mdd_pct == pytest.approx(11000 / 110000 * 100)


# ---------------------------------------------------------------- Sharpe ---

def test_sharpe_none_on_flat_equity():
    assert sharpe_ratio(eq([100000, 100000, 100000])) is None  # zero variance


def test_sharpe_positive_on_rising_equity():
    e = eq([100000 * (1.0001 ** i) for i in range(50)])
    s = sharpe_ratio(e)
    assert s is not None and s > 0


def test_sortino_none_when_no_downside():
    e = eq([100000 + 100 * i for i in range(30)])  # monotonic up
    assert sortino_ratio(e) is None  # no negative returns


def test_sortino_present_with_downside():
    e = eq([100000, 100500, 100200, 100800, 100400, 101000])
    assert sortino_ratio(e) is not None


# ----------------------------------------------------------- period returns ---

def test_daily_returns():
    start = datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc)
    # two days: day1 100->110 (+10%), day2 110->121 (+10%)
    e = [
        EquityPoint(start, 100.0), EquityPoint(start + timedelta(hours=1), 110.0),
        EquityPoint(start + timedelta(days=1), 110.0), EquityPoint(start + timedelta(days=1, hours=1), 121.0),
    ]
    dr = period_returns(e, "daily")
    assert list(dr.values()) == pytest.approx([10.0, 10.0])


def test_monthly_and_yearly_returns():
    start = datetime(2024, 1, 31, 9, 15, tzinfo=timezone.utc)
    e = [
        EquityPoint(start, 100.0),
        EquityPoint(datetime(2024, 2, 29, 9, 15, tzinfo=timezone.utc), 110.0),
        EquityPoint(datetime(2024, 3, 31, 9, 15, tzinfo=timezone.utc), 99.0),
    ]
    mr = period_returns(e, "monthly")
    assert list(mr.values())[0] == pytest.approx(0.0)     # Jan flat (single point)
    assert list(mr.values())[1] == pytest.approx(10.0)    # Feb +10%
    assert list(mr.values())[2] == pytest.approx(-10.0)   # Mar -10%
    yr = period_returns(e, "yearly")
    assert list(yr.values())[0] == pytest.approx(-1.0)    # 100 -> 99 over 2024


def test_weekly_returns_bucketed():
    start = datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc)  # Monday, ISO week 1
    e = [EquityPoint(start, 100.0),
         EquityPoint(start + timedelta(days=3), 105.0),   # same ISO week
         EquityPoint(start + timedelta(days=8), 115.5)]   # next ISO week
    wr = period_returns(e, "weekly")
    assert list(wr.values()) == pytest.approx([5.0, 10.0])
