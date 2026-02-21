# MCP Server Architecture (Hackathon v1, Python)

This document defines the final **MCP tool server** architecture to expose **Tools 1–5** described in [docs/PRD.md](PRD.md), plus the surrounding **orchestrator flow** used by OpenCode (LLM) to generate a blast-radius report using [docs/REPORT_TEMPLATE.md](REPORT_TEMPLATE.md).

---

## 1) System boundary

- **MCP Server (this repo component):** exposes five deterministic, cacheable tools over MCP.
- **Orchestrator (OpenCode LLM + thin driver):** converts NL intent (+ optional unified diff + optional anchors) into a tool-call plan, executes tools, merges evidence, and renders a Markdown report.

Design goal: **tools are deterministic** and **LLM is evidence-constrained**.

---

## 2) Folder layout

Recommended layout (single MCP server process hosting Tools 1–5):

- blast_radius/
  - README.md
  - pyproject.toml
  - blast_radius_mcp/
    - __init__.py
    - server.py                  # MCP entrypoint: registers tools 1–5
    - settings.py                # env + defaults
    - logging.py                 # structured logs
    - ids.py                     # deterministic run_id + query_id
    - schemas/
      - __init__.py
      - common.py                # Location, EvidenceRef, Node, Edge, etc.
      - tool1_ast.py
      - tool2_lineage.py
      - tool3_semantic.py
      - tool4_coupling.py
      - tool5_tests.py
    - validation/
      - __init__.py
      - validate.py              # request/response validation gates
    - cache/
      - __init__.py
      - sqlite.py                # SQLite schema + get/set
      - keys.py                  # cache key canonicalization
    - repo/
      - __init__.py
      - fingerprint.py           # git HEAD + file hashes
      - io.py                    # safe file reads, globbing
    - tools/
      - __init__.py
      - tool1_ast_engine.py
      - tool2_data_lineage.py
      - tool3_semantic_neighbors.py
      - tool4_temporal_coupling.py
      - tool5_test_impact.py
    - indices/
      - __init__.py
      - semantic_index.py         # local vector/BM25 index build + query
  - scripts/
    - run_mcp_server.py           # convenience entry for local dev
    - warm_cache.py               # optional: pre-index repo
  - orchestrator/
    - README.md                   # describes OpenCode prompts + flow
    - normalize.py                # ChangeSpec normalization helpers
    - diff_parser.py              # unified diff parsing
    - merge_evidence.py           # deterministic merge + pruning
    - report_render.py            # markdown report renderer (template-driven)

