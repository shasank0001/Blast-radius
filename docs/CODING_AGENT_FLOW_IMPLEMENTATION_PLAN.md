# Coding Agent Flow — Detailed Implementation Plan (v1)

> **Purpose**: Step-by-step, phase-by-phase implementation guide for a coding agent to build the Blast Radius MCP system from scratch. Every milestone is broken into ordered phases with exact file targets, acceptance criteria, and dependencies.
>
> **Derived from**: [PRD.md](PRD.md), [MAIN_MCP_DETAILED_PLAN.md](MAIN_MCP_DETAILED_PLAN.md), [MCP_SERVER_ARCHITECTURE.md](MCP_SERVER_ARCHITECTURE.md), [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), [ALIGNMENT_CROSSCHECK_REPORT.md](ALIGNMENT_CROSSCHECK_REPORT.md), Tool 1–5 Detailed Plans & Schemas, [REPORT_TEMPLATE.md](REPORT_TEMPLATE.md), [Blast Radius Challenge.md](Blast%20Radius%20Challenge.md).

---

## Locked Decisions (do not revisit)

1. Language scope: **Python-only** repositories.
2. `schema_version = "v1"` everywhere.
3. Deterministic hash-based `run_id` and `query_id`.
4. Tool 3 default: OpenAI + Pinecone primary, BM25 fallback.
5. Tool 2 canonical API: `field_path + entry_points[]`.
6. Minimal orchestrator merge/prune pipeline is **mandatory** in v1.
7. Evidence-first: no impact claims without tool-backed evidence.
8. Semantic-only results are "unknown risk zones" unless corroborated by Tool 1 or Tool 2.

---

## Build Order (8 Milestones)

| # | Milestone | Depends on |
|---|---|---|
| M1 | Project skeleton + MCP server boot + schemas + validation | — |
| M2 | SQLite cache + repo fingerprinting + deterministic IDs | M1 |
| M3 | Tool 1 — AST Structural Engine | M1, M2 |
| M4 | Orchestrator — merge/prune + report render | M1, M2, M3 |
| M5 | Tool 2 — Data Lineage Engine | M1, M2, M3 |
| M6 | Tool 5 — Test Impact Analyzer | M1, M2, M3 |
| M7 | Tool 4 — Temporal Coupling + Tool 3 — Semantic Neighbors | M1, M2 |
| M8 | End-to-end integration, demo hardening, polish | M1–M7 |

---

## Milestone 1 — Project Skeleton + MCP Server Boot + Schemas + Validation

**Goal**: Bootable MCP server process that registers 5 stub tools, validates envelopes via Pydantic v2, and exports JSON schemas.

### Phase 1.1 — Project Structure & Dependencies

**Files to create:**

```
blast_radius/
  README.md
  pyproject.toml
  blast_radius_mcp/
    __init__.py
    server.py
    settings.py
    logging_config.py
    ids.py
    schemas/
      __init__.py
      common.py
      tool1_ast.py
      tool2_lineage.py
      tool3_semantic.py
      tool4_coupling.py
      tool5_tests.py
    validation/
      __init__.py
      validate.py
    cache/
      __init__.py
      sqlite.py
      keys.py
    repo/
      __init__.py
      fingerprint.py
      io.py
    tools/
      __init__.py
      tool1_ast_engine.py
      tool2_data_lineage.py
      tool3_semantic_neighbors.py
      tool4_temporal_coupling.py
      tool5_test_impact.py
    indices/
      __init__.py
      semantic_index.py
  orchestrator/
    __init__.py
    normalize.py
    diff_parser.py
    merge_evidence.py
    report_render.py
  scripts/
    run_mcp_server.py
  tests/
    __init__.py
    conftest.py
    fixtures/
```

**Steps:**

1. Create `pyproject.toml` with:
   - Python `>=3.11`
   - Dependencies: `mcp`, `pydantic>=2.0`, `xxhash`, `tree-sitter`, `tree-sitter-python` (or `tree_sitter_languages`), `rank-bm25`, `openai`, `pinecone-client`
   - Dev dependencies: `pytest`, `pytest-asyncio`
   - Package name: `blast-radius-mcp`
   - Entry point script: `blast-radius-mcp = blast_radius_mcp.server:main`
2. Create all `__init__.py` files (empty or with `__version__`).
3. Create `blast_radius_mcp/settings.py`:
   - Use `pydantic_settings.BaseSettings` or plain env var reads.
   - Define: `REPO_ROOT`, `CACHE_DB_PATH` (default `~/.blast_radius/cache.db`), `SCHEMA_VERSION = "v1"`, `LOG_LEVEL`, `OPENAI_API_KEY`, `PINECONE_API_KEY`, `PINECONE_INDEX`, `PINECONE_HOST`, `OPENAI_EMBEDDING_MODEL` (default `text-embedding-3-small`).
4. Create `blast_radius_mcp/logging_config.py`:
   - Structured JSON logging with fields: `run_id`, `query_id`, `tool_name`, `cached`, `timing_ms`.
   - Use stdlib `logging` with a JSON formatter.

**Acceptance:**
- `pip install -e .` succeeds.
- All directories and `__init__.py` files exist.
- `settings.py` loads defaults without crashing.

---

### Phase 1.2 — Pydantic Schemas (Common + All 5 Tools)

**File: `blast_radius_mcp/schemas/common.py`**

Define shared types (all with `model_config = ConfigDict(extra="forbid")`):

```python
class Position(BaseModel):
    line: int          # 1-based
    col: int           # 0-based
    offset: int = -1   # 0-based byte offset, -1 if unavailable

class Range(BaseModel):
    start: Position
    end: Position

class Location(BaseModel):
    file: str
    range: Range

class RepoFingerprint(BaseModel):
    git_head: str | None
    dirty: bool
    fingerprint_hash: str

class ToolRequestEnvelope(BaseModel):
    schema_version: str = "v1"
    repo_root: str
    inputs: dict        # tool-specific, validated per-tool
    anchors: list[str] = []
    diff: str = ""
    options: dict = {}

class StructuredError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    location: Location | None = None

class ToolResponseEnvelope(BaseModel):
    schema_version: str = "v1"
    tool_name: str
    run_id: str
    query_id: str
    repo_fingerprint: RepoFingerprint
    cached: bool
    timing_ms: int
    result: dict        # tool-specific
    errors: list[StructuredError] = []
```

**File: `blast_radius_mcp/schemas/tool1_ast.py`**

