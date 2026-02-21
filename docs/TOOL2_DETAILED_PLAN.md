# Tool 2 Detailed Plan — Data Lineage Engine

## Tool identity

- Name: `trace_data_shape`
- Goal: high-precision field/path impact tracing for API/schema/validation changes.
- Canonical v1 input style: `field_path + entry_points[]`.

---

## 1) Input contract (inside envelope `inputs`)

```json
{
  "field_path": "OrderRequest.user_id",
  "entry_points": ["route:POST /orders", "symbol:app/api/orders.py:create_order"],
  "options": {
    "direction": "request",
    "max_call_depth": 2,
    "max_sites": 200,
    "include_writes": true
  }
}
```

---

## 2) Output contract (inside envelope `result`)

- `changed_field`: canonicalized field identity
- `entry_points_resolved[]`
- `read_sites[]`
- `write_sites[]`
- `validations[]`
- `transforms[]`
- `summary`

### per-site required fields

- `location` (file + range)
- `enclosing_symbol_id` (links to Tool 1 symbols)
- `access_pattern` (`attribute|dict_subscript|get_call|model_field|serializer`)
- `breakage` (`if_removed`, `if_renamed`, optional `if_type_changed`)
- `confidence`
- `evidence_snippet`

---

## 3) Internal implementation plan

### index phase (cached)

1. Build route index from FastAPI/Starlette decorators and `add_api_route`.
2. Build model index for Pydantic models and field aliases.
3. Build validator index (`validator`, `field_validator`, `model_validator`).
4. Build span-to-symbol mapping using Tool 1 graph.

### query phase

1. Resolve `entry_points[]` to handler symbols.
2. Canonicalize `field_path` with alias rules.
3. Scan handler and callees (depth-bounded) for:
   - attribute reads (`obj.user_id`)
   - dict reads (`payload["user_id"]`, `.get("user_id")`)
   - writes / transform steps / casts
   - validation checks and constraints
4. Emit structured sites and confidence.

---

## 4) Caching and determinism

### caching

- route/model/validator indexes keyed by repo fingerprint + tool version
- query result keyed by canonical `(field_path, sorted(entry_points), options)`

### determinism

- fixed traversal order by `(file, line, col)`
- deterministic alias-precedence rules
- stable site IDs from `(field, symbol, span, pattern)` hash

---

## 5) Failure handling

- no usable entry point: return limitation code `needs_anchor` and empty lineage lists.
- ambiguous alias/model path: emit low confidence sites and mark ambiguity reason.
- unsupported framework pattern: include diagnostic and continue partial extraction.

---

## 6) Trigger policy

Run Tool 2 when:

1. `ChangeSpec` indicates API/schema/field/validation change, and
2. at least one route/symbol anchor is available.

If NL-only without entry points, do not run global lineage scan in v1.

---

## 7) Acceptance checklist (MVP)

1. Detects read sites for `attribute`, `dict_subscript`, and `.get("field")`.
2. Resolves at least one route anchor to handler symbol in FastAPI repo.
3. Emits breakage flags for removed/renamed field scenarios.
4. Links findings to Tool 1 symbol IDs.

---

## 8) Stretch improvements

- nested model propagation beyond depth-2
- support for additional web frameworks
- richer type-change propagation confidence
