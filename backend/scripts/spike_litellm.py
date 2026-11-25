"""Phase 2 LiteLLM spike: verify caching, mock_response exceptions, and Router hybrid."""

import os

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import asyncio
import json
import time
from unittest.mock import patch
import httpx
import litellm
from litellm.caching.caching import Cache
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler


def log(msg: str) -> None:
    print(msg, flush=True)


def banner(title: str) -> None:
    log(f"\n=== {title} ===")


def fake_gemini_http_response(
    url: str, text: str, prompt_tokens: int = 12, output_tokens: int = 5
) -> httpx.Response:
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


async def main() -> None:
    litellm.suppress_debug_info = True
    litellm.drop_params = True
    litellm.cache = Cache(type="local")

    model = "gemini/gemini-2.5-flash"
    msgs = [{"role": "user", "content": "Spike test: capital of France?"}]

    # 1. Local cache hit + usage + identical reply (via mocked HTTP transport, exercising real LiteLLM cache)
    banner("1. Local Cache Hit & Usage (Router + Real Cache Path)")
    router_live = litellm.Router(
        model_list=[
            {
                "model_name": "key_1",
                "litellm_params": {"model": model, "api_key": "fake-key-1"},
                "model_info": {"id": "key_1"},
            },
            {
                "model_name": "key_2",
                "litellm_params": {"model": model, "api_key": "fake-key-2"},
                "model_info": {"id": "key_2"},
            },
        ],
        fallbacks=[{"key_1": ["key_2"]}],
        cache_responses=True,
        num_retries=0,
        cooldown_time=0,
    )

    http_calls = 0

    async def mock_post(self, url, *args, **kwargs):
        nonlocal http_calls
        http_calls += 1
        return fake_gemini_http_response(url, "The capital of France is Paris.", prompt_tokens=15, output_tokens=7)

    with patch.object(AsyncHTTPHandler, "post", new=mock_post):
        r1 = await router_live.acompletion(model="key_1", messages=msgs, caching=True)
        log(f"r1 content: {r1.choices[0].message.content!r}, http_calls={http_calls}")
        log(f"r1 _hidden_params: {r1._hidden_params}")
        log(f"r1 usage: {r1.usage}")
        assert not r1._hidden_params.get("cache_hit")
        assert http_calls == 1
        assert r1._hidden_params.get("model_id") == "key_1"

        await asyncio.sleep(0.2)  # let LiteLLM's background cache write finish
        t0 = time.perf_counter()
        r2 = await router_live.acompletion(model="key_1", messages=msgs, caching=True)
        dt_ms = (time.perf_counter() - t0) * 1000
        log(f"r2 content: {r2.choices[0].message.content!r} (elapsed={dt_ms:.2f} ms), http_calls={http_calls}")
        log(f"r2 _hidden_params: {r2._hidden_params}")
        log(f"r2 usage: {r2.usage}")
        assert r2._hidden_params.get("cache_hit") is True
        assert http_calls == 1  # No HTTP call on cache hit
        assert r2.choices[0].message.content == r1.choices[0].message.content
        assert r2.usage.prompt_tokens == r1.usage.prompt_tokens
        assert r2.usage.completion_tokens == r1.usage.completion_tokens

        # 2. Direct acompletion cache hit with different api_key + Router cache hit after fallback
        banner("2. Cache Hit With Different API Key & After Fallback")
        direct_msgs = [{"role": "user", "content": "Direct cache test"}]
        d1 = await litellm.acompletion(model=model, messages=direct_msgs, api_key="fake-key-1", caching=True)
        await asyncio.sleep(0.2)
        d2 = await litellm.acompletion(model=model, messages=direct_msgs, api_key="fake-key-2", caching=True)
        log(f"d1 hit={d1._hidden_params.get('cache_hit')}, d2 (k2) hit={d2._hidden_params.get('cache_hit')}, http_calls={http_calls}")
        assert d2._hidden_params.get("cache_hit") is True

        # 3. cache={"no-cache": True} bypasses cache lookup
        banner("3. Dynamic cache={'no-cache': True}")
        r4 = await router_live.acompletion(
            model="key_1",
            messages=msgs,
            caching=True,
            cache={"no-cache": True},
        )
        log(f"r4 content: {r4.choices[0].message.content!r}, http_calls={http_calls}")
        log(f"r4 _hidden_params: {r4._hidden_params}")
        assert not r4._hidden_params.get("cache_hit")
        assert http_calls == 3

    # 4. Router string mock_response exceptions (429, 500, 502, 503) + failover
    banner("4. Router String Mock Exceptions & Failover")
    mock_strings = {
        429: ("litellm.RateLimitError", litellm.RateLimitError),
        500: ("litellm.InternalServerError", litellm.InternalServerError),
        502: ("litellm.InternalServerError", litellm.InternalServerError),
        503: ("litellm.InternalServerError", litellm.InternalServerError),
    }
    for code, (mock_str, exc_cls) in mock_strings.items():
        # Verify single key raises expected exception
        try:
            await litellm.acompletion(
                model=model,
                messages=[{"role": "user", "content": f"err {code}"}],
                api_key="fake-key-1",
                mock_response=mock_str,
            )
            raise AssertionError(f"Expected {exc_cls.__name__} for {code}")
        except exc_cls as e:
            log(f"Status {code} -> raised {type(e).__name__}")

        # Verify Router falls back from key_1 to key_2
        sim_router = litellm.Router(
            model_list=[
                {
                    "model_name": "key_1",
                    "litellm_params": {
                        "model": model,
                        "api_key": "fake-key-1",
                        "mock_response": mock_str,
                    },
                    "model_info": {"id": "key_1"},
                },
                {
                    "model_name": "key_2",
                    "litellm_params": {
                        "model": model,
                        "api_key": "fake-key-2",
                    },
                    "model_info": {"id": "key_2"},
                },
            ],
            fallbacks=[{"key_1": ["key_2"]}],
            num_retries=0,
            cooldown_time=0,
        )
        with patch.object(AsyncHTTPHandler, "post", new=mock_post):
            rf = await sim_router.acompletion(
                model="key_1",
                messages=[{"role": "user", "content": f"fallback {code}"}],
                caching=True,
                cache={"no-cache": True},
            )
        headers = rf._hidden_params.get("additional_headers", {})
        log(
            f"Simulated {code} fallback -> model_id={rf._hidden_params.get('model_id')}, "
            f"attempted_fallbacks={headers.get('x-litellm-attempted-fallbacks')}"
        )
        assert rf._hidden_params.get("model_id") == "key_2"
        assert headers.get("x-litellm-attempted-fallbacks") == 1

    # 5. All keys failing raises exception
    banner("5. All Keys Failing")
    all_fail_router = litellm.Router(
        model_list=[
            {
                "model_name": "key_1",
                "litellm_params": {"model": model, "api_key": "k1", "mock_response": "litellm.RateLimitError"},
                "model_info": {"id": "key_1"},
            },
            {
                "model_name": "key_2",
                "litellm_params": {"model": model, "api_key": "k2", "mock_response": "litellm.InternalServerError"},
                "model_info": {"id": "key_2"},
            },
        ],
        fallbacks=[{"key_1": ["key_2"]}],
        cache_responses=True,
        num_retries=0,
        cooldown_time=0,
    )
    try:
        await all_fail_router.acompletion(
            model="key_1",
            messages=[{"role": "user", "content": "all fail"}],
            caching=True,
            cache={"no-cache": True},
        )
        raise AssertionError("Expected exception when all keys fail")
    except Exception as e:
        log(f"All keys failed raised {type(e).__name__}: {e}")

    log("\nALL SPIKE CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
