"""Application settings loaded from environment variables."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Blast Radius MCP settings, loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="BLAST_RADIUS_",
        env_file=".env",
        extra="ignore",
    )

    REPO_ROOT: str = Field(default=".")
    CACHE_DB_PATH: str = Field(default="~/.blast_radius/cache.db")
    SCHEMA_VERSION: str = Field(default="v1")
    LOG_LEVEL: str = Field(default="INFO")
    OPENAI_API_KEY: str = Field(default="")
    PINECONE_API_KEY: str = Field(default="")
    PINECONE_INDEX: str = Field(default="blast-radius")
    PINECONE_HOST: str = Field(default="")
    OPENAI_EMBEDDING_MODEL: str = Field(default="text-embedding-3-small")


# Module-level singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the cached settings singleton, creating it on first call."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# Backward-compatible module-level instance so existing
# ``from blast_radius_mcp.settings import settings`` keeps working.
settings: Settings = get_settings()
