# Tool 5 Detailed Plan — Test Impact Analyzer

## Tool identity

- Name: `get_covering_tests`
- Goal: return a ranked minimal test set likely to validate impacted nodes.
- Role: actionability layer for engineers.

---

## 1) Input contract (inside envelope `inputs`)

```json
{
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
}
```

---

## 2) Output contract (inside envelope `result`)

- `tests[]`
- `unmatched_impacts[]`
- `selection_stats`

### test item fields

- `test_id`
- `nodeid`
- `file`
- `score`
- `rank`
- `reasons[]` (typed evidence)
- `confidence`

---

## 3) Internal implementation plan

1. Discover tests from pytest config or conventions.
2. Parse test files and build import/reference index.
3. Build lightweight module graph for transitive mapping.
4. Score each test against impacted nodes:
   - direct import/reference (high)
   - transitive module links (medium)
   - literal field-key hints (low)
5. Rank deterministically and trim to `max_tests`.
6. Return explicit reasons for each selected test.

---

## 4) Caching and determinism

### caching

- test AST/index artifacts keyed by test file hash
- result cache keyed by impacted node signature + options + repo fingerprint

### determinism

- fixed scoring weights from config
- stable sort `(score desc, file asc, nodeid asc)`
- contiguous rank generation

---

## 5) Failure handling

- no tests found: empty `tests[]` with warning `tests_not_found`.
- parse failures in some tests: skip with diagnostics; continue.
- unmatched impacts: list in `unmatched_impacts[]` explicitly.

---

## 6) Acceptance checklist (MVP)

1. Produces ranked tests for impacted modules/symbols.
2. Limits output to <= configured max (default 10).
3. Provides evidence reasons per selected test.
4. Deterministic order for identical input.

---

## 7) Optional dynamic mode

- `coverage_mode=optional` may run focused coverage when repo is runnable.
- dynamic evidence augments static scoring but does not replace it.
