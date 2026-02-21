"""Tool 4 — Temporal Coupling schema models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Request ──────────────────────────────────────────────────────────

class Tool4Options(BaseModel):
    """Options for temporal coupling analysis."""
    model_config = ConfigDict(extra="forbid")

    max_files: int = Field(default=20, ge=1, le=200)
    window_commits: int = Field(default=500, ge=1, le=20000)
    follow_renames: bool = True
    exclude_merges: bool = True
    max_commit_size: int = Field(default=200, ge=1, le=5000)


class Tool4Request(BaseModel):
    """Tool 4 request inputs."""
    model_config = ConfigDict(extra="forbid")

    file_paths: list[str] = Field(min_length=1)
    options: Tool4Options = Field(default_factory=Tool4Options)


# ── Response components ──────────────────────────────────────────────

class CouplingTarget(BaseModel):
    """A target file with history metadata."""
    model_config = ConfigDict(extra="forbid")

    file: str
    aliases: list[str] = []
    support_commits: int


class ExampleCommit(BaseModel):
    """An example commit showing co-change."""
    model_config = ConfigDict(extra="forbid")

    sha: str
    date: str
    message: str


class Coupling(BaseModel):
    """A coupling relationship between files."""
    model_config = ConfigDict(extra="forbid")

    target_file: str
    coupled_file: str
    weight: float = Field(ge=0.0, le=1.0)
    support: int
    example_commits: list[ExampleCommit] = []


class HistoryStats(BaseModel):
    """Git history scanning statistics."""
    model_config = ConfigDict(extra="forbid")

    commits_scanned: int
    commits_used: int
    renames_followed: int
    date_range: str = ""
    files_in_history: int = 0


class Tool4Diagnostic(BaseModel):
    """Diagnostics for Tool 4."""
    model_config = ConfigDict(extra="forbid")

    severity: Literal["info", "warning", "error"]
    code: Literal[
        "git_history_unavailable",
        "low_history_support",
        "target_not_in_history",
        "history_window_truncated",
    ]
    message: str


class Tool4Result(BaseModel):
    """Complete result payload for Tool 4."""
    model_config = ConfigDict(extra="forbid")

    targets: list[CouplingTarget] = []
    couplings: list[Coupling] = []
    history_stats: HistoryStats
    diagnostics: list[Tool4Diagnostic] = []
