"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path


class Settings:
    """Blast Radius MCP settings, loaded from environment variables."""

    def __init__(self) -> None:
        self.REPO_ROOT: str = os.environ.get("REPO_ROOT", ".")
        self.CACHE_DB_PATH: str = os.environ.get(
            "CACHE_DB_PATH",
            str(Path.home() / ".blast_radius" / "cache.db"),
        )
        self.SCHEMA_VERSION: str = "v1"
        self.LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
        self.OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
        self.PINECONE_API_KEY: str = os.environ.get("PINECONE_API_KEY", "")
        self.PINECONE_INDEX: str = os.environ.get("PINECONE_INDEX", "")
        self.PINECONE_HOST: str = os.environ.get("PINECONE_HOST", "")
        self.OPENAI_EMBEDDING_MODEL: str = os.environ.get(
            "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
        )


# Module-level singleton
settings = Settings()
