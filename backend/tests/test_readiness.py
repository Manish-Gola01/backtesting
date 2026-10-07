"""Readiness engine tests — honest, evidence-based, never fabricates profitability."""
from datetime import datetime, timedelta, timezone

from app.analytics.readiness import DISCLAIMER, assess_readiness
from app.backtesting.types import ExitReason, PositionSide, Trade

T0 = datetime(2024, 1, 1, 9, 15, tzinfo=timezone.utc)


def mk_trade(net, i):
    return Trade(trade_seq=i, symbol="T", strategy="s", side=PositionSide.LONG,
                 entry_time=T0, entry_price=100.0, exit_time=T0 + timedelta(minutes=1),
                 exit_price=101.0, quantity=1.0, stop_loss=99.0, take_profit=102.0,
                 gross_pnl=net, brokerage=0.0, slippage_cost=0.0, other_costs=0.0,
                 net_pnl=net, pnl_pct=net / 100, exit_reason=ExitReason.TAKE_PROFIT, holding_seconds=60)


def strong_metrics(n=40):
    trades = [mk_trade(50 if i % 4 else -30, i) for i in range(n)]  # mostly winners, net positive
    nets = [t.net_pnl for t in trades]
    return {
        "net_profit": sum(nets), "expectancy": sum(nets) / n, "max_drawdown_pct": 12.0,
        "max_consecutive_losses": 2, "total_trades": n,
    }, trades


def test_disclaimer_always_present_and_no_proof():
    m, tr = strong_metrics()
    r = assess_readiness(m, tr)
    assert r["disclaimer"] == DISCLAIMER
    assert r["is_proof_of_profitability"] is False


def test_too_few_trades_not_ready():
    trades = [mk_trade(100, i) for i in range(3)]  # only 3 trades
    m = {"net_profit": 300, "expectancy": 100, "max_drawdown_pct": 5, "max_consecutive_losses": 0, "total_trades": 3}
    r = assess_readiness(m, trades)
    sample = next(c for c in r["checks"] if c["name"] == "sample_size")
    assert sample["passed"] is False
    assert r["verdict"] in ("INSUFFICIENT EVIDENCE", "NEEDS MORE VALIDATION", "NOT READY")


def test_no_oos_means_insufficient_evidence():
    m, tr = strong_metrics()
    r = assess_readiness(m, tr, oos_metrics=None)  # no out-of-sample run
    oos = next(c for c in r["checks"] if c["name"] == "out_of_sample")
    assert oos["passed"] is False
    assert "walk-forward" in oos["note"].lower() or "held-out" in oos["note"].lower()
    assert r["verdict"] == "INSUFFICIENT EVIDENCE"


def test_strong_insample_plus_oos_promising():
    m, tr = strong_metrics()
    oos = {"net_profit": 800.0}  # positive OOS
    r = assess_readiness(m, tr, oos_metrics=oos)
    oos_check = next(c for c in r["checks"] if c["name"] == "out_of_sample")
    assert oos_check["passed"] is True
    assert r["verdict"] == "RESEARCH-PROMISING"
    assert r["readiness_score"] >= 70


def test_oos_loss_flags_overfitting_and_blocks_promising():
    m, tr = strong_metrics()  # strong in-sample
    oos = {"net_profit": -500.0}  # but loses out-of-sample
    r = assess_readiness(m, tr, oos_metrics=oos)
    oos_check = next(c for c in r["checks"] if c["name"] == "out_of_sample")
    assert oos_check["passed"] is False
    assert r["verdict"] != "RESEARCH-PROMISING"


def test_one_lucky_trade_fails_consistency():
    # 1 huge winner + many tiny losers, net positive but concentrated
    trades = [mk_trade(1000, 0)] + [mk_trade(-10, i) for i in range(1, 40)]
    nets = [t.net_pnl for t in trades]
    m = {"net_profit": sum(nets), "expectancy": sum(nets) / 40, "max_drawdown_pct": 8, "max_consecutive_losses": 5, "total_trades": 40}
    r = assess_readiness(m, trades)
    cons = next(c for c in r["checks"] if c["name"] == "consistency")
    assert cons["passed"] is False


def test_losing_backtest_not_ready():
    trades = [mk_trade(-20, i) for i in range(40)]
    m = {"net_profit": -800, "expectancy": -20, "max_drawdown_pct": 30, "max_consecutive_losses": 40, "total_trades": 40}
    r = assess_readiness(m, trades)
    assert r["verdict"] == "NOT READY"
    assert r["readiness_score"] < 50


def test_live_trading_readiness_structure():
    m, tr = strong_metrics()
    r = assess_readiness(m, tr)
    ltr = r["live_trading_readiness"]
    assert "verdict" in ltr
    assert "readiness_score" in ltr
    assert "checks_passed" in ltr
    assert "checks_total" in ltr
    assert "critical_checks_passed" in ltr
    assert ltr["readiness_score"] == r["readiness_score"]


def test_current_proof_of_profitability_empirical_edge():
    m, tr = strong_metrics()
    r = assess_readiness(m, tr)
    pop = r["current_proof_of_profitability"]
    assert pop["has_empirical_edge"] is True
    assert pop["status"] == "HISTORICAL_EVIDENCE_ONLY"
    assert pop["is_guaranteed_proof"] is False
    assert pop["live_validation_required"] is True
    assert "paper" in pop["recommended_next_step"].lower()

    chk = next(c for c in r["checks"] if c["name"] == "current_proof_of_profitability")
    assert chk["passed"] is True
    assert "empirical net profit" in chk["note"].lower()


def test_current_proof_of_profitability_losing():
    trades = [mk_trade(-20, i) for i in range(40)]
    m = {"net_profit": -800, "expectancy": -20, "max_drawdown_pct": 30, "max_consecutive_losses": 40, "total_trades": 40}
    r = assess_readiness(m, trades)
    pop = r["current_proof_of_profitability"]
    assert pop["has_empirical_edge"] is False
    assert pop["status"] == "NO_EDGE_DEMONSTRATED"
    assert pop["is_guaranteed_proof"] is False
    chk = next(c for c in r["checks"] if c["name"] == "current_proof_of_profitability")
    assert chk["passed"] is False
