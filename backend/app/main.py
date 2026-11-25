"""FastAPI application factory, lifespan wiring, and CORS configuration."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db import Database
from app.errors import register_exception_handlers
from app.llm.gateway import LLMGateway
from app.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


class _SecretRedactingFilter(logging.Filter):
    """Mask configured API keys in all log records (including third-party libraries)."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        msg = record.getMessage()
        for secret in self._secrets:
            if secret in msg:
                msg = msg.replace(secret, "***REDACTED***")
        record.msg = msg
        record.args = ()
        return True


def _install_log_protection(secrets: list[str]) -> None:
    """Attach secret-redaction filter and quiet verbose third-party LiteLLM loggers."""
    for name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy"):
        logging.getLogger(name).setLevel(logging.WARNING)
    root_logger = logging.getLogger()
    redactor = _SecretRedactingFilter(secrets)
    for handler in root_logger.handlers:
        handler.addFilter(redactor)
    root_logger.addFilter(redactor)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    cfg = settings or get_settings()
    _install_log_protection([entry.api_key for entry in cfg.parse_key_pool()])

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        db = Database(cfg.resolve_sqlite_path())
        await db.init_db()
        gateway = LLMGateway(cfg)

        if len(gateway.pool) < 2:
            logger.warning(
                "Only %d API key(s) configured; at least 2 keys are recommended for failover.",
                len(gateway.pool),
            )
        else:
            logger.info("Configured %d API keys in failover pool.", len(gateway.pool))

        application.state.settings = cfg
        application.state.db = db
        application.state.gateway = gateway
        yield

    application = FastAPI(
        title="Lyftr AI Chatbot Gateway",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.parse_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    register_exception_handlers(application)
    application.include_router(router)
    return application


app = create_app()

