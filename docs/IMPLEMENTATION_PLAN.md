# Implementation Plan — Blast Radius (Hackathon v1, Python)

This plan is derived from:
- [docs/PRD.md](PRD.md)
- [docs/TOOL1_SCHEMA.md](TOOL1_SCHEMA.md)
- [docs/TOOL2_SCHEMA.md](TOOL2_SCHEMA.md)
- [docs/TOOL3_SCHEMA.md](TOOL3_SCHEMA.md)
- [docs/TOOL4_SCHEMA.md](TOOL4_SCHEMA.md)
- [docs/TOOL5_SCHEMA.md](TOOL5_SCHEMA.md)
- [docs/MCP_SERVER_ARCHITECTURE.md](MCP_SERVER_ARCHITECTURE.md)
- [docs/REPORT_TEMPLATE.md](REPORT_TEMPLATE.md)

Scope decisions already locked:
- **Language**: Python-only
- **User input**: Natural language intent; demo provides **git-style unified diff**; system must degrade gracefully with NL-only.
- **Evidence-first**: No impact claims without tool evidence. Semantic similarity is “unknown risk zone” unless corroborated.

---

## 0) Repo deliverables (what you ship)

### A) MCP Server (required)
A single MCP server process exposing 5 tools:
1. `get_ast_dependencies` (Tool 1)
2. `trace_data_shape` (Tool 2)
3. `find_semantic_neighbors` (Tool 3)
4. `get_historical_coupling` (Tool 4)
5. `get_covering_tests` (Tool 5)

The server must be deterministic, cacheable (SQLite), and return structured JSON.

### B) Orchestrator driver (required, minimal)
A thin deterministic driver (can be called by OpenCode prompt or CLI) that:
- Normalizes NL intent → `ChangeSpec`
- Parses unified diff
- Selects tools + runs them
- Merges/prunes evidence
- Renders Markdown report using [docs/REPORT_TEMPLATE.md](REPORT_TEMPLATE.md)

---

## 1) Shared primitives (used by all tools)

### 1.1 Canonical `Location`
Standardize on repo-relative file URIs and 1-based line + 0-based column.
- `uri`: `path/to/file.py`
- `range.start`: `{ line: 1.., column: 0.. }`
- `range.end`: `{ line: 1.., column: 0.. }`
- optional `snippet` (short excerpt, bounded)

### 1.2 Deterministic IDs
- `run_id`: stable hash of `(schema_version, normalized_intent, sorted_anchors, diff_hash, repo_fingerprint_hash)`
- `query_id`: stable hash of `(tool_name, canonical_request_json, repo_fingerprint_hash)`
- Tool-specific node IDs:
  - Tool 1 nodes follow [docs/TOOL1_SCHEMA.md](TOOL1_SCHEMA.md)

### 1.3 Repo fingerprint
Chosen for v1 (strong correctness):
- `git_head` (if `.git` exists)
- `dirty` flag
- hash of **all `*.py` files** (repo-relative) to prevent cache reuse on any code change

Implementation note:
- Cache the computed file-hash manifest in SQLite keyed by `git_head+dirty` to avoid re-hashing everything on every run.

### 1.4 Caching (SQLite)
- Cache key: `sha256(tool_name + schema_version + canonical_request_json + repo_fingerprint_hash + tool_impl_version)`
- Store raw request + raw response JSON
- Deterministic response ordering is mandatory so cache hits are safe.

---

## 2) Tool 1 — AST Structural Engine (`get_ast_dependencies`)

### 2.1 Goal
Build the **base structural graph** for a list of Python files:
- Nodes: `module | class | function | method`
- Edges: `imports | calls | inherits | references`
- Every edge includes evidence span + confidence + resolution state.

### 2.2 Input
- `target_files: list[str]` (repo-relative)
- `options`:
  - `include_references: bool` (default false for scale)
  - `max_edges_per_file` (cap)

### 2.3 Implementation steps
1. **File ingestion**
   - Normalize paths, read bytes, compute file hash.
   - Build a per-file line index for mapping offsets if needed.
2. **Parse**
   - v1 default: **Tree-sitter Python** for deterministic spans and error-tolerant parsing.
   - Record syntax errors as diagnostics; still emit partial nodes/edges when possible.
3. **Build per-file symbol table**
   - Definitions: classes/functions/methods with ranges.
   - Imports: alias map for `import` and `from import`.
   - Minimal scope tracking for local name resolution (no type inference).