Notes:
- The **orchestrator/** minimal deterministic pipeline is required in v1 to enforce evidence merge/pruning rules.
- Keep orchestrator code lightweight, but do not omit it in the final v1 deliverable.

---

## 3) Dependency choices (minimal-first)

### Required (server core)
- **mcp**: official MCP Python SDK. Use `FastMCP` (async tool registration and JSON in/out).
- **pydantic (v2)**: canonical request/response models and JSON Schema generation.
- **jsonschema**: belt-and-suspenders runtime validation against exported schemas (optional but helpful for debugging).
- **xxhash**: fast stable hashing for cache keys (fallback to sha256 if unavailable).

### Tool 1 (AST structural)
- **tree-sitter** + **tree-sitter-python** OR **tree_sitter_languages**:
  - deterministic parsing; can be incremental if you store parse trees keyed by file hash.
- Alternative (faster to implement, lower precision): Python built-in `ast` module.

### Tool 2 (payload lineage)
- **Python ast** is sufficient for v1 for attribute access and dict literal key subscripts.
- Optional precision upgrades:
  - **libcst** for robust metadata and docstring/decorator handling.
  - FastAPI/Pydantic heuristics without importing the target project (avoid side effects).

### Tool 3 (semantic neighbors)
Two-tier approach for hackathon reliability:
- **Tier A (primary):** OpenAI embeddings + Pinecone vector retrieval.
- **Tier B (fallback, always works):** `rank-bm25` for lexical similarity.

### Tool 4 (temporal coupling)
- No dependency required: run `git` via `subprocess`.

### Tool 5 (test impact)
- No dependency required (static): `ast` import scanning + simple heuristics.
- Optional dynamic (only if runnable): `coverage`.

---

## 4) MCP tool routing & contracts

### 4.1 One-process tool server

Implement a single server that registers all five tools. Routing is explicit and stable:

- `get_ast_dependencies` (Tool 1)
- `trace_data_shape` (Tool 2)
- `find_semantic_neighbors` (Tool 3)
- `get_historical_coupling` (Tool 4)
- `get_covering_tests` (Tool 5)

All tools accept a **ToolRequestEnvelope** and return a **ToolResponseEnvelope**.

### 4.2 Envelope schema (common)

**Request envelope**:
- `schema_version`: string (e.g., `"v1"`)
- `repo_root`: string (absolute or workspace-relative)
- `inputs`: tool-specific object
- `anchors`: optional list (route anchors, symbol anchors, file anchors)
- `diff`: optional unified diff string
- `options`: optional tool-specific settings (limits, timeouts)

**Response envelope**:
- `schema_version`: `"v1"`
- `tool_name`: string
- `query_id`: deterministic per tool call
- `run_id`: deterministic per orchestrator run (see §6)
- `repo_fingerprint`: object (git HEAD, dirty flag, file hashes scope)
- `cached`: boolean
- `timing_ms`: number
- `result`: tool-specific object
- `errors`: optional list (structured)

Rationale:
- Envelope ensures every tool output is traceable and cacheable.
- The server stays stateless; cache provides memoization.

### 4.3 JSON Schema validation policy

Validation happens in two stages:

1) **Pydantic model parsing** (fast, typed):
   - Reject unknown fields unless explicitly allowed.
   - Enforce types (lists, strings, enums, bounds).

2) **JSON Schema validation** (debug / contract):
   - Export schema from pydantic models.
   - Validate the raw incoming JSON and outgoing JSON.

This prevents LLM tool-call drift and keeps the tool outputs stable for report generation.

---

## 5) SQLite caching layer

### 5.1 Goals
- Speed up repeated runs (incremental indexing).
- Guarantee deterministic “same input + same repo state → same output” unless tool version changes.

### 5.2 Cache key

Cache key is computed from:
- `tool_name`
- `schema_version`
- **normalized request JSON** (canonical JSON: sorted keys, no whitespace)
- `repo_fingerprint` (git HEAD + relevant file hashes)
- `tool_impl_version` (manually bumped constant per tool)

Recommended format:

`cache_key = sha256(tool_name + schema_version + canonical_request + repo_fingerprint_hash + tool_impl_version)`

### 5.3 SQLite schema (minimal)

Tables:

1) `runs`
- `run_id TEXT PRIMARY KEY`
- `created_at TEXT`
- `repo_root TEXT`
- `repo_fingerprint TEXT` (json)
- `intent TEXT`
- `anchors TEXT` (json)
- `diff_hash TEXT`

2) `tool_results`
- `cache_key TEXT PRIMARY KEY`
- `tool_name TEXT`
- `query_id TEXT`
- `run_id TEXT`
- `repo_fingerprint_hash TEXT`
- `request_json TEXT`
- `response_json TEXT`
- `created_at TEXT`
- `timing_ms INTEGER`

3) `artifacts` (optional)
- `artifact_id TEXT PRIMARY KEY`
- `kind TEXT` (e.g., `semantic_index`)
- `repo_fingerprint_hash TEXT`
- `blob BLOB` or `path TEXT`

SQLite pragmas:
- WAL mode for concurrency.
- `synchronous=NORMAL` for speed.

---

## 6) Deterministic run IDs & query IDs

### 6.1 Run ID (orchestrator-level)

The **run_id** represents the user request (intent + anchors + diff) scoped to a repo state.

Compute:

- Normalize input:
  - `intent_norm`: trim + collapse whitespace
  - `anchors_norm`: sorted list
  - `diff_norm`: if present, canonicalize line endings and compute `diff_hash`
- Combine with repo fingerprint:
  - `repo_fingerprint_hash`: hash of `git_head + dirty_flag + relevant_file_hashes`

Then:

`run_id = sha256("run" + schema_version + intent_norm + json(anchors_norm) + diff_hash + repo_fingerprint_hash)`

This ensures:
- same request on same commit → same run_id
- different commit → different run_id

### 6.2 Query ID (tool-call-level)

Each tool call gets a deterministic query_id derived from the tool name + canonical request JSON + repo fingerprint hash:

`query_id = sha256("query" + tool_name + canonical_request + repo_fingerprint_hash)`

This makes evidence references stable inside the final report.

---

## 7) Tool implementations (routing + behavior)

### Tool 1 — AST Structural Engine (`get_ast_dependencies`)

**Inputs**
- `target_files: list[str]` (optional; default: changed files from diff)
- `max_edges: int` (optional)
- `include_references: bool` (optional)

**Core output**
- `nodes`: symbols (module/class/function/method)
- `edges`: typed edges (`imports`, `calls`, `inherits`, `references`)
- `locations`: file + (line, col)
- `file_hashes`: sha256 per file

Implementation notes:
- Use tree-sitter for speed and stable offsets.
- Cache parse results keyed by file hash.

### Tool 2 — Data Lineage Engine (`trace_data_shape`)

**Inputs**
- `field_path: str`
- `entry_points: list[str]` (route/symbol anchors)

**Core output**
- `read_sites`: list of exact read sites (file, symbol, access kind)
- `write_sites`: optional
- `transforms`: rename/cast/defaulting steps
- `breaks_if_removed`: boolean per read

Implementation notes:
- For FastAPI: detect route decorators (`@app.post("/orders")`), then inspect handler signature models.
- For Pydantic: detect `BaseModel` subclasses and field declarations.
- Track dict subscripts with literal keys and `.get("field")`.

### Tool 3 — Semantic Vector Search (`find_semantic_neighbors`)

**Inputs**
- `query_text: str` (diff snippet preferred; else intent)
- `scope`: optional (paths/globs)

**Core output**
- `neighbors`: list of `{file, symbol, score, snippet}`

Rules:
- Orchestrator must treat results as **unknown risk zones** unless corroborated by Tool 1 or Tool 2.

### Tool 4 — Temporal Coupling (`get_historical_coupling`)

**Inputs**
- `file_paths: list[str]`
- `max_files: int`
- `window_commits: int` (optional)

**Core output**
- `coupled_files`: list of `{file, weight, example_commits}`

Implementation notes:
- Use `git log --name-only` and compute co-occurrence.

### Tool 5 — Test Impact Analyzer (`get_covering_tests`)

**Inputs**
- `impacted_nodes: list[{file, symbol, kind}]`

**Core output**
- ranked `tests`: `{test_id, file, reason, score}`

Implementation notes:
- Static pass: parse tests (`tests/`), collect imports and symbol references.
- Optional enhancement: if coverage available and runnable, suggest a minimal focused set.

---

## 8) Orchestrator flow (NL intent + diff + anchors → report)

The orchestrator is a deterministic pipeline with an LLM only at the “intent interpretation + summarization” layers.

### 8.1 Inputs
- `intent` (required)
- `diff` (optional unified diff)
- `anchors` (optional route or symbol anchors)

### 8.2 Steps

1) **Normalize inputs**
- Canonicalize anchors and diff.
- Compute repo fingerprint and `run_id`.

2) **Derive ChangeSpec** (LLM-guided, evidence constrained)
- Convert intent (+ diff + anchors) → `ChangeSpec` fields (change class, entity kind, operation, field path, etc.).
- If ambiguous: mark assumptions; widen search with lower confidence.

3) **Select tool plan**
Heuristic tool plan:
- If diff present → Tool 1 always (structural scope), Tool 3 optional.
- If ChangeSpec is API/data/validation → Tool 2 required.
- If anchors present → focus Tool 1/2 on anchored entry points.
- Tool 4 on each primary target file.
- Tool 5 after impacted nodes are assembled.

4) **Execute tools (parallel where possible)**
- Compute query_id for each planned tool call.
- For each tool call:
  - check SQLite cache
  - if miss: run tool, validate response schema, store result

5) **Merge evidence (deterministic)**
- Build a candidate impacted set from Tool 1 and Tool 2.
- Enrich with Tool 4 and Tool 5.
- Add Tool 3 results as “unknown risk zones” only.
- Prune aggressively:
  - remove items not touching the field-path for API changes
  - cap per-section counts
  - require at least one “hard” evidence source to label as direct impact

6) **Generate Markdown report**
- Load template from [docs/REPORT_TEMPLATE.md](REPORT_TEMPLATE.md).
- Fill sections with merged evidence.
- Include `query_id`s in Evidence appendix.

7) **Output**
- Save a report file (optional) and print to stdout.

---

## 9) End-to-end sequence diagram (text)

Legend: `->` request, `<-` response, `||` parallel.

User
  -> OpenCode Orchestrator: intent + optional diff + optional anchors
OpenCode Orchestrator
  -> Repo Fingerprinter: compute git HEAD + file hashes
  <- Repo Fingerprinter: repo_fingerprint
  -> ID Generator: compute run_id
  <- ID Generator: run_id
  -> MCP Client: plan tool calls (Tool1..Tool5)

  ||
  MCP Client -> MCP Server: Tool 1 request (envelope)
  MCP Client -> MCP Server: Tool 2 request (envelope)
  MCP Client -> MCP Server: Tool 3 request (envelope)
  MCP Client -> MCP Server: Tool 4 request(s) (envelope)
  ||

MCP Server
  -> SQLite Cache: lookup cache_key
  <- SQLite Cache: hit/miss
  alt miss
    MCP Server -> Tool Engine (1/2/3/4/5): execute
    Tool Engine -> Repo IO / Git / Indices: read/analyze
    Tool Engine <- Repo IO / Git / Indices: evidence
    MCP Server -> Schema Validator: validate response JSON
    MCP Server -> SQLite Cache: store response
  end
  MCP Server <- MCP Client: tool response (envelope)

OpenCode Orchestrator
  -> Evidence Merger: unify nodes/edges/lineage/coupling/tests
  <- Evidence Merger: merged evidence
  -> Report Renderer: fill [docs/REPORT_TEMPLATE.md](REPORT_TEMPLATE.md)
  <- Report Renderer: Markdown report
  -> User: final blast-radius report

---

## 10) Hackathon implementation milestones (step-by-step)

1) **Project skeleton + MCP server boot**
- Create `blast_radius_mcp/server.py` with MCP startup and one toy tool.

2) **Schemas & validation**
- Implement pydantic models for envelopes and Tool 1 response.
- Add strict validation gates and golden JSON fixtures.

3) **SQLite cache**
- Implement cache tables + `get_or_compute()` wrapper.
- Add deterministic cache keys and tool impl version constants.

4) **Repo fingerprinting**
- Implement git HEAD detection + dirty flag.
- For v1 deterministic cache correctness: hash all relevant Python files in scope.

5) **Tool 1 (AST) MVP**
- Start with Python `ast` for imports + function defs + call edges.
- Upgrade to tree-sitter if time.

6) **Tool 2 (lineage) MVP**
- Implement literal field read-site detection:
  - attribute reads (`obj.user_id`)
  - dict subscripts and `.get("user_id")`
- Add FastAPI route decorator detection for entry-point focus.

7) **Tool 4 (temporal coupling) MVP**
- Add `git log --name-only` co-change scoring.

8) **Tool 5 (tests) MVP**
- Parse `tests/` files, build import map, rank tests by overlap.

9) **Tool 3 (semantic neighbors) MVP**
- Implement OpenAI + Pinecone primary retrieval.
- Always provide BM25 fallback for reliability/offline degradation.

10) **Orchestrator demo driver**
- Create a thin script that:
  - accepts intent/diff/anchors
  - calls tools in a deterministic plan
  - merges evidence deterministically
  - renders report from template

11) **End-to-end demo hardening**
- Add timeouts, max result caps, and stable sorting.
- Ensure report always renders, even with partial tool failures.

12) **Polish**
- Add sample runs + screenshots and keep one “judges happy” scenario:
  - API field removal on a FastAPI project
  - clear read-sites + tests to run

---

## 11) Determinism checklist (must pass)

- Canonical JSON serialization for hashing.
- Stable sorting of lists (by file, symbol, line).
- No non-deterministic timestamps inside `result` objects.
- Cache keys include tool implementation version.
- Tools do not import/execute target project code (no side effects).

