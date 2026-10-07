"""Walk-forward testing (spec §22): Train -> Validate -> Test, roll, repeat.

A walk-forward run re-optimizes on each training window and evaluates the next
out-of-sample window, then aggregates out-of-sample performance — the honest
estimate of live behaviour. No test window is ever used for selection.
"""
from __future__ import annotations

import itertools
import logging
from typing import Any

from app.analytics import compute_metrics
from app.analytics.optimize import OVERFITTING_WARNING
from app.backtesting import run_backtest
from app.backtesting.registry import get_strategy
from app.services.backtest_service import _build_config

logger = logging.getLogger(__name__)


def _best_params_on_train(train_frame, base_request, param_grid, rank_by, strategy):
    combos = [dict(zip(param_grid, c)) for c in itertools.product(*param_grid.values())]
    best, best_score = None, None
    for params in combos:
        try:
            cfg = _build_config({**base_request, "params": params})
            m = compute_metrics(run_backtest(train_frame, strategy, cfg))
        except Exception:
            continue
        score = m.get(rank_by)
        if score is None or score != score:  # None/NaN
            continue
        if best_score is None or score > best_score:
            best, best_score = params, score
    return best


def walk_forward(
    frame,
    base_request: dict,
    param_grid: dict,
    *,
    train_size: int,
    test_size: int,
    rank_by: str = "sharpe_ratio",
    anchored: bool = False,
) -> dict:
    """Roll a (train, test) window across the data.

    train_size/test_size are candle counts. anchored=True grows the train
    window from the start each step; otherwise it slides.
    Returns per-window results + aggregated out-of-sample metrics.
    """
    n = len(frame)
    strategy = get_strategy(base_request["strategy"])
    windows = []
    start = 0
    step = test_size
    w = 0
    while True:
        tr_end = start + train_size
        te_end = tr_end + test_size
        if te_end > n:
            break
        tr = frame.iloc[start:tr_end].reset_index(drop=True)
        te = frame.iloc[tr_end:te_end].reset_index(drop=True)

        # select best params on the TRAIN window only (test never used)
        best_params = _best_params_on_train(tr, base_request, param_grid, rank_by, strategy)
        if best_params is None:
            start = start + (0 if anchored else step)
            continue

        # evaluate the chosen params on the out-of-sample test window
        req = {**base_request, "params": best_params}
        cfg = _build_config(req)
        res = run_backtest(te, strategy, cfg)
        m = compute_metrics(res)
        windows.append({
            "window": w,
            "train_range": [int(start), int(tr_end)],
            "test_range": [int(tr_end), int(te_end)],
            "best_params": best_params,
            "test_metrics": {k: m.get(k) for k in ("total_trades", "net_profit", "win_rate", "sharpe_ratio", "max_drawdown_pct")},
        })
        w += 1
        start = start + (0 if anchored else step)

    # aggregate out-of-sample
    if windows:
        nets = [x["test_metrics"]["net_profit"] or 0 for x in windows]
        agg = {
            "windows": len(windows),
            "total_oos_net_profit": sum(nets),
            "avg_oos_net_profit": sum(nets) / len(nets),
            "positive_windows": sum(1 for x in nets if x > 0),
        }
    else:
        agg = {"windows": 0}

    logger.info("walk-forward: %d windows, oos net=%.2f", agg.get("windows", 0), agg.get("total_oos_net_profit", 0.0))
    return {"windows": windows, "aggregate": agg, "warning": OVERFITTING_WARNING}
