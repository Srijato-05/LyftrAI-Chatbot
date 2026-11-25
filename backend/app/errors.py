"""Custom domain exceptions and JSON error handlers."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AllProvidersUnavailable(Exception):
    """Raised when every configured API key fails for a request."""


class SessionNotFoundError(Exception):
    """Raised when a requested session does not exist in SQLite."""


class DatabaseUnavailableError(Exception):
    """Raised when SQLite health ping fails."""


def register_exception_handlers(app: FastAPI) -> None:
    """Register JSON-only exception handlers so stack traces or HTML never leak."""

    @app.exception_handler(AllProvidersUnavailable)
    async def handle_providers_unavailable(_: Request, __: AllProvidersUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "all providers unavailable"})

    @app.exception_handler(SessionNotFoundError)
    async def handle_session_not_found(_: Request, __: SessionNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "session not found"})

    @app.exception_handler(DatabaseUnavailableError)
    async def handle_db_unavailable(_: Request, __: DatabaseUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "database unavailable"})

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server exception: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

