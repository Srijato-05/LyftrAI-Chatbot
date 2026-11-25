"""Tests for POST /chat contract and metadata fields."""


def test_chat_response_contract(client):
    res = client.post(
        "/chat",
        json={"session_id": "s-chat-1", "message": "What is the capital of France?"},
    )
    assert res.status_code == 200
    body = res.json()

    assert body["session_id"] == "s-chat-1"
    assert isinstance(body["reply"], str) and len(body["reply"]) > 0

    meta = body["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "gemini/gemini-2.5-flash"
    assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] >= 0
    assert isinstance(meta["input_tokens"], int) and meta["input_tokens"] > 0
    assert isinstance(meta["output_tokens"], int) and meta["output_tokens"] > 0
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0


def test_session_id_is_echoed_verbatim(client):
    raw_sid = "  s-keep-spaces  "
    res = client.post("/chat", json={"session_id": raw_sid, "message": "hi"})
    assert res.status_code == 200
    assert res.json()["session_id"] == raw_sid

