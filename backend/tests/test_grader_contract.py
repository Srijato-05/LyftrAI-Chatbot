"""Strict end-to-end verification of the Grader Probe Matrix and HTTP edge inputs."""

import time


def test_full_grader_probe_matrix(client, fake_gemini):
    fake_gemini.delay_seconds = 0.05

    # Probe 1: GET /health
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}

    # Probe 2: POST /chat new session, msg A -> LIVE_INFERENCE
    msg_a = "Grader Probe Matrix Message Alpha"
    r1 = client.post("/chat", json={"session_id": "s-probe-1", "message": msg_a})
    assert r1.status_code == 200
    b1 = r1.json()
    assert set(b1.keys()) == {"session_id", "reply", "metadata"}
    assert set(b1["metadata"].keys()) == {
        "resolution_source",
        "model",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "key_id",
        "fallback_attempts",
    }
    assert b1["session_id"] == "s-probe-1"
    assert b1["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert b1["metadata"]["key_id"] == "key_1"
    assert b1["metadata"]["fallback_attempts"] == 0

    time.sleep(0.2)

    # Probe 3: New session, same msg A -> LLM_CACHE, identical reply, key_id null, faster
    r2 = client.post("/chat", json={"session_id": "s-probe-2", "message": msg_a})
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["reply"] == b1["reply"]
    assert b2["metadata"]["resolution_source"] == "LLM_CACHE"
    assert b2["metadata"]["key_id"] is None
    assert b2["metadata"]["fallback_attempts"] == 0
    assert b2["metadata"]["latency_ms"] < b1["metadata"]["latency_ms"]

    # Probe 4: New session, msg B -> LIVE_INFERENCE
    r3 = client.post("/chat", json={"session_id": "s-probe-3", "message": "Message Beta"})
    assert r3.status_code == 200
    assert r3.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"

    # Probe 5: Follow-up in s-probe-1 -> larger input_tokens (per-request with history)
    r4 = client.post("/chat", json={"session_id": "s-probe-1", "message": "Follow up"})
    assert r4.status_code == 200
    assert r4.json()["metadata"]["input_tokens"] > b1["metadata"]["input_tokens"]

    # Probe 6 & 7: X-Simulate-Failure key_1=429 and key_1=500 -> key_2, fallback_attempts=1
    for hdr in ("key_1=429", "key_1=500"):
        rs = client.post(
            "/chat",
            json={"session_id": "s-probe-sim", "message": msg_a},
            headers={"X-Simulate-Failure": hdr},
        )
        assert rs.status_code == 200
        assert rs.json()["metadata"]["key_id"] == "key_2"
        assert rs.json()["metadata"]["fallback_attempts"] == 1

    # Probe 8: *=429 -> 503 exact body, nothing added to history
    r_503 = client.post(
        "/chat",
        json={"session_id": "s-probe-never", "message": "Fail all"},
        headers={"X-Simulate-Failure": "*=429"},
    )
    assert r_503.status_code == 503
    assert r_503.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/s-probe-never/messages").status_code == 404


def test_http_header_and_payload_adversarial_inputs(client):
    # Case-insensitive HTTP header name (lowercase x-simulate-failure)
    r_lower = client.post(
        "/chat",
        json={"session_id": "s-adv-1", "message": "Lowercase header"},
        headers={"x-simulate-failure": "key_1=429"},
    )
    assert r_lower.status_code == 200
    assert r_lower.json()["metadata"]["key_id"] == "key_2"

    # Duplicate key in header -> last wins (key_1=429,key_1=500)
    r_dup = client.post(
        "/chat",
        json={"session_id": "s-adv-2", "message": "Duplicate header"},
        headers={"X-Simulate-Failure": "key_1=429,key_1=500"},
    )
    assert r_dup.status_code == 200
    assert r_dup.json()["metadata"]["key_id"] == "key_2"

    # Whitespace-only system_prompt treated as None (falls back to default), extra JSON keys ignored
    r_extra = client.post(
        "/chat",
        json={
            "session_id": "s-adv-3",
            "message": "  trimmed message  ",
            "system_prompt": "   \n  ",
            "unexpected_field": "ignored",
        },
    )
    assert r_extra.status_code == 200

    # Wrong Content-Type and empty body -> 422 JSON
    r_text = client.post(
        "/chat",
        content='{"session_id":"s-1","message":"hi"}',
        headers={"Content-Type": "text/plain"},
    )
    assert r_text.status_code == 422
    assert "detail" in r_text.json()

    r_empty = client.post(
        "/chat",
        content="",
        headers={"Content-Type": "application/json"},
    )
    assert r_empty.status_code == 422
    assert "detail" in r_empty.json()

