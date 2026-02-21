"""Tool 5 — Test Impact Analyzer schema models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Request ──────────────────────────────────────────────────────────

class ImpactedNode(BaseModel):
    """An impacted code node to find tests for."""
    model_config = ConfigDict(extra="forbid")

    file: str
    symbol: str | None = None
    kind: Literal["module", "class", "function", "method", "field"] | None = None


class Tool5Options(BaseModel):
    """Options for test impact analysis."""
    model_config = ConfigDict(extra="forbid")

    max_tests: int = Field(default=10, ge=1, le=200)
    include_transitive: bool = True
    transitive_depth: int = Field(default=2, ge=0, le=5)
    include_literal_field_matches: bool = True
    coverage_mode: Literal["off", "optional"] = "off"


class Tool5Request(BaseModel):
    """Tool 5 request inputs."""
    model_config = ConfigDict(extra="forbid")

    impacted_nodes: list[ImpactedNode] = Field(min_length=1)
    options: Tool5Options = Field(default_factory=Tool5Options)


# ── Response components ──────────────────────────────────────────────

class TestReason(BaseModel):
    """A reason why a test was selected."""
    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "direct_import",
        "from_import_symbol",
        "transitive_import",
        "symbol_reference",
        "field_literal_match",
        "coverage_confirmation",
    ]
    evidence: str


class TestItem(BaseModel):
    """A selected test with ranking and evidence."""
    model_config = ConfigDict(extra="forbid")

    test_id: str
    nodeid: str
    file: str
    score: float = Field(ge=0.0, le=1.0)
    rank: int
    confidence: Literal["high", "medium", "low"]
    reasons: list[TestReason] = []


class UnmatchedImpact(BaseModel):
    """An impacted node with no matching tests."""
    model_config = ConfigDict(extra="forbid")

    file: str
    symbol: str | None = None
    reason: Literal[
        "no_test_reference",
        "test_discovery_empty",
        "mapping_ambiguous",
    ]


class SelectionStats(BaseModel):
    """Test selection statistics."""
    model_config = ConfigDict(extra="forbid")

    tests_considered: int
    tests_selected: int
    high_confidence: int


class Tool5Diagnostic(BaseModel):
    """Diagnostics for Tool 5."""
    model_config = ConfigDict(extra="forbid")

    severity: Literal["info", "warning", "error"]
    code: Literal[
        "tests_not_found",
        "test_parse_error",
        "coverage_unavailable",
        "selection_truncated",
    ]
    message: str


class Tool5Result(BaseModel):
    """Complete result payload for Tool 5."""
    model_config = ConfigDict(extra="forbid")

    tests: list[TestItem] = []
    unmatched_impacts: list[UnmatchedImpact] = []
    selection_stats: SelectionStats
    diagnostics: list[Tool5Diagnostic] = []
