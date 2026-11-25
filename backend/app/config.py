"""Application settings parsed from environment variables."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class KeyEntry:
    """Single API key entry in the ordered failover pool."""

    key_id: str
    api_key: str
    model: str


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_api_keys: str = Field(default="", alias="LLM_API_KEYS")
    llm_model: str = Field(default="gemini/gemini-2.5-flash", alias="LLM_MODEL")
    llm_models: str | None = Field(default=None, alias="LLM_MODELS")

    database_url: str = Field(default="sqlite:////data/app.db", alias="DATABASE_URL")
    allowed_origins: str = Field(default="http://localhost:3000", alias="ALLOWED_ORIGINS")
    enable_failure_simulation: bool = Field(default=False, alias="ENABLE_FAILURE_SIMULATION")

    default_system_prompt: str = Field(
        default="You are a helpful assistant.",
        alias="DEFAULT_SYSTEM_PROMPT",
    )
    cache_type: str = Field(default="local", alias="CACHE_TYPE")
    cache_dir: str = Field(default="/data/llm_cache", alias="CACHE_DIR")
    llm_timeout_seconds: float = Field(default=30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_temperature: float = Field(default=0.7, alias="LLM_TEMPERATURE")
    max_history_messages: int = Field(default=50, alias="MAX_HISTORY_MESSAGES")
    port: int = Field(default=8000, alias="PORT")

    def parse_key_pool(self) -> list[KeyEntry]:
        """Parse LLM_API_KEYS (and optional LLM_MODELS) into ordered KeyEntry items."""
        raw_keys = [k.strip() for k in self.llm_api_keys.split(",") if k.strip()]
        if not raw_keys:
            return []

        per_key_models: list[str] = []
        if self.llm_models:
            per_key_models = [m.strip() for m in self.llm_models.split(",") if m.strip()]

        pool: list[KeyEntry] = []
        for idx, api_key in enumerate(raw_keys, start=1):
            model = per_key_models[idx - 1] if idx - 1 < len(per_key_models) else self.llm_model.strip()
            pool.append(KeyEntry(key_id=f"key_{idx}", api_key=api_key, model=model))
        return pool

    def parse_allowed_origins(self) -> list[str]:
        """Parse comma-separated CORS origins."""
        origins = [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]
        return origins or ["http://localhost:3000"]

    def resolve_sqlite_path(self) -> str:
        """Convert DATABASE_URL (e.g. sqlite:////data/app.db) to a filesystem path."""
        url = self.database_url.strip()
        if url == ":memory:" or url == "sqlite:///:memory:":
            return ":memory:"
        if url.startswith("sqlite:////"):
            # Four slashes -> POSIX absolute path (/data/app.db) or Windows drive (sqlite:////C:/...)
            rest = url[len("sqlite:////") :]
            if len(rest) >= 2 and rest[1] == ":":
                path = Path(rest)
            else:
                path = Path("/" + rest)
        elif url.startswith("sqlite:///"):
            path = Path(url[len("sqlite:///") :])
        else:
            path = Path(url)

        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()