Implement full Pydantic models matching `TOOL1_SCHEMA.md`:
- `Tool1Request` (with `target_files`, `options`)
- `Tool1Options` (all option fields with defaults)
- `NodeAttributes`, `ASTNode`, `TargetRef`, `EdgeResolution`, `ImportMetadata`, `CallMetadata`, `InheritanceMetadata`, `ReferenceMetadata`, `EdgeMetadata`, `ASTEdge`
- `FileInfo`, `Diagnostic`, `CacheStats`, `Tool1Stats`
- `Tool1Result` (containing `files`, `nodes`, `edges`, `diagnostics`, `stats`)

**File: `blast_radius_mcp/schemas/tool2_lineage.py`**

Implement models matching `TOOL2_SCHEMA.md`:
- `Tool2Request`, `Tool2Options`
- `EntryPointResolved`, `ReadWriteSite`, `Validation`, `Transform`, `Tool2Diagnostic`, `Tool2Stats`
- `Tool2Result`

**File: `blast_radius_mcp/schemas/tool3_semantic.py`**

Implement models matching `TOOL3_SCHEMA.md`:
- `Tool3Request`, `Scope`, `Tool3Options`
- `Neighbor`, `IndexStats`, `Tool3Diagnostic`
- `Tool3Result`

**File: `blast_radius_mcp/schemas/tool4_coupling.py`**

Implement models matching `TOOL4_SCHEMA.md`:
- `Tool4Request`, `Tool4Options`
- `CouplingTarget`, `ExampleCommit`, `Coupling`, `HistoryStats`, `Tool4Diagnostic`
- `Tool4Result`

**File: `blast_radius_mcp/schemas/tool5_tests.py`**

Implement models matching `TOOL5_SCHEMA.md`:
- `Tool5Request`, `ImpactedNode`, `Tool5Options`
- `TestReason`, `TestItem`, `UnmatchedImpact`, `SelectionStats`, `Tool5Diagnostic`
- `Tool5Result`

**Acceptance:**
- All schema models can be instantiated with valid data.
- `model_json_schema()` exports valid JSON Schema for each tool.
- Unknown fields are rejected (`extra="forbid"`).
- All enums constrain to documented values.

---

### Phase 1.3 — Validation Layer

**File: `blast_radius_mcp/validation/validate.py`**

```python
def validate_request(envelope: dict, tool_name: str) -> ToolRequestEnvelope:
    """Parse + validate incoming request. Raises ValidationError on bad input."""

def validate_tool_inputs(inputs: dict, tool_name: str) -> BaseModel:
    """Route to the correct Tool*Request model and validate."""

def validate_response(result: dict, tool_name: str) -> ToolResponseEnvelope:
    """Validate outgoing response shape (used in tests and debug mode)."""
```

- Dispatch to the correct schema by `tool_name`.
- Return typed Pydantic model instances.
- On failure, produce a `StructuredError` with `code="validation_error"`.

**Acceptance:**
- Invalid requests raise `ValidationError` with clear messages.
- Valid requests return typed model instances.

---

### Phase 1.4 — MCP Server Boot with 5 Stub Tools

**File: `blast_radius_mcp/server.py`**

Steps:
1. Import `FastMCP` from `mcp.server.fastmcp`.
2. Create `mcp = FastMCP("blast-radius")`.
3. Register 5 tools as async functions with proper names:
   - `get_ast_dependencies`
   - `trace_data_shape`
   - `find_semantic_neighbors`
   - `get_historical_coupling`
   - `get_covering_tests`
4. Each stub tool should:
   - Accept the request envelope as a JSON string or dict argument.
   - Validate the input via `validate_request()`.
   - Return a minimal valid `ToolResponseEnvelope` with empty `result` and `timing_ms=0`.
5. Add a `main()` function that calls `mcp.run()`.

**File: `scripts/run_mcp_server.py`**

Convenience script:
```python
from blast_radius_mcp.server import main
if __name__ == "__main__":
    main()
```

**Acceptance:**
- Server starts without errors.
- All 5 tools are listed via MCP tool discovery.
- Calling any tool with a valid envelope returns a valid response envelope (empty result).
- Calling any tool with an invalid envelope returns a structured error.

---

### Phase 1.5 — Golden Fixture Tests

**File: `tests/test_schemas.py`**

- For each of the 5 tools, create at least one golden JSON fixture (`tests/fixtures/tool{N}_request.json`, `tests/fixtures/tool{N}_response.json`).
- Test that the fixture parses into the correct Pydantic model without error.
- Test that re-serializing produces identical JSON (round-trip).
- Test that an invalid fixture (extra field, wrong type) is rejected.

**Acceptance:**
- `pytest tests/test_schemas.py` passes.
- At least 5 golden fixtures exist (one per tool).

---

## Milestone 2 — SQLite Cache + Repo Fingerprinting + Deterministic IDs

**Goal**: Working cache layer, repo fingerprinting, and deterministic `run_id`/`query_id` generation.

### Phase 2.1 — Deterministic ID Generation

**File: `blast_radius_mcp/ids.py`**

```python
import hashlib, json

def canonical_json(obj: dict) -> str:
    """Sort keys, no whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def compute_run_id(schema_version: str, intent_norm: str, anchors_norm: list[str], diff_hash: str, repo_fingerprint_hash: str) -> str:
    """run_id = sha256("run" + schema_version + intent_norm + json(sorted(anchors)) + diff_hash + repo_fp_hash)"""

def compute_query_id(tool_name: str, canonical_request: str, repo_fingerprint_hash: str) -> str:
    """query_id = sha256("query" + tool_name + canonical_request + repo_fp_hash)"""

def compute_cache_key(tool_name: str, schema_version: str, canonical_request: str, repo_fingerprint_hash: str, tool_impl_version: str) -> str:
    """cache_key = sha256(tool_name + schema_version + canonical_request + repo_fp_hash + tool_impl_version)"""

def normalize_intent(intent: str) -> str:
    """Trim whitespace, collapse multiple spaces, lowercase."""

def compute_diff_hash(diff: str) -> str:
    """sha256 of line-ending-normalized diff."""
```

**Canonicalization rules** (from MAIN_MCP_DETAILED_PLAN.md §3):
- UTF-8 only.
- Line endings normalized to `\n`.
- JSON keys sorted for hashing.
- Lists sorted where order is non-semantic.

**Acceptance:**
- Same inputs → identical IDs across runs.
- Different inputs → different IDs.
- Unit tests in `tests/test_ids.py`.

---

### Phase 2.2 — Repo Fingerprinting

**File: `blast_radius_mcp/repo/fingerprint.py`**

```python
def compute_repo_fingerprint(repo_root: str) -> RepoFingerprint:
    """
    1. Detect .git and read HEAD commit hash.
    2. Check dirty flag via `git status --porcelain`.
    3. Hash all *.py files (sorted repo-relative paths, sha256 of each content, then sha256 of combined).
    4. Return RepoFingerprint(git_head, dirty, fingerprint_hash).
    """
```

