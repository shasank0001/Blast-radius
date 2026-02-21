# Tool 3 — Semantic Neighbor Search (v1) JSON Contract

This document defines the stable JSON contract for Tool 3: **Semantic Neighbor Search**.

- Tool name: `find_semantic_neighbors`
- Primary backend (v1): OpenAI embeddings + Pinecone.
- Fallback (v1): BM25 lexical retrieval.
- Governance rule: semantic hits are `uncorroborated=true` by default.

---

## Request envelope

```json
{
  "schema_version": "v1",
  "repo_root": ".",
  "inputs": {
    "query_text": "Remove user_id from POST /orders payload",
    "scope": {
      "paths": ["app/", "services/"],
      "globs": ["**/*.py"]
    },
    "options": {
      "top_k": 25,
      "min_score": 0.35,
      "mode": "auto"
    }
  },
  "anchors": [],
  "diff": "@@ ...",
  "options": {
    "timeout_ms": 20000
  }
}
```

### `inputs` fields

- `query_text` (required, string, min length 3)
- `scope` (optional):
  - `paths` (array[string])
  - `globs` (array[string])
- `options` (optional):
  - `top_k` (integer `1..200`, default `25`)
  - `min_score` (number `0..1`, default `0.35`)
  - `mode`: `auto | embedding | bm25` (default `auto`)

---

## Response envelope

```json
{
  "schema_version": "v1",
  "tool_name": "find_semantic_neighbors",
  "run_id": "sha256(...)",
  "query_id": "sha256(...)",
  "repo_fingerprint": {
    "git_head": "abc123",
    "dirty": false,
    "fingerprint_hash": "sha256(...)"
  },
  "cached": true,
  "timing_ms": 189,
  "result": {
    "retrieval_mode": "embedding_primary",
    "neighbors": [],
    "index_stats": {
      "chunks_total": 420,
      "chunks_scanned": 420,
      "backend": "openai_pinecone"
    },
    "diagnostics": []
  },
  "errors": []
}
```

---

## `result` schema

### `retrieval_mode`

- `embedding_primary`
- `bm25_fallback`

### `neighbors[]`

- `neighbor_id` (string, deterministic)
- `file` (string)
- `symbol` (string)
- `span`:
  - `start` `{line, col}`
  - `end` `{line, col}`
- `score` (number `0..1`)
- `method`: `openai_pinecone | bm25`
- `rationale_snippet` (string)
- `uncorroborated` (boolean, must be `true`)

### `index_stats`

- `chunks_total` (integer)
- `chunks_scanned` (integer)
- `backend` (`openai_pinecone | bm25`)

### `diagnostics[]`

- `severity`: `info | warning | error`
- `code`:
  - `semantic_provider_unavailable`
  - `vector_index_missing`
  - `semantic_index_empty`
  - `threshold_filtered_all`
- `message` (string)

---

## Determinism requirements

1. Stable chunking by function/method boundaries.
2. Stable ranking tie-break by `(score desc, file asc, span.start.line asc, span.start.col asc)`.
3. Always set `uncorroborated=true` in this tool output.
