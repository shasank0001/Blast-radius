# Blast Radius MCP — Project State

> **Last Updated**: 2026-02-21  
> **Repository**: https://github.com/shasank0001/Blast-radius.git  
> **Branch**: `main`  
> **Python**: >=3.11 | **Build**: hatchling | **Tests**: 177 passing (0 failures)

---

## Overall Progress

| # | Milestone | Status | Commit |
|---|-----------|--------|--------|
| M1 | Project skeleton + MCP server boot + schemas + validation | ✅ Complete | `1368cc6` |
| M2 | SQLite cache + repo fingerprinting + deterministic IDs | ✅ Complete | `3f4f937` |
| M3 | Tool 1 — AST Structural Engine | ✅ Complete | `3aaf699` |
| M4 | Orchestrator — merge/prune + report render | ⬜ Not started | — |
| M5 | Tool 2 — Data Lineage Engine | ⬜ Not started | — |
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
│   │   ├── tool2_data_lineage.py            # ⬜ Stub
│   │   ├── tool3_semantic_neighbors.py      # ⬜ Stub
│   │   ├── tool4_temporal_coupling.py       # ⬜ Stub
│   │   └── tool5_test_impact.py             # ⬜ Stub
│   └── indices/                            # ⬜ Stub — semantic index pending
│       └── semantic_index.py
├── orchestrator/                           # ⬜ Stub files — implementations pending
│   ├── normalize.py
│   ├── diff_parser.py
│   ├── merge_evidence.py
│   └── report_render.py
├── scripts/
│   └── run_mcp_server.py                   # Convenience entry point
└── tests/
    ├── conftest.py
    ├── test_schemas.py                     # 55 tests — golden fixtures, validation, settings
    ├── test_ids.py                         # 24 tests — deterministic ID generation
    ├── test_fingerprint.py                 # 16 tests — repo I/O and fingerprinting
    ├── test_cache.py                       # 20 tests — SQLite cache + cache keys
    ├── test_tool1_ast.py                   # 62 tests — AST engine unit + integration
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
10. Server uses shared `execute_tool()` helper: parse envelope → validate → fingerprint → check cache → execute → store → return

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
  - `cleanup(max_age_days=30)` — deletes old tool_results, returns count
  - `get_stats()` — row counts for all 3 tables
- `cache/keys.py`:
  - `build_cache_key(tool_name, schema_version, request_dict, repo_fp_hash, impl_version)` — serializes request via `canonical_json()` then delegates to `compute_cache_key()`

**Phase 2.4 — Wire Cache + IDs into Server**
- Rewrote `server.py` with shared `execute_tool()` helper function
- Pipeline: parse envelope → validate inputs → compute repo fingerprint → build cache key → check cache → on miss: execute tool builder, store result → return `ToolResponseEnvelope`
- Lazy `_get_cache()` singleton for `CacheDB` (created on first call)
- Each tool registers via `@mcp.tool()` and delegates to `execute_tool()` with a stub `_build_toolN_result()` function
- Tool implementation versions tracked: `TOOL1_IMPL_VERSION = "1.0.0"` through `TOOL5_IMPL_VERSION = "1.0.0"`
- Timing via `time.perf_counter()` → `timing_ms`
- `query_id` and `cache_key` computed using real fingerprint hash
- Cache hit returns stored response with `cached=True`

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
- ✅ `pytest tests/` — 115 tests passing

---

## Milestone 3 Summary — Tool 1: AST Structural Engine

**Commit**: `3aaf699`  
**Tests**: 177 passing (115 M1+M2 + 62 M3)  

### What was built

**Phase 3.1 — File Ingestion & Parsing**
- `load_and_hash_files(repo_root, target_files)` — reads files via `safe_read_file()`, computes SHA-256 per file, returns `list[FileInfo]` + source text dict
- `parse_python_file(source, file_path)` — uses stdlib `ast.parse()`, returns `(tree, None)` on success or `(None, Diagnostic)` on SyntaxError
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
- `emit_edges(tree, file_path, symbol_table, options, source_lines)` — emits 3 edge types:
  - **Import edges** (`type="imports"`): from `ast.Import`/`ast.ImportFrom`, source=module node, metadata has module/name/alias/level
  - **Call edges** (`type="calls"`): from `ast.Call`, source=enclosing function/method, callee resolved via import alias map + symbol table, confidence 0.9/0.6/0.3
  - **Inheritance edges** (`type="inherits"`): from `ast.ClassDef.bases`, source=class node, target=base class
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
- ✅ Unresolved targets explicit (not silently dropped)
- ✅ Cross-file imports resolve to concrete module/symbol nodes
- ✅ Two identical runs produce identical JSON output (determinism)
- ✅ Server `get_ast_dependencies` returns fully populated, schema-valid response
- ✅ `pytest tests/` — 177 tests passing

---

## Next Up: Milestone 4 — Orchestrator: Merge/Prune + Report Render

**Depends on**: M1 ✅, M2 ✅, M3 ✅  

Phases:
1. **4.1** — ChangeSpec normalization
2. **4.2** — Diff parser
3. **4.3** — Tool call planner
4. **4.4** — Evidence merge & pruning
5. **4.5** — Report renderer (Markdown)
6. **4.6** — Orchestrator main pipeline

**Key files**: `orchestrator/normalize.py`, `orchestrator/diff_parser.py`, `orchestrator/merge_evidence.py`, `orchestrator/report_render.py` (all currently stubs)

---

## Test Summary

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_schemas.py` | 55 | Schemas, fixtures, validation, settings, JSON export |
| `test_ids.py` | 24 | canonical_json, run_id, query_id, cache_key, normalize, diff_hash |
| `test_fingerprint.py` | 16 | safe_read_file, glob_python_files, file_hash, repo fingerprint |
| `test_cache.py` | 20 | CacheDB CRUD, stats, cleanup, build_cache_key |
| `test_tool1_ast.py` | 62 | AST engine: nodes, edges, cross-file, determinism, integration |
| **Total** | **177** | **All passing** |