**File: `blast_radius_mcp/repo/io.py`**

```python
def safe_read_file(repo_root: str, rel_path: str) -> bytes:
    """Read file ensuring path stays inside repo_root (no path traversal)."""

def glob_python_files(repo_root: str) -> list[str]:
    """Return sorted list of repo-relative *.py file paths."""

def compute_file_hash(content: bytes) -> str:
    """sha256 hex digest."""
```

**Security**: Normalize and sandbox paths under `repo_root`. Reject any path with `..` that escapes.

**Acceptance:**
- Fingerprint is deterministic for the same repo state.
- Changing any `.py` file changes the fingerprint hash.
- Works without `.git` (returns `git_head=None`, `dirty=True`).
- Unit tests in `tests/test_fingerprint.py`.

---

### Phase 2.3 — SQLite Cache Layer

**File: `blast_radius_mcp/cache/sqlite.py`**

Schema (3 tables):

```sql
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    repo_root TEXT NOT NULL,
    repo_fingerprint TEXT NOT NULL,  -- JSON
    intent TEXT NOT NULL,
    anchors TEXT NOT NULL,            -- JSON
    diff_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_results (
    cache_key TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    query_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    repo_fingerprint_hash TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    timing_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    repo_fingerprint_hash TEXT NOT NULL,
    path_or_blob TEXT
);
```

Implement:

```python
class CacheDB:
    def __init__(self, db_path: str): ...
    def _init_db(self): ...           # CREATE tables, set WAL + synchronous=NORMAL
    def get_cached_result(self, cache_key: str) -> dict | None: ...
    def store_result(self, cache_key: str, tool_name: str, query_id: str, run_id: str, repo_fp_hash: str, request_json: str, response_json: str, timing_ms: int): ...
    def store_run(self, run_id: str, repo_root: str, repo_fp: dict, intent: str, anchors: list, diff_hash: str): ...
    def cleanup(self, max_age_days: int = 30, max_size_mb: int = 500): ...
```

**File: `blast_radius_mcp/cache/keys.py`**

```python
def build_cache_key(tool_name: str, schema_version: str, request: dict, repo_fingerprint_hash: str, tool_impl_version: str) -> str:
    """Wraps ids.compute_cache_key with canonical_json."""
```

**Acceptance:**
- Cache miss returns `None`.
- Cache hit returns stored response JSON.
- Same request + same repo → cache hit.
- Different repo fingerprint → cache miss.
- WAL and synchronous pragmas are set.
- Unit tests in `tests/test_cache.py`.

---

### Phase 2.4 — Wire Cache + IDs into Server Stubs

**Update: `blast_radius_mcp/server.py`**

Each tool handler should now:
1. Compute `repo_fingerprint` via `compute_repo_fingerprint(envelope.repo_root)`.
2. Compute `query_id` via `compute_query_id(...)`.
3. Compute `cache_key` and check cache.
4. If cache hit → return cached response with `cached=True`.
5. If cache miss → execute tool logic, store result, return with `cached=False`.
6. Wrap timing with `time.perf_counter()` for `timing_ms`.

Create a shared `execute_tool()` helper that handles this flow.

**Acceptance:**
- Second call with identical inputs returns `cached=True` and identical result.
- Logs include `run_id`, `query_id`, `cached`, `timing_ms`.

---

## Milestone 3 — Tool 1: AST Structural Engine

**Goal**: Fully functional `get_ast_dependencies` that returns nodes + edges with evidence spans for Python files.

### Phase 3.1 — File Ingestion & Parsing

**File: `blast_radius_mcp/tools/tool1_ast_engine.py`**

Step 1: Implement `load_and_hash_files(repo_root, target_files)`:
- Normalize paths relative to `repo_root`.
- Read file bytes via `safe_read_file()`.
- Compute `sha256` per file.
- Return list of `FileInfo` objects + raw content map.

Step 2: Implement `parse_python_file(source: str, file_path: str, parse_mode: str)`:
- **v1 default**: Use Python's built-in `ast` module (`ast.parse(source, filename=file_path)`).
- On `SyntaxError`: capture error, return partial AST or `None`, emit `Diagnostic`.
- Optional upgrade path: use `tree-sitter-python` for `parse_mode="tree_sitter"`.

**Acceptance:**
- Valid Python files parse without error.
- Syntax-error files produce a `Diagnostic` and partial results.
- File hashes are deterministic.

---

### Phase 3.2 — Symbol Table & Node Emission

Implement `build_symbol_table(tree: ast.AST, file_path: str, qualified_prefix: str)`:

Walk the AST and collect:
- **Module node**: one per file, qualified name from file path.
- **Class nodes**: `ast.ClassDef` → kind=`class`, bases list, decorators.
- **Function nodes**: `ast.FunctionDef` / `ast.AsyncFunctionDef` → kind=`function` (top-level) or `method` (inside class).
- For each: compute stable `id` = `sha256("node" + qualified_name + file + start_line)` truncated to `sym_` prefix + 16 hex chars.
- Extract: `name`, `qualified_name`, `file`, `range` (line/col/offset), `signature` (best-effort from `ast.arguments`), `decorators`, `bases`, `docstring` (from `ast.get_docstring`), `attributes` (is_async, is_generator, is_property).

Implement `emit_nodes(symbol_table) -> list[ASTNode]`:
- Sort by `id` for determinism.

**Acceptance:**
- FastAPI route handlers appear as function/method nodes.
- Class definitions include bases and decorators.
- Node IDs are stable across repeated runs on unchanged files.

---

### Phase 3.3 — Edge Emission (imports, calls, inherits)

Implement `emit_edges(tree, symbol_table, options, file_path)`:

**Import edges** (`type="imports"`):
- Walk `ast.Import` and `ast.ImportFrom`.
- Source = enclosing module node.
- Target = resolved module/symbol if resolvable via file lookup.
- `resolution.status` = `resolved | unresolved`.
- `metadata.import` = `{module, name, alias, level}`.
- Evidence `range` = AST node's line/col.

**Call edges** (`type="calls"`):
- Walk `ast.Call` nodes.
- Source = enclosing function/method node (from symbol table scope).
- Target = resolve callee `ast.Name.id` or `ast.Attribute.attr` against import alias map and symbol table.
- `metadata.call` = `{callee_text, arg_count}`.
- Resolution: `resolved` if callee maps to a known symbol; `unresolved` otherwise.
- Confidence: 0.9 for direct name match, 0.6 for attribute chain, 0.3 for unresolved.

