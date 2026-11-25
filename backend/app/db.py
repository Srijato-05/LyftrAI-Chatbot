"""SQLite persistence layer for chat sessions and messages."""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    system_prompt TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata    TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thread-safe async wrapper around stdlib sqlite3."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sync(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(SCHEMA_SQL)

    async def init_db(self) -> None:
        """Create tables and indexes on startup."""
        await asyncio.to_thread(self._init_sync)

    def _ping_sync(self) -> None:
        with self._connect() as conn:
            conn.execute("SELECT 1;").fetchone()

    async def ping(self) -> None:
        """Verify SQLite connectivity."""
        await asyncio.to_thread(self._ping_sync)

    def _get_session_sync(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT session_id, system_prompt, created_at FROM sessions WHERE session_id = ?;",
                (session_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return session row or None if unknown."""
        return await asyncio.to_thread(self._get_session_sync, session_id)

    def _get_history_sync(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content, metadata
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC;
                """,
                (session_id,),
            ).fetchall()
            history: list[dict[str, Any]] = []
            for row in rows:
                entry: dict[str, Any] = {
                    "role": row["role"],
                    "content": row["content"],
                }
                if row["role"] == "assistant" and row["metadata"]:
                    entry["metadata"] = json.loads(row["metadata"])
                else:
                    entry["metadata"] = None
                history.append(entry)
            return history

    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        """Return all stored messages for a session ordered oldest-first."""
        return await asyncio.to_thread(self._get_history_sync, session_id)

    def _save_turn_sync(
        self,
        session_id: str,
        system_prompt: str | None,
        user_content: str,
        assistant_content: str,
        metadata: dict[str, Any],
    ) -> None:
        now = _utc_now_iso()
        metadata_json = json.dumps(metadata)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, system_prompt, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    system_prompt = COALESCE(excluded.system_prompt, sessions.system_prompt);
                """,
                (session_id, system_prompt, now),
            )
            conn.execute(
                """
                INSERT INTO messages (session_id, role, content, metadata, created_at)
                VALUES (?, 'user', ?, NULL, ?);
                """,
                (session_id, user_content, now),
            )
            conn.execute(
                """
                INSERT INTO messages (session_id, role, content, metadata, created_at)
                VALUES (?, 'assistant', ?, ?, ?);
                """,
                (session_id, assistant_content, metadata_json, now),
            )

    async def save_turn(
        self,
        session_id: str,
        system_prompt: str | None,
        user_content: str,
        assistant_content: str,
        metadata: dict[str, Any],
    ) -> None:
        """Persist session upsert + user/assistant messages in a single transaction."""
        await asyncio.to_thread(
            self._save_turn_sync,
            session_id,
            system_prompt,
            user_content,
            assistant_content,
            metadata,
        )

