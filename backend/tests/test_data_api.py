"""API-level tests for POST /api/v1/data/upload and GET /api/v1/instruments."""
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

Q = "symbol=SENSEX&exchange=BSE&timeframe=1m"


def _upload(client, fixture: str, query: str = Q):
    with open(FIXTURES / fixture, "rb") as fh:
        return client.post(f"/api/v1/data/upload?{query}", files={"file": (fixture, fh, "text/csv")})


def test_upload_valid_csv_returns_coverage(client):
    resp = _upload(client, "valid_1m.csv")
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "stored"
    assert body["symbol"] == "SENSEX"
    assert body["candles"] == 10
    assert body["has_oi"] is True
    assert body["start"] < body["end"]


def test_upload_invalid_csv_422_with_row_errors(client):
    resp = _upload(client, "bad_ohlc.csv")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "DATA_VALIDATION_FAILED"
    assert detail["row_errors"]  # exact rows reported


def test_upload_duplicate_timestamps_422(client):
    resp = _upload(client, "duplicate_timestamps.csv")
    assert resp.status_code == 422
    assert "duplicate timestamp" in resp.json()["detail"]["issues"][0]


def test_upload_wrong_extension_400(client):
    resp = client.post(
        f"/api/v1/data/upload?{Q}",
        files={"file": ("data.txt", b"timestamp,open\n1,2", "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_missing_column_422_schema(client):
    csv = b"timestamp,open,high,low,close\n2024-01-01T09:15:00+00:00,1,2,0.5,1.5\n"
    resp = client.post(f"/api/v1/data/upload?{Q}", files={"file": ("x.csv", csv, "text/csv")})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "DATA_SCHEMA_INVALID"


def test_reupload_rejected_unless_overwrite(client):
    assert _upload(client, "valid_1m.csv").status_code == 201
    again = _upload(client, "valid_1m.csv")
    assert again.status_code == 422
    assert "already exists" in again.json()["detail"]["issues"][0]
    replaced = _upload(client, "valid_1m.csv", Q + "&overwrite=true")
    assert replaced.status_code == 201


def test_missing_oi_rejected_when_required(client):
    resp = _upload(client, "valid_no_oi.csv", Q + "&require_oi=true")
    assert resp.status_code == 422
    assert "never fabricated" in resp.json()["detail"]["issues"][0]


def test_instruments_lists_uploaded_coverage(client):
    assert client.get("/api/v1/instruments").json()["instruments"] == []
    _upload(client, "valid_1m.csv")
    _upload(client, "valid_no_oi.csv", "symbol=NIFTY&exchange=NSE&timeframe=5m")
    body = client.get("/api/v1/instruments").json()
    assert len(body["instruments"]) == 2
    by_symbol = {i["symbol"]: i for i in body["instruments"]}
    assert by_symbol["SENSEX"]["has_oi"] is True
    assert by_symbol["NIFTY"]["has_oi"] is False