**Inheritance edges** (`type="inherits"`):
- From `ast.ClassDef.bases`.
- Source = class node.
- Target = resolve base class name.
- `metadata.inheritance` = `{base_text}`.

**Reference edges** (`type="references"`, only if `include_references=True`):
- Walk `ast.Name` and `ast.Attribute` for reads/writes.
- Sub-kind via `context`: `load`, `store`, `del`.
- Lower priority, skip in MVP if time-constrained.

Edge ID: `sha256("edge" + source_id + type + target_ref + start_line + start_col)` → `edge_` prefix + 16 hex chars.

**Resolution policy** (precision > recall):
- Only create concrete cross-file targets when uniquely resolved via import table.
- Otherwise emit `resolution=ambiguous` or `unresolved` + low confidence.
- Optional `target_candidates` for ambiguous.

**Acceptance:**
- Import edges link modules correctly.
- Call edges for `Name()` calls are emitted with evidence spans.
- Inheritance edges from `ClassDef.bases` are present.
- Unresolved targets are explicit (not silently dropped).

---

### Phase 3.4 — Cross-file Resolution & Symbol Index

Implement `build_cross_file_index(repo_root, target_files)`:
- Parse all target files.
- Build a mapping: `qualified_name → (file, node_id, kind)`.
- Build import alias map per file: `alias → qualified_name`.
- Use this index to resolve cross-file edges.

Implement `resolve_targets(edges, symbol_index)`:
- For each unresolved edge, attempt resolution against the global index.
- Update `resolution.status` and `target` / `target_ref` fields.

**Acceptance:**
- Cross-file imports resolve to concrete module/symbol nodes.
- Call edges that reference imported symbols resolve correctly.
- Multi-file parsing maintains deterministic results.

---

### Phase 3.5 — Determinism & Sorting

Implement `finalize_and_sort(nodes, edges, diagnostics)`:
- Sort `nodes` by `id`.
- Sort `edges` by `(source, type, target, id)`.
- Sort `diagnostics` by `(file, range.start.line, range.start.col)`.
- Compute `stats`.

**Acceptance:**
- Two identical runs on the same unchanged repo produce byte-identical JSON output.
- `tests/test_tool1_determinism.py` → parse same files twice, assert `result` equality.

---

### Phase 3.6 — Integration with Server + Cache

Wire `tool1_ast_engine.py` into `server.py`:
1. Replace the Tool 1 stub with actual implementation.
2. The handler receives validated `Tool1Request`, calls the engine, wraps in `ToolResponseEnvelope`.
3. Per-file caching: cache parse results by `sha256(file_hash + parse_mode + tool_impl_version)`.
4. Full query caching via the SQLite layer.

Define `TOOL1_IMPL_VERSION = "1.0.0"` in the tool module.

**Acceptance:**
- Calling `get_ast_dependencies` via MCP returns a fully populated, schema-valid response.
- Second call on same files returns `cached=True`.
- On a small FastAPI repo:
  - All route handlers appear as function nodes.
  - Import edges to router/app modules present.
  - Call edges for obvious `Name()` calls present.

---

## Milestone 4 — Orchestrator: Merge/Prune + Report Render

**Goal**: Deterministic pipeline that normalizes inputs, calls tools, merges evidence, prunes, and renders Markdown report.

### Phase 4.1 — ChangeSpec Normalization

**File: `orchestrator/normalize.py`**

```python
class ChangeSpec(BaseModel):
    change_class: Literal["api_change", "behavior_change", "structural_change"]
    entity_kind: Literal["field", "function", "validator", "schema", "route", "module"]
    entity_id: str           # e.g., "POST /orders", "OrderRequest.user_id"
    operation: Literal["add", "remove", "rename", "type_change", "relax", "tighten", "refactor"]
    field_path: str | None   # e.g., "request.user_id"
    from_type: str | None
    to_type: str | None
    notes: str = ""

def normalize_intent(intent: str, anchors: list[str], diff: str) -> ChangeSpec:
    """
    Parse NL intent into ChangeSpec.
    Uses heuristic keyword extraction:
    - "remove" / "delete" → operation=remove
    - "rename" → operation=rename
    - "type" / "change type" → operation=type_change
    - "field" / "payload" / "request" / "response" → entity_kind=field, change_class=api_change
    - "refactor" / "signature" → change_class=structural_change
    - "validation" / "validator" → entity_kind=validator, change_class=behavior_change
    If ambiguous, default to structural_change with notes.
    Extract entity_id and field_path from anchors when available.
    """
```

**Acceptance:**
- UC1 "Remove user_id from POST /orders" → `ChangeSpec(change_class=api_change, entity_kind=field, operation=remove, field_path=request.user_id, entity_id=POST /orders)`.
- UC4 "Change signature of parse_user_id" → `ChangeSpec(change_class=structural_change, entity_kind=function, operation=refactor, entity_id=parse_user_id)`.

---

### Phase 4.2 — Diff Parser

**File: `orchestrator/diff_parser.py`**

```python
class DiffResult(BaseModel):
    changed_files: list[str]          # repo-relative paths
    added_lines: dict[str, list[int]] # file → line numbers
    removed_lines: dict[str, list[int]]
    key_identifiers: list[str]        # extracted symbol/field names from diff

def parse_unified_diff(diff: str) -> DiffResult:
    """
    Parse git-style unified diff.
    1. Extract file paths from --- / +++ headers.
    2. Extract line ranges from @@ hunks.
    3. Classify added/removed lines.
    4. Extract potential identifiers: function names, field names, class names from changed lines.
    """
```

**Acceptance:**
- Parses standard git unified diff format.
- Extracts correct file paths (strips `a/`, `b/` prefixes).
- Returns changed line numbers.
- Extracts key identifiers from added/removed lines.

---

### Phase 4.3 — Tool Call Planner

**File: `orchestrator/normalize.py` (extend)**

```python
def build_tool_plan(change_spec: ChangeSpec, diff_result: DiffResult | None, anchors: list[str], repo_root: str) -> list[dict]:
    """
    Decide which tools to call and with what inputs.
    
    Rules (from MCP_SERVER_ARCHITECTURE §8.2):
    - Tool 1: ALWAYS. target_files = diff.changed_files + small neighborhood.
    - Tool 2: IF change_spec.change_class == api_change AND entry_points exist.
    - Tool 4: IF .git directory exists.
    - Tool 5: IF tests directory/files exist.
    - Tool 3: ALWAYS (cheap), or only when confidence is medium/low.
    
    Returns ordered list of {tool_name, inputs, priority}.
    """
```

