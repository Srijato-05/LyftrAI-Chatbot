"""Exhaustive failover tests: 3-key pools, transport errors, mixed models, empty pool."""

import httpx


def test_three_key_chain_failover_attempts_and_order(make_client, fake_gemini):
    c = make_client(
        api_keys="secret-1,secret-2,secret-3",
        db_name="three_keys.db",
    )

    assert c.get("/health").json()["keys_configured"] == 3

    # key_1 fails -> key_2 answers (fallback_attempts = 1)
    r1 = c.post(
        "/chat",
        json={"session_id": "s-3k-1", "message": "Test 1"},
        headers={"X-Simulate-Failure": "key_1=429"},
    )
    assert r1.status_code == 200
    assert r1.json()["metadata"]["key_id"] == "key_2"
    assert r1.json()["metadata"]["fallback_attempts"] == 1

    # key_1 and key_2 fail -> key_3 answers (fallback_attempts = 2)
    r2 = c.post(
        "/chat",
        json={"session_id": "s-3k-2", "message": "Test 2"},
        headers={"X-Simulate-Failure": "key_1=429,key_2=500"},
    )
    assert r2.status_code == 200
    assert r2.json()["metadata"]["key_id"] == "key_3"
    assert r2.json()["metadata"]["fallback_attempts"] == 2
    assert fake_gemini.calls[-1]["api_key"] == "secret-3"

    # Only key_2 simulated -> key_1 succeeds immediately (fallback_attempts = 0)
    r3 = c.post(
        "/chat",
        json={"session_id": "s-3k-3", "message": "Test 3"},
        headers={"X-Simulate-Failure": "key_2=503"},
    )
    assert r3.status_code == 200
    assert r3.json()["metadata"]["key_id"] == "key_1"
    assert r3.json()["metadata"]["fallback_attempts"] == 0

    # All 3 fail -> 503
    r4 = c.post(
        "/chat",
        json={"session_id": "s-3k-4", "message": "Test 4"},
        headers={"X-Simulate-Failure": "*=502"},
    )
    assert r4.status_code == 503
    assert r4.json() == {"detail": "all providers unavailable"}


def test_real_http_status_errors_and_transport_exceptions_fail_over(client, fake_gemini):
    for code in (429, 500, 502, 503, 401, 403):
        fake_gemini.clear_errors()
        fake_gemini.set_key_error("test-secret-key-1", code)
        res = client.post("/chat", json={"session_id": f"s-http-{code}", "message": f"msg {code}"})
        assert res.status_code == 200
        assert res.json()["metadata"]["key_id"] == "key_2"
        assert res.json()["metadata"]["fallback_attempts"] == 1

    for exc in (httpx.ConnectError("dns fail"), httpx.ReadTimeout("timed out")):
        fake_gemini.clear_errors()
        fake_gemini.set_key_exception("test-secret-key-1", exc)
        res = client.post(
            "/chat",
            json={"session_id": f"s-exc-{type(exc).__name__}", "message": f"exc {type(exc).__name__}"},
        )
        assert res.status_code == 200
        assert res.json()["metadata"]["key_id"] == "key_2"
        assert res.json()["metadata"]["fallback_attempts"] == 1


def test_per_key_models_override_reports_exact_fallback_model(make_client):
    c = make_client(
        api_keys="k1,k2",
        llm_models="gemini/gemini-2.5-flash,gemini/gemini-2.0-flash",
        db_name="models.db",
    )
    r1 = c.post("/chat", json={"session_id": "s-m1", "message": "Primary model"})
    assert r1.status_code == 200
    assert r1.json()["metadata"]["model"] == "gemini/gemini-2.5-flash"
    assert r1.json()["metadata"]["key_id"] == "key_1"

    r2 = c.post(
        "/chat",
        json={"session_id": "s-m2", "message": "Fallback model"},
        headers={"X-Simulate-Failure": "key_1=429"},
    )
    assert r2.status_code == 200
    assert r2.json()["metadata"]["model"] == "gemini/gemini-2.0-flash"
    assert r2.json()["metadata"]["key_id"] == "key_2"


def test_empty_key_pool_returns_503_on_chat(make_client):
    c = make_client(api_keys="", db_name="empty_pool.db")
    h = c.get("/health")
    assert h.status_code == 200
    assert h.json()["keys_configured"] == 0

    res = c.post("/chat", json={"session_id": "s-empty-pool", "message": "Hello"})
    assert res.status_code == 503
    assert res.json() == {"detail": "all providers unavailable"}

