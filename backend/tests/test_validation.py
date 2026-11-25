"""Tests for request validation and 422 JSON error responses."""


def test_missing_fields_return_422(client):
    r1 = client.post("/chat", json={"session_id": "s-1"})
    assert r1.status_code == 422
    assert "detail" in r1.json()

    r2 = client.post("/chat", json={"message": "hello"})
    assert r2.status_code == 422
    assert "detail" in r2.json()


def test_empty_and_whitespace_message_return_422(client):
    for bad in ("", "   ", "\n\t  "):
        res = client.post("/chat", json={"session_id": "s-empty", "message": bad})
        assert res.status_code == 422
        assert "detail" in res.json()


def test_empty_or_oversized_session_id_return_422(client):
    for bad_sid in ("", "   ", "a" * 129):
        res = client.post("/chat", json={"session_id": bad_sid, "message": "hello"})
        assert res.status_code == 422
        assert "detail" in res.json()


def test_message_length_boundary_4000_vs_4001(client):
    ok = client.post("/chat", json={"session_id": "s-len", "message": "x" * 4000})
    assert ok.status_code == 200

    # Whitespace around 4000 chars trims down to 4000 -> still valid
    ok_padded = client.post("/chat", json={"session_id": "s-len2", "message": "  " + "y" * 4000 + "  "})
    assert ok_padded.status_code == 200

    too_long = client.post("/chat", json={"session_id": "s-len", "message": "x" * 4001})
    assert too_long.status_code == 422
    assert "detail" in too_long.json()


def test_malformed_json_returns_422(client):
    res = client.post(
        "/chat",
        content="{not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 422
    assert "detail" in res.json()


def test_failed_validation_does_not_create_session(client):
    res = client.post("/chat", json={"session_id": "s-never", "message": "   "})
    assert res.status_code == 422

    hist = client.get("/sessions/s-never/messages")
    assert hist.status_code == 404
    assert hist.json() == {"detail": "session not found"}

