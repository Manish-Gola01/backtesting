# Strategy Specification — Liquidity Sweep + Open Interest

> Status: **specification** (implemented in Phase 5). Nothing here claims
> profitability; every parameter is configurable and must be validated with
> real historical data.

---

## 1. Concept

Stop hunts cluster around obvious swing highs/lows. A **liquidity sweep**
occurs when price briefly trades beyond a well-watched level (triggering
stops) and then **reclaims** it — evidence the breakout lacked conviction.
We combine this price pattern with an **Open Interest (OI)** confirmation:
derivatives positioning must move in the expected direction by at least a
threshold, filtering sweeps that had no real participation.

---

## 2. Definitions

Candles: $c_t = (T_t, O_t, H_t, L_t, C_t, V_t, OI_t)$, ascending in time.
Lookback: $N$ (default 20). All levels are computed from **strictly prior**
candles — candle $t$ never contributes to its own reference level.

### Liquidity levels (at close of candle $t$)

$$L_t^{low} = \min\{L_{t-N}, \dots, L_{t-1}\}, \qquad
L_t^{high} = \max\{H_{t-N}, \dots, H_{t-1}\}$$

### OI percentage change

$$\Delta OI_t \;=\; \frac{OI_t - OI_{t-1}}{OI_{t-1}} \times 100$$

Requires $OI_{t-1} > 0$; otherwise the OI condition is **undefined** and
handled per `oi_missing_policy` (§6).

---

## 3. Bullish setup (LONG)

At the **close** of candle $t$:

| Step | Condition | Parameter |
|---|---|---|
| 1. Level | $L_t^{low}$ well-defined ($t \geq N$) | `lookback` $N$ |
| 2. Sweep | $L_t < L_t^{low}$ (wick below the level) | — |
| 3. Reclaim | $C_t > L_t^{low}$ (close back above) | `reclaim_mode`: `close_above` (default), `close_above_body`, `pct_reclaim` |
| 4. OI confirm | $\Delta OI_t \geq \theta_{OI}$ | `oi_threshold` $\theta$ (default 2.5), `oi_direction` |
| 5. Signal | LONG at close of $t$ | — |
| 6. Entry | $\text{fill} = O_{t+1} \times (1 + s)$ | `execution_model`: `next_open` (default); $s$ = `slippage_pct` |

**Stop loss** (configurable, default 1%): $SL = P_e \times (1 - x_{SL})$.
Alternative mode `swing`: $SL = L_t - \delta$ (below the sweep wick).
**Take profit** (default 2%): $TP = P_e \times (1 + x_{TP})$, or
`risk_reward` mode: $TP = P_e + R \times (P_e - SL)$.

## 4. Bearish setup (SHORT) — exact mirror

1. $L_t^{high}$ from prior $N$ candles.
2. Sweep: $H_t > L_t^{high}$.
3. Reject: $C_t < L_t^{high}$.
4. OI confirm: $\Delta OI_t \geq \theta_{OI}$ (sign per `oi_direction`).
5. SHORT at close of $t$ → fill $= O_{t+1} \times (1 - s)$.
6. $SL = P_e (1 + x_{SL})$, $TP = P_e (1 - x_{TP})$.

---

## 5. Parameters (all configurable — nothing hard-coded)

| Parameter | Default | Notes |
|---|---|---|
| `lookback` | 20 | candles used for swing level |
| `oi_threshold` | 2.5 | percent |
| `oi_direction` | `rising_confirms` | `rising_confirms` \| `falling_confirms` \| `either` |
| `oi_required` | true | if true and OI missing → strategy ineligible (error, not fabrication) |
| `reclaim_mode` | `close_above` | see §3 |
| `sweep_lookahead` | 1 | candles allowed between sweep and reclaim (>1 = multi-candle pattern) |
| `execution_model` | `next_open` | `next_open` \| `signal_close` (documented as aggressive) |
| `stop_loss_percent` | 1.0 | or `stop_mode: swing` |
| `take_profit_percent` | 2.0 | or `risk_reward: R` |
| `slippage_pct` | 0.0 | applied on entry and exit |
| `intrabar_policy` | `conservative` | same-candle SL/TP resolution (§7) |

## 6. OI availability rules

- Instruments are declared with or without OI (`has_oi`).
- `open_interest IS NULL` in any candle ⇒ OI condition **undefined** for that
  candle.
- If `oi_required = true`: the strategy refuses to run on OI-less data with a
  clear error. If `false`: the OI filter is skipped and every result is
  labelled `"oi_filter": "disabled"`.
- The platform **never synthesizes** OI values.

## 7. Same-candle SL/TP

If a candle's range touches both SL and TP, the fill order is unknowable from
OHLC alone. Policy `intrabar_policy`:

- `conservative` (default): SL first — worst case.
- `optimistic`: TP first — best case.
- `lower_timeframe`: resolve from finer data when provided; else fall back to
  `conservative`.

The chosen policy is stored on the backtest record and printed on reports.

## 8. Look-ahead rules (hard constraints)

1. Levels use candles $< t$ only (off-by-one errors are the classic bug —
   the level of candle $t$ excludes candle $t$).
2. Signal is emitted at the **close** of $t$; the engine fills at $t+1$ open.
3. Indicators (OI delta included) use $\leq t$ data only.
4. Phase 10 adds automated tests: synthetic future spikes must never change
   an earlier signal.

## 9. Worked example (bullish)

$N{=}5$, prior lows $= \{100.2, 99.8, 100.0, 100.5, 100.1\}$ ⇒
$L_t^{low} = 99.8$.
Candle $t$: $L_t = 99.5 < 99.8$ (sweep), $C_t = 100.1 > 99.8$ (reclaim).
$OI_{t-1} = 10{,}000$, $OI_t = 10{,}300$ ⇒ $\Delta OI_t = 3.0\% \geq 2.5\%$ ✓
⇒ LONG signal at close of $t$; entry $= O_{t+1} \times 1.000$ (slippage 0).
With $O_{t+1} = 100.3$: $SL = 99.297$, $TP = 102.306$.

## 10. Known limitations (disclosed on every report)

- Intrabar sequence ambiguity (§7).
- OI interpretation is regime-dependent; the sign convention is a hypothesis,
  not a law — hence configurable.
- Sweep/reclaim within one candle is a simplification; `sweep_lookahead > 1`
  models multi-candle patterns at the cost of fewer signals.
