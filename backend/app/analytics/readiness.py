"""Live Trading Readiness assessment (research evidence, NOT a profitability guarantee).

Produces a multi-dimensional readiness report from a completed backtest:
- statistical sufficiency (enough trades to mean anything)
- consistency (win distribution, not one lucky trade)
- out-of-sample robustness (walk-forward agreement when run)
- overfitting risk (in-sample vs out-of-sample degradation)
- risk profile (drawdown, consecutive losses vs limits)
- current proof of profitability (evaluates empirical edge vs live requirements)

Every check is evidence-based from the actual trades/metrics. The final verdict
is a READINESS SCORE, and it always carries a hard disclaimer: a profitable
backtest is NOT proof of future profitability.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

DISCLAIMER = (
    "This is a RESEARCH readiness assessment derived from historical backtest "
    "evidence only. It is NOT investment advice and NOT a guarantee or proof of "
    "future profitability. Live trading involves execution, slippage, liquidity, "
    "latency, and regime risks a backtest cannot fully model."
)

# minimum sample sizes before we trust any statistic
_MIN_TRADES_STATS = 30
_MIN_TRADES_ANY = 5


@dataclass
class Check:
    name: str
    passed: bool
    value: Any
    note: str = ""

    def __post_init__(self) -> None:
        # numpy.bool_ / numpy scalars are not JSON-serializable -> force native types
        self.passed = bool(self.passed)
        if isinstance(self.value, bool):
            pass
        elif hasattr(self.value, "item"):  # numpy scalar
            try:
                self.value = self.value.item()
            except Exception:
                pass


def _g(x, default=None):
    return x if x is not None else default


def assess_readiness(
    metrics: dict,
    trades: list,
    *,
    oos_metrics: Optional[dict] = None,   # out-of-sample metrics if walk-forward was run
    max_drawdown_limit: Optional[float] = None,
) -> dict:
    """Return a readiness report. `oos_metrics` is the held-out / walk-forward
    metric set; without it, out-of-sample robustness is reported as UNKNOWN
    (never assumed)."""
    checks: list[Check] = []
    # Coerce to native floats — pandas/numpy values are not JSON-serializable.
    nets = [float(t.net_pnl) for t in trades]
    metrics = {k: (float(v) if isinstance(v, (int, float)) and v is not None else v) for k, v in metrics.items()}
    n = len(nets)

    # 1. Statistical sufficiency -------------------------------------------
    checks.append(Check(
        "sample_size", n >= _MIN_TRADES_STATS, n,
        f"{n} trades; need >= {_MIN_TRADES_STATS} for statistical confidence"
        + ("" if n >= _MIN_TRADES_STATS else (f" (only {n} — far too few)" if n < _MIN_TRADES_ANY else " — marginal)")),
    ))

    # 2. Net profitability (in-sample) --------------------------------------
    net = _g(metrics.get("net_profit"), 0.0)
    checks.append(Check("profitable_in_sample", net > 0, round(net, 2),
                        "net profit must be positive after all costs"))

    # 3. Expectancy -----------------------------------------------------------
    exp = metrics.get("expectancy")
    checks.append(Check("positive_expectancy", (exp is not None and exp > 0),
                        round(exp, 2) if exp is not None else None,
                        "average net per trade must be > 0"))

    # 4. Consistency — not one lucky trade ----------------------------------
    if nets and net > 0:
        best = max(nets)
        concentration = best / net if net > 0 else 1.0
        consistent = concentration < 0.5 and n >= 5
        checks.append(Check("consistency", consistent, round(concentration, 2),
                            f"largest winner is {concentration*100:.0f}% of net profit; "
                            f"{'OK' if concentration < 0.5 else 'too concentrated in one trade'}"))
    else:
        checks.append(Check("consistency", False, None, "no profitable trades to assess"))

    # 5. Risk: drawdown -------------------------------------------------------
    mdd_pct = metrics.get("max_drawdown_pct")
    dd_ok = (mdd_pct is not None and mdd_pct <= 25.0)
    checks.append(Check("drawdown", dd_ok, round(mdd_pct, 2) if mdd_pct is not None else None,
                        f"max drawdown {mdd_pct:.1f}% (guideline <= 25%)" if mdd_pct is not None else "no drawdown data"))

    # 6. Risk: consecutive losses vs a sanity bound --------------------------
    cons_l = metrics.get("max_consecutive_losses") or 0
    checks.append(Check("loss_streak", cons_l <= 8, cons_l,
                        f"max consecutive losses {cons_l}; a live account must survive this streak"))

    # 7. Out-of-sample robustness --------------------------------------------
    if oos_metrics is not None:
        oos_net = _g(oos_metrics.get("net_profit"), 0.0)
        oos_ok = oos_net > 0
        # overfitting signal: OOS sharply worse than in-sample
        degrad = None
        if net > 0 and oos_net is not None:
            degrad = round((net - oos_net) / abs(net) * 100.0, 1)
        checks.append(Check("out_of_sample", oos_ok, round(oos_net, 2),
                            f"out-of-sample net {oos_net:.2f}; in-sample->OOS degradation {degrad}%"
                            if degrad is not None else f"out-of-sample net {oos_net:.2f}"))
    else:
        checks.append(Check("out_of_sample", False, None,
                            "NOT measured — run walk-forward / held-out test to assess (required before live)"))

    # 8. Current proof of profitability (empirical evidence status) ----------
    has_empirical_edge = bool(net > 0 and (exp is not None and exp > 0))
    checks.append(Check(
        "current_proof_of_profitability",
        has_empirical_edge,
        round(net, 2) if has_empirical_edge else 0.0,
        f"Empirical net profit {net:.2f} (expectancy {exp if exp is not None else 0:.2f}) observed in backtest. "
        + ("Provides historical evidence of edge; live execution validation (paper trading) is still required."
           if has_empirical_edge else "Zero or negative edge in backtest — profitability is NOT demonstrated."),
    ))

    # ---- score ---------------------------------------------------------------
    passed = sum(1 for c in checks if c.passed)
    total = len(checks)
    critical = {"sample_size", "out_of_sample", "profitable_in_sample"}
    critical_ok = all(c.passed for c in checks if c.name in critical)
    score = round(passed / total * 100)

    # A losing (or zero-edge) backtest is not ready regardless of OOS state.
    if net <= 0 or (exp is not None and exp <= 0):
        verdict = "NOT READY"
        verdict_note = "The backtest is not profitable after costs. Do not trade this configuration live."
    elif not any(c.name == "out_of_sample" and c.value is not None for c in checks):
        verdict = "INSUFFICIENT EVIDENCE"
        verdict_note = "Profitable in-sample, but out-of-sample validation has not been run. No live-readiness conclusion is possible without it."
    elif critical_ok and score >= 70:
        verdict = "RESEARCH-PROMISING"
        verdict_note = "Metrics look healthy on the evidence available, but this remains a backtest. Paper-trade first."
    elif net > 0 and n >= _MIN_TRADES_ANY:
        verdict = "NEEDS MORE VALIDATION"
        verdict_note = "Some evidence of edge, but sample size, consistency, or out-of-sample robustness is not yet sufficient."
    else:
        verdict = "NOT READY"
        verdict_note = "Does not meet the minimum evidence bar for live trading."

    return {
        "verdict": verdict,
        "verdict_note": verdict_note,
        "readiness_score": score,
        "checks_passed": passed,
        "checks_total": total,
        "checks": [
            {"name": c.name, "passed": c.passed, "value": c.value, "note": c.note} for c in checks
        ],
        "disclaimer": DISCLAIMER,
        "is_proof_of_profitability": False,  # a backtest can never be this — stated explicitly
        "live_trading_readiness": {
            "verdict": verdict,
            "verdict_note": verdict_note,
            "readiness_score": score,
            "checks_passed": passed,
            "checks_total": total,
            "critical_checks_passed": critical_ok,
        },
        "current_proof_of_profitability": {
            "has_empirical_edge": has_empirical_edge,
            "status": "HISTORICAL_EVIDENCE_ONLY" if has_empirical_edge else "NO_EDGE_DEMONSTRATED",
            "is_guaranteed_proof": False,
            "summary": (
                f"Historical backtest indicates positive edge (Net: {net:+.2f}, Expectancy: {exp if exp is not None else 0:+.2f}), "
                "providing empirical research evidence under modelled conditions. "
                "However, backtest performance does NOT constitute mathematical proof of future live profitability. "
                "Execution factors (slippage, queue latency, regime change) require paper-trading validation."
                if has_empirical_edge else
                f"Net profit is non-positive ({net:.2f}). No empirical proof of profitability exists for this configuration."
            ),
            "live_validation_required": True,
            "recommended_next_step": (
                "Deploy on real-time paper trading before risking capital"
                if has_empirical_edge else "Refine strategy hypothesis or parameters before further testing"
            ),
        },
    }