**Acceptance:**
- API change with anchors → plans Tool 1, 2, 3, 4, 5.
- Structural change without anchors → plans Tool 1, 3, 4, 5 (no Tool 2).
- No `.git` → skips Tool 4.
- No tests → skips Tool 5.

---

### Phase 4.4 — Evidence Merge & Pruning

**File: `orchestrator/merge_evidence.py`**

```python
class ImpactCandidate(BaseModel):
    file: str
    symbol: str | None
    kind: str | None
    impact_risk: Literal["breaking", "behavior_change", "unknown"]
    impact_surface: Literal["api", "business_logic", "data_handling", "contract_compatibility", "tests", "docs", "unknown"]
    reason: str
    evidence: list[dict]      # list of {tool, query_id, detail}
    confidence: Literal["high", "medium", "low"]
    suggested_action: str
    corroborated: bool        # True if backed by Tool 1 or Tool 2

def merge_evidence(
    tool1_result: dict | None,
    tool2_result: dict | None,
    tool3_result: dict | None,
    tool4_result: dict | None,
    tool5_result: dict | None,
    change_spec: ChangeSpec
) -> list[ImpactCandidate]:
    """
    1. Build candidate set from Tool 1 edges (direct structural impacts).
    2. Enrich with Tool 2 read-sites (data-shape impacts, breakage flags).
    3. Add Tool 4 coupled files as review suggestions.
    4. Add Tool 3 neighbors as "unknown risk zones" (uncorroborated=True).
    5. Map Tool 5 tests to impacted candidates.
    """

def prune_candidates(
    candidates: list[ImpactCandidate],
    change_spec: ChangeSpec
) -> list[ImpactCandidate]:
    """
    Pruning rules (from MAIN_MCP_DETAILED_PLAN §7):
    1. Drop low-confidence structural edges unless they match the changed field/path.
    2. Never promote semantic-only neighbors to "impacted" without Tool 1/2 corroboration.
    3. For API changes, remove items not touching the changed field_path.
    4. Cap per-section counts.
    5. Low-confidence unresolved links require corroboration.
    """

def assign_risk_surface(
    candidate: ImpactCandidate,
    change_spec: ChangeSpec
) -> ImpactCandidate:
    """
    Assign impact_risk and impact_surface based on evidence types:
    - Tool 2 breakage=True → breaking
    - Tool 1 call edge only → behavior_change
    - Tool 3 only → unknown
    - Read site → api surface
    - Call edge → business_logic
    """
```

**Acceptance:**
- Tool 1 edges → `corroborated=True`, direct impacts.
- Tool 3-only items → `corroborated=False`, stay in "unknown risk zones".
- API change pruning removes irrelevant structural edges.
- All candidates have `impact_risk`, `impact_surface`, `confidence`, `reason`.

---

### Phase 4.5 — Report Renderer

**File: `orchestrator/report_render.py`**

```python
def render_report(
    intent: str,
    anchors: list[str],
    change_spec: ChangeSpec,
    impacts: list[ImpactCandidate],
    tool_results: dict[str, dict],   # tool_name → result dict
    query_ids: dict[str, str],       # tool_name → query_id
    assumptions: list[str],
    limitations: list[str]
) -> str:
    """
    Render Markdown report following REPORT_TEMPLATE.md structure:
    
    Sections:
    1. Executive summary (intent, anchors, top 3 risks, overall confidence)
    2. Direct structural impacts (AST) — table format
    3. Data-shape impacts (payload lineage) — read sites, transforms
    4. Unknown risk zones (semantic neighbors)
    5. Implicit dependencies (temporal coupling)
    6. Tests to run (impact prover) — ranked list
    7. Recommended engineer actions
    8. Evidence appendix (query_ids)
    9. Assumptions & limitations
    """
```

Template filling rules:
- Executive summary: derive `overall_confidence` from the distribution of high/medium/low across all candidates.
- Direct impacts table: filter `corroborated=True` candidates, format as Markdown table with all 7 columns from template.
- Data-shape section: only present when Tool 2 ran and has results.
- Unknown risk zones: filter `corroborated=False` candidates (Tool 3 sourced).
- Temporal coupling: list Tool 4 coupled files with weights.
- Tests: list Tool 5 ranked tests with reasons.
- Evidence appendix: list all `query_id`s.
- Assumptions: include NL-only mode caveats, missing anchor warnings, etc.

**Acceptance:**
- Output is valid Markdown.
- Every impact has: impact risk, impact surface, location, reason, evidence, confidence, suggested action.
- Template structure matches `REPORT_TEMPLATE.md`.
- Empty tool results produce graceful "No data available" sections (not crashes).

---

### Phase 4.6 — Orchestrator Main Pipeline

**File: `orchestrator/__init__.py`** or a new `orchestrator/pipeline.py`

```python
async def run_blast_radius(
    intent: str,
    repo_root: str,
    anchors: list[str] = [],
    diff: str = "",
    run_id: str | None = None
) -> str:
    """
    End-to-end orchestrator flow:
    1. Normalize intent → ChangeSpec.
    2. Parse diff → DiffResult (if provided).
    3. Compute repo fingerprint.
    4. Compute run_id (if not provided).
    5. Build tool call plan.
    6. Execute tools (parallel where possible).
    7. Merge evidence.
    8. Prune candidates.
    9. Render Markdown report.
    10. Return report string.
    """
```

**Acceptance:**
- Given intent + diff + anchors → produces complete Markdown report.
- Given intent-only → produces report with wider "unknown risk zone" and lower confidence.
- All tool calls use deterministic IDs.
- Report includes evidence appendix with query_ids.

---

## Milestone 5 — Tool 2: Data Lineage Engine

**Goal**: High-precision field/path tracing for API payload changes.

### Phase 5.1 — Route Index (FastAPI/Starlette)

**File: `blast_radius_mcp/tools/tool2_data_lineage.py`**

Implement `build_route_index(repo_root, target_files)`:
1. Parse each Python file with `ast`.
2. Find decorators matching FastAPI patterns:
   - `@app.get("/path")`, `@app.post("/path")`, `@router.get(...)`, etc.
   - `app.add_api_route("/path", handler)`.
3. Extract: HTTP method, path, handler function name, handler location.
4. Map `route:METHOD /path` → handler function `(file, symbol, node_id)`.

**Acceptance:**
- Detects `@app.post("/orders")` → maps to handler function.
- Handles `APIRouter` prefix composition (best-effort).
- Returns `entry_point_unresolved` diagnostic for unmatched anchors.

---

### Phase 5.2 — Pydantic Model Index

Implement `build_model_index(repo_root, target_files)`:
1. Find all classes inheriting from `BaseModel` (via `ast.ClassDef.bases` inspection).
2. For each model, extract:
   - Field names (from `ast.AnnAssign` in class body).
   - Field aliases (`alias=...` in `Field()` calls).
   - Field defaults and constraints.
   - Validators: `@validator("field")`, `@field_validator("field")`, `@model_validator`.
