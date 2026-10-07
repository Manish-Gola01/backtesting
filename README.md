# Algo Trading Backtesting Platform

A production-quality, **multi-market** algorithmic trading backtesting platform.
Upload real historical data, configure a strategy, run a deterministic,
look-ahead-bias-free backtest, and receive a professional quantitative
performance report.

> Research and validation tool first. A profitable backtest is **not** a
> guarantee of future trading performance.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — full system design
- [docs/STRATEGY.md](docs/STRATEGY.md) — Liquidity Sweep + OI strategy specification
- [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) — assumptions, ambiguities, decisions
- [docs/LIVE_READINESS_AND_PROFITABILITY.md](docs/LIVE_READINESS_AND_PROFITABILITY.md) — live readiness rubric & proof of profitability analysis

## Roadmap / Build Phases

- [x] **Phase 1** — Architecture + project setup
- [x] **Phase 2** — Historical CSV data ingestion + validation
- [x] **Phase 3** — Database (SQLAlchemy models + Alembic; PostgreSQL prod / SQLite local verify)
- [x] **Phase 4** — Deterministic backtesting engine
- [x] **Phase 5** — Liquidity Sweep + OI strategy
- [x] **Phase 6** — Performance analytics (metrics, equity, drawdown)
- [x] **Phase 7** — REST APIs + background jobs
- [x] **Phase 8** — React dashboard
- [x] **Phase 9** — Charts & trade analysis UI
- [x] **Phase 10** — Full test suite (incl. look-ahead-bias tests)
- [x] **Phase 11** — Parameter optimization framework
- [x] **Phase 12** — Walk-forward / out-of-sample testing
- [x] **Phase 13** — Live trading readiness & Current proof of profitability analysis framework


## Repository Layout

```
backend/          FastAPI backend (see docs/ARCHITECTURE.md)
  app/            application package
  tests/          pytest suite
frontend/         React + TypeScript (Vite)
docs/             architecture, strategy spec, assumptions
docker-compose.yml  PostgreSQL (optional in Phase 1, required from Phase 3)
```

## Quickstart (Phase 1)

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

- Health check: <http://localhost:8000/api/v1/health>
- Interactive API docs: <http://localhost:8000/docs>

### Upload historical data (Phase 2)

```powershell
# CSV needs: timestamp (tz-aware), open, high, low, close, volume [, open_interest]
curl -X POST "http://localhost:8000/api/v1/data/upload?symbol=SENSEX&exchange=BSE&timeframe=1m" `
  -F "file=@path\to\data.csv"

# List uploaded coverage
curl "http://localhost:8000/api/v1/instruments"
```

### Run a backtest (Phase 7)

```powershell
# 1. strategies + their parameter schemas
curl "http://localhost:8000/api/v1/strategies"

# 2. create a backtest job (returns 202 + job id; runs in background)
curl -X POST "http://localhost:8000/api/v1/backtests" -H "Content-Type: application/json" -d '{
  "strategy":"liquidity_oi","symbol":"SENSEX","exchange":"BSE","timeframe":"1m",
  "initial_capital":100000,"params":{"lookback":20,"oi_threshold":2.5},
  "sizing":{"model":"risk_pct","value":1},"costs":{"brokerage_per_trade":5,"slippage_pct":0.05},
  "stop_loss_pct":1.0,"take_profit_pct":2.0
}'

# 3. poll status, then fetch artifacts
curl "http://localhost:8000/api/v1/backtests/{id}"                      # QUEUED|RUNNING|COMPLETED|FAILED
curl "http://localhost:8000/api/v1/backtests/{id}/trades"
curl "http://localhost:8000/api/v1/backtests/{id}/metrics"
curl "http://localhost:8000/api/v1/backtests/{id}/equity"
curl "http://localhost:8000/api/v1/backtests/{id}/drawdown"
curl "http://localhost:8000/api/v1/backtests/{id}/monthly-performance"
```

### Optimize & walk-forward (Phases 11–12)

```powershell
# grid search on TRAIN slice only; reports held-out validation/test + warning
curl -X POST "http://localhost:8000/api/v1/optimize" -H "Content-Type: application/json" -d '{
  "strategy":"liquidity_oi","symbol":"SENSEX","exchange":"BSE","timeframe":"1m",
  "initial_capital":100000,
  "param_grid":{"lookback":[10,20,30],"oi_threshold":[1.0,2.5,5.0]},
  "rank_by":"sharpe_ratio"
}'

# rolling walk-forward: re-optimize on train window, evaluate next OOS window
curl -X POST "http://localhost:8000/api/v1/walkforward" -H "Content-Type: application/json" -d '{
  "strategy":"liquidity_oi","symbol":"SENSEX","exchange":"BSE","timeframe":"1m",
  "initial_capital":100000,"param_grid":{"lookback":[10,20]},
  "train_size":500,"test_size":200
}'
```

Both endpoints return an explicit overfitting warning: the best historical
parameter is **not** claimed to be the best live parameter. Selection never
touches the test slice.

### Live Trading Readiness & Current Proof of Profitability (Phase 13)

Assess whether a completed backtest satisfies the quantitative standards for live capital deployment, and evaluate current proof of profitability:

```powershell
# Get readiness score, check breakdown, and proof-of-profitability status
curl "http://localhost:8000/api/v1/backtests/{id}/readiness"
```

Response includes:
- **`live_trading_readiness`**: Score (0–100), verdict (`RESEARCH-PROMISING`, `NEEDS MORE VALIDATION`, `INSUFFICIENT EVIDENCE`, `NOT READY`), passed checks.
- **`current_proof_of_profitability`**: Status (`HISTORICAL_EVIDENCE_ONLY` vs `NO_EDGE_DEMONSTRATED`), empirical edge summary, and explicit reminder that backtests do **not** constitute future live guarantees.
- Full details documented in [docs/LIVE_READINESS_AND_PROFITABILITY.md](docs/LIVE_READINESS_AND_PROFITABILITY.md).

Invalid files are rejected with HTTP 422 and per-row errors; nothing invalid
is persisted. See [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) for the data rules.


### Database (Phase 3)

PostgreSQL in production, SQLite for zero-install local verification — same
schema (engine-agnostic SQLAlchemy + Alembic).

```powershell
# production (requires Docker Desktop):
docker compose up -d db           # PostgreSQL 16 on :5432
cd backend
$env:DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/backtesting"
.\.venv\Scripts\alembic upgrade head      # create all 8 tables

# local verification (no Docker): SQLite
$env:DATABASE_URL = "sqlite:///./dev.db"
.\.venv\Scripts\alembic upgrade head

# run the API against the DB-backed store instead of in-memory:
$env:DATA_BACKEND = "db"
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

- App: <http://localhost:5173> (proxies `/api` to the backend on port 8000)

### Tests

```powershell
cd backend
pytest -v
```

