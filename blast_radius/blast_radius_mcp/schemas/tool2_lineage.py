"""Tool 2 — Data Lineage Engine schema models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import Location


# ── Request ──────────────────────────────────────────────────────────

class Tool2Options(BaseModel):
    """Options for the data lineage engine."""
    model_config = ConfigDict(extra="forbid")

    direction: Literal["request", "response", "both"] = "both"
    max_call_depth: int = Field(default=2, ge=0, le=5)
    max_sites: int = Field(default=200, ge=1, le=1000)
    include_writes: bool = True


class Tool2Request(BaseModel):
    """Tool 2 request inputs."""
    model_config = ConfigDict(extra="forbid")

    field_path: str
    entry_points: list[str] = Field(min_length=1)
    options: Tool2Options = Field(default_factory=Tool2Options)


# ── Response components ──────────────────────────────────────────────

class EntryPointResolved(BaseModel):
    """A resolved entry point (route/symbol → handler)."""
    model_config = ConfigDict(extra="forbid")

    anchor: str
    handler_symbol_id: str
    location: Location
    confidence: Literal["high", "medium", "low"]


class Breakage(BaseModel):
    """Breakage flags for a read/write site."""
    model_config = ConfigDict(extra="forbid")

    if_removed: bool = False
    if_renamed: bool = False
    if_type_changed: bool | None = None


class ReadWriteSite(BaseModel):
    """A location where a field is read or written."""
    model_config = ConfigDict(extra="forbid")

    site_id: str
    field_path: str
    location: Location
    enclosing_symbol_id: str
    access_pattern: Literal[
        "attribute", "dict_subscript", "dict_get", "model_field", "serializer"
    ]
    breakage: Breakage = Field(default_factory=Breakage)
    confidence: Literal["high", "medium", "low"]
    evidence_snippet: str | None = None


class Validation(BaseModel):
    """A validation rule applied to a field."""
    model_config = ConfigDict(extra="forbid")

    validation_id: str
    kind: Literal["pydantic_field_constraint", "pydantic_validator", "custom_guard"]
    field_path: str
    location: Location
    enclosing_symbol_id: str
    rule_summary: str
    confidence: Literal["high", "medium", "low"]


class Transform(BaseModel):
    """A data transformation on a field."""
    model_config = ConfigDict(extra="forbid")

    transform_id: str
    kind: Literal["rename", "cast", "defaulting", "normalization"]
    from_field: str | None = None
    to_field: str | None = None
    from_type: str | None = None
    to_type: str | None = None
    location: Location
    enclosing_symbol_id: str
    confidence: Literal["high", "medium", "low"]


class Tool2Diagnostic(BaseModel):
    """Diagnostics for Tool 2."""
    model_config = ConfigDict(extra="forbid")

    severity: Literal["info", "warning", "error"]
    code: Literal[
        "needs_anchor", "entry_point_unresolved",
        "alias_ambiguous", "lineage_truncated"
    ]
    message: str
    location: Location | None = None


class Tool2Stats(BaseModel):
    """Statistics for a Tool 2 run."""
    model_config = ConfigDict(extra="forbid")

    files_scanned: int
    sites_emitted: int
    truncated: bool


class Tool2Result(BaseModel):
    """Complete result payload for Tool 2."""
    model_config = ConfigDict(extra="forbid")

    changed_field: str
    entry_points_resolved: list[EntryPointResolved] = []
    read_sites: list[ReadWriteSite] = []
    write_sites: list[ReadWriteSite] = []
    validations: list[Validation] = []
    transforms: list[Transform] = []
    diagnostics: list[Tool2Diagnostic] = []
    stats: Tool2Stats
