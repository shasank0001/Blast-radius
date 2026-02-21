# Alignment Crosscheck Report (Detailed, v1)

## 1) Objective

Cross-check all planning artifacts for consistency across:

- Product requirements
- MCP architecture
- tool-level implementation plans
- reporting and evidence constraints

This report reflects final clarified decisions selected in planning.

---

## 2) Requirement-to-plan alignment matrix

| Requirement | Status | Where enforced |
|---|---|---|
| End-to-end blast radius report | Aligned | `MAIN_MCP_DETAILED_PLAN.md` (orchestrator flow + DoD) |
| Python-only v1 scope | Aligned | Main MCP + all Tool docs |
| Evidence-first impacts | Aligned | Main MCP merge/prune rules + Tool evidence fields |
| API-field precision via data lineage | Aligned | `TOOL2_DETAILED_PLAN.md` |
| Semantic neighbors as unknown zones | Aligned | `TOOL3_DETAILED_PLAN.md` + main pruning rules |
| Historical coupling suggestions | Aligned | `TOOL4_DETAILED_PLAN.md` |
| Ranked tests to run | Aligned | `TOOL5_DETAILED_PLAN.md` |
| Deterministic IDs and caching | Aligned | Main MCP deterministic formulas + cache schema |
| NL-only graceful degradation | Aligned | Main + Tool2/Tool4/Tool5 failure modes |

---

## 3) Resolved ambiguities

### A) Semantic backend conflict

- **Final decision**: OpenAI + Pinecone primary, BM25 fallback.
- **Applied in docs**: Tool 3 detailed plan and main MCP.

### B) Tool 2 input shape mismatch

- **Final decision**: canonical `field_path + entry_points[]`.
- **Applied in docs**: Tool 2 detailed plan and main orchestration trigger rules.

### C) ID/schema inconsistency

- **Final decision**: `schema_version = v1`, deterministic hash `run_id/query_id`.
- **Applied in docs**: main MCP contract section.

### D) Orchestrator optionality

- **Final decision**: minimal orchestrator is mandatory in v1.
- **Applied in docs**: main MCP scope + DoD.

---

## 4) Remaining contract gaps to close

These are not design blockers anymore, but documentation/contract tasks:

1. Add explicit global error code registry (`needs_anchor`, `git_history_unavailable`, `tests_not_found`, etc.) in one shared schema/common doc.
2. Add explicit confidence rubric for direct-impact classification and report scoring.

---

## 5) Cross-tool consistency checks

### data handoff compatibility

- Tool 1 symbol IDs are referenced by Tool 2 findings.
- Tool 1 + Tool 2 corroborate direct impacts.
- Tool 3 feeds unknown-risk zones unless corroborated.
- Tool 4/Tool 5 enrich actions and validation priorities.

### deterministic behavior checks

- all tools use canonical request hash keys.
- all tools define deterministic tie-break order.
- all tools return structured errors instead of silent failures.

---

## 6) Execution readiness status

Overall status: **Ready for implementation kickoff**.

Recommended first sprint order:

1. main MCP envelope + validation + cache
2. Tool 1
3. orchestrator merge/prune + report render
4. Tool 2
5. Tool 5
6. Tool 4
7. Tool 3