4. **Create nodes**
   - Module node per file.
   - Class/function/method nodes with stable IDs and locations.
5. **Create edges (evidence-first)**
   - `imports`: module → resolved module/symbol when resolvable.
   - `inherits`: class → base class symbol when resolvable.
   - `calls`: enclosing function/method → callee when resolvable.
   - `references`: only if enabled; split kinds (`reads_name`, `writes_name`, etc.) via `attributes.reference_kind`.
6. **Resolution policy (precision > recall)**
   - Only create concrete cross-file targets when uniquely resolved.
   - Otherwise emit `resolution=ambiguous/unresolved` + low confidence + optional `target_candidates`.
7. **Determinism**
   - Sort `nodes` by `id` and `edges` by `(source, kind, target, id)`.
8. **Caching**
   - Per-file cache keyed by file hash + tool version.
   - Optional global symbol index to speed up resolution.

### 2.4 Output
Must conform to [docs/TOOL1_SCHEMA.md](TOOL1_SCHEMA.md).

### 2.5 MVP acceptance tests
- On a small FastAPI repo, Tool 1 returns:
  - all route handlers as function nodes
  - import edges to router/app modules
  - call edges for obvious `Name()` calls
  - deterministic ordering across repeated runs

---

## 3) Tool 2 — Data Lineage Engine (`trace_data_shape`)

### 3.1 Goal
High-precision tracing for API payload/field changes:
- exact **read sites** (breaks-if-removed)
- validations (Pydantic validators, Field constraints)
- transformations (rename/cast/default)
- links findings to Tool 1 `enclosing_symbol_id`

### 3.2 Inputs
- `field_path`: e.g. `request.user_id` or `OrderRequest.user_id`
- `entry_points`: route anchor (`POST /orders`) and/or symbol anchor
- `tool1_snapshot/query_id`: to link node IDs and reuse file hashes
- optional `diff_unified` (for scoping only)

### 3.3 Index phase (cached)
Build minimal indexes for the repo (or for a scoped file set):
1. **Route index**
   - Find FastAPI/Starlette routes via decorators and `add_api_route`.
   - Map method+path → handler function location → Tool 1 node id.
2. **Model index**
   - Detect Pydantic models (`BaseModel`).
   - Extract fields, aliases (`alias`, `serialization_alias`, etc.), defaults, Field constraints.
   - Extract validators (`validator`, `field_validator`, `model_validator`) and map field → validator symbol.
3. **Symbol linkage**
   - Map any code span → Tool 1 enclosing symbol id.

### 3.4 Query phase (bounded tracing)
1. Resolve the canonical field identity (handle aliases and model nesting best-effort).
2. Seed sources based on request/response direction.
3. Perform intra-procedural scan in handler:
   - Reads: `payload.user_id`, `payload["user_id"]`, `.get("user_id")`.
   - Writes: dict literals/updates, response model construction.
   - Transforms: casts (`UUID(...)`), rename (`userId`↔`user_id`), defaults.
4. Optional inter-procedural expansion (depth cap):
   - Follow Tool 1 call edges for `process(payload)` / `process(payload.user_id)`.
   - Trace callee with argument→parameter mapping.
5. Emit results with evidence spans and confidence.

Parsing decision (v1):
- Use **Tree-sitter Python** for extracting access expressions and exact evidence spans.
- Avoid importing the target project; operate purely on source text.

### 3.5 Output (tool-specific JSON)
- `changed_field`: canonical id
- `read_sites[]`, `write_sites[]`, `validations[]`, `transforms[]`
- each item includes `location`, `enclosing_symbol_id`, `access_pattern`, `breakage`, `confidence`

### 3.6 Trigger policy (important)
- If NL intent + diff implies field/schema/validation change AND an entry point exists → run Tool 2.
- In NL-only with no entry point → avoid global tracing; output “needs anchor” as limitation.

---

## 4) Tool 3 — Semantic Neighbor Search (`find_semantic_neighbors`)

### 4.1 Goal
Find “unknown risk zones” (similar code elsewhere) for review.

### 4.2 Index (incremental)
- Chunk code at function/method level.
- Store chunks in SQLite keyed by `(file_hash, qualified_symbol, span)`.

### 4.3 Retrieval tiers
Chosen for v1:
- Tier A (primary): **OpenAI embeddings** + **Pinecone** for nearest-neighbor search.
- Tier B (safety fallback): lexical BM25 (SQLite FTS5) when embeddings/VD are unavailable.

