# Tool 4 — Temporal Coupling (v1) JSON Contract

This document defines the stable JSON contract for Tool 4: **Temporal Coupling**.

- Tool name: `get_historical_coupling`
- Source: Git history (read-only)
- Purpose: identify files that co-change with target files.

---

## Request envelope

```json
{
  "schema_version": "v1",
  "repo_root": ".",
  "inputs": {
    "file_paths": [
      "app/api/orders.py"
    ],
    "options": {
      "max_files": 20,
      "window_commits": 500,
      "follow_renames": true,
      "exclude_merges": true,
      "max_commit_size": 200
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

- `file_paths` (required, array[string], min 1)
- `options` (optional):
  - `max_files` (integer `1..200`, default `20`)
  - `window_commits` (integer `1..20000`, default `500`)
  - `follow_renames` (boolean, default `true`)
  - `exclude_merges` (boolean, default `true`)
  - `max_commit_size` (integer `1..5000`, default `200`)

---

## Response envelope

```json
{
  "schema_version": "v1",
  "tool_name": "get_historical_coupling",
  "run_id": "sha256(...)",
  "query_id": "sha256(...)",
  "repo_fingerprint": {
    "git_head": "abc123",
    "dirty": false,
    "fingerprint_hash": "sha256(...)"
  },
  "cached": false,
  "timing_ms": 260,
  "result": {
    "targets": [],
    "couplings": [],
    "history_stats": {
      "commits_scanned": 500,
      "commits_used": 378,
      "renames_followed": 4
    },
    "diagnostics": []
  },
  "errors": []
}
```

---

## `result` schema

### `targets[]`

- `file` (string)
- `aliases` (array[string])
- `support_commits` (integer)

### `couplings[]`

- `target_file` (string)
- `coupled_file` (string)
- `weight` (number `0..1`)
- `support` (integer)
- `example_commits[]`:
  - `sha` (string)
  - `date` (RFC3339 string)
  - `message` (string)

### `history_stats`

- `commits_scanned` (integer)
- `commits_used` (integer)
- `renames_followed` (integer)

### `diagnostics[]`

- `severity`: `info | warning | error`
- `code`:
  - `git_history_unavailable`
  - `low_history_support`
  - `target_not_in_history`
  - `history_window_truncated`
- `message` (string)

---

## Determinism requirements

1. Stable path normalization before aggregation.
2. Stable ranking sort: `(weight desc, support desc, coupled_file asc)`.
3. Deterministic rounding for `weight` representation.
