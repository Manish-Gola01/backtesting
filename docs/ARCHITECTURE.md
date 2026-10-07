# System Architecture

This document is the authoritative architecture reference for the platform.
Every phase must stay consistent with the layering, data flow, and contracts
defined here.

---

## 1. System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        React SPA (frontend)                       │
│  Dashboard │ Backtest │ Strategy Config │ Data Upload │ Results  │
└──────────────────────────────┬───────────────────────────────────┘
                               │ REST / JSON
┌──────────────────────────────▼───────────────────────────────────┐
│                        FastAPI backend                            │
│                                                                   │
│  ┌─────────────┐   ┌──────────────┐   ┌───────────────────────┐  │
│  │  API layer  │──▶│ Service layer│──▶│  Backtesting engine   │  │
│  │  (routers,  │   │ (orchestrate │   │  (deterministic       │  │
│  │   schemas,  │   │  jobs, auth) │   │   candle-by-candle    │  │
│  │   validate) │   └──────┬───────┘   │   event loop)         │  │
│  └─────────────┘          │           └──────────┬────────────┘  │
│                           │                      │               │
│                     ┌─────▼─────┐     ┌──────────▼──────────┐    │
│                     │ Job queue │     │ Strategy plugins     │   │
│                     │ (BG tasks │     │ (BaseStrategy ABC)   │   │
│                     │  → Celery)│     └──────────┬───────────┘   │
│                     └───────────┘                │               │
│                           │           ┌──────────▼──────────┐    │
│                           │           │ Analytics (metrics, │    │
│                           │           │ equity, drawdown)   │    │
│                           │           └─────────────────────┘    │
│                     ┌─────▼──────────────────────────────┐       │
│                     │ Data layer (CSV ingest, validation, │       │
│                     │ repositories)                       │       │
│                     └─────┬──────────────────────────────┘       │
│                     ┌─────▼─────┐                                │
│                     │ SQLAlchemy│                                │
│                     └─────┬─────┘                                │
└───────────────────────────┼──────────────────────────────────────┘
                     ┌──────▼──────┐
                     │ PostgreSQL  │
                     └─────────────┘
```

### Layering rules (enforced throughout the project)

1. **API layer** — HTTP only: parse, validate (Pydantic), authorize, delegate
   to services, shape responses. No business logic, no SQL.
2. **Service layer** — orchestration: create backtest jobs, fetch results,
   manage uploads. Talks to repositories, engine, and job runner.
3. **Strategy layer** — pure functions of `(candle, history, params) → Signal`.
   No I/O, no globals, no access to engine internals. **Receives only past +
   current-closed candles.**
4. **Backtesting engine** — deterministic event loop, portfolio/position
   accounting, execution model, cost model, risk limits. Knows nothing about
   HTTP or the database schema.
5. **Analytics layer** — pure functions over trade lists and equity series.
6. **Data layer** — CSV parsing, validation, repository pattern for DB access.
7. **Database layer** — SQLAlchemy models, session management, Alembic
   migrations.

### Determinism contract

Identical `(data, config)` ⇒ identical results. Concretely:

- Candles are always processed in ascending timestamp order, single pass.
- No wall-clock reads, no RNG, no `set` iteration affecting output order.
- Signal at close of candle *t* ⇒ execution on candle *t+1* open (default
  execution model). The strategy interface is physically incapable of seeing
  candle *t+1* when generating the signal for *t*.
- Floating-point accumulation order is fixed (chronological).

---

## 2. Technology Stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ (developed on 3.14) | Backend |
| Web framework | FastAPI + Pydantic v2 | OpenAPI docs auto-generated |
| ASGI server | Uvicorn | |
| Numerics | pandas, NumPy (Phase 2+) | Indicators, metrics |
| Database | PostgreSQL 16 | Phase 3 |
| ORM / migrations | SQLAlchemy 2.0, Alembic | Phase 3 |
| Jobs | FastAPI BackgroundTasks → Celery/RQ + Redis | Interface-ready |
| Frontend | React 18 + TypeScript + Vite | Phase 8 |
| Charts | lightweight-charts / Recharts | Phase 9 |
| Testing | pytest + httpx (backend), Vitest (frontend, later) | |
| Logging | stdlib structured logging now; structlog optional | |

---

## 3. Repository Layout

```
backend/
  requirements.txt            # runtime deps (grow per phase)
  requirements-dev.txt        # test/dev deps
  pyproject.toml              # project metadata + pytest config
  .env.example
  app/
    main.py                   # application factory
    core/
      config.py               # pydantic-settings (env-driven)
      logging.py              # logging setup
      security.py             # (Phase 7) auth helpers
    api/
      v1/
        router.py             # aggregates v1 routers
        routes/
          health.py
          data.py             # (Phase 2/7) upload, instruments
          backtests.py        # (Phase 7)
          strategies.py       # (Phase 7)
    schemas/                  # Pydantic request/response DTOs
    models/                   # (Phase 3) SQLAlchemy models
    database/                 # (Phase 3) engine, session, Alembic env
    data/                     # (Phase 2) CSV loading, validation
    strategies/               # strategy plugins
      base.py                 # BaseStrategy contract (Phase 1)
      liquidity_oi.py         # (Phase 5)
    backtesting/              # (Phase 4) engine, execution, portfolio, costs
    analytics/                # (Phase 6) metrics, equity, drawdown
    services/                 # (Phase 7) orchestration
    utils/
  tests/
