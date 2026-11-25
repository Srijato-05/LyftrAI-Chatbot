"""Tests for automatic key failover and X-Simulate-Failure hook."""

import time


def test_simulated_key1_429_falls_back_to_key2(client, fake_gemini):
    res = client.post(
        "/chat",
        json={"session_id": "s-sim-429", "message": "Failover 429 test"},
        headers={"X-Simulate-Failure": "key_1=429"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert body["metadata"]["key_id"] == "key_2"
    assert body["metadata"]["fallback_attempts"] == 1
    assert "test-secret-key-2" not in res.text
    assert len(fake_gemini.calls) == 1
    assert fake_gemini.calls[0]["api_key"] == "test-secret-key-2"


def test_simulated_key1_500_502_503_fall_back_to_key2(client):
    for status in (500, 502, 503):
        res = client.post(
            "/chat",
            json={"session_id": f"s-sim-{status}", "message": f"Failover {status}"},
            headers={"X-Simulate-Failure": f"key_1={status}"},
        )
        assert res.status_code == 200
        meta = res.json()["metadata"]
        assert meta["key_id"] == "key_2"
        assert meta["fallback_attempts"] == 1


def test_simulated_all_keys_fail_returns_503_and_no_history(client):
    for header in ("*=429", "key_1=429,key_2=500"):
        sid = f"s-all-fail-{header}"
        res = client.post(
            "/chat",
            json={"session_id": sid, "message": "Should fail"},
            headers={"X-Simulate-Failure": header},
        )
        assert res.status_code == 503
        assert res.json() == {"detail": "all providers unavailable"}

        hist = client.get(f"/sessions/{sid}/messages")
        assert hist.status_code == 404
        assert hist.json() == {"detail": "session not found"}


def test_simulation_does_not_poison_next_request_or_use_cache(client):
    msg = "Cached then simulated"
    r1 = client.post("/chat", json={"session_id": "s-c1", "message": msg})
    assert r1.status_code == 200
    assert r1.json()["metadata"]["key_id"] == "key_1"
    time.sleep(0.2)

    # Even though msg is cached, X-Simulate-Failure must bypass cache and fail over to key_2
    r2 = client.post(
        "/chat",
        json={"session_id": "s-c2", "message": msg},
        headers={"X-Simulate-Failure": "key_1=429"},
    )
    assert r2.status_code == 200
    assert r2.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert r2.json()["metadata"]["key_id"] == "key_2"
    assert r2.json()["metadata"]["fallback_attempts"] == 1

    # Next normal request without header still uses key_1 (no cooldown leak) or cache
    r3 = client.post("/chat", json={"session_id": "s-c3", "message": "Fresh after simulation"})
    assert r3.status_code == 200
    assert r3.json()["metadata"]["key_id"] == "key_1"
    assert r3.json()["metadata"]["fallback_attempts"] == 0


def test_simulation_header_ignored_when_disabled(make_client):
    c = make_client(enable_simulation=False, db_name="sim_off.db")
    res = c.post(
        "/chat",
        json={"session_id": "s-sim-off", "message": "Should ignore header"},
        headers={"X-Simulate-Failure": "*=429"},
    )
    assert res.status_code == 200
    assert res.json()["metadata"]["key_id"] == "key_1"
    assert res.json()["metadata"]["fallback_attempts"] == 0


def test_real_provider_429_and_500_fail_over_and_recover(client, fake_gemini):
    fake_gemini.set_key_error("test-secret-key-1", 429)
    r1 = client.post("/chat", json={"session_id": "s-real-1", "message": "Real 429"})
    assert r1.status_code == 200
    assert r1.json()["metadata"]["key_id"] == "key_2"
    assert r1.json()["metadata"]["fallback_attempts"] == 1

    # Clear key_1 error: key_1 should work again immediately (cooldown_time=0)
    fake_gemini.clear_errors()
    r2 = client.post("/chat", json={"session_id": "s-real-2", "message": "Recovered key 1"})
    assert r2.status_code == 200
    assert r2.json()["metadata"]["key_id"] == "key_1"
    assert r2.json()["metadata"]["fallback_attempts"] == 0


def test_real_all_keys_failing_returns_503_and_preserves_prior_history(client, fake_gemini):
    r1 = client.post("/chat", json={"session_id": "s-preserve", "message": "Turn 1 ok"})
    assert r1.status_code == 200

    fake_gemini.set_key_error("test-secret-key-1", 429)
    fake_gemini.set_key_error("test-secret-key-2", 503)
    r2 = client.post("/chat", json={"session_id": "s-preserve", "message": "Turn 2 fails"})
    assert r2.status_code == 503
    assert r2.json() == {"detail": "all providers unavailable"}

    hist = client.get("/sessions/s-preserve/messages")
    assert hist.status_code == 200
    messages = hist.json()["messages"]
    assert len(messages) == 2
    assert messages[0]["content"] == "Turn 1 ok"

