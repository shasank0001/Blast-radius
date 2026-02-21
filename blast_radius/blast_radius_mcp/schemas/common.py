"""Common schema types shared across all tools."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Position(BaseModel):
    """Source position. line is 1-based, col is 0-based."""
    model_config = ConfigDict(extra="forbid")

    line: int
    col: int
    offset: int = -1


class Range(BaseModel):
    """Source range with start and end positions."""
    model_config = ConfigDict(extra="forbid")

    start: Position
    end: Position


class Location(BaseModel):
    """File location with range."""
    model_config = ConfigDict(extra="forbid")

    file: str
    range: Range


class RepoFingerprint(BaseModel):
    """Repository state fingerprint."""
    model_config = ConfigDict(extra="forbid")

    git_head: str | None
    dirty: bool
    fingerprint_hash: str


class StructuredError(BaseModel):
    """Structured error with code and optional location."""
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    detail: str = ""
    retryable: bool = False
    location: Location | None = None


class ToolRequestEnvelope(BaseModel):
    """Generic MCP tool request envelope."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "v1"
    run_id: str = ""
    tool_name: str = ""
    repo_root: str
    inputs: dict
    anchors: list[str] = []
    diff: str = ""
    options: dict = {}


class ToolResponseEnvelope(BaseModel):
    """Generic MCP tool response envelope."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "v1"
    tool_name: str
    run_id: str
    query_id: str
    repo_fingerprint: RepoFingerprint
    cached: bool
    timing_ms: int
    result: dict
    errors: list[StructuredError] = []