frontend/
  package.json  vite.config.ts  tsconfig.json  index.html
  src/
    api/                      # typed API client
    pages/  components/       # (Phase 8)
    App.tsx  main.tsx
docs/
docker-compose.yml            # PostgreSQL 16
```

---

## 4. Database Architecture (implemented in Phase 3)

### Tables

**users** — `id UUID PK`, `email UNIQUE NOT NULL`, `password_hash`,
`created_at`. (Auth wiring is Phase 7; the table exists so backtests can be
scoped to users later.)

**instruments** — `id SERIAL PK`, `symbol`, `exchange`,
`instrument_type ENUM('index','stock','future','option')`, `tick_size`,
`lot_size`, `has_oi BOOLEAN`, `created_at`,
`UNIQUE(symbol, exchange, instrument_type)`.

**strategies** — `id SERIAL PK`, `name UNIQUE`, `description`, `version`,
`param_schema JSONB` (drives dynamic UI forms + server-side validation),
`created_at`.

**historical_data** — the hot table:
`instrument_id FK`, `timeframe VARCHAR(8)`, `timestamp TIMESTAMPTZ`,
`open/high/low/close DOUBLE PRECISION`, `volume DOUBLE PRECISION`,
`open_interest DOUBLE PRECISION NULL`,
`PRIMARY KEY (instrument_id, timeframe, timestamp)`.
Composite PK gives **idempotent re-uploads** (duplicates rejected/upserted)
and doubles as the lookup index. Additional index:
`(instrument_id, timeframe, timestamp DESC)` for range scans.
`open_interest NULL` ⇔ instrument has no OI data — **NULL is never filled
with fabricated values**.

**backtests** — `id UUID PK`, `user_id FK NULL`, `strategy_name`,
`instrument_id FK`, `timeframe`, `start_date`, `end_date`,
`config JSONB` (full immutable config snapshot → reproducibility),
`status ENUM('QUEUED','RUNNING','COMPLETED','FAILED')`, `error TEXT`,
`created_at`, `started_at`, `finished_at`, `duration_ms`.
Indexes: `(status)`, `(created_at DESC)`.

**backtest_trades** — one row per closed trade: `id BIGSERIAL PK`,
`backtest_id FK`, `trade_seq INT`, `symbol`, `strategy`,
`direction ENUM('LONG','SHORT')`, `entry_time`, `entry_price`, `exit_time`,
`exit_price`, `quantity`, `stop_loss`, `take_profit`, `gross_pnl`,
`brokerage`, `slippage_cost`, `other_costs`, `net_pnl`, `pnl_pct`,
`exit_reason ENUM('STOP_LOSS','TAKE_PROFIT','SIGNAL_EXIT','END_OF_DATA')`,
`holding_seconds`. Index: `(backtest_id, trade_seq)`.

**backtest_metrics** — `backtest_id PK/FK`, headline numeric columns
(`net_profit`, `win_rate`, `profit_factor`, `max_drawdown_pct`,
`sharpe_ratio`, …) for cheap listing/comparison, plus `metrics JSONB` for the
full detailed set (consecutive wins/losses, holding times, period returns).

**backtest_equity** — `backtest_id FK`, `timestamp`, `equity`, `drawdown`,
`PRIMARY KEY (backtest_id, timestamp)`. Powers equity/drawdown charts without
recomputation.

### Principles

- **Immutability**: `config` in `backtests` is never updated after creation;
  a re-run with different parameters is a new row. Reproducibility by
  construction.
- **No duplicate candles**: enforced by the composite PK, not by convention.
- **Soft separation of concerns**: metrics/equity/trades are separate tables
  so large result payloads are fetched on demand.

---

## 5. Backtesting Engine Architecture (implemented in Phase 4)

### Event loop (single chronological pass)

```
candles = load(instrument, timeframe, start, end)   # ascending, validated
state   = Portfolio(initial_capital, cost_model, risk_limits)

