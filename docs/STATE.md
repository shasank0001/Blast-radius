# Blast Radius MCP — Project State

> **Last Updated**: 2026-02-21  
> **Repository**: https://github.com/shasank0001/Blast-radius.git  
> **Branch**: `main`  
> **Python**: >=3.11 | **Build**: hatchling | **Tests**: 280 passing (0 failures)

---

## Overall Progress

| # | Milestone | Status | Commit |
|---|-----------|--------|--------|
| M1 | Project skeleton + MCP server boot + schemas + validation | ✅ Complete | `1368cc6` |
| M2 | SQLite cache + repo fingerprinting + deterministic IDs | ✅ Complete | `3f4f937` |
| M3 | Tool 1 — AST Structural Engine | ✅ Complete | `3aaf699` |
| M4 | Orchestrator — merge/prune + report render | ✅ Complete | — |
| M5 | Tool 2 — Data Lineage Engine | ✅ Complete | — |
| M6 | Tool 5 — Test Impact Analyzer | ⬜ Not started | — |
| M7 | Tool 4 — Temporal Coupling + Tool 3 — Semantic Neighbors | ⬜ Not started | — |
| M8 | End-to-end integration, demo hardening, polish | ⬜ Not started | — |

---

## Project Structure

```
blast_radius/
├── pyproject.toml                          # Package config, deps, entry point
├── README.md
├── .gitignore
├── blast_radius_mcp/
│   ├── __init__.py
│   ├── server.py                           # FastMCP server with 5 tools + execute_tool() pipeline
│   ├── settings.py                         # Env-var config via pydantic-settings
│   ├── logging_config.py                   # Structured JSON logging
│   ├── ids.py                              # Deterministic ID generation (SHA-256)
│   ├── schemas/
│   │   ├── common.py                       # Shared models: Position, Range, Location, Envelopes
│   │   ├── tool1_ast.py                    # AST engine request/response schemas
│   │   ├── tool2_lineage.py                # Data lineage schemas
│   │   ├── tool3_semantic.py               # Semantic neighbors schemas
│   │   ├── tool4_coupling.py               # Temporal coupling schemas
│   │   └── tool5_tests.py                  # Test impact schemas
│   ├── validation/
│   │   └── validate.py                     # Request/response validation dispatch
│   ├── cache/
│   │   ├── sqlite.py                       # SQLite cache (WAL mode, 3 tables)
│   │   └── keys.py                         # Cache key construction
│   ├── repo/
│   │   ├── io.py                           # Safe file I/O, glob, hash
│   │   └── fingerprint.py                  # Repo fingerprinting (git HEAD, dirty, content hash)
│   ├── tools/
│   │   ├── tool1_ast_engine.py              # ✅ Full AST engine (980 lines)
│   │   ├── tool2_data_lineage.py            # ✅ Full Data Lineage Engine (1,580 lines)
│   │   ├── tool3_semantic_neighbors.py      # ⬜ Stub
│   │   ├── tool4_temporal_coupling.py       # ⬜ Stub
│   │   └── tool5_test_impact.py             # ⬜ Stub
│   └── indices/                            # ⬜ Stub — semantic index pending
│       └── semantic_index.py
├── orchestrator/                           # ✅ Full implementation (2,150 lines)
│   ├── __init__.py                         # ✅ Main pipeline: run_blast_radius() (281 lines)
│   ├── normalize.py                        # ✅ ChangeSpec normalization + tool planner (495 lines)
│   ├── diff_parser.py                      # ✅ Unified diff parser (186 lines)
│   ├── merge_evidence.py                   # ✅ Evidence merge, prune, risk assignment (775 lines)
│   └── report_render.py                    # ✅ Markdown report renderer (413 lines)
├── scripts/
│   └── run_mcp_server.py                   # Convenience entry point
└── tests/
    ├── conftest.py
    ├── test_schemas.py                     # 58 tests — golden fixtures, validation, settings
    ├── test_ids.py                         # 24 tests — deterministic ID generation
    ├── test_fingerprint.py                 # 16 tests — repo I/O and fingerprinting
    ├── test_cache.py                       # 21 tests — SQLite cache + cache keys
    ├── test_tool1_ast.py                   # 65 tests — AST engine unit + integration
    ├── test_tool2.py                       # 94 tests — Data lineage: IDs, routes, models, tracing, integration
    ├── test_server.py                      # 2 tests — execute_tool deterministic run/cache behavior
    └── fixtures/
        ├── tool1_request.json
        ├── tool1_response.json
        ├── tool2_request.json
        ├── tool2_response.json
        ├── tool3_request.json
        ├── tool3_response.json
        ├── tool4_request.json
        ├── tool4_response.json
        ├── tool5_request.json
        └── tool5_response.json
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `mcp[cli]` | FastMCP server framework |
| `pydantic>=2.0` | Schema validation (`ConfigDict(extra="forbid")`) |
| `pydantic-settings>=2.0` | Env-var based settings |
| `xxhash` | Fast hashing (available, not yet used in hot paths) |
| `tree-sitter` + `tree-sitter-python` | AST parsing (optional upgrade path, v1 uses stdlib `ast`) |
| `rank-bm25` | BM25 fallback for semantic search (M7) |
| `openai` | Embedding generation for semantic search (M7) |
| `pinecone-client` | Vector DB for semantic neighbors (M7) |
| `pytest` + `pytest-asyncio` | Testing (dev) |

---

## Key Design Decisions

1. **Python-only** repositories — no multi-language support in v1
2. `schema_version = "v1"` locked everywhere
3. **Deterministic hash-based** `run_id` / `query_id` / `cache_key` (SHA-256)
4. All Pydantic models use `ConfigDict(extra="forbid")` — unknown fields rejected
5. EdgeMetadata uses `import_` field with `alias="import"` + `populate_by_name=True` (Python reserved word)
6. SQLite with **WAL mode** + `synchronous=NORMAL` for cache performance
7. Cache tables: `runs`, `tool_results`, `artifacts` (3-table schema)
8. Safe file I/O — path traversal protection via `safe_read_file()`
9. Repo fingerprinting: git HEAD + dirty flag + SHA-256 of all `.py` file contents
10. Server uses shared `execute_tool()` helper: parse envelope → validate → fingerprint → compute IDs → check cache → execute → store → return

---

## Milestone 1 Summary — Project Skeleton + Schemas + Validation

**Commit**: `1368cc6`  
**Tests**: 55 passing  

### What was built

**Phase 1.1 — Project Structure & Dependencies**
- Created full project skeleton with `pyproject.toml` (hatchling build backend), all directories, and `__init__.py` files
- `settings.py` using `pydantic_settings.BaseSettings` — loads `REPO_ROOT`, `CACHE_DB_PATH` (default `~/.blast_radius/cache.db`), `SCHEMA_VERSION`, `LOG_LEVEL`, `OPENAI_API_KEY`, `PINECONE_API_KEY`, etc.
- `logging_config.py` with `JSONFormatter` emitting structured logs with `run_id`, `query_id`, `tool_name`, `cached`, `timing_ms`
- `ids.py` with `canonical_json()`, `compute_run_id()`, `compute_query_id()`, `compute_cache_key()`, `normalize_intent()`, `compute_diff_hash()` — all SHA-256, deterministic

**Phase 1.2 — Pydantic Schemas (Common + 5 Tools)**
- `schemas/common.py`: `Position`, `Range`, `Location`, `RepoFingerprint`, `StructuredError`, `ToolRequestEnvelope`, `ToolResponseEnvelope`
- `schemas/tool1_ast.py`: 12 models — `Tool1Request`, `Tool1Options`, `ASTNode` (kind: module/class/function/method), `ASTEdge` (type: imports/calls/inherits/references), `EdgeMetadata`, `EdgeResolution`, `TargetRef`, `FileInfo`, `Tool1Result`, `Tool1Stats`, etc.
- `schemas/tool2_lineage.py`: `Tool2Request` (field_path + entry_points min_length=1), `ReadWriteSite`, `Breakage`, `EntryPointResolved`, `Validation`, `Transform`, `Tool2Result`
- `schemas/tool3_semantic.py`: `Tool3Request` (query_text min_length=3), `Scope`, `Neighbor` (uncorroborated=True), `Span`, `IndexStats`, `Tool3Result`
- `schemas/tool4_coupling.py`: `Tool4Request` (file_paths min_length=1), `Coupling`, `CouplingTarget`, `ExampleCommit`, `HistoryStats`, `Tool4Result`
- `schemas/tool5_tests.py`: `Tool5Request` (impacted_nodes min_length=1), `ImpactedNode`, `TestItem`, `TestReason`, `UnmatchedImpact`, `SelectionStats`, `Tool5Result`

**Phase 1.3 — Validation Layer**
- `validation/validate.py` with `validate_request()`, `validate_tool_inputs()`, `validate_response()`, `make_validation_error_response()`
- Routes to correct schema model via `_TOOL_REQUEST_MODELS` dict mapping tool names to Pydantic models
- Invalid inputs produce `StructuredError` with `code="validation_error"`

**Phase 1.4 — MCP Server Boot**
- `server.py` using `FastMCP("blast-radius")` with 5 registered tools: `get_ast_dependencies`, `trace_data_shape`, `find_semantic_neighbors`, `get_historical_coupling`, `get_covering_tests`
- Each tool accepted JSON string envelope, validated via `validate_request()`, returned minimal valid `ToolResponseEnvelope`
- Entry point: `blast-radius-mcp = blast_radius_mcp.server:main`

**Phase 1.5 — Golden Fixture Tests**
- 10 golden JSON fixtures (request + response for each tool) in `tests/fixtures/`
- `test_schemas.py` with classes: `TestCommonSchemas`, `TestTool1-5Fixtures`, `TestValidation`, `TestIDs`, `TestSettings`, `TestJsonSchemaExport`
- Tests cover: valid parsing, round-trip serialization, extra field rejection, bad type rejection, min_length constraints, JSON schema export

### Acceptance Criteria Met
- ✅ `pip install -e ".[dev]"` succeeds
- ✅ All directories and `__init__.py` files exist
- ✅ Settings load defaults without crashing
- ✅ All schema models instantiate with valid data and export JSON schemas
- ✅ Unknown fields rejected (`extra="forbid"`)
- ✅ Invalid requests raise `ValidationError` with clear messages
- ✅ Server registers all 5 tools
- ✅ `pytest tests/test_schemas.py` — 55 tests passing

---

## Milestone 2 Summary — Cache + Fingerprinting + IDs

**Commit**: `3f4f937`  
**Tests**: 115 passing (55 M1 + 60 M2)  

### What was built

**Phase 2.1 — Deterministic ID Generation** (completed in M1)
- `ids.py` was already fully implemented with all ID functions
- Canonicalization: UTF-8, sorted keys, no whitespace, `\n` line endings
- Anchor lists sorted before hashing for order-independent results
- 24 dedicated tests in `test_ids.py` covering determinism, differentiation, normalization, hex format

**Phase 2.2 — Repo Fingerprinting**
- `repo/io.py`:
  - `safe_read_file(repo_root, rel_path)` — reads file bytes, rejects path traversal (resolves and checks prefix)
  - `glob_python_files(repo_root)` — sorted `.py` files excluding `__pycache__`, `.git`, `.venv`, `node_modules`, `.tox`, `.mypy_cache`, `.pytest_cache`
  - `compute_file_hash(content)` — SHA-256 hex digest
- `repo/fingerprint.py`:
  - `compute_repo_fingerprint(repo_root)` → `RepoFingerprint`
  - Reads git HEAD via `git rev-parse HEAD` subprocess
  - Checks dirty via `git status --porcelain`
  - Content fingerprint: hashes all `.py` files sorted by path, then hashes the combined `path:hash` pairs
  - Without `.git`: returns `git_head=None`, `dirty=True`
  - Validates repo_root exists and is a directory

**Phase 2.3 — SQLite Cache Layer**
- `cache/sqlite.py` — `CacheDB` class:
  - 3 tables: `runs` (run metadata), `tool_results` (cached responses), `artifacts` (index files)
  - WAL mode + `synchronous=NORMAL` for concurrent read performance
  - Thread-safe with `threading.Lock()`
  - `get_cached_result(cache_key)` → parsed JSON dict or `None`
  - `store_result()` — INSERT OR REPLACE with timestamp
  - `store_run()` — INSERT OR IGNORE (idempotent)
  - `store_artifact()` — INSERT OR REPLACE
  - `cleanup(max_age_days=30, max_size_mb=500)` — deletes old rows by age and enforces max DB size by pruning oldest `tool_results`
  - `get_stats()` — row counts for all 3 tables
- `cache/keys.py`:
  - `build_cache_key(tool_name, schema_version, request_dict, repo_fp_hash, impl_version)` — serializes request via `canonical_json()` then delegates to `compute_cache_key()`

**Phase 2.4 — Wire Cache + IDs into Server**
- Rewrote `server.py` with shared `execute_tool()` helper function
- Pipeline: parse envelope → validate inputs → compute repo fingerprint → build cache key → check cache → on miss: execute tool builder, store result → return `ToolResponseEnvelope`
- Deterministic `run_id` is computed in `execute_tool()` from schema version + normalized intent + sorted anchors + diff hash + repo fingerprint
- `store_run()` is called for every request (idempotent by `run_id`)
- Lazy `_get_cache()` singleton for `CacheDB` (created on first call)
- Each tool registers via `@mcp.tool()` and delegates to `execute_tool()` with a stub `_build_toolN_result()` function
- Tool implementation versions tracked: `TOOL1_IMPL_VERSION = "1.0.0"` through `TOOL5_IMPL_VERSION = "1.0.0"`
- Timing via `time.perf_counter()` → `timing_ms`
- `query_id` and `cache_key` computed using real fingerprint hash
- Cache hit returns stored response with `cached=True` and refreshed deterministic `run_id`/`query_id`

### Acceptance Criteria Met
- ✅ Same inputs → identical IDs across runs
- ✅ Different inputs → different IDs
- ✅ Fingerprint deterministic for same repo state
- ✅ Changing any `.py` file changes the fingerprint hash
- ✅ Works without `.git` (git_head=None, dirty=True)
- ✅ Cache miss returns `None`
- ✅ Cache hit returns stored response JSON
- ✅ Same request + same repo → cache hit
- ✅ Different repo fingerprint → cache miss
- ✅ WAL and synchronous pragmas set
- ✅ Second call with identical inputs returns `cached=True`
- ✅ `run_id` is deterministic and persisted in cache runs table
- ✅ `pytest tests/` — 186 tests passing

---

## Milestone 3 Summary — Tool 1: AST Structural Engine

**Commit**: `3aaf699`  
**Tests**: 186 passing (includes post-M3 hardening + server tests)  

### What was built

**Phase 3.1 — File Ingestion & Parsing**
- `load_and_hash_files(repo_root, target_files)` — reads files via `safe_read_file()`, computes SHA-256 per file, returns `list[FileInfo]` + source text dict
- `parse_python_file(source, file_path)` — uses stdlib `ast.parse()`, returns `(tree, None)` on success or `(None, Diagnostic)` on SyntaxError
- `parse_mode` is now consumed from Tool1 options; `tree_sitter` mode gracefully falls back to `python_ast` with a warning diagnostic when unavailable
- Graceful handling of missing files (FileInfo with `parse_status="error"`)

**Phase 3.2 — Symbol Table & Node Emission**
- `build_symbol_table(tree, file_path, source_lines)` — walks AST, collects module/class/function/method nodes
- Node ID: `sym_` + 16 hex chars from `sha256("node" + qualified_name + file + start_line)`
- Extracts: `name`, `qualified_name` (module.Class.method format), `Range`, `signature`, `decorators`, `bases`, `docstring`, `attributes` (is_async, is_generator, is_property)
- `_extract_signature()` — best-effort from `ast.arguments` (handles self, defaults, *args, **kwargs, keyword-only)
- `_file_path_to_module()` — `foo/bar.py` → `foo.bar`, `__init__.py` → parent module name
- Generator detection via `ast.Yield`/`ast.YieldFrom` walk
- Property detection via `@property` decorator check
- `_extract_exports()` — reads `__all__` list from module body

**Phase 3.3 — Edge Emission**
- `emit_edges(tree, file_path, symbol_table, options, source_lines)` — emits 4 edge types:
  - **Import edges** (`type="imports"`): from `ast.Import`/`ast.ImportFrom`, source=module node, metadata has module/name/alias/level
  - **Call edges** (`type="calls"`): from `ast.Call`, source=enclosing function/method, callee resolved via import alias map + symbol table, confidence 0.9/0.6/0.3
  - **Inheritance edges** (`type="inherits"`): from `ast.ClassDef.bases`, source=class node, target=base class
  - **Reference edges** (`type="references"`): from `ast.Name`, metadata includes `{name, context}` where context is `load|store|del`
- Edge ID: `edge_` + 16 hex chars from `sha256("edge" + source_id + type + target + line + col)`
- `_find_enclosing_scope()` — finds which function/method/module node contains a given line
- `_build_import_alias_map()` — maps `alias → (module_path, original_name)` for resolution
- `_lookup_symbol()` — resolves callee text against import map and symbol table
- `_resolve_callee_text()` — uses `ast.unparse()` for callee text extraction
- Snippets extracted from source lines, capped at `max_snippet_chars`

**Phase 3.4 — Cross-file Resolution & Symbol Index**
- `build_cross_file_index(nodes_by_file)` — builds `qualified_name → (file, node_id, kind)` mapping across all parsed files
- `resolve_cross_file_edges(edges, cross_file_index, import_maps)` — resolves unresolved import/call edges against the global index, updates `resolution.status`, `target`, and `target_ref`

**Phase 3.5 — Determinism & Sorting**
- `finalize_and_sort(nodes, edges, diagnostics)` — sorts nodes by `id`, edges by `(source, type, target, id)`, diagnostics by `(file, line, col)`
- Two identical runs on the same unchanged repo produce byte-identical JSON output

**Phase 3.6 — Integration with Server**
- `run_tool1(request, repo_root)` — full pipeline: load files → parse → symbol tables → import maps → emit edges → cross-file resolution → finalize → build stats → return `Tool1Result.model_dump(by_alias=True)`
- Server `_build_tool1_result()` now delegates to `run_tool1()` (replaces stub)
- Full query caching via the SQLite layer (cache hit returns `cached=True`)
- `TOOL1_IMPL_VERSION = "1.0.0"` in the tool module

### Key Implementation Details
- **980 lines** of production code in `tool1_ast_engine.py`
- **20 functions** — 14 public + 6 internal helpers
- Uses Python stdlib `ast` module (v1 default), tree-sitter available as upgrade path
- Precision > recall: only creates concrete cross-file targets when uniquely resolved
- Unresolved targets are explicit (`resolution.status="unresolved"`) — never silently dropped

### Acceptance Criteria Met
- ✅ Valid Python files parse without error
- ✅ Syntax-error files produce Diagnostic and partial results
- ✅ File hashes are deterministic
- ✅ Module, class, function, method nodes correctly extracted
- ✅ Class definitions include bases and decorators
- ✅ Node IDs are stable across repeated runs on unchanged files
- ✅ Import edges link modules correctly
- ✅ Call edges emitted with evidence spans and confidence scores
- ✅ Inheritance edges from ClassDef.bases present
- ✅ Reference edges emitted deterministically when `include_references=True`
- ✅ Unresolved targets explicit (not silently dropped)
- ✅ `tree_sitter` parse mode fallback emits warning diagnostics and still parses successfully
- ✅ Cross-file imports resolve to concrete module/symbol nodes
- ✅ Two identical runs produce identical JSON output (determinism)
- ✅ Server `get_ast_dependencies` returns fully populated, schema-valid response
- ✅ `pytest tests/` — 186 tests passing

---

## Milestone 4 Summary — Orchestrator: Merge/Prune + Report Render

**Depends on**: M1 ✅, M2 ✅, M3 ✅  
**Tests**: 186 passing (all prior tests pass, M4 smoke-tested end-to-end)

### What was built

**Phase 4.1 — ChangeSpec Normalization** (`orchestrator/normalize.py`, 495 lines)
- `ChangeSpec` Pydantic model with `extra="forbid"`, 8 fields covering change class, entity kind, operation, field path, type changes
- `normalize_intent(intent, anchors, diff) → ChangeSpec` — heuristic keyword extraction:
  - Maps operation keywords: remove/delete → remove, rename → rename, add/new → add, type/change type → type_change, relax → relax, tighten → tighten, refactor/signature → refactor
  - Maps entity kind: field/payload/request/response → field+api_change, validator → validator+behavior_change, route/endpoint → route
  - Extracts entity_id from HTTP method patterns, dotted identifiers, anchors
  - Derives field_path from context; falls back to diff content when anchors insufficient
  - Defaults to `structural_change` / `function` / `refactor` when ambiguous

**Phase 4.2 — Diff Parser** (`orchestrator/diff_parser.py`, 186 lines)
- `DiffResult` Pydantic model with changed_files, added_lines, removed_lines, key_identifiers
- `parse_unified_diff(diff) → DiffResult` — full git unified diff parser:
  - Extracts file paths from `---`/`+++` headers (strips `a/`/`b/` prefixes)
  - Parses `@@` hunk headers for line ranges
  - Classifies added (+) and removed (-) lines with numbers
  - Extracts identifiers: function names, class names, assignments, self.attributes, underscore patterns
  - Handles edge cases: empty diff, `/dev/null`, binary markers, multi-file diffs

**Phase 4.3 — Tool Call Planner** (`orchestrator/normalize.py`, integrated)
- `build_tool_plan(change_spec, diff_result, anchors, repo_root) → list[dict]`
  - Tool 1 (get_ast_dependencies): ALWAYS included (priority 1)
  - Tool 2 (trace_data_shape): only for api_change with entry points (priority 2)
  - Tool 3 (find_semantic_neighbors): ALWAYS included (priority 3)
  - Tool 4 (get_historical_coupling): only if `.git/` exists (priority 4)
  - Tool 5 (get_covering_tests): only if `tests/`/`test/` exists (priority 5)

**Phase 4.4 — Evidence Merge & Pruning** (`orchestrator/merge_evidence.py`, 775 lines)
- `ImpactCandidate` Pydantic model with file, symbol, kind, impact_risk, impact_surface, reason, evidence, confidence, suggested_action, corroborated
- `merge_evidence(tool1_result, tool2_result, tool3_result, tool4_result, tool5_result, change_spec)`:
  1. Builds candidates from Tool 1 edges (corroborated=True, direct structural)
  2. Enriches with Tool 2 read-sites (breakage flags → impact_risk=breaking)
  3. Adds Tool 4 coupled files as review suggestions
  4. Adds Tool 3 neighbors as "unknown risk zones" (corroborated=False)
  5. Maps Tool 5 tests to impacted candidates
  6. Deduplicates by (file, symbol) with evidence merging
- `prune_candidates(candidates, change_spec)`:
  - Drops low-confidence structural-only edges not matching changed field
  - Never promotes semantic-only neighbors without Tool 1/2 corroboration
  - For API changes, removes items not touching changed field_path (unless strongly evidenced)
  - Caps at 50 corroborated / 20 uncorroborated candidates
  - Deterministic sort: (corroborated desc, confidence desc, file asc, symbol asc)
- `assign_risk_surface(candidate, change_spec)` — refines risk and surface from evidence types

**Phase 4.5 — Report Renderer** (`orchestrator/report_render.py`, 413 lines)
- `render_report(intent, anchors, change_spec, impacts, tool_results, query_ids, assumptions, limitations) → str`
- Renders 9-section Markdown report matching REPORT_TEMPLATE.md:
  1. Executive summary with derived overall confidence and top 3 risks
  2. Direct structural impacts table (corroborated=True candidates, 7 columns)
  3. Data-shape impacts (Tool 2 read sites with breakage flags, transformations)
  4. Unknown risk zones (uncorroborated candidates from Tool 3)
  5. Implicit dependencies (Tool 4 temporal coupling with weights)
  6. Tests to run (Tool 5 ranked tests with reasons)
  7. Recommended engineer actions (grouped by action type)
  8. Evidence appendix (all query_ids by tool)
  9. Assumptions & limitations
- Graceful handling: empty results → "No data available", missing tools → "Tool not executed"

**Phase 4.6 — Orchestrator Main Pipeline** (`orchestrator/__init__.py`, 281 lines)
- `run_blast_radius(intent, repo_root, anchors, diff, run_id) → str` — full async pipeline:
  1. Normalizes intent → ChangeSpec
  2. Parses diff → DiffResult (if provided)
  3. Computes repo fingerprint
  4. Derives deterministic run_id
  5. Builds tool call plan
  6. Executes each tool via `_call_tool()` (wraps server.execute_tool with error handling)
  7. Merges evidence from all tool results
  8. Prunes candidates
  9. Builds assumptions and limitations lists
  10. Renders and returns Markdown report
- `_call_tool()` helper — builds ToolRequestEnvelope and delegates to execute_tool
- `_TOOL_REGISTRY` maps tool names → impl versions + builder functions

### Key Implementation Details
- **2,150 lines** total new production code across 5 files
- **18+ functions** across 5 modules
- Fully deterministic: same inputs → identical report
- Evidence-first: no impact claims without tool-backed evidence
- Semantic-only results stay as "unknown risk zones" unless corroborated

### Acceptance Criteria Met
- ✅ UC1 "Remove user_id from POST /orders" → correct ChangeSpec (api_change, field, remove)
- ✅ UC4 "Change signature of parse_user_id" → correct ChangeSpec (structural_change, function, refactor)
- ✅ Diff parser extracts file paths, line numbers, identifiers correctly
- ✅ Tool planner: API change → plans all 5 tools; structural change → skips Tool 2; no .git → skips Tool 4
- ✅ Tool 1 edges → corroborated=True, direct impacts
- ✅ Tool 3-only items → corroborated=False, "unknown risk zones"
- ✅ Tool 2 breakage flags → impact_risk=breaking
- ✅ API change pruning removes irrelevant structural edges
- ✅ Report output matches REPORT_TEMPLATE.md structure
- ✅ Every impact has: impact risk, impact surface, location, reason, evidence, confidence, suggested action
- ✅ Empty tool results produce graceful "No data available" sections
- ✅ Evidence appendix lists all query_ids
- ✅ All 186 prior tests still passing

---

## Milestone 5 Summary — Tool 2: Data Lineage Engine

**Depends on**: M1 ✅, M2 ✅, M3 ✅  
**Tests**: 280 passing (186 prior + 94 new)  

### What was built

**Phase 5.1 — Route Index (FastAPI/Starlette)** (`tool2_data_lineage.py`)
- `build_route_index(repo_root, target_files, sources, trees)` → `dict[str, RouteEntry]` keyed by `"METHOD /path"`
- Detects `@app.get/post/put/patch/delete("/path")` and `@router.get/post/...` decorators via AST
- `RouteEntry` dataclass stores: `method`, `path`, `handler_name`, `file`, `line`, `end_line`, `col`, `func_node`
- Handles sync and async handlers, `Depends()`, `response_model`, and all HTTP methods
- Graceful handling of syntax errors and missing files (returns empty dict)

**Phase 5.2 — Pydantic Model Index** (`tool2_data_lineage.py`)
- `build_model_index(repo_root, target_files, sources, trees)` → `dict[str, PydanticModelEntry]`
- Detects `BaseModel` subclasses via `_is_basemodel_subclass()` heuristic (checks base names against `_BASEMODEL_NAMES`)
- `PydanticModelEntry` dataclass: `class_name`, `file`, `line/end_line/col`, `fields` (dict of `PydanticField`), `validators` (list of `PydanticValidator`), `bases`
- `PydanticField` dataclass: `name`, `annotation`, `alias`, `has_default`, `line`, `col`
- Extracts field aliases via `_extract_field_alias()` — detects `Field(alias="...")`
- Detects `@field_validator`, `@validator`, `@model_validator` decorators with target field extraction
- Detects field-level constraints via `_field_constraint_summary()` (ge, le, gt, lt, min_length, max_length, pattern)
- Handles optional fields, complex types (`list[str]`, `dict[str, int]`), and default values

**Phase 5.3 — Field Read/Write Site Detection** (`tool2_data_lineage.py`)
- `trace_field(field_path, handler_file, handler_func_node, ...)` — main field tracing function
- `_scan_function_body(func_node, field_name, model_name, ...)` — AST walker detecting:
  - **Attribute reads**: `request.user_id` → access_pattern `"attribute"`, confidence `"high"`
  - **Dict subscript reads**: `data["user_id"]` → access_pattern `"dict_subscript"`, confidence `"high"`
  - **Dict `.get()` reads**: `data.get("user_id")` → access_pattern `"dict_get"`, confidence `"medium"`
  - **Attribute writes**: `order.user_id = ...` → write site with breakage flags
  - **Dict writes**: `data["user_id"] = ...` → write site
  - **Transforms/casts**: `UUID(request.user_id)`, `str(request.user_id)` → transform entries
  - **Chained attribute access**: `request.data.nested.user_id` → detected
- `trace_field_in_function()` — convenience wrapper for testing with simplified interface
- Breakage flags: `if_removed=True` (when no default), `if_renamed=True` (for literal keys)
- Evidence snippets extracted from source lines
- Confidence levels: `"high"` (direct attribute/subscript), `"medium"` (.get), `"low"` (heuristic)
- No false positives: exact field name matching (not partial)

**Phase 5.4 — Wire into Server + Output Assembly** (`tool2_data_lineage.py` + `server.py`)
- `_resolve_entry_points(entry_points, route_index, func_index, sources, trees)` → `(resolved, diagnostics, handler_tuples)`
  - `route:METHOD /path` anchors resolved against route index
  - `symbol:file.py:func_name` anchors resolved against function index
  - Unresolved anchors emit `Tool2Diagnostic(code="entry_point_unresolved")`
- `_build_function_index(target_files, trees)` → `dict[str, FunctionEntry]` keyed by `"file.py:func_name"`
- `_load_sources(repo_root, target_files)` — loads and parses `.py` files, returns `(sources, trees, error_count)`
- `run_tool2(request: Tool2Request, repo_root: str)` → dict — full pipeline:
  1. Parse field_path into model_name + field_name
  2. Glob Python files and load sources
  3. Build route index, model index, function index
  4. Resolve entry points
  5. Trace field in each resolved handler
  6. Collect validations from model index (pydantic validators + field constraints)
  7. Enforce `max_sites` truncation with `truncated=True` flag
  8. Deterministic sort of all output arrays
  9. Return `Tool2Result.model_dump(by_alias=True)`
- Server `_build_tool2_result()` now delegates to `run_tool2()` (replaces stub)
- `TOOL2_IMPL_VERSION = "1.0.0"`

### Deterministic ID Generation
- `_sha256_prefix(prefix, *parts)` — SHA-256 of `"|".join(parts)`, truncated to 16 hex chars
- `_compute_site_id(field, symbol_id, file, line, col, pattern)` → `site_` + 16 hex
- `_compute_validation_id(kind, field, file, line)` → `val_` + 16 hex
- `_compute_transform_id(kind, field, file, line, col)` → `xform_` + 16 hex
- `_compute_symbol_id(file, name, line)` → `sym_` + 16 hex

### Key Implementation Details
- **1,580 lines** of production code in `tool2_data_lineage.py`
- **20+ functions** — public API, internal helpers, and dataclasses
- Uses Python stdlib `ast` module for static analysis
- Static heuristic for BaseModel detection (direct subclass only)
- Two identical runs produce identical output (deterministic sort + content-derived IDs)

### Acceptance Criteria Met
- ✅ FastAPI route decorators detected (@app.get/post/put/patch/delete, @router.*)
- ✅ Pydantic models with fields, aliases, validators, and constraints indexed
- ✅ Field reads detected: attribute access, dict subscript, .get()
- ✅ Field writes detected: attribute assignment, dict assignment
- ✅ Transforms/casts detected (e.g., UUID(field), str(field))
- ✅ Breakage flags set correctly (if_removed, if_renamed)
- ✅ Entry points resolved from route: and symbol: anchors
- ✅ Unresolved anchors produce diagnostics
- ✅ max_sites truncation works with truncated flag
- ✅ Deterministic: same inputs → identical output
- ✅ Evidence snippets extracted from source
- ✅ No false positives for unrelated fields
- ✅ Syntax errors handled gracefully
- ✅ Missing files produce empty results, not crashes
- ✅ Server wired: `trace_data_shape` returns fully populated Tool2Result
- ✅ `pytest tests/` — 280 tests passing

---

## Next Up: Milestone 6 — Tool 5: Test Impact Analyzer

**Depends on**: M1 ✅, M2 ✅, M3 ✅  

**Key files**: `blast_radius_mcp/tools/tool5_test_impact.py` (currently stub)

---

## Test Summary

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_schemas.py` | 58 | Schemas, fixtures, validation, settings, JSON export |
| `test_ids.py` | 24 | canonical_json, run_id, query_id, cache_key, normalize, diff_hash |
| `test_fingerprint.py` | 16 | safe_read_file, glob_python_files, file_hash, repo fingerprint |
| `test_cache.py` | 21 | CacheDB CRUD, stats, cleanup (age + size cap), build_cache_key |
| `test_tool1_ast.py` | 65 | AST engine: nodes, edges, cross-file, determinism, parse-mode fallback, integration |
| `test_tool2.py` | 94 | Data lineage: IDs, routes, models, field tracing, entry points, integration, determinism |
| `test_server.py` | 2 | execute_tool deterministic `run_id` persistence + cache-hit behavior |
| **Total** | **280** | **All passing** |