3. Build mapping: `ModelName.field → (file, line, type, aliases, validators)`.

**Acceptance:**
- Detects Pydantic `BaseModel` subclasses.
- Extracts field names and aliases.
- Finds `@field_validator` / `@validator` decorators.

---

### Phase 5.3 — Field Read/Write Site Detection

Implement `trace_field(field_path, handler_file, handler_symbol, model_index, call_graph, options)`:

Intra-procedural scan:
1. Parse handler function body.
2. Find all `ast.Attribute` nodes where `attr == field_name`:
   - `obj.user_id` → read site (access_pattern=`attribute`).
3. Find all `ast.Subscript` with string literal keys:
   - `payload["user_id"]` → read site (access_pattern=`dict_subscript`).
4. Find all `.get("field")` calls:
   - `payload.get("user_id")` → read site (access_pattern=`dict_get`).
5. Find writes: `obj.user_id = ...`, `payload["user_id"] = ...`.
6. Find transforms: `UUID(obj.user_id)` → cast, `user_id = payload.pop("userId")` → rename.
7. For each site, compute `breakage`:
   - `if_removed=True` for reads without defaults.
   - `if_renamed=True` for literal key accesses.

Inter-procedural expansion (depth-bounded by `max_call_depth`):
1. If handler calls `process(payload)` or `process(obj.user_id)`:
   - Follow Tool 1 call edges into callee.
   - Map argument → parameter.
   - Scan callee body for field access patterns.
2. Cap at `max_call_depth` (default 2).

**Acceptance:**
- Detects `payload.user_id`, `payload["user_id"]`, `payload.get("user_id")`.
- Emits breakage flags.
- Links each site to `enclosing_symbol_id` from Tool 1.
- Evidence snippets included.

---

### Phase 5.4 — Wire into Server + Output Assembly

1. Replace Tool 2 stub in `server.py`.
2. Implement the full `trace_data_shape` handler:
   - Receive `Tool2Request`.
   - Build indexes (cached by repo fingerprint).
   - Resolve entry points.
   - Trace field.
   - Assemble `Tool2Result` with `read_sites`, `write_sites`, `validations`, `transforms`.
3. Sort all sites by `(file, start.line, start.col, site_id)`.

Define `TOOL2_IMPL_VERSION = "1.0.0"`.

**Acceptance:**
- On a FastAPI repo with Pydantic models:
  - Route anchor resolves to handler.
  - Field read sites are detected with correct access patterns.
  - Breakage flags match expected behavior.
- `needs_anchor` diagnostic when no entry point provided.
- Deterministic ordering.

---

## Milestone 6 — Tool 5: Test Impact Analyzer

**Goal**: Ranked minimal test set for impacted nodes.

### Phase 6.1 — Test Discovery

**File: `blast_radius_mcp/tools/tool5_test_impact.py`**

Implement `discover_tests(repo_root)`:
1. Check for `pytest.ini`, `pyproject.toml [tool.pytest]`, `setup.cfg [tool:pytest]` for `testpaths`.
2. Fall back to conventions: `tests/`, `test/`, files matching `test_*.py` or `*_test.py`.
3. Return list of test file paths (repo-relative).

**Acceptance:**
- Finds tests in standard layouts.
- Returns `tests_not_found` diagnostic when no tests are found.

---

### Phase 6.2 — Test Import/Reference Index

Implement `build_test_index(repo_root, test_files)`:
1. Parse each test file with `ast`.
2. Extract imports: `import X`, `from X import Y`.
3. Extract test nodeids: functions starting with `test_`, classes inheriting `TestCase`.
4. Extract lightweight reference signals: string literals (`"user_id"`), `ast.Name` / `ast.Attribute` references.
5. Build mapping: `test_file → {nodeids, imported_modules, imported_symbols, references}`.

Implement `build_module_graph(repo_root)`:
1. For all Python files, extract `import` statements.
2. Build a directed graph: `module → imported_modules` (transitive).
3. Bound transitive depth to `transitive_depth` setting.

**Acceptance:**
- Correctly extracts imports from test files.
- Builds module-level import graph.
- Handles `from . import X` (relative imports).

---

### Phase 6.3 — Scoring & Ranking

Implement `score_tests(impacted_nodes, test_index, module_graph, options)`:

Scoring weights:
- `direct_import` (test imports impacted module): weight = 1.0
- `from_import_symbol` (test imports specific impacted symbol): weight = 1.0
- `transitive_import` (test imports something that imports impacted module, via module_graph): weight = 0.5 / depth
- `symbol_reference` (test references impacted symbol name as `ast.Name`): weight = 0.4
- `field_literal_match` (test contains string literal matching field name): weight = 0.2

For each test, compute `score = sum(matched_weights)`, capped at 1.0.

Deterministic ranking:
1. Sort by `(score desc, file asc, nodeid asc)`.
2. Assign contiguous `rank` from 1.
3. Trim to `max_tests`.
4. Assign `confidence`: score >= 0.7 → `high`, >= 0.4 → `medium`, else `low`.

Track `unmatched_impacts`: impacted nodes with no test references at all.

**Acceptance:**
- Tests importing impacted modules rank highest.
- Ranking is deterministic.
- `unmatched_impacts` lists nodes without test coverage.
- Reasons list includes typed evidence.

---

### Phase 6.4 — Wire into Server

1. Replace Tool 5 stub in `server.py`.
2. Full handler: receive `Tool5Request`, discover tests, build indexes, score, rank, return `Tool5Result`.
3. Cache test index by file hashes. Cache query result by impacted node signature + options + repo fingerprint.

Define `TOOL5_IMPL_VERSION = "1.0.0"`.

**Acceptance:**
- Returns ranked tests for impacted modules/symbols.
- Limits output to `max_tests`.
- Each test has evidence reasons.
- Deterministic order.

---

## Milestone 7 — Tool 4: Temporal Coupling + Tool 3: Semantic Neighbors

### Phase 7.1 — Tool 4: Git History Parsing

**File: `blast_radius_mcp/tools/tool4_temporal_coupling.py`**

Implement `parse_git_log(repo_root, window_commits, exclude_merges, max_commit_size, follow_renames)`:
1. Run `git log --name-status -M --format="%H|%aI|%s" -n {window_commits}` via `subprocess`.
   - Use fixed argument lists (no shell interpolation) for security.
