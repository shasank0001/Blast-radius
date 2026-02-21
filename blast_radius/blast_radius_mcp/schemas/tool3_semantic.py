"""Tool 3 — Semantic Neighbor Search schema models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import Position


# ── Request ──────────────────────────────────────────────────────────

class Scope(BaseModel):
    """Scope for semantic search."""
    model_config = ConfigDict(extra="forbid")

    paths: list[str] = []
    globs: list[str] = []


class Tool3Options(BaseModel):
    """Options for semantic neighbor search."""
    model_config = ConfigDict(extra="forbid")

    top_k: int = Field(default=25, ge=1, le=200)
    min_score: float = Field(default=0.35, ge=0.0, le=1.0)
    mode: Literal["auto", "embedding", "bm25"] = "auto"


class Tool3Request(BaseModel):
    """Tool 3 request inputs."""
    model_config = ConfigDict(extra="forbid")

    query_text: str = Field(min_length=3)
    scope: Scope = Field(default_factory=Scope)
    options: Tool3Options = Field(default_factory=Tool3Options)


# ── Response components ──────────────────────────────────────────────

class Span(BaseModel):
    """Source span with start/end positions (line 1-based, col 0-based)."""
    model_config = ConfigDict(extra="forbid")

    start: Position
    end: Position


class Neighbor(BaseModel):
    """A semantic neighbor result."""
    model_config = ConfigDict(extra="forbid")

    neighbor_id: str
    file: str
    symbol: str
    span: Span
    score: float = Field(ge=0.0, le=1.0)
    method: Literal["openai_pinecone", "bm25"]
    rationale_snippet: str
    uncorroborated: bool = True


class IndexStats(BaseModel):
    """Index statistics."""
    model_config = ConfigDict(extra="forbid")

    chunks_total: int
    chunks_scanned: int
    backend: Literal["openai_pinecone", "bm25"]


class Tool3Diagnostic(BaseModel):
    """Diagnostics for Tool 3."""
    model_config = ConfigDict(extra="forbid")

    severity: Literal["info", "warning", "error"]
    code: Literal[
        "semantic_provider_unavailable",
        "vector_index_missing",
        "semantic_index_empty",
        "threshold_filtered_all",
    ]
    message: str


class Tool3Result(BaseModel):
    """Complete result payload for Tool 3."""
    model_config = ConfigDict(extra="forbid")

    retrieval_mode: Literal["embedding_primary", "bm25_fallback"]
    neighbors: list[Neighbor] = []
    index_stats: IndexStats
    diagnostics: list[Tool3Diagnostic] = []
