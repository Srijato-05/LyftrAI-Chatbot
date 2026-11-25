"""Exhaustive cache tests: latency speedup, system_prompt key splitting, multi-turn cache hits."""

import time


def test_cache_hit_is_faster_than_live_inference(client, fake_gemini):
    fake_gemini.delay_seconds = 0.15
    msg = "Latency benchmark question"

    r1 = client.post("/chat", json={"session_id": "s-lat-1", "message": msg})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert d1["metadata"]["latency_ms"] >= 140

    time.sleep(0.2)

    r2 = client.post("/chat", json={"session_id": "s-lat-2", "message": msg})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["metadata"]["resolution_source"] == "LLM_CACHE"
    assert d2["metadata"]["latency_ms"] < d1["metadata"]["latency_ms"]


def test_system_prompt_is_part_of_cache_key(client, fake_gemini):
    msg = "Who are you?"

    r1 = client.post(
        "/chat",
        json={"session_id": "s-sp-1", "message": msg, "system_prompt": "You are a chef."},
    )
    assert r1.status_code == 200
    assert r1.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    time.sleep(0.2)

    # Different system_prompt -> must NOT hit cache
    r2 = client.post(
        "/chat",
        json={"session_id": "s-sp-2", "message": msg, "system_prompt": "You are a pilot."},
    )
    assert r2.status_code == 200
    assert r2.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert len(fake_gemini.calls) == 2
    time.sleep(0.2)

    # Matching system_prompt in a brand new session -> MUST hit cache
    r3 = client.post(
        "/chat",
        json={"session_id": "s-sp-3", "message": msg, "system_prompt": "You are a chef."},
    )
    assert r3.status_code == 200
    assert r3.json()["metadata"]["resolution_source"] == "LLM_CACHE"
    assert r3.json()["reply"] == r1.json()["reply"]
    assert len(fake_gemini.calls) == 2


def test_identical_multi_turn_history_hits_cache_on_turn_2(client, fake_gemini):
    # Deterministic reply so turn-1 assistant output is identical in both sessions
    fake_gemini.reply_fn = lambda contents, _n: (f"Reply to {len(contents)} turns", 20, 6)

    assert client.post("/chat", json={"session_id": "s-mt-a", "message": "Hi"}).status_code == 200
    time.sleep(0.15)
    t2_a = client.post("/chat", json={"session_id": "s-mt-a", "message": "Next"}).json()
    assert t2_a["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    time.sleep(0.2)

    # Session B replays exact same turns -> both turn 1 and turn 2 hit cache
    t1_b = client.post("/chat", json={"session_id": "s-mt-b", "message": "Hi"}).json()
    assert t1_b["metadata"]["resolution_source"] == "LLM_CACHE"
    t2_b = client.post("/chat", json={"session_id": "s-mt-b", "message": "Next"}).json()
    assert t2_b["metadata"]["resolution_source"] == "LLM_CACHE"
    assert t2_b["reply"] == t2_a["reply"]


def test_simulation_does_not_store_to_cache(client, fake_gemini):
    msg = "Simulated must not pollute cache"
    r_sim = client.post(
        "/chat",
        json={"session_id": "s-nostore-1", "message": msg},
        headers={"X-Simulate-Failure": "key_1=429"},
    )
    assert r_sim.status_code == 200
    assert r_sim.json()["metadata"]["key_id"] == "key_2"
    time.sleep(0.2)

    # Normal request afterwards should still execute LIVE_INFERENCE on key_1
    r_live = client.post("/chat", json={"session_id": "s-nostore-2", "message": msg})
    assert r_live.status_code == 200
    assert r_live.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert r_live.json()["metadata"]["key_id"] == "key_1"
    assert len(fake_gemini.calls) == 2

