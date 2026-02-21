# Tool 1 — AST Structural Engine (v1) JSON Contract

This document defines the **stable JSON schema** for Tool 1: **AST Structural Engine**.

Tool 1 provides **hard structural evidence** for the blast-radius system: modules/classes/functions/methods plus edges for imports, calls, inheritance, and references.

- Language scope (v1): **Python only**
- Evidence-first: every edge must include a source location (and optional snippet) so the orchestrator can cite evidence.
- Deterministic + cacheable: includes per-file hashes.

---

## Tool name

`get_ast_dependencies`

## Request envelope

```json
{
  "schema_version": "v1",
  "repo_root": ".",
  "inputs": {
    "target_files": ["relative/path/to/file.py"],
    "options": {
      "include_references": true,
      "include_import_edges": true,
      "include_call_edges": true,
      "include_inheritance_edges": true,
      "max_snippet_chars": 240,
      "resolve_imports": true,
      "resolve_calls": true,
      "python_version": "3.11",
      "parse_mode": "python_ast"
    }
  }
}
```

### `inputs` fields

- `target_files` (required): list of repo-relative file paths to analyze.
- `options` (optional): configuration flags.
  - `parse_mode`: `python_ast | tree_sitter` (v1 implementations may support only `python_ast` and still be schema-compliant).

### Current runtime notes (2026-02-21)

- `parse_mode="tree_sitter"` falls back to `python_ast` with a warning diagnostic when `tree_sitter` is unavailable.
- `resolution.status` supports `ambiguous` in schema, but current Tool 1 runtime primarily emits `resolved` or `unresolved` for edges.
- Duplicate qualified names are surfaced as diagnostics with `code="ambiguous_symbol"`.
- `Position.offset` is best-effort and commonly remains `-1` in current output.

---

## Response envelope

```json
{
  "schema_version": "v1",
  "tool_name": "get_ast_dependencies",
  "run_id": "sha256(...)",
  "query_id": "sha256(...)",
  "repo_fingerprint": {
    "git_head": "abc123",
    "dirty": false,
    "fingerprint_hash": "sha256(...)"
  },
  "cached": false,
  "timing_ms": 842,
  "result": {
    "language": "python",
    "repo_root": ".",
    "files": [
      {
        "path": "relative/path/to/file.py",
        "sha256": "hex",
        "size_bytes": 1234,
        "parse_status": "ok",
        "syntax_error": null
      }
    ],
    "nodes": [
      {
        "id": "sym_...",
        "kind": "module",
        "name": "file",
        "qualified_name": "pkg.subpkg.file",
        "file": "relative/path/to/file.py",
        "range": {
          "start": {"line": 1, "col": 0, "offset": 0},
          "end": {"line": 120, "col": 0, "offset": 3456}
        },
        "signature": null,
        "decorators": [],
        "bases": [],
        "docstring": null,
        "exports": [],
        "attributes": {
          "is_async": false,
          "is_generator": false,
          "is_property": false
        }
      }
    ],
    "edges": [
      {
        "id": "edge_...",
        "type": "calls",
        "source": "sym_caller",
        "target": "sym_callee",
        "target_ref": {
          "kind": "symbol",
          "qualified_name": "pkg.mod.func",
          "file": "relative/path/to/mod.py",
          "symbol_id": "sym_..."
        },
        "range": {
          "start": {"line": 10, "col": 4, "offset": 120},
          "end": {"line": 10, "col": 20, "offset": 136}
        },
        "confidence": 0.92,
        "resolution": {
          "status": "resolved",
          "strategy": "local_scope",
          "candidates": []
        },
        "snippet": "result = parse_user_id(value)",
        "metadata": {
          "call": {"callee_text": "parse_user_id", "arg_count": 1},
          "import": null,
          "inheritance": null,
          "reference": null
        }
      }
    ],
    "diagnostics": [
      {
        "file": "relative/path/to/file.py",
        "severity": "error",
        "message": "SyntaxError: invalid syntax",
        "range": {"start": {"line": 12, "col": 0, "offset": 220}, "end": {"line": 12, "col": 10, "offset": 230}}
      }
    ],
    "stats": {
      "target_files": 3,
      "parsed_ok": 3,
      "parsed_error": 0,
      "nodes": 120,
      "edges": 560,
      "duration_ms": 842,
      "cache": {"hits": 2, "misses": 1}
    }
  },
  "errors": []
}
```

