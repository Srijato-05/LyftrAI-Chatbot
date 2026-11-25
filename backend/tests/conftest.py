"""Shared pytest fixtures for backend tests (fully offline, mocked HTTP transport)."""

import os

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import asyncio
import json
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

from app.config import Settings
from app.main import create_app


def make_gemini_response(
    url: str,
    text: str,
    prompt_tokens: int = 24,
    output_tokens: int = 8,
) -> httpx.Response:
    """Build a synthetic Gemini generateContent HTTP 200 response."""
    payload = {
        "candidates": [
            {
                "content": {"parts": [{"text": text}], "role": "model"},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": output_tokens,
            "totalTokenCount": prompt_tokens + output_tokens,
        },
        "modelVersion": "gemini-2.5-flash",
    }
    return httpx.Response(
        status_code=200,
        content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", url),
    )


class FakeGeminiBackend:
    """Programmable fake for AsyncHTTPHandler.post that logs calls and supports fault/delay injection."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.key_errors: dict[str, int] = {}
        self.key_exceptions: dict[str, Exception] = {}
        self.delay_seconds: float = 0.0
        self.reply_fn: Callable[[list[dict[str, Any]], int], tuple[str, int, int]] | None = None

    def set_key_error(self, api_key: str, status_code: int) -> None:
        """Force HTTP error status whenever a request uses api_key."""
        self.key_errors[api_key] = status_code

    def set_key_exception(self, api_key: str, exc: Exception) -> None:
        """Force transport/network exception whenever a request uses api_key."""
        self.key_exceptions[api_key] = exc

    def clear_errors(self) -> None:
        """Clear all injected HTTP and transport faults."""
        self.key_errors.clear()
        self.key_exceptions.clear()

    async def post(self, url: str = "", *args: Any, **kwargs: Any) -> httpx.Response:
        headers = kwargs.get("headers") or {}
        params = kwargs.get("params") or {}
        api_key = headers.get("x-goog-api-key") or params.get("key") or ""
        if not api_key and "key=" in url:
            api_key = url.split("key=", 1)[1].split("&", 1)[0]

        raw_data = kwargs.get("data") or kwargs.get("json")
        if isinstance(raw_data, (bytes, str)):
            body = json.loads(raw_data)
        elif isinstance(raw_data, dict):
            body = raw_data
        else:
            body = {}

        self.calls.append({"url": url, "api_key": api_key, "body": body})

        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)

        if api_key in self.key_exceptions:
            raise self.key_exceptions[api_key]

        if api_key in self.key_errors:
            status = self.key_errors[api_key]
            return httpx.Response(
                status_code=status,
                content=json.dumps({"error": {"code": status, "message": f"Mock HTTP {status}"}}).encode("utf-8"),
                headers={"content-type": "application/json"},
                request=httpx.Request("POST", url),
            )

        contents = body.get("contents") or []
        if self.reply_fn is not None:
            text, p_tok, o_tok = self.reply_fn(contents, len(self.calls))
        else:
            last_text = ""
            if contents:
                parts = contents[-1].get("parts") or []
                if parts:
                    last_text = parts[0].get("text", "")
            text = f"Echo({len(self.calls)}): {last_text}"
            total_chars = sum(
                len(p.get("text", ""))
                for item in contents
                for p in (item.get("parts") or [])
            )
            p_tok = max(10, total_chars)
            o_tok = max(4, len(text.split()))

        return make_gemini_response(url, text=text, prompt_tokens=p_tok, output_tokens=o_tok)


@pytest.fixture
def fake_gemini() -> FakeGeminiBackend:
    """Provide a programmable fake Gemini HTTP handler patched onto AsyncHTTPHandler.post."""
    backend = FakeGeminiBackend()
    with patch.object(AsyncHTTPHandler, "post", new=backend.post):
        yield backend


@pytest.fixture
def make_client(tmp_path: Path, fake_gemini: FakeGeminiBackend):
    """Factory fixture returning a TestClient backed by an isolated SQLite DB."""
    clients: list[TestClient] = []

    def _factory(
        *,
        enable_simulation: bool = True,
        api_keys: str = "test-secret-key-1,test-secret-key-2",
        llm_model: str = "gemini/gemini-2.5-flash",
        llm_models: str | None = None,
        allowed_origins: str = "http://localhost:3000",
        max_history_messages: int = 50,
        cache_type: str = "local",
        cache_dir: str | None = None,
        db_name: str = "test.db",
    ) -> TestClient:
        db_file = tmp_path / db_name
        settings = Settings(
            LLM_API_KEYS=api_keys,
            LLM_MODEL=llm_model,
            LLM_MODELS=llm_models,
            DATABASE_URL=f"sqlite:///{db_file}",
            ALLOWED_ORIGINS=allowed_origins,
            ENABLE_FAILURE_SIMULATION=enable_simulation,
            MAX_HISTORY_MESSAGES=max_history_messages,
            CACHE_TYPE=cache_type,
            CACHE_DIR=cache_dir or str(tmp_path / "llm_cache"),
            LLM_TIMEOUT_SECONDS=10.0,
        )
        app = create_app(settings=settings)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield _factory

    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    """Default TestClient with 2 keys and failure simulation enabled."""
    return make_client(enable_simulation=True)