Implementation notes:
- Implement an `EmbeddingProvider` interface (OpenAI-backed) and a `VectorStore` interface (VD-backed).
- If `OPENAI_API_KEY` (or VD config) is missing, automatically fall back to BM25 so the demo still runs offline.

Configuration (v1):
- Required env vars:
   - `OPENAI_API_KEY`
   - `PINECONE_API_KEY`
   - `PINECONE_INDEX`
   - `PINECONE_ENV` or `PINECONE_HOST` (depending on Pinecone SDK)
- Embedding model (suggested default): `text-embedding-3-small` (override via `OPENAI_EMBEDDING_MODEL`).

### 4.4 Query formulation
- Build query text from NL intent + top changed diff lines + extracted identifiers/keys.

### 4.5 Output
- `neighbors[]`: chunk metadata, excerpt, scores, and a rationale.
- Mark every neighbor as `uncorroborated` by default.

---

## 5) Tool 4 — Temporal Coupling (`get_historical_coupling`)

### 5.1 Goal
Mine Git history to find files that co-change with the changed file(s).

### 5.2 Implementation
1. Parse `git log --name-status -M` in a bounded window.
2. Normalize paths, filter noise (merges, mega-commits, generated files).
3. Handle renames (at least `target_follow`).
4. Compute coupling weights (default: conditional probability with commit-size normalization).
5. Return top-K coupled files + example commits as evidence.

### 5.3 Output
- `targets[]`: target file + aliases + support counts
- `couplings[]`: coupled file + weight + support + evidence commits

---

## 6) Tool 5 — Test Impact Analyzer (`get_covering_tests`)

### 6.1 Goal
Return a **ranked minimal set of tests** likely to cover impacted nodes.

### 6.2 Implementation (static-first)
1. Discover tests (pytest config if present; else conventions).
2. Build module index (module name ↔ file path).
3. Build import graph (module → imported modules) with evidence.
4. For each test file, parse AST to extract:
   - imported modules/symbols
   - test nodeids (pytest functions, unittest TestCase methods)
   - lightweight reference signals (Names/Attributes/String literals)
5. Map impacted nodes to match keys:
   - impacted module, symbol names, impacted file
   - for field changes, include field key string (lower weight)
6. Rank tests deterministically using:
   - direct imports/from-imports (high)
   - transitive imports (bounded depth)
   - symbol references within tests (medium)
   - weak literal-only matches (low)
7. Output ranked list with evidence refs.

### 6.3 Optional dynamic enhancement
Chosen for v1:
- Provide **optional coverage mode** if explicitly enabled and repo runnable:
- run focused subset under `coverage.py` to confirm real coverage.
- treat this as additional evidence, not as a required dependency.

---

## 7) Orchestrator (OpenCode driver) — end-to-end flow

### 7.1 Normalize inputs
- Parse NL intent → derived `ChangeSpec` (class/entity/operation/field path).
- Parse unified diff → changed files + key identifiers + potential anchors.
- Combine with user-provided anchors.

### 7.2 Tool call plan (typical)
- Always: Tool 1 on changed files (+ small neighborhood if needed).
- Conditional:
  - Tool 2 if field/schema/validation change + entry point.
  - Tool 4 if `.git` exists.
  - Tool 5 if tests exist.
  - Tool 3 always (cheap) or only when confidence is medium/low (configurable).

### 7.3 Evidence merge + pruning
- Merge all candidates into a single evidence set.
- Prune rules:
  - drop low-confidence structural edges unless they match the changed field/path.
  - never promote semantic neighbors to “impacted” without Tool 1/2 corroboration.
- Assign:
  - `impact_risk` (breaking/behavior/unknown)
  - `impact_surface` (api/business/data/contract/tests/docs/unknown)

### 7.4 Render Markdown report
Fill [docs/REPORT_TEMPLATE.md](REPORT_TEMPLATE.md) sections and include:
- evidence appendix: `query_id`s
- assumptions/limitations: especially for NL-only mode

---

## 8) Hackathon build order (fastest path)

1. MCP server skeleton + envelopes + SQLite cache
2. Tool 1 (nodes + imports + calls + inherits; references optional)
3. Orchestrator merge/prune + report renderer
4. Tool 2 (FastAPI route discovery + field read-site detection)
5. Tool 5 (static test ranking)
6. Tool 4 (git coupling)
7. Tool 3 (BM25 first; embeddings optional)
8. Determinism hardening + demo scenarios
