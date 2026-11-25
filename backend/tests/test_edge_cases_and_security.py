"""Exhaustive tests for security, CORS, error formatting, and input edge cases."""

import logging
import sqlite3
from pathlib import Path


def test_no_secret_key_leaked_anywhere(make_client, tmp_path: Path, caplog):
    secret_1 = "AIzaSySuperSecretKeyOne123456"
    secret_2 = "AIzaSySuperSecretKeyTwo789012"
    c = make_client(api_keys=f"{secret_1},{secret_2}", db_name="secrets.db")

    with caplog.at_level(logging.DEBUG):
        r_health = c.get("/health")
        assert secret_1 not in r_health.text and secret_2 not in r_health.text

        r_chat = c.post("/chat", json={"session_id": "s-sec-1", "message": "Hello"})
        assert r_chat.status_code == 200
        assert secret_1 not in r_chat.text and secret_2 not in r_chat.text

        r_sim = c.post(
            "/chat",
            json={"session_id": "s-sec-2", "message": "Failover"},
            headers={"X-Simulate-Failure": "key_1=429"},
        )
        assert r_sim.status_code == 200
        assert secret_1 not in r_sim.text and secret_2 not in r_sim.text

        r_fail = c.post(
            "/chat",
            json={"session_id": "s-sec-3", "message": "All fail"},
            headers={"X-Simulate-Failure": "*=429"},
        )
        assert r_fail.status_code == 503
        assert secret_1 not in r_fail.text and secret_2 not in r_fail.text

        r_hist = c.get("/sessions/s-sec-2/messages")
        assert secret_1 not in r_hist.text and secret_2 not in r_hist.text

    # Check logs never recorded raw secrets
    assert secret_1 not in caplog.text
    assert secret_2 not in caplog.text

    # Check SQLite DB raw contents never stored raw secrets
    db_bytes = (tmp_path / "secrets.db").read_bytes()
    assert secret_1.encode() not in db_bytes
    assert secret_2.encode() not in db_bytes


def test_cors_preflight_allowed_and_disallowed(make_client):
    c = make_client(
        allowed_origins="https://my-frontend.vercel.app, http://localhost:3000",
        db_name="cors.db",
    )
    ok = c.options(
        "/chat",
        headers={
            "Origin": "https://my-frontend.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-simulate-failure",
        },
    )
    assert ok.status_code == 200
    assert ok.headers.get("access-control-allow-origin") == "https://my-frontend.vercel.app"

    bad = c.options(
        "/chat",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in bad.headers


def test_unknown_route_and_method_not_allowed_return_json_not_html(client):
    r404 = client.get("/nonexistent-endpoint")
    assert r404.status_code == 404
    assert r404.headers["content-type"].startswith("application/json")
    assert "detail" in r404.json()

    r405 = client.get("/chat")
    assert r405.status_code == 405
    assert r405.headers["content-type"].startswith("application/json")
    assert "detail" in r405.json()


def test_unhandled_exception_returns_clean_500_json(client):
    from fastapi.testclient import TestClient

    async def explode(*args, **kwargs):
        raise RuntimeError("boom sensitive internal state")

    client.app.state.db.get_session = explode
    non_raising_client = TestClient(client.app, raise_server_exceptions=False)
    res = non_raising_client.post("/chat", json={"session_id": "s-boom", "message": "hello"})
    assert res.status_code == 500
    assert res.json() == {"detail": "internal server error"}
    assert "boom" not in res.text
    assert "Traceback" not in res.text


def test_empty_provider_reply_returns_503_and_saves_nothing(client, fake_gemini):
    fake_gemini.reply_fn = lambda _contents, _n: ("   ", 10, 0)
    res = client.post("/chat", json={"session_id": "s-empty-reply", "message": "Hello"})
    assert res.status_code == 503
    assert res.json() == {"detail": "all providers unavailable"}

    hist = client.get("/sessions/s-empty-reply/messages")
    assert hist.status_code == 404


def test_unicode_emojis_newlines_and_sqli_strings(client):
    tricky_sid = "s-emoji-🚀-' OR 1=1;--"
    tricky_msg = "Line 1\nLine 2 🚀 日本語 '; DROP TABLE messages; --"

    res = client.post("/chat", json={"session_id": tricky_sid, "message": tricky_msg})
    assert res.status_code == 200
    assert res.json()["session_id"] == tricky_sid

    hist = client.get("/sessions/{}/messages".format(tricky_sid))
    # URL-safe check without semicolon path ambiguity using params/encoded path
    import urllib.parse

    encoded_sid = urllib.parse.quote(tricky_sid, safe="")
    hist = client.get(f"/sessions/{encoded_sid}/messages")
    assert hist.status_code == 200
    assert hist.json()["messages"][0]["content"] == tricky_msg


def test_session_id_length_boundaries_and_wrong_json_types(client):
    assert client.post("/chat", json={"session_id": "a", "message": "hi"}).status_code == 200
    assert client.post("/chat", json={"session_id": "b" * 128, "message": "hi"}).status_code == 200
    assert client.post("/chat", json={"session_id": "c" * 129, "message": "hi"}).status_code == 422

    for bad_payload in (
        {"session_id": 123, "message": "hi"},
        {"session_id": "s-1", "message": 456},
        {"session_id": None, "message": "hi"},
        {"session_id": "s-1", "message": ["hi"]},
    ):
        r = client.post("/chat", json=bad_payload)
        assert r.status_code == 422
        assert "detail" in r.json()

