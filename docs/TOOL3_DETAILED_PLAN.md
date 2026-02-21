# Tool 3 Detailed Plan — Semantic Neighbor Search

## Tool identity

- Name: `find_semantic_neighbors`
- Goal: identify unknown-risk zones with conceptual similarity.
- Constraint: semantic results are **non-authoritative** until corroborated by Tool 1 or Tool 2.

---

## 1) Input contract (inside envelope `inputs`)

```json
{
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
}
```

---

## 2) Output contract (inside envelope `result`)

- `neighbors[]`
- `retrieval_mode` (`embedding_primary|bm25_fallback`)
- `index_stats`

### neighbor fields

- `file`, `symbol`, `span`
- `score`
- `rationale_snippet`
- `method` (`openai_pinecone|bm25`)
- `uncorroborated = true`

---

## 3) Retrieval strategy (locked)

### primary path

- OpenAI embeddings
- Pinecone vector index

### fallback path

- BM25 lexical retrieval from local code chunks

Fallback must be automatic when:

- credentials are missing
- provider is unavailable
- vector index is absent/unhealthy

---

## 4) Internal implementation plan

### index build/update

1. Chunk Python code by function/method.
2. Store chunk metadata (file, symbol, span, hash).
3. Upsert embeddings to Pinecone for changed chunks.
4. Maintain local BM25 corpus in SQLite/FTS for fallback.

### query flow

1. Build query text from intent + diff signals + key identifiers.
2. Try embedding retrieval (`top_k`).
3. If unavailable/fails, switch to BM25.
4. Deduplicate and stable-sort neighbors.
5. Mark all results `uncorroborated=true`.

---

## 5) Caching and determinism

### caching

- chunk artifact cache by `file_hash + symbol + span`
- query cache by canonical `(query_text, scope, options, repo_fingerprint)`

### determinism

- deterministic chunk boundaries
- deterministic tie-break: `(score desc, file asc, span.start asc)`
- deterministic fallback decision order

---

## 6) Failure handling

- provider failure: return BM25 result with warning code `semantic_provider_unavailable`.
- empty corpus: return empty neighbors with warning `semantic_index_empty`.
- score threshold too strict: return top fallback item set with threshold note.

---

## 7) Acceptance checklist (MVP)

1. Produces semantically related neighbors with score + snippet.
2. Works with OpenAI+Pinecone in normal mode.
3. Automatically degrades to BM25 without crashing.
4. Every item is explicitly non-authoritative (`uncorroborated=true`).

---

## 8) Stretch improvements

- reranking with a cross-encoder
- semantic cluster deduping
- query intent decomposition for better recall
