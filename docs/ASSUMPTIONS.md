# Assumptions, Ambiguities & Decisions

Every ambiguity found during design is listed here with the decision taken
and the knob that reopens it. Nothing is silently hard-coded.

## A. Data assumptions

1. **A1 — CSV as the initial source of truth.** Vendors/APIs plug in later
   behind the same data-layer interface.
   *Decision:* repository pattern; loaders are swappable.
2. **A2 — Timestamps are bar-start times, timezone-aware.** Mixed/naive
   timestamps in uploads are rejected with a clear error (Phase 2
   validation) rather than guessed.
3. **A3 — `open_interest` may be absent** (spot indices, equities).
   *Decision:* NULL = "no data"; never imputed. See STRATEGY.md §6.
4. **A4 — Corporate actions / contract rolls are out of scope** for the
   first version; adjusted series are the uploader's responsibility.
   *Reopen:* add an adjustment layer when futures continuous contracts are
   introduced.
5. **A5 — Survivorship bias**: single-instrument backtests can't avoid it;
   documented on reports. *Reopen:* universe/constituent tables later.

## B. Execution assumptions

6. **B1 — Entry at next candle open** after a signal close (default). This is
   the standard anti-look-ahead convention. *Knob:* `execution_model`.
7. **B2 — Intrabar path unknowable from OHLC.** *Decision:* configurable
   `intrabar_policy`, default `conservative`. See STRATEGY.md §7.
8. **B3 — Fills are full and immediate** at the modelled price; partial
   fills/queue position are out of scope for a candle-level engine.
9. **B4 — Slippage** modelled as a fixed percentage per side in Phase 4.
   *Reopen:* tick-based / volume-based slippage models later.

## C. Strategy ambiguities

10. **C1 — OI direction semantics.** Rising OI into a bullish reclaim can be
    read as long buildup (confirmation) or as new shorts trapped (also
    bullish). *Decision:* `oi_direction` parameter, default
    `rising_confirms`.
11. **C2 — Sweep and reclaim in one candle vs. several.** *Decision:*
    default single-candle; `sweep_lookahead` enables multi-candle patterns.
12. **C3 — Reclaim definition** (close above level vs. body above level vs.
    percentage reclaim). *Decision:* `reclaim_mode`, default `close_above`.
13. **C4 — Stop placement**: percentage vs. beyond sweep wick. *Decision:*
    `stop_mode: percent | swing`.

## D. Risk & accounting

14. **D1 — One open position per instrument** by default;
    `max_open_positions` governs the global cap.
15. **D2 — Position sizing models**: `fixed_qty`, `fixed_amount`,
    `pct_capital`, `risk_pct` (`qty = risk_amount / |entry − stop|`). Fractional
    quantities allowed in backtests; lot-size rounding is a config flag.
16. **D3 — Costs are always separate** from gross P&L: brokerage, slippage
    cost, and other charges are individual columns; `net = gross − Σcosts`.
17. **D4 — Compounding ON**: position sizing uses current equity, not
    initial capital. *Knob:* `compounding: true | false`.

## E. Platform

18. **E1 — Single-user initially**; auth-ready schema and DI hooks from
    Phase 1, enforcement in Phase 7.
19. **E2 — In-process background tasks** for jobs first; Celery/RQ + Redis
    behind the `JobRunner` interface when scale demands it.
20. **E3 — No fabricated data anywhere**: no demo backtests, no synthetic
    charts, no fake API responses. Empty states say "no data".

## F. Reproducibility rules (project-wide, non-negotiable)

- Full config snapshot stored per backtest; code is deterministic.
- Every computed number must be re-derivable from (data, config) alone.
- Any future randomness (e.g., optimizer tie-breaking) takes an explicit
  `seed` recorded in the config.

## G. Live Trading Readiness & Proof of Profitability

21. **G1 — Backtest edge is empirical evidence, NOT proof of future profit.**
    No matter how high the Sharpe ratio or net profit, historical backtests cannot
    model live liquidity crashes, broker execution latency, or non-stationary regime
    shifts. The engine explicitly flags `is_guaranteed_proof: false`.
22. **G2 — Mandatory sample size and out-of-sample gates.** Live readiness cannot be
    granted without at least 30 trades and verified out-of-sample / walk-forward performance.

