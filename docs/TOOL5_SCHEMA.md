# Tool 5 — Test Impact Analyzer (v1) JSON Contract

This document defines the stable JSON contract for Tool 5: **Test Impact Analyzer**.

- Tool name: `get_covering_tests`
- Purpose: produce a ranked, minimal test set for impacted nodes.
- Constraint: deterministic ranking with explicit evidence reasons.

---

## Request envelope

```json
{
  "schema_version": "v1",
  "repo_root": ".",
  "inputs": {
    "impacted_nodes": [
      {
        "file": "app/api/orders.py",
        "symbol": "create_order",
        "kind": "function"
      }
    ],
    "options": {
      "max_tests": 10,
      "include_transitive": true,
      "transitive_depth": 2,
      "include_literal_field_matches": true,
      "coverage_mode": "off"
    }
  },
  "anchors": [],
  "diff": "",
  "options": {
    "timeout_ms": 20000
  }
}
```

### `inputs` fields

#### `impacted_nodes[]`

- `file` (required, string)
- `symbol` (optional, string)
- `kind` (optional): `module | class | function | method | field`

#### `options`

- `max_tests` (integer `1..200`, default `10`)
- `include_transitive` (boolean, default `true`)
- `transitive_depth` (integer `0..5`, default `2`)
- `include_literal_field_matches` (boolean, default `true`)
- `coverage_mode`: `off | optional` (default `off`)

---

## Response envelope

```json
{
  "schema_version": "v1",
  "tool_name": "get_covering_tests",
  "run_id": "sha256(...)",
  "query_id": "sha256(...)",
  "repo_fingerprint": {
    "git_head": "abc123",
    "dirty": false,
    "fingerprint_hash": "sha256(...)"
  },
  "cached": false,
  "timing_ms": 145,
  "result": {
    "tests": [],
    "unmatched_impacts": [],
    "selection_stats": {
      "tests_considered": 120,
      "tests_selected": 8,
      "high_confidence": 4
    },
    "diagnostics": []
  },
  "errors": []
}
```

---

## `result` schema

### `tests[]`

- `test_id` (string)
- `nodeid` (string)
- `file` (string)
- `score` (number `0..1`)
- `rank` (integer, contiguous from 1)
- `confidence`: `high | medium | low`
- `reasons[]`:
  - `type`:
    - `direct_import`
    - `from_import_symbol`
    - `transitive_import`
    - `symbol_reference`
    - `field_literal_match`
    - `coverage_confirmation`
  - `evidence` (string)

### `unmatched_impacts[]`

- `file` (string)
- `symbol` (string, optional)
- `reason`:
  - `no_test_reference`
  - `test_discovery_empty`
  - `mapping_ambiguous`

### `selection_stats`

- `tests_considered` (integer)
- `tests_selected` (integer)
- `high_confidence` (integer)

### `diagnostics[]`

- `severity`: `info | warning | error`
- `code`:
  - `tests_not_found`
  - `test_parse_error`
  - `coverage_unavailable`
  - `selection_truncated`
- `message` (string)

---

## Determinism requirements

1. Fixed scoring weights and depth policy.
2. Stable sort: `(score desc, file asc, nodeid asc)`.
3. Deterministic rank assignment after sorting.
