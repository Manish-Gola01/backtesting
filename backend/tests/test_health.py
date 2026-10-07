"""Phase 1 smoke tests: the API boots and reports its identity."""


def test_health_returns_200(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200


def test_health_payload_shape(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["app"]
    assert body["version"]
    assert body["environment"] == "development"
    assert "timestamp" in body