### Envelope fields

- `schema_version` (required): `"v1"`.
- `tool_name` (required): always `get_ast_dependencies`.
- `run_id` (required): deterministic hash ID for orchestrator run.
- `query_id` (required): deterministic hash ID for this tool call.
- `repo_fingerprint` (required): repo state metadata/hash.
- `cached` (required): cache hit indicator.
- `timing_ms` (required): execution duration.
- `result` (required): tool-specific payload (defined below).
- `errors` (optional): structured execution errors.

---

## `result.files[]`

- `path` (required): repo-relative path.
- `sha256` (required): file content hash.
- `size_bytes` (required)
- `parse_status` (required): `ok | error`.
- `syntax_error` (required): `null` or a compact message string.

---

## `result.nodes[]`

Node `kind` is one of:
- `module`
- `class`
- `function`
- `method`

Fields:
- `id` (required): deterministic identifier derived from symbol identity/span.
- `kind` (required)
- `name` (required): short name.
- `qualified_name` (required): fully qualified dotted name where possible.
- `file` (required): repo-relative path.
- `range` (required): start/end positions.
- `signature` (optional): for functions/methods, a best-effort signature string.
- `decorators` (required): list of decorator expressions as strings.
- `bases` (required): for classes only; list of base class expressions as strings.
- `docstring` (optional)
- `exports` (required): list of exported names if determinable (best-effort).
- `attributes` (required): booleans; non-applicable values should be `false`.

`range.start|end` positions:
- `line` is 1-based
- `col` is 0-based
- `offset` is 0-based UTF-8 byte offset (best-effort; may be `-1` if unavailable)

---

## `result.edges[]`

Edge `type` is one of:
- `imports`
- `calls`
- `inherits`
- `references`

Fields:
- `id` (required)
- `type` (required)
- `source` (required): `nodes[].id`
- `target` (required): `nodes[].id` when resolved; may be `""` when unresolved
- `target_ref` (required): structured target reference even if unresolved
  - `kind`: `symbol | module | unresolved`
  - `qualified_name`: dotted name if known else `""`
  - `file`: best-effort else `""`
  - `symbol_id`: best-effort else `""`
- `range` (required): location of the syntactic evidence that created the edge
- `confidence` (required): float in `[0.0, 1.0]`
- `resolution` (required): how the target was resolved
  - `status`: `resolved | unresolved | ambiguous`
  - `strategy`: `local_scope | import_table | attribute_chain | class_method | builtin | unknown`
  - `candidates`: for ambiguous resolution, list of candidate `target_ref` objects
- `snippet` (optional): truncated code snippet at the evidence location
- `metadata` (required): typed metadata buckets (non-applicable set to `null`)

`metadata` shapes:
- For `type="imports"`: `metadata.import = {"module": "...", "name": "...", "alias": "...", "level": 0}`
- For `type="calls"`: `metadata.call = {"callee_text": "...", "arg_count": 0}`
- For `type="inherits"`: `metadata.inheritance = {"base_text": "..."}`
- For `type="references"`: `metadata.reference = {"name": "...", "context": "load|store|del"}`

---

## `result.diagnostics[]`

- `file` (required)
- `severity` (required): `info | warning | error`
- `message` (required)
- `range` (optional)

---

## `result.stats`

- `target_files` (required)
- `parsed_ok` (required)
- `parsed_error` (required)
- `nodes` (required)
- `edges` (required)
- `duration_ms` (required)
- `cache` (required): `{"hits": int, "misses": int}`