2. Parse output: extract commit sha, date, message, and file status lines (A/M/D/R).
3. Build list of `Commit(sha, date, message, files[])`.
4. Apply filters:
   - Drop merge commits (check for multiple parents via `--no-merges` flag or parent count).
   - Drop commits touching more than `max_commit_size` files.
   - Normalize rename paths (`R100 old.py new.py` → track both).

**Acceptance:**
- Correctly parses git log output.
- Filters large commits and merges.
- Handles rename tracking.

---

### Phase 7.2 — Tool 4: Co-change Scoring

Implement `compute_coupling(target_files, commits, options)`:
1. For each target file, find all commits that include it.
2. For each of those commits, record all other files that appeared.
3. Compute conditional probability: `weight = co_change_count / target_change_count`.
4. Normalize by commit size: weight down files that co-occur only in large commits.
5. Rank by `(weight desc, support desc, coupled_file asc)`.
6. Return top `max_files` coupled files with evidence `example_commits`.

**Acceptance:**
- Returns coupled files with float weights in [0, 1].
- Evidence commits include sha, date, message.
- Deterministic rounding and ordering.

---

### Phase 7.3 — Tool 4: Wire into Server

1. Replace Tool 4 stub.
2. Handle failure: no `.git` → `git_history_unavailable` diagnostic.
3. Handle `low_history_support` when fewer than 10 commits.
4. Cache parsed log snapshot by `(HEAD, options_hash)`.

Define `TOOL4_IMPL_VERSION = "1.0.0"`.

**Acceptance:**
- Returns ranked coupled files for known changed files.
- Graceful degradation without `.git`.

---

### Phase 7.4 — Tool 3: BM25 Fallback (implement first)

**File: `blast_radius_mcp/tools/tool3_semantic_neighbors.py`**
**File: `blast_radius_mcp/indices/semantic_index.py`**

Implement `build_bm25_index(repo_root, scope)`:
1. Glob Python files within `scope.paths` / `scope.globs`.
2. Chunk code at function/method level using `ast`:
   - For each function/method in each file, extract source text + metadata.
   - Chunk ID: `sha256(file_hash + qualified_name + start_line)`.
3. Tokenize chunks (simple word tokenization + lowercasing).
4. Build BM25 index using `rank-bm25` library.
5. Store chunk metadata in local SQLite.

Implement `query_bm25(query_text, index, top_k, min_score)`:
1. Tokenize query.
2. Score all chunks.
3. Filter by `min_score`.
4. Return top_k neighbors with score, file, symbol, span, rationale snippet.
5. Set `uncorroborated=True` on all results.
6. Set `method="bm25"`.

**Acceptance:**
- BM25 search returns semantically relevant chunks.
- Works without any external API keys.
- All results marked `uncorroborated=True`.

---

### Phase 7.5 — Tool 3: OpenAI + Pinecone Primary Path

**File: `blast_radius_mcp/indices/semantic_index.py` (extend)**

Implement `EmbeddingProvider`:
```python
class OpenAIEmbeddingProvider:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small"): ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Implement `VectorStore`:
```python
class PineconeVectorStore:
    def __init__(self, api_key: str, index_name: str, host: str): ...
    async def upsert(self, ids: list[str], vectors: list[list[float]], metadata: list[dict]): ...
    async def query(self, vector: list[float], top_k: int) -> list[dict]: ...
```

Implement primary retrieval:
1. Check `OPENAI_API_KEY` and `PINECONE_API_KEY` availability.
2. If available:
   - Build query embedding from `query_text`.
   - Query Pinecone for `top_k` nearest neighbors.
   - Map results to `Neighbor` objects.
   - Set `method="openai_pinecone"`, `retrieval_mode="embedding_primary"`.
3. If unavailable → automatic fallback to BM25 with `retrieval_mode="bm25_fallback"` and diagnostic `semantic_provider_unavailable`.

Implement index update:
1. On first run or when chunk hashes change:
   - Embed new/changed chunks.
   - Upsert to Pinecone.
2. Track indexed chunk hashes in local SQLite to avoid re-embedding unchanged code.

**Acceptance:**
- With valid API keys: returns embedding-based neighbors.
- Without API keys: gracefully falls back to BM25.
- All results marked `uncorroborated=True`.

---

### Phase 7.6 — Tool 3: Wire into Server

1. Replace Tool 3 stub.
2. Build query text from `inputs.query_text` (intent + diff signals + identifiers).
3. Try embedding retrieval; fallback to BM25.
4. Deduplicate and stable-sort neighbors by `(score desc, file asc, span.start.line asc, span.start.col asc)`.
5. Cache by `(query_text, scope, options, repo_fingerprint)`.

Define `TOOL3_IMPL_VERSION = "1.0.0"`.

**Acceptance:**
- Produces semantically related neighbors with scores.
- Automatic degradation to BM25 without crashing.
- Every item `uncorroborated=True`.
- Deterministic tie-break order.

---

## Milestone 8 — End-to-End Integration, Demo Hardening, Polish

**Goal**: Complete working system with demo scenario, determinism guarantees, and documentation.

### Phase 8.1 — End-to-End Wiring

1. Update `orchestrator/pipeline.py` to call all 5 real tool implementations (not stubs).
2. Ensure parallel tool execution where possible (Tool 1 || Tool 4, then Tool 2 after Tool 1, then Tool 5 after merge, Tool 3 anytime).
3. Wire the `merge_evidence` + `prune_candidates` pipeline.
4. Wire `render_report` with all tool results.

**Create: `scripts/run_blast_radius.py`**

CLI entry point:
```python
"""
Usage:
  python scripts/run_blast_radius.py \
    --repo /path/to/repo \
    --intent "Remove user_id from POST /orders payload" \
    --anchor "route:POST /orders" \
    --diff-file changes.patch \
    --output report.md
"""
```

**Acceptance:**
- Full pipeline runs without errors on a sample FastAPI repo.
- Report markdown is produced with all sections filled.

---

### Phase 8.2 — Demo Scenario: API Field Removal

Create a small demo FastAPI project at `demo_repo/`:

```
demo_repo/
  app/
    __init__.py
    main.py          # FastAPI app with POST /orders endpoint
    models.py         # OrderRequest with user_id field
    services/
      __init__.py
      order_service.py   # reads order.user_id
      notification.py    # reads user_id for notifications
    utils/
      __init__.py
      validators.py      # validates user_id format
  tests/
    __init__.py
    test_orders.py       # tests create_order
    test_services.py     # tests order_service
```

Run the demo:
```bash
python scripts/run_blast_radius.py \
  --repo demo_repo \
  --intent "Remove user_id from the request payload of POST /orders" \
  --anchor "route:POST /orders" \
  --anchor "symbol:app/models.py:OrderRequest"
