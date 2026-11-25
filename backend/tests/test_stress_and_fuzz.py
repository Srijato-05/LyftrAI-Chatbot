"""Concurrency stress, rapid failover, and long multi-turn conversation tests."""

import asyncio
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.main import create_app


@pytest.mark.asyncio
async def test_mixed_workload_30_concurrent_requests(tmp_path: Path, fake_gemini):
    fake_gemini.delay_seconds = 0.02
    db_file = tmp_path / "stress.db"
    settings = Settings(
        LLM_API_KEYS="stress-k1,stress-k2",
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
            # Seed one prompt into cache first
            seed = await ac.post("/chat", json={"session_id": "s-seed", "message": "Cached seed prompt"})
            assert seed.status_code == 200
            await asyncio.sleep(0.2)

            coros = []
            # 10 live requests across distinct sessions
            for i in range(10):
                coros.append(
                    ac.post("/chat", json={"session_id": f"s-live-{i}", "message": f"Live {i}"})
                )
            # 5 cache hits
            for i in range(5):
                coros.append(
                    ac.post("/chat", json={"session_id": f"s-hit-{i}", "message": "Cached seed prompt"})
                )
            # 5 simulated single-key failovers
            for i in range(5):
                coros.append(
                    ac.post(
                        "/chat",
                        json={"session_id": f"s-sim-{i}", "message": f"Sim {i}"},
                        headers={"X-Simulate-Failure": "key_1=429"},
                    )
                )
            # 4 simulated all-fail (503)
            for i in range(4):
                coros.append(
                    ac.post(
                        "/chat",
                        json={"session_id": f"s-fail-{i}", "message": f"Fail {i}"},
                        headers={"X-Simulate-Failure": "*=503"},
                    )
                )
            # 3 invalid payloads (422)
            for i in range(3):
                coros.append(
                    ac.post("/chat", json={"session_id": f"s-bad-{i}", "message": "   "})
                )
            # 3 health checks
            for _ in range(3):
                coros.append(ac.get("/health"))

            results = await asyncio.gather(*coros)

            live_res = results[0:10]
            hit_res = results[10:15]
            sim_res = results[15:20]
            fail_res = results[20:24]
            bad_res = results[24:27]
            health_res = results[27:30]

            for i, r in enumerate(live_res):
                assert r.status_code == 200
                assert r.json()["session_id"] == f"s-live-{i}"
                assert f"Live {i}" in r.json()["reply"]

            for r in hit_res:
                assert r.status_code == 200
                assert r.json()["metadata"]["resolution_source"] == "LLM_CACHE"
                assert r.json()["metadata"]["key_id"] is None

            for r in sim_res:
                assert r.status_code == 200
                assert r.json()["metadata"]["key_id"] == "key_2"
                assert r.json()["metadata"]["fallback_attempts"] == 1

            for i, r in enumerate(fail_res):
                assert r.status_code == 503
                assert r.json() == {"detail": "all providers unavailable"}
                assert (await ac.get(f"/sessions/s-fail-{i}/messages")).status_code == 404

            for i, r in enumerate(bad_res):
                assert r.status_code == 422
                assert (await ac.get(f"/sessions/s-bad-{i}/messages")).status_code == 404

            for r in health_res:
                assert r.status_code == 200
                assert r.json()["status"] == "ok"


def test_ten_turn_conversation_ordering_and_token_growth(client):
    sid = "s-ten-turns"
    prev_input_tokens = 0
    for turn in range(1, 11):
        res = client.post(
            "/chat",
            json={"session_id": sid, "message": f"Turn {turn} unique user message"},
        )
        assert res.status_code == 200
        toks = res.json()["metadata"]["input_tokens"]
        assert toks > prev_input_tokens
        prev_input_tokens = toks

    hist = client.get(f"/sessions/{sid}/messages")
    assert hist.status_code == 200
    msgs = hist.json()["messages"]
    assert len(msgs) == 20
    for turn in range(1, 11):
        user_msg = msgs[(turn - 1) * 2]
        asst_msg = msgs[(turn - 1) * 2 + 1]
        assert user_msg["role"] == "user"
        assert user_msg["content"] == f"Turn {turn} unique user message"
        assert asst_msg["role"] == "assistant"
        assert "metadata" in asst_msg


def test_rapid_repeated_failover_then_clean_recovery(client):
    for i in range(5):
        r = client.post(
            "/chat",
            json={"session_id": f"s-rap-{i}", "message": f"Rapid sim {i}"},
            headers={"X-Simulate-Failure": "key_1=502"},
        )
        assert r.status_code == 200
        assert r.json()["metadata"]["key_id"] == "key_2"
        assert r.json()["metadata"]["fallback_attempts"] == 1

    r_ok = client.post("/chat", json={"session_id": "s-rap-ok", "message": "Normal request"})
    assert r_ok.status_code == 200
    assert r_ok.json()["metadata"]["key_id"] == "key_1"
    assert r_ok.json()["metadata"]["fallback_attempts"] == 0

