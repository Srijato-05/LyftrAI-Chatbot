"""FastAPI route definitions for /health, /chat, and /sessions/{session_id}/messages."""

import logging
from time import perf_counter

from fastapi import APIRouter, Request

from app.errors import DatabaseUnavailableError, SessionNotFoundError
from app.llm.simulation import parse_simulation_header
from app.schemas import (
    ChatMetadata,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    HistoryMessage,
    HistoryResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return 200 when SQLite is reachable and the key pool is loaded."""
    db = request.app.state.db
    gateway = request.app.state.gateway

    try:
        await db.ping()
    except Exception as exc:
        logger.error("Health check database ping failed: %s", type(exc).__name__)
        raise DatabaseUnavailableError() from exc

    return HealthResponse(
        status="ok",
        keys_configured=len(gateway.pool),
        cache_enabled=gateway.cache_enabled,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Handle a multi-turn chat message with key failover and response caching."""
    t_start = perf_counter()

    settings = request.app.state.settings
    db = request.app.state.db
    gateway = request.app.state.gateway

    simulated = parse_simulation_header(
        request.headers.get("X-Simulate-Failure"),
        gateway.key_ids,
        settings.enable_failure_simulation,
    )

    session = await db.get_session(payload.session_id)
    effective_system_prompt = (
        payload.system_prompt
        or (session["system_prompt"] if session else None)
        or settings.default_system_prompt
    )

    stored_history = await db.get_history(payload.session_id)
    if settings.max_history_messages > 0 and len(stored_history) > settings.max_history_messages:
        stored_history = stored_history[-settings.max_history_messages :]

    llm_messages: list[dict[str, str]] = [{"role": "system", "content": effective_system_prompt}]
    for item in stored_history:
        llm_messages.append({"role": item["role"], "content": item["content"]})
    llm_messages.append({"role": "user", "content": payload.message})

    result = await gateway.complete(llm_messages, simulated=simulated)
    latency_ms = int((perf_counter() - t_start) * 1000)

    metadata = ChatMetadata(
        resolution_source=result.resolution_source,  # type: ignore[arg-type]
        model=result.model,
        latency_ms=latency_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        key_id=result.key_id,
        fallback_attempts=result.fallback_attempts,
    )

    stored_system_prompt = payload.system_prompt or (session["system_prompt"] if session else None)
    await db.save_turn(
        session_id=payload.session_id,
        system_prompt=stored_system_prompt,
        user_content=payload.message,
        assistant_content=result.reply,
        metadata=metadata.model_dump(),
    )

    logger.info(
        "chat session=%s source=%s key_id=%s fallbacks=%d latency_ms=%d",
        payload.session_id,
        metadata.resolution_source,
        metadata.key_id,
        metadata.fallback_attempts,
        metadata.latency_ms,
    )

    return ChatResponse(
        session_id=payload.session_id,
        reply=result.reply,
        metadata=metadata,
    )


@router.get(
    "/sessions/{session_id}/messages",
    response_model=HistoryResponse,
    response_model_exclude_none=True,
)
async def get_session_messages(session_id: str, request: Request) -> HistoryResponse:
    """Return oldest-first message history for a session without the system prompt."""
    db = request.app.state.db
    session = await db.get_session(session_id)
    if session is None:
        raise SessionNotFoundError()

    rows = await db.get_history(session_id)
    messages = [
        HistoryMessage(
            role=row["role"],
            content=row["content"],
            metadata=row["metadata"],
        )
        for row in rows
    ]
    return HistoryResponse(session_id=session_id, messages=messages)

