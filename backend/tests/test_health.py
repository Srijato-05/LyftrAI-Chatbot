"""Tests for GET /health."""


def test_health_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["keys_configured"] == 2
    assert body["cache_enabled"] is True


def test_health_db_failure_returns_503(client):
    async def broken_ping():
        raise RuntimeError("disk offline")

    client.app.state.db.ping = broken_ping
    res = client.get("/health")
    assert res.status_code == 503
    assert "detail" in res.json()

