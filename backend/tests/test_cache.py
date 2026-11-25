"""Tests for LiteLLM response caching behavior."""

import time


def test_same_first_message_in_new_session_hits_cache(client, fake_gemini):
    msg = "Unique cache prompt 101"

    r1 = client.post("/chat", json={"session_id": "s-cache-a", "message": msg})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert d1["metadata"]["key_id"] == "key_1"
    assert d1["metadata"]["fallback_attempts"] == 0
    assert len(fake_gemini.calls) == 1

    # Allow LiteLLM's async background cache write to complete
    time.sleep(0.2)

    r2 = client.post("/chat", json={"session_id": "s-cache-b", "message": msg})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["reply"] == d1["reply"]
    assert d2["metadata"]["resolution_source"] == "LLM_CACHE"
    assert d2["metadata"]["key_id"] is None
    assert d2["metadata"]["fallback_attempts"] == 0
    assert d2["metadata"]["input_tokens"] == d1["metadata"]["input_tokens"]
    assert d2["metadata"]["output_tokens"] == d1["metadata"]["output_tokens"]
    # Zero extra HTTP calls to provider
    assert len(fake_gemini.calls) == 1


def test_different_message_does_not_hit_cache(client, fake_gemini):
    r1 = client.post("/chat", json={"session_id": "s-diff-1", "message": "Prompt Alpha"})
    assert r1.status_code == 200
    time.sleep(0.2)

    r2 = client.post("/chat", json={"session_id": "s-diff-2", "message": "Prompt Beta"})
    assert r2.status_code == 200
    assert r2.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert len(fake_gemini.calls) == 2


def test_same_message_with_different_history_misses_cache(client, fake_gemini):
    r1 = client.post("/chat", json={"session_id": "s-hist-1", "message": "First question"})
    assert r1.status_code == 200
    time.sleep(0.2)

    # Same text as a follow-up has non-empty prior history -> different LLM message list -> live call
    r2 = client.post("/chat", json={"session_id": "s-hist-1", "message": "First question"})
    assert r2.status_code == 200
    assert r2.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert len(fake_gemini.calls) == 2

