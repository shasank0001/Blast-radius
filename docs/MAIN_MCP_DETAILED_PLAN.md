# Main MCP Detailed Plan (Hackathon v1, Python)

## 1) Scope and intent

This document defines the implementation-ready plan for the **main MCP server** and mandatory **minimal orchestrator boundary**.

### v1 scope lock

- Language: Python repositories only.
- Inputs: natural-language intent (required), anchors (optional but recommended), unified diff (optional but recommended).
- Tools: Tool 1..Tool 5 exposed by one MCP process.
- Output: evidence-backed Markdown blast-radius report.

### locked architecture decisions

1. `schema_version = "v1"` for all requests/responses.
2. `run_id` and `query_id` are deterministic hashes.
3. Tool 3 retrieval defaults to OpenAI + Pinecone with BM25 fallback.
4. Minimal orchestrator merge/prune is required in v1 (not optional).

---

## 2) System boundary

### MCP server responsibilities

- Register and execute tools deterministically.
- Validate request/response contracts.
- Compute repo fingerprint and stable IDs.
- Cache tool outputs in SQLite.
- Return structured evidence and structured failures.

### Orchestrator responsibilities (mandatory minimal)

- Normalize NL intent into derived `ChangeSpec`.
- Build tool-call plan from `ChangeSpec + anchors + diff`.
- Merge and prune tool evidence with explicit corroboration rules.
- Render report in the template shape.

---

## 3) Canonical MCP contract (envelope)

### Request envelope

```json
{
  "schema_version": "v1",
  "repo_root": "/abs/or/relative/path",
  "inputs": {},
  "anchors": [],
  "diff": "",
  "options": {}
}
```

### Response envelope

```json
{
  "schema_version": "v1",
  "tool_name": "get_ast_dependencies",
  "run_id": "sha256(...)",
  "query_id": "sha256(...)",
  "repo_fingerprint": {
    "git_head": "...",
    "dirty": false,
    "fingerprint_hash": "sha256(...)"
  },
  "cached": true,
  "timing_ms": 123,
  "result": {},
  "errors": []
}
```

### deterministic ID formulas

- `run_id = sha256("run" + schema_version + intent_norm + anchors_norm + diff_hash + repo_fingerprint_hash)`
- `query_id = sha256("query" + tool_name + canonical_request_json + repo_fingerprint_hash)`

### canonicalization rules

- UTF-8 only.
- Line endings normalized to `\n`.
- JSON keys sorted for hashing.
- Lists sorted where order is non-semantic.

---

## 4) Server module plan

```text
blast_radius_mcp/
  server.py
  settings.py
  logging.py
  ids.py
  schemas/
    common.py
    tool1_ast.py
    tool2_lineage.py
    tool3_semantic.py
    tool4_coupling.py
    tool5_tests.py
  validation/
    validate.py
  cache/
    sqlite.py
    keys.py
  repo/
    fingerprint.py
    io.py
  tools/
    tool1_ast_engine.py
    tool2_data_lineage.py
    tool3_semantic_neighbors.py
    tool4_temporal_coupling.py
    tool5_test_impact.py
  indices/
    semantic_index.py
orchestrator/
  normalize.py
  diff_parser.py
  merge_evidence.py
  report_render.py
```

---

## 5) Validation policy

Validation runs in two phases:

1. **Typed parse** (Pydantic v2): reject unknown fields by default.
2. **JSON schema check**: validate raw request and final response shape.

### failure behavior

- Return structured `errors[]` with `code`, `message`, `retryable`, and optional `location`.
- For partial tool failures, still return best-effort `result` with diagnostics.
- Never silently drop evidence.

---

## 6) SQLite cache and persistence

### cache tables

1. `runs`
   - `run_id` (PK)
   - `created_at`
   - `repo_root`
   - `repo_fingerprint_json`
   - `intent_norm`
   - `anchors_json`
   - `diff_hash`

2. `tool_results`
   - `cache_key` (PK)
   - `tool_name`
   - `query_id`
   - `run_id`
   - `repo_fingerprint_hash`
   - `request_json`
   - `response_json`
   - `timing_ms`
   - `created_at`

3. `artifacts` (optional)
   - `artifact_id` (PK)
   - `kind`
   - `repo_fingerprint_hash`
   - `path_or_blob`

### cache key

`cache_key = sha256(tool_name + schema_version + canonical_request_json + repo_fingerprint_hash + tool_impl_version)`

### pragmas

- WAL mode.
- `synchronous=NORMAL`.
- bounded cleanup policy by age and size.

---

## 7) Orchestrator minimal flow (required)

1. Normalize input into `ChangeSpec`.
2. Parse diff, infer changed files/symbol hints.
3. Build call plan:
   - Tool 1 always.
   - Tool 2 when API/schema/field/validation intent + entry points exist.
   - Tool 4 when `.git` exists.
   - Tool 5 when tests exist.
   - Tool 3 for unknown-zone discovery.
4. Merge all findings into candidate impacts.
5. Prune:
   - no semantic-only item may be promoted to direct impact.
   - low-confidence unresolved links require corroboration.
6. Assign risk/surface/confidence.
7. Render report with evidence IDs.

---

## 8) Observability and operations

### structured logs

Every tool call must log:

- `run_id`, `query_id`, `tool_name`
- `cached`, `timing_ms`
- `result_counts` (nodes/edges/sites/tests etc.)
- `error_count`

### telemetry targets

- tool P50/P95 latency
- cache hit ratio
- unresolved edge ratio (Tool 1)
- uncorroborated semantic ratio (Tool 3)
- report generation time

---

## 9) Security and safety constraints

- Source-only analysis: never import/execute user repo modules.
- Normalize and sandbox paths under `repo_root`.
- `git` calls use fixed argument lists (no shell interpolation).
- Snippets redacted/truncated by configured limit.

---

## 10) Definition of done

v1 is complete when:

1. MCP exposes all 5 tools with stable v1 envelopes.
2. Deterministic rerun on same input + repo state yields stable IDs and ordering.
3. Orchestrator produces report with required sections and evidence appendix.
4. API field-removal scenario shows concrete Tool 2 read-site breakage + Tool 5 tests.
5. Semantic-only hits remain in unknown risk zone unless corroborated.
