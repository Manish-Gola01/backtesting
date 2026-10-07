"""Parameter optimization (spec §23) + train/validation/test splits (§21).

Grid-searches parameter combinations over TRAINING data only, ranks by a
chosen metric, and evaluates the top set on held-out validation/test data.
Includes explicit overfitting warnings — the best historical parameter is NOT
claimed to be the best live parameter.
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import Any, Optional

from app.analytics import compute_metrics
from app.backtesting import BacktestConfig, run_backtest
from app.backtesting.registry import get_strategy

logger = logging.getLogger(__name__)

OVERFITTING_WARNING = (
    "Parameters were selected on historical (in-sample) data. Past-optimal "
    "parameters frequently fail out-of-sample; treat the ranking as a research "
    "signal, not a guarantee. Always validate on held-out data and prefer "
    "walk-forward analysis before trusting a configuration live."
)


@dataclass
class SplitData:
    train: Any
    validation: Any
    test: Any


def split_data(frame, train=0.6, validation=0.2, test=0.2) -> SplitData:
    """Chronological (no shuffle) split — shuffling would leak the future."""
    assert abs(train + validation + test - 1.0) < 1e-9, "splits must sum to 1.0"
    n = len(frame)
    i_tr = int(n * train)
    i_va = i_tr + int(n * validation)
    return SplitData(
        train=frame.iloc[:i_tr].reset_index(drop=True),
        validation=frame.iloc[i_tr:i_va].reset_index(drop=True),
        test=frame.iloc[i_va:].reset_index(drop=True),
    )


def _grid(param_grid: dict[str, list]) -> list[dict]:
    keys = list(param_grid)
    return [dict(zip(keys, combo)) for combo in itertools.product(*(param_grid[k] for k in keys))]


def optimize(
    frame,
    base_request: dict,
    param_grid: dict[str, list],
    *,
    rank_by: str = "sharpe_ratio",
    split: tuple[float, float, float] = (0.6, 0.2, 0.2),
    max_combinations: int = 1000,
) -> dict:
    """Grid-search params on the TRAIN slice; report validation/test for the best.

    Returns {ranking, best, out_of_sample, warning}. Never runs the test slice
    during selection (no test-set leakage).
    """
    combos = _grid(param_grid)
    if len(combos) > max_combinations:
        raise ValueError(f"{len(combos)} combinations exceeds cap {max_combinations}")

    data = split_data(frame, *split)
    strategy_name = base_request["strategy"]
    strategy = get_strategy(strategy_name)

    def run_on(slice_frame, params):
        from app.services.backtest_service import _build_config
        req = {**base_request, "params": params}
        cfg: BacktestConfig = _build_config(req)
        res = run_backtest(slice_frame, strategy, cfg)
        m = compute_metrics(res, risk_free_rate=float(req.get("risk_free_rate", 0.0)))
        return res, m

    ranking = []
    for params in combos:
        try:
            _, m = run_on(data.train, params)
        except Exception as exc:
            logger.debug("combo %s failed: %s", params, exc)
            continue
        score = m.get(rank_by)
        ranking.append({
            "params": params,
            "rank_metric": rank_by,
            "score": (None if score is None or score != score else score),  # NaN->None
            "train": {k: m.get(k) for k in ("total_trades", "net_profit", "win_rate", "profit_factor", "max_drawdown_pct", "sharpe_ratio")},
        })

    # sort: None scores last
    ranking.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
    best = ranking[0] if ranking else None

    oos = None
    if best is not None:
        _, vm = run_on(data.validation, best["params"])
        _, tm = run_on(data.test, best["params"])
        oos = {
            "validation": {k: vm.get(k) for k in ("total_trades", "net_profit", "win_rate", "sharpe_ratio")},
            "test": {k: tm.get(k) for k in ("total_trades", "net_profit", "win_rate", "sharpe_ratio")},
        }

    logger.info("optimization: %d combos, best score=%s", len(ranking), best["score"] if best else None)
    return {
        "combinations_tested": len(ranking),
        "rank_by": rank_by,
        "best": best,
        "out_of_sample": oos,
        "ranking": ranking,
        "warning": OVERFITTING_WARNING,
    }