```

**Expected output**:
- Tool 1: structural graph showing imports from `models.py` to `services/`, calls to `order_service.process_order()`.
- Tool 2: read sites for `user_id` in `order_service.py`, `notification.py`, `validators.py` with breakage flags.
- Tool 3: similar code patterns in `utils/` or other modules.
- Tool 4: historically coupled files.
- Tool 5: `test_orders.py`, `test_services.py` ranked.
- Report: complete Markdown with all sections.

**Acceptance:**
- Report accurately identifies all `user_id` read sites.
- Report includes tests to run.
- Report includes unknown risk zones.
- Every impact has evidence citations.

---

### Phase 8.3 — Determinism Hardening

**File: `tests/test_determinism.py`**

1. Run the full pipeline twice on the same demo repo with identical inputs.
2. Assert `run_id` is identical.
3. Assert all `query_id`s are identical.
4. Assert the final report markdown is byte-identical.
5. Assert no non-deterministic timestamps inside `result` objects.

Additional checks:
- Canonical JSON serialization for hashing (sorted keys, no whitespace).
- Stable sorting of all lists (by file, symbol, line).
- Cache keys include tool implementation version.
- Tools do not import/execute target project code.

**Acceptance:**
- `pytest tests/test_determinism.py` passes.
- Two identical runs produce identical reports.

---

### Phase 8.4 — Error Handling & Graceful Degradation

Ensure robust failure modes across all components:

1. **NL-only mode** (no diff, no anchors):
   - System still produces a report.
   - Wider search scope, lower confidence.
   - More items in "unknown risk zones".
   - Tool 2 skipped (no entry point), emits `needs_anchor` limitation.

2. **Partial tool failures**:
   - If Tool 3 fails (API errors): report renders without semantic neighbors, includes limitation note.
   - If Tool 4 fails (no `.git`): report renders without coupling section, includes limitation note.
   - If Tool 2 fails: report still has structural impacts from Tool 1.

3. **Timeouts and caps**:
   - `max_edges_per_file`, `max_sites`, `max_tests`, `max_files` are respected.
   - Truncation produces a diagnostic, not a crash.

4. **Invalid input**:
   - Invalid `repo_root` → structured error.
   - Empty `target_files` → structured error.
   - Malformed diff → skip diff parsing, log warning, continue.

**Acceptance:**
- Every failure mode produces structured errors or diagnostics.
- Report always renders, even with partial data.
- No unhandled exceptions escape to the user.

---

### Phase 8.5 — Observability & Logging

Update all tool handlers to log:
- `run_id`, `query_id`, `tool_name`
- `cached` (hit/miss)
- `timing_ms`
- `result_counts` (nodes, edges, sites, tests, etc.)
- `error_count`

**Acceptance:**
- Structured log entries emitted for every tool call.
- Logs include enough information to debug any tool failure.

---

### Phase 8.6 — Documentation & README

**File: `blast_radius/README.md`**

Contents:
1. Project overview (what Blast Radius does).
2. Setup instructions (`pip install -e .`, env vars for OpenAI/Pinecone).
3. Quick start with demo command.
4. Architecture diagram (text-based).
5. Tool descriptions (1-sentence each).
6. Sample report output.

**Acceptance:**
- A new developer can run the demo from README instructions alone.

---

## Execution Checklist (Definition of Done)

From `MAIN_MCP_DETAILED_PLAN.md §10`:

- [ ] MCP exposes all 5 tools with stable v1 envelopes.
- [ ] Deterministic rerun on same input + repo state yields stable IDs and ordering.
- [ ] Orchestrator produces report with all required sections and evidence appendix.
- [ ] API field-removal scenario shows concrete Tool 2 read-site breakage + Tool 5 tests.
- [ ] Semantic-only hits remain in unknown risk zone unless corroborated.

From `Blast Radius Challenge.md`:

- [ ] System models the codebase as a graph (modules, classes, functions, APIs, relationships).
- [ ] Accepts change intent and produces structured, explainable blast radius report.
- [ ] Identifies directly impacted and indirectly impacted components.
- [ ] Classifies impacts by category (API, business logic, data handling, contract).
- [ ] Explains **why** each component is impacted with evidence.
- [ ] Report is structured, explainable, and engineer-readable.

From `PRD.md §13` (success metrics):

- [ ] ≥ 70% of listed impacts are relevant (precision proxy).
- [ ] Report generates in < 2 minutes after indexing.
- [ ] Report recommends ≤ 10 tests for typical change.
- [ ] ≥ 90% of impacts have at least 2 evidence types.

---

## Quick Reference: File → Milestone Mapping

| File | Milestone |
|---|---|
| `pyproject.toml` | M1 |
| `blast_radius_mcp/server.py` | M1, M2, M3, M5, M6, M7 |
| `blast_radius_mcp/settings.py` | M1 |
| `blast_radius_mcp/logging_config.py` | M1, M8 |
| `blast_radius_mcp/ids.py` | M2 |
| `blast_radius_mcp/schemas/common.py` | M1 |
| `blast_radius_mcp/schemas/tool1_ast.py` | M1 |
| `blast_radius_mcp/schemas/tool2_lineage.py` | M1 |
| `blast_radius_mcp/schemas/tool3_semantic.py` | M1 |
| `blast_radius_mcp/schemas/tool4_coupling.py` | M1 |
| `blast_radius_mcp/schemas/tool5_tests.py` | M1 |
| `blast_radius_mcp/validation/validate.py` | M1 |
| `blast_radius_mcp/cache/sqlite.py` | M2 |
| `blast_radius_mcp/cache/keys.py` | M2 |
| `blast_radius_mcp/repo/fingerprint.py` | M2 |
| `blast_radius_mcp/repo/io.py` | M2 |
| `blast_radius_mcp/tools/tool1_ast_engine.py` | M3 |
| `blast_radius_mcp/tools/tool2_data_lineage.py` | M5 |
| `blast_radius_mcp/tools/tool3_semantic_neighbors.py` | M7 |
| `blast_radius_mcp/tools/tool4_temporal_coupling.py` | M7 |
| `blast_radius_mcp/tools/tool5_test_impact.py` | M6 |
| `blast_radius_mcp/indices/semantic_index.py` | M7 |
| `orchestrator/normalize.py` | M4 |
| `orchestrator/diff_parser.py` | M4 |
| `orchestrator/merge_evidence.py` | M4 |
| `orchestrator/report_render.py` | M4 |
| `orchestrator/pipeline.py` | M4, M8 |
| `scripts/run_blast_radius.py` | M8 |
| `scripts/run_mcp_server.py` | M1 |
| `demo_repo/` | M8 |
| `tests/` | M1, M2, M3, M8 |
