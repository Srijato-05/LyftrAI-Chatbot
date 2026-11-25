"""LiteLLM Router hybrid gateway handling ordered key failover and caching."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import litellm
from litellm.caching.caching import Cache

from app.config import KeyEntry, Settings
from app.errors import AllProvidersUnavailable
from app.llm.simulation import status_to_mock_string

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GatewayResult:
    """Structured LLM completion output returned to the route layer."""

    reply: str
    model: str
    input_tokens: int
    output_tokens: int
    resolution_source: str
    key_id: str | None
    fallback_attempts: int


def _build_router_args(
    pool: list[KeyEntry],
    simulated: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, list[str]]]]:
    """Construct Router model_list and ordered fallbacks from the key pool."""
    model_list: list[dict[str, Any]] = []
    for entry in pool:
        litellm_params: dict[str, Any] = {
            "model": entry.model,
            "api_key": entry.api_key,
        }
        if simulated and entry.key_id in simulated:
            litellm_params["mock_response"] = status_to_mock_string(simulated[entry.key_id])

        model_list.append(
            {
                "model_name": entry.key_id,
                "litellm_params": litellm_params,
                "model_info": {"id": entry.key_id},
            }
        )

    fallbacks: list[dict[str, list[str]]] = []
    if len(pool) > 1:
        fallbacks.append({pool[0].key_id: [entry.key_id for entry in pool[1:]]})

    return model_list, fallbacks


def _create_router(
    pool: list[KeyEntry],
    timeout_seconds: float,
    simulated: dict[str, int] | None = None,
) -> litellm.Router:
    model_list, fallbacks = _build_router_args(pool, simulated=simulated)
    return litellm.Router(
        model_list=model_list,
        fallbacks=fallbacks,
        cache_responses=True,
        num_retries=0,
        cooldown_time=0,
        timeout=timeout_seconds,
    )


def configure_litellm_cache(settings: Settings) -> bool:
    """Initialize LiteLLM's built-in cache according to settings."""
    cache_type = settings.cache_type.strip().lower()
    if cache_type == "disk":
        Path(settings.cache_dir).mkdir(parents=True, exist_ok=True)
        litellm.cache = Cache(type="disk", disk_cache_dir=settings.cache_dir)
    else:
        litellm.cache = Cache(type="local")
    return litellm.cache is not None


class LLMGateway:
    """Manages LiteLLM Router failover across the configured API key pool."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pool: list[KeyEntry] = settings.parse_key_pool()
        self.key_ids: list[str] = [entry.key_id for entry in self.pool]
        self._model_by_key: dict[str, str] = {entry.key_id: entry.model for entry in self.pool}

        litellm.drop_params = True
        litellm.suppress_debug_info = True
        self.cache_enabled = configure_litellm_cache(settings)

        self.router: litellm.Router | None = (
            _create_router(self.pool, timeout_seconds=settings.llm_timeout_seconds)
            if self.pool
            else None
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        simulated: dict[str, int] | None = None,
    ) -> GatewayResult:
        """Resolve a chat completion using LiteLLM Router and response caching."""
        if not self.pool or self.router is None:
            raise AllProvidersUnavailable()

        is_simulated = bool(simulated)
        active_router = (
            _create_router(
                self.pool,
                timeout_seconds=self.settings.llm_timeout_seconds,
                simulated=simulated,
            )
            if is_simulated
            else self.router
        )

        call_kwargs: dict[str, Any] = {
            "model": self.pool[0].key_id,
            "messages": messages,
            "temperature": self.settings.llm_temperature,
            "timeout": self.settings.llm_timeout_seconds,
            "caching": True,
        }
        # Bypass cache read & write during failure simulation so tests are completely isolated.
        if is_simulated:
            call_kwargs["cache"] = {"no-cache": True, "no-store": True}

        try:
            resp = await active_router.acompletion(**call_kwargs)
        except Exception as exc:
            logger.warning("All keys failed via LiteLLM Router: %s", type(exc).__name__)
            raise AllProvidersUnavailable() from exc

        hidden = getattr(resp, "_hidden_params", None) or {}
        cache_hit = bool(hidden.get("cache_hit"))
        text = ((resp.choices[0].message.content if resp.choices else "") or "").strip()
        if not text:
            logger.warning("LiteLLM returned empty reply content")
            raise AllProvidersUnavailable()

        usage = getattr(resp, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        headers = hidden.get("additional_headers") or {}
        if cache_hit:
            winning_key: str | None = None
            fallback_attempts = 0
            model_used = self.pool[0].model
            resolution_source = "LLM_CACHE"
        else:
            raw_model_id = hidden.get("model_id")
            winning_key = raw_model_id if raw_model_id in self._model_by_key else self.pool[0].key_id
            fallback_attempts = int(headers.get("x-litellm-attempted-fallbacks", 0) or 0)
            model_used = self._model_by_key.get(winning_key, self.pool[0].model)
            resolution_source = "LIVE_INFERENCE"

        return GatewayResult(
            reply=text,
            model=model_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            resolution_source=resolution_source,
            key_id=winning_key,
            fallback_attempts=fallback_attempts,
        )
