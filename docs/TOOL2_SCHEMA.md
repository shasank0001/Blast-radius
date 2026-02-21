# Tool 2 — Data Lineage Engine (v1) JSON Contract

This document defines the stable JSON contract for Tool 2: **Data Lineage Engine**.

- Tool name: `trace_data_shape`
- Scope (v1): Python repositories, FastAPI/Starlette + Pydantic oriented heuristics.
- Contract style: MCP envelope + tool-specific payload under `inputs` and `result`.

---

## Request envelope

```json
{
  "schema_version": "v1",
  "repo_root": ".",
  "inputs": {
    "field_path": "OrderRequest.user_id",
    "entry_points": [
      "route:POST /orders",
      "symbol:app/api/orders.py:create_order"
    ],
    "options": {
      "direction": "request",
      "max_call_depth": 2,
      "max_sites": 200,
      "include_writes": true
    }
  },
  "anchors": [
    "route:POST /orders"
  ],
  "diff": "@@ ...",
  "options": {
    "timeout_ms": 30000
  }
}
```

### `inputs` fields

- `field_path` (required, string): canonical field target.
  - examples: `OrderRequest.user_id`, `request.user_id`
- `entry_points` (required, array[string], min 1): route/symbol anchors.
  - route format: `route:METHOD /path`
  - symbol format: `symbol:path/to/file.py:symbol_name`
- `options` (optional):
  - `direction`: `request | response | both` (default `both`)
  - `max_call_depth`: integer `0..5` (default `2`)
  - `max_sites`: integer `1..1000` (default `200`)
  - `include_writes`: boolean (default `true`)

---

## Response envelope

```json
{
  "schema_version": "v1",
  "tool_name": "trace_data_shape",
  "run_id": "sha256(...)",
  "query_id": "sha256(...)",
  "repo_fingerprint": {
    "git_head": "abc123",
    "dirty": false,
    "fingerprint_hash": "sha256(...)"
  },
  "cached": false,
  "timing_ms": 412,
  "result": {
    "changed_field": "OrderRequest.user_id",
    "entry_points_resolved": [
      {
        "anchor": "route:POST /orders",
        "handler_symbol_id": "sym_...",
        "location": {
          "file": "app/api/orders.py",
          "range": {
            "start": {"line": 21, "col": 0},
            "end": {"line": 43, "col": 0}
          }
        },
        "confidence": "high"
      }
    ],
    "read_sites": [],
    "write_sites": [],
    "validations": [],
    "transforms": [],
    "diagnostics": [],
    "stats": {
      "files_scanned": 12,
      "sites_emitted": 8,
      "truncated": false
    }
  },
  "errors": []
}
```

---

## `result` schema

### `entry_points_resolved[]`

- `anchor` (string)
- `handler_symbol_id` (string)
- `location` (Location)
- `confidence` (`high | medium | low`)

### `read_sites[]` / `write_sites[]`

Site object:

- `site_id` (string, deterministic)
- `field_path` (string)
- `location` (Location)
- `enclosing_symbol_id` (string)
- `access_pattern`:
  - `attribute`
  - `dict_subscript`
  - `dict_get`
  - `model_field`
  - `serializer`
- `breakage`:
  - `if_removed` (boolean)
  - `if_renamed` (boolean)
  - `if_type_changed` (boolean, optional)
- `confidence` (`high | medium | low`)
- `evidence_snippet` (string, optional)

### `validations[]`

- `validation_id` (string)
- `kind`:
  - `pydantic_field_constraint`
  - `pydantic_validator`
  - `custom_guard`
- `field_path` (string)
- `location` (Location)
- `enclosing_symbol_id` (string)
- `rule_summary` (string)
- `confidence` (`high | medium | low`)

### `transforms[]`

- `transform_id` (string)
- `kind`:
  - `rename`
  - `cast`
  - `defaulting`
  - `normalization`
- `from_field` (string, optional)
- `to_field` (string, optional)
- `from_type` (string, optional)
- `to_type` (string, optional)
- `location` (Location)
- `enclosing_symbol_id` (string)
- `confidence` (`high | medium | low`)

### `diagnostics[]`

- `severity`: `info | warning | error`
- `code`:
  - `needs_anchor`
  - `entry_point_unresolved`
  - `alias_ambiguous`
  - `lineage_truncated`
- `message` (string)
- `location` (Location, optional)

### `stats`

- `files_scanned` (integer)
- `sites_emitted` (integer)
- `truncated` (boolean)

---

## Common type: `Location`

```json
{
  "file": "path/to/file.py",
  "range": {
    "start": {"line": 10, "col": 4},
    "end": {"line": 10, "col": 26}
  }
}
```

Rules:

- `line` is 1-based.
- `col` is 0-based.

---

## Determinism requirements

1. Sort sites by `(file, start.line, start.col, site_id)`.
2. Keep stable IDs from content-derived hashes.
3. Emit explicit diagnostics instead of silent drops.
