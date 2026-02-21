# Demo E2E Blast Radius Report

Date: 2026-02-22  
Repository: `demo_target_repo`  
Workflow: `blast-radius-workflow` skill (Tool 1 → Tool 5)

## 1) Scope and normalized inputs

- **Intent:** Rename `account_id` to `customer_id` in order creation flow.
- **Anchor:** `symbol:app/api/orders.py:create_order`
- **Diff basis:**

```diff
diff --git a/app/api/orders.py b/app/api/orders.py
--- a/app/api/orders.py
+++ b/app/api/orders.py
@@
-    required = ["order_id", "account_id", "amount_cents"]
+    required = ["order_id", "customer_id", "amount_cents"]
@@
-        account_id=payload["account_id"],
+        customer_id=payload["customer_id"],
```

## 2) Setup checks

- Blast Radius MCP tools were available.
- `repo_root` resolved to `demo_target_repo`.
- Target paths were repo-relative in tool inputs.
- `.git` history exists (5 commits), so temporal coupling was eligible.
- Tests exist (`tests/test_orders.py`), so test impact was eligible.

## 3) Tool execution summary

### Tool 1 — `get_ast_dependencies` (always)

- **Status:** Success
- **Target files:** 4
- **Parsed OK:** 4
- **Nodes:** 13
- **Edges:** 107
- **Key structural evidence:**
  - `app.api.orders.create_order` calls `validate_payload` and `charge_customer`.
  - `Order` model and `tests/test_orders.py` are directly linked by import/reference graph.

### Tool 2 — `trace_data_shape` (conditional for field/API changes)

- **Status:** Success
- **Changed field:** `Order.account_id`
- **Entry point resolved:** `symbol:app/api/orders.py:create_order` (high confidence)
- **Read sites found:** 2
  1. `app/api/orders.py` line 20, `payload["account_id"]`, `if_renamed=true`
  2. `app/api/orders.py` line 23, `order.account_id`, `if_renamed=true`
- **Write sites:** 0
- **Diagnostics:** none

### Tool 3 — `find_semantic_neighbors` (always)

- **Status:** Success (with fallback)
- **Retrieval mode:** `bm25_fallback`
- **Top neighbors:** `create_order`, `get_order`, `validate_payload`, and related tests.
- **Diagnostics:** `semantic_provider_unavailable` in MCP runtime for this call.
- **Interpretation per skill:** semantic-only hits are suggestive and treated as unknown-risk corroboration unless supported by structural tools.

### Tool 4 — `get_historical_coupling` (conditional)

- **Status:** Success
- **History stats:** 5 commits scanned/used
- **Top coupling evidence:**
  - `app/api/orders.py` ↔ `tests/test_orders.py` (weight 1.0, support 4)
  - `app/api/orders.py` ↔ `app/services/billing.py` (weight 0.7071, support 3)
  - `app/models.py` ↔ `app/api/orders.py` (weight 1.0, support 2)
- **Diagnostics:** `low_history_support` (small history window size in practice)

### Tool 5 — `get_covering_tests` (conditional)

- **Status:** Success
- **Tests selected:** 3 / 3 considered
- **High-confidence tests:** 3
- **Prioritized tests:**
  1. `tests/test_orders.py::test_create_order_and_lookup`
  2. `tests/test_orders.py::test_create_order_rejects_non_positive_amount`
  3. `tests/test_orders.py::test_create_order_requires_fields`

## 4) Merged impact report

| Impact item | Risk | Confidence | Evidence summary |
|---|---|---|---|
| `app/api/orders.py:create_order` | **high** | **high** | Tool 1 call graph + Tool 2 direct read sites with rename breakage flags |
| `app/api/orders.py:validate_payload` | **high** | **high** | Tool 1 + field requirement list tied to renamed payload key |
| `app/models.py:Order.account_id` | **high** | **medium** | Tool 1 model dependency + Tool 4 co-change support |
| `app/services/billing.py:charge_customer` | **medium** | **medium** | Tool 1 downstream usage + Tool 4 coupling with orders |
| `tests/test_orders.py` | **high** | **high** | Tool 5 ranked all tests + Tool 4 strongest coupling |

## 5) Prioritized tests run

Executed in Tool 5 priority order:

```bash
pytest -q \
  tests/test_orders.py::test_create_order_and_lookup \
  tests/test_orders.py::test_create_order_rejects_non_positive_amount \
  tests/test_orders.py::test_create_order_requires_fields
```

Result: **all 3 tests passed**.

## 6) Facts, assumptions, limitations

### Facts

- Structural and lineage tools (Tool 1 + Tool 2) provided direct, concrete evidence of rename-sensitive callsites.
- Historical coupling and test impact consistently ranked `tests/test_orders.py` as top validation target.

### Assumptions

- The proposed rename includes payload key updates and model/usage propagation, not only surface string replacement.

### Limitations

- Tool 3 used BM25 fallback in this MCP invocation context; semantic evidence was treated as suggestive.
- Tool 4 reported low history support due small commit count, so coupling weights are informative but less stable.

## 7) Conclusion

The end-to-end workflow executed successfully and produced deterministic, evidence-backed blast radius results for the rename scenario. The highest-risk breakage zone is the order creation path and associated tests, with immediate validation focus on `tests/test_orders.py`.