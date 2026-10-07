"""End-to-end API tests: upload data -> create backtest -> fetch all artifacts.

FastAPI's TestClient runs BackgroundTasks synchronously before returning the
response, so a created backtest is COMPLETED by the time POST returns — which
lets us assert the full pipeline deterministically.
"""
import io
from pathlib import Path

import pytest

from app.services.jobs import job_store

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _jobs():
    job_store.clear()
    yield
    job_store.clear()


def _upload(client):
    with open(FIXTURES / "valid_1m.csv", "rb") as fh:
        r = client.post(
            "/api/v1/data/upload?symbol=SENSEX&exchange=BSE&timeframe=1m",
            files={"file": ("valid_1m.csv", fh, "text/csv")},
        )
    assert r.status_code == 201


def _create(client, **over):
    payload = {
        "strategy": "liquidity_oi",
        "symbol": "SENSEX", "exchange": "BSE", "timeframe": "1m",
        "initial_capital": 100000,
        "params": {"lookback": 5, "oi_threshold": 2.0},
        "sizing": {"model": "fixed_qty", "value": 10},
        "costs": {"brokerage_per_trade": 5, "slippage_pct": 0.05},
        "stop_loss_pct": 1.0, "take_profit_pct": 2.0,
        "warmup": 5,
    }
    payload.update(over)
    return client.post("/api/v1/backtests", json=payload)


# ---------------------------------------------------------------- strategies ---

def test_list_strategies(client):
    r = client.get("/api/v1/strategies")
    assert r.status_code == 200
    names = [s["name"] for s in r.json()]
    assert "liquidity_oi" in names


def test_strategy_param_schema_exposed(client):
    r = client.get("/api/v1/strategies/liquidity_oi")
    assert r.status_code == 200
    body = r.json()
    assert "lookback" in body["param_schema"]
    assert "oi_threshold" in body["param_schema"]


def test_unknown_strategy_404(client):
    assert client.get("/api/v1/strategies/nope").status_code == 404


# ----------------------------------------------------------------- backtests ---

def test_create_backtest_completes_and_returns_artifacts(client):
    _upload(client)
    r = _create(client)
    assert r.status_code == 202
    job_id = r.json()["id"]

    # BackgroundTasks run synchronously under TestClient -> already COMPLETED
    status = client.get(f"/api/v1/backtests/{job_id}").json()
    assert status["status"] == "COMPLETED"
    assert status["started_at"] and status["finished_at"]

    trades = client.get(f"/api/v1/backtests/{job_id}/trades")
    assert trades.status_code == 200

    metrics = client.get(f"/api/v1/backtests/{job_id}/metrics").json()["metrics"]
    assert metrics["initial_capital"] == 100000
    assert metrics["total_trades"] == len(trades.json())
    assert "sharpe_ratio" in metrics and "max_drawdown_pct" in metrics

    equity = client.get(f"/api/v1/backtests/{job_id}/equity").json()
    assert equity and equity[0]["equity"] == 100000
    drawdown = client.get(f"/api/v1/backtests/{job_id}/drawdown").json()
    assert len(drawdown) == len(equity)
    monthly = client.get(f"/api/v1/backtests/{job_id}/monthly-performance").json()
    assert "monthly_returns" in monthly

    readiness = client.get(f"/api/v1/backtests/{job_id}/readiness").json()
    assert "readiness_score" in readiness
    assert "live_trading_readiness" in readiness
    assert "current_proof_of_profitability" in readiness
    assert readiness["is_proof_of_profitability"] is False



def test_backtest_without_data_fails_job(client):
    r = client.post("/api/v1/backtests", json={
        "strategy": "liquidity_oi", "symbol": "NODATA", "exchange": "X",
        "timeframe": "1m", "initial_capital": 1000, "params": {"lookback": 5},
    })
    job_id = r.json()["id"]
    status = client.get(f"/api/v1/backtests/{job_id}").json()
    assert status["status"] == "FAILED"
    assert "no data" in status["error"]
    # artifacts unavailable
    assert client.get(f"/api/v1/backtests/{job_id}/metrics").status_code == 409


def test_unknown_backtest_id_404(client):
    assert client.get("/api/v1/backtests/does-not-exist").status_code == 404


def test_invalid_strategy_fails_job(client):
    _upload(client)
    r = _create(client, strategy="not_a_strategy")
    job_id = r.json()["id"]
    status = client.get(f"/api/v1/backtests/{job_id}").json()
    assert status["status"] == "FAILED"
    assert "not registered" in status["error"]


def test_backtest_respects_capital_and_costs(client):
    _upload(client)
    r = _create(client)
    job_id = r.json()["id"]
    metrics = client.get(f"/api/v1/backtests/{job_id}/metrics").json()["metrics"]
    # final capital reflects net P&L (costs included)
    assert metrics["final_capital"] == 100000 + metrics["net_profit"]
