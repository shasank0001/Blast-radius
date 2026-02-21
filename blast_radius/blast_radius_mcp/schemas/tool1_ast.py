"""Tool 1 — AST Structural Engine schema models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import Range


# ── Request ──────────────────────────────────────────────────────────

class Tool1Options(BaseModel):
    """Options for the AST structural engine."""
    model_config = ConfigDict(extra="forbid")

    include_references: bool = True
    include_import_edges: bool = True
    include_call_edges: bool = True
    include_inheritance_edges: bool = True
    max_snippet_chars: int = 240
    resolve_imports: bool = True
    resolve_calls: bool = True
    python_version: str = "3.11"
    parse_mode: Literal["python_ast", "tree_sitter"] = "python_ast"


class Tool1Request(BaseModel):
    """Tool 1 request inputs."""
    model_config = ConfigDict(extra="forbid")

    target_files: list[str]
    options: Tool1Options = Field(default_factory=Tool1Options)


# ── Response components ──────────────────────────────────────────────

class NodeAttributes(BaseModel):
    """Boolean attributes for an AST node."""
    model_config = ConfigDict(extra="forbid")

    is_async: bool = False
    is_generator: bool = False
    is_property: bool = False


class ASTNode(BaseModel):
    """A symbol node extracted from the AST."""
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["module", "class", "function", "method"]
    name: str
    qualified_name: str
    file: str
    range: Range
    signature: str | None = None
    decorators: list[str] = []
    bases: list[str] = []
    docstring: str | None = None
    exports: list[str] = []
    attributes: NodeAttributes = Field(default_factory=NodeAttributes)


class TargetRef(BaseModel):
    """Structured reference to an edge target."""
    model_config = ConfigDict(extra="forbid")

    kind: Literal["symbol", "module", "unresolved"]
    qualified_name: str = ""
    file: str = ""
    symbol_id: str = ""


class ImportMetadata(BaseModel):
    """Metadata for import edges."""
    model_config = ConfigDict(extra="forbid")

    module: str
    name: str = ""
    alias: str = ""
    level: int = 0


class CallMetadata(BaseModel):
    """Metadata for call edges."""
    model_config = ConfigDict(extra="forbid")

    callee_text: str
    arg_count: int = 0


class InheritanceMetadata(BaseModel):
    """Metadata for inheritance edges."""
    model_config = ConfigDict(extra="forbid")

    base_text: str


class ReferenceMetadata(BaseModel):
    """Metadata for reference edges."""
    model_config = ConfigDict(extra="forbid")

    name: str
    context: Literal["load", "store", "del"]


class EdgeResolution(BaseModel):
    """How an edge target was resolved."""
    model_config = ConfigDict(extra="forbid")

    status: Literal["resolved", "unresolved", "ambiguous"]
    strategy: Literal[
        "local_scope", "import_table", "attribute_chain",
        "class_method", "builtin", "unknown"
    ] = "unknown"
    candidates: list[TargetRef] = []


class EdgeMetadata(BaseModel):
    """Typed metadata buckets for edges (non-applicable set to None)."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    import_: ImportMetadata | None = Field(default=None, alias="import")
    call: CallMetadata | None = None
    inheritance: InheritanceMetadata | None = None
    reference: ReferenceMetadata | None = None


class ASTEdge(BaseModel):
    """A relationship edge between AST nodes."""
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["imports", "calls", "inherits", "references"]
    source: str
    target: str = ""
    target_ref: TargetRef
    range: Range
    confidence: float = Field(ge=0.0, le=1.0)
    resolution: EdgeResolution
    snippet: str | None = None
    metadata: EdgeMetadata


class FileInfo(BaseModel):
    """Information about a parsed file."""
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    size_bytes: int
    parse_status: Literal["ok", "error"]
    syntax_error: str | None = None


class Diagnostic(BaseModel):
    """A diagnostic message from parsing."""
    model_config = ConfigDict(extra="forbid")

    file: str
    severity: Literal["info", "warning", "error"]
    message: str
    range: Range


class CacheStats(BaseModel):
    """Cache hit/miss statistics."""
    model_config = ConfigDict(extra="forbid")

    hits: int = 0
    misses: int = 0


class Tool1Stats(BaseModel):
    """Statistics for a Tool 1 run."""
    model_config = ConfigDict(extra="forbid")

    target_files: int
    parsed_ok: int
    parsed_error: int
    nodes: int
    edges: int
    duration_ms: int
    cache: CacheStats = Field(default_factory=CacheStats)


class Tool1Result(BaseModel):
    """Complete result payload for Tool 1."""
    model_config = ConfigDict(extra="forbid")

    language: str = "python"
    repo_root: str
    files: list[FileInfo] = []
    nodes: list[ASTNode] = []
    edges: list[ASTEdge] = []
    diagnostics: list[Diagnostic] = []
    stats: Tool1Stats