for i in range(warmup, len(candles) - 1):
    t       = candles[i]                        # just-closed candle
    history = candles[0 .. i]                   # strictly <= t

    # 1. Manage open positions using ONLY candle t's OHLC
    for pos in state.open_positions:
        state.evaluate_exits(pos, t, same_candle_policy)  # SL/TP/signal exits

    # 2. Risk gates (daily loss limit, max drawdown, max positions)
    if state.trading_halted: continue

    # 3. Strategy signal — sees nothing beyond t
    signal = strategy.on_candle(t, history, params)

    # 4. Execution model (default: next-candle open)
    if signal.type in (LONG, SHORT) and state.can_open():
        fill_price = candles[i+1].open adjusted by slippage
        state.open_position(signal, fill_price, candles[i+1].timestamp)

    # 5. Mark-to-market equity point
    state.record_equity(t.timestamp, t.close)

state.force_close_open_positions(candles[-1])  # END_OF_DATA exits
```

### Execution & cost model

- **Fill price** = next candle open × (1 ± slippage), sign by direction.
- **Intrabar exits**: on each candle after entry, SL and TP levels are checked
  against high/low.
- **Same-candle SL+TP policy** (config `intrabar_policy`):
  - `conservative` (default): assume SL hit first (worst case).
  - `optimistic`: assume TP hit first (best case).
  - `lower_timeframe`: if lower-TF data supplied, resolve the true order;
    otherwise fall back to `conservative`.
  The policy and its limitation are recorded on every backtest result.
- **Costs** tracked separately and summed: `net_pnl = gross_pnl − brokerage
  − slippage_cost − other_costs`. Slippage applied at entry and exit.

### Risk management (all configurable)

- Position sizing: `fixed_qty` | `fixed_amount` | `pct_capital` | `risk_pct`
  (`qty = risk_amount / |entry − stop|`).
- Limits: `max_position_size`, `max_open_positions`, `daily_loss_limit`,
  `max_drawdown_limit` (halts new entries when breached; recorded in logs).

### Position lifecycle

`SIGNAL → PENDING(fill at next open) → OPEN → (SL | TP | SIGNAL_EXIT |
END_OF_DATA) → CLOSED` with a full audit record per trade.

---

## 6. Strategy Plugin Architecture

Contract defined in Phase 1 ([backend/app/strategies/base.py](../backend/app/strategies/base.py)):

- `BaseStrategy.on_candle(candle, history, params) -> Signal`
  - `history` contains **only** candles with `timestamp <= candle.timestamp`,
    ascending, with `candle` last. The engine guarantees this; strategies
    cannot import data loaders.
- `Signal { type: NONE|LONG|SHORT|EXIT, reason, stop_loss?, take_profit? }`
  — `reason` is persisted for auditability of every decision.
- `param_schema` declares typed parameters with defaults/ranges → drives
  server-side validation and, later, auto-generated UI forms.
- Registry pattern (Phase 5): strategies self-register by name; adding
  `EMAVWAPStrategy` or `RSIStrategy` later = one new file + registration, zero
  engine changes.

**Liquidity Sweep + OI** (Phase 5) is fully specified in
[STRATEGY.md](STRATEGY.md).

---

## 7. API Architecture (implemented in Phase 7)

Base prefix: `/api/v1`. JSON everywhere. Pydantic schemas for all bodies.
Errors: RFC-7807-style `{ detail, code }` with correct HTTP statuses.

| Method | Path | Purpose | Phase |
|---|---|---|---|
| GET | `/health` | Liveness/readiness | 1 |
| POST | `/data/upload` | Multipart CSV upload → validate → store | 2/7 |
| GET | `/instruments` | List instruments with data coverage | 7 |
| GET | `/strategies` | List strategy plugins + param schemas | 7 |
| POST | `/strategies` | Register custom strategy config | 7 |
| POST | `/backtests` | Create backtest job → `{ id, status: QUEUED }` | 7 |
| GET | `/backtests` | List/filter backtests | 7 |
| GET | `/backtests/{id}` | Status + config + summary | 7 |
| GET | `/backtests/{id}/trades` | Paginated, filterable trade table | 7 |
| GET | `/backtests/{id}/metrics` | Full metric set | 7 |
| GET | `/backtests/{id}/equity` | Equity curve series | 7 |
| GET | `/backtests/{id}/drawdown` | Drawdown series | 7 |
| GET | `/backtests/{id}/monthly-performance` | Monthly return matrix | 7 |
| GET | `/backtests/{id}/export?format=csv\|json` | Export trades/report | 7 |
| POST | `/optimize` | (Phase 11) parameter grid search | 11 |
| POST | `/walkforward` | (Phase 12) walk-forward runs | 12 |

### Background jobs

- `POST /backtests` inserts a `QUEUED` row and returns `202 Accepted`
  immediately; a runner abstraction (`JobRunner` protocol) executes the
  backtest.
- Phase 7 implementation: `BackgroundTasksRunner` (in-process).
- Later: `CeleryRunner` / `RQRunner` + Redis — swap via config, no API change.
- Status machine: `QUEUED → RUNNING → COMPLETED | FAILED` with timestamps and
  `duration_ms`; the UI polls `GET /backtests/{id}`.

---

## 8. Frontend Architecture (implemented in Phases 8–9)

- **Vite + React 18 + TypeScript**, React Router pages:
  `/dashboard`, `/backtest`, `/strategies`, `/data`, `/results`,
  `/results/:id` (KPIs, equity, drawdown, monthly heatmap, trade table),
  `/compare`.
- **Typed API client** (`src/api/`) generated-by-hand from the OpenAPI
  contract; TanStack Query for server-state caching/polling of job status.
- **Forms** driven by each strategy's `param_schema` (dynamic parameter
  inputs), client-side validation mirroring server rules.
- **Charts**: equity + drawdown from real `backtest_equity` rows only —
  no simulated/demo data anywhere in the UI.
- Dev server proxies `/api` → `localhost:8000`; CORS allow-list configured
  on the backend as well.

---

## 9. Cross-Cutting Concerns

### Security
- Pydantic validation on every input; strict types, range checks.
- Upload restrictions: extension allow-list (`.csv`), size cap
  (`MAX_UPLOAD_MB`, default 100), streamed parsing, **never** executed.
- SQLAlchemy parameter binding only — no string-built SQL (injection-proof
  by construction).
- Auth-ready: `users` table + dependency-injection point for JWT auth in
  Phase 7; all queries user-scoped once enabled.
- Secrets only via environment / `.env` (git-ignored).

### Logging
- Structured, levelled logs through `app.core.logging`.
- Backtest run log lines: start, config hash, data range, candle count,
  signal/trade counts, completion, duration, errors with stack traces.

### Testing strategy (Phase 10, foundations from Phase 1)
- Unit tests per layer; property-style tests for indicators/metrics.
- **Look-ahead-bias tests**: synthetic candle series with a known future
  spike — assert signals never reference it; assert strategy receives only
  `<= t` history (engine contract test).
- **Same-candle SL/TP tests**: candles engineered to touch both levels,
  verifying each policy's outcome.
- Golden-dataset tests: small hand-computed backtest, metrics asserted to
  the cent.
- API tests with FastAPI `TestClient` (already wired in Phase 1).

---

## 10. Development Roadmap

| Phase | Deliverable | Exit criteria |
|---|---|---|
| 1 | Architecture + skeleton | Health endpoint live, tests green, FE builds |
| 2 | CSV ingestion + validation | Invalid files rejected with precise errors; valid files parsed |
| 3 | Database | Alembic migration up; candles stored deduplicated |
| 4 | Engine | Deterministic loop + costs + risk limits, unit-tested |
| 5 | Liquidity+OI strategy | Signals match hand-verified examples |
| 6 | Analytics | Full metric list + equity/drawdown, unit-tested |
| 7 | APIs + jobs | End-to-end backtest via REST, async status |
| 8 | Dashboard | All pages wired to real APIs |
| 9 | Charts/trades UI | Equity, drawdown, monthly heatmap, trade table |
| 10 | Test suite | Look-ahead + intrabar + golden metrics green |
| 11 | Optimization | Grid search with overfitting warnings, train/val/test splits |
| 12 | Walk-forward | Rolling windows, aggregated OOS report |
| 13 | Live Readiness & Proof of Profitability | Multi-check readiness scoring, proof-of-profitability status & UI badge |

---

## 11. Live Trading Readiness & Current Proof of Profitability Engine

Implemented in `backend/app/analytics/readiness.py` and visualized in `frontend/src/pages/Results.tsx`:

- **Live Trading Readiness Framework**:
  - Statistical sufficiency ($\ge 30$ trades)
  - In-sample net profitability and positive expectancy
  - Win concentration limits ($< 50\%$ net from best trade)
  - Maximum drawdown limits ($\le 25\%$) and loss streak bounds ($\le 8$)
  - Out-of-sample / walk-forward robustness check
  - Readiness score ($0–100$) and action verdicts (`RESEARCH-PROMISING`, `NEEDS MORE VALIDATION`, `INSUFFICIENT EVIDENCE`, `NOT READY`).

- **Current Proof of Profitability Framework**:
  - Evaluates whether current simulation demonstrates positive empirical edge.
  - Distinguishes historical empirical edge from live profitability proof.
  - Mandates paper-trading validation prior to live capital commitment.
  - See [docs/LIVE_READINESS_AND_PROFITABILITY.md](LIVE_READINESS_AND_PROFITABILITY.md) for full specification.

