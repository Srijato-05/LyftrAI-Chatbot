"""Tests for multi-turn state, session isolation, and GET /sessions/{id}/messages."""


def test_unknown_session_returns_404(client):
    res = client.get("/sessions/does-not-exist/messages")
    assert res.status_code == 404
    assert res.json() == {"detail": "session not found"}


def test_multi_turn_history_and_ordering(client, fake_gemini):
    sid = "s-multi-1"
    r1 = client.post("/chat", json={"session_id": sid, "message": "My name is Alice."})
    assert r1.status_code == 200

    r2 = client.post("/chat", json={"session_id": sid, "message": "What is my name?"})
    assert r2.status_code == 200

    # Second provider call must include the first turn in Gemini contents payload
    second_contents = fake_gemini.calls[1]["body"]["contents"]
    joined_texts = " | ".join(
        p.get("text", "") for item in second_contents for p in (item.get("parts") or [])
    )
    assert "My name is Alice." in joined_texts
    assert "What is my name?" in joined_texts

    # Per-request input_tokens grows with history (not identical to turn 1)
    assert r2.json()["metadata"]["input_tokens"] > r1.json()["metadata"]["input_tokens"]

    hist = client.get(f"/sessions/{sid}/messages")
    assert hist.status_code == 200
    body = hist.json()
    assert body["session_id"] == sid
    msgs = body["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"] == "My name is Alice."
    assert "metadata" not in msgs[0]
    assert msgs[1]["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert msgs[1]["metadata"]["input_tokens"] == r1.json()["metadata"]["input_tokens"]
    assert msgs[2]["content"] == "What is my name?"
    assert "metadata" not in msgs[2]


def test_sessions_stay_isolated(client, fake_gemini):
    client.post("/chat", json={"session_id": "s-iso-1", "message": "Secret alpha"})
    client.post("/chat", json={"session_id": "s-iso-2", "message": "Hello beta"})

    second_contents = fake_gemini.calls[1]["body"]["contents"]
    joined = " | ".join(
        p.get("text", "") for item in second_contents for p in (item.get("parts") or [])
    )
    assert "Secret alpha" not in joined


def test_per_request_tokens_not_cumulative_across_sessions(client):
    r1 = client.post("/chat", json={"session_id": "s-tok-1", "message": "Twelve chars"})
    r2 = client.post("/chat", json={"session_id": "s-tok-2", "message": "Different12!"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["metadata"]["input_tokens"] == r2.json()["metadata"]["input_tokens"]


def test_custom_system_prompt_persisted_and_excluded_from_history(client, fake_gemini):
    sid = "s-sys-1"
    r1 = client.post(
        "/chat",
        json={
            "session_id": sid,
            "message": "Hello",
            "system_prompt": "Always speak like a pirate.",
        },
    )
    assert r1.status_code == 200

    r2 = client.post("/chat", json={"session_id": sid, "message": "Second turn"})
    assert r2.status_code == 200

    # System instruction should still be sent on turn 2 without client resending it
    second_body = fake_gemini.calls[1]["body"]
    sys_inst = second_body.get("system_instruction") or {}
    sys_parts = sys_inst.get("parts") or []
    assert any("pirate" in p.get("text", "") for p in sys_parts)

    # History endpoint must exclude system prompt
    hist = client.get(f"/sessions/{sid}/messages").json()
    assert all(m["role"] in ("user", "assistant") for m in hist["messages"])
    assert len(hist["messages"]) == 4

