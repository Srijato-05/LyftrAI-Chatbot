"""Exhaustive persistence, schema, truncation, and concurrency tests."""

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.main import create_app


def test_sqlite_schema_and_persistence_across_app_restarts(make_client, tmp_path: Path, fake_gemini):
    db_name = "restart.db"
    sid = "s-restart-1"

    # App instance #1
    c1 = make_client(db_name=db_name)
    r1 = c1.post("/chat", json={"session_id": sid, "message": "Remember number 42."})
    assert r1.status_code == 200

    # Verify exact SQLite table schema & ISO-8601 timestamps
    db_file = tmp_path / db_name
    with sqlite3.connect(db_file) as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(messages);").fetchall()]
        assert cols == ["id", "session_id", "role", "content", "metadata", "created_at"]
        rows = conn.execute("SELECT role, metadata, created_at FROM messages ORDER BY id ASC;").fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "user" and rows[0][1] is None
        assert rows[1][0] == "assistant" and rows[1][1] is not None
        datetime.fromisoformat(rows[0][2])
        datetime.fromisoformat(rows[1][2])

    # App instance #2 pointing to the exact same SQLite file (simulating container restart)
    c2 = make_client(db_name=db_name)
    hist = c2.get(f"/sessions/{sid}/messages")
    assert hist.status_code == 200
    assert len(hist.json()["messages"]) == 2

    r2 = c2.post("/chat", json={"session_id": sid, "message": "What number did I say?"})
    assert r2.status_code == 200
    second_contents = fake_gemini.calls[1]["body"]["contents"]
    joined = " | ".join(
        p.get("text", "") for item in second_contents for p in (item.get("parts") or [])
    )
    assert "Remember number 42." in joined


def test_max_history_messages_limits_context_while_preserving_db(make_client, fake_gemini):
    c = make_client(max_history_messages=2, db_name="max_hist.db")
    sid = "s-trunc-1"

    c.post("/chat", json={"session_id": sid, "message": "Turn one message"})
    c.post("/chat", json={"session_id": sid, "message": "Turn two message"})
    c.post("/chat", json={"session_id": sid, "message": "Turn three message"})

    # Turn 3 should only send the last 2 stored messages (turn 2 user+assistant) + turn 3 user
    last_contents = fake_gemini.calls[-1]["body"]["contents"]
    joined = " | ".join(
        p.get("text", "") for item in last_contents for p in (item.get("parts") or [])
    )
    assert "Turn one message" not in joined
    assert "Turn two message" in joined
    assert "Turn three message" in joined

    # Full history in SQLite remains intact (3 turns = 6 messages)
    hist = c.get(f"/sessions/{sid}/messages").json()
    assert len(hist["messages"]) == 6


@pytest.mark.asyncio
async def test_concurrent_requests_across_sessions_no_db_locks_or_bleed(tmp_path: Path, fake_gemini):
    db_file = tmp_path / "concurrent.db"
    settings = Settings(
        LLM_API_KEYS="conc-k1,conc-k2",
        LLM_MODEL="gemini/gemini-2.5-flash",
        DATABASE_URL=f"sqlite:///{db_file}",
        ALLOWED_ORIGINS="http://localhost:3000",
        ENABLE_FAILURE_SIMULATION=True,
        CACHE_TYPE="local",
    )
    app = create_app(settings=settings)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            tasks = [
                ac.post(
                    "/chat",
                    json={"session_id": f"s-conc-{i}", "message": f"Concurrent prompt {i}"},
                )
                for i in range(10)
            ]
            responses = await asyncio.gather(*tasks)

        assert all(r.status_code == 200 for r in responses)
        for i, r in enumerate(responses):
            body = r.json()
            assert body["session_id"] == f"s-conc-{i}"
            assert f"Concurrent prompt {i}" in body["reply"]

