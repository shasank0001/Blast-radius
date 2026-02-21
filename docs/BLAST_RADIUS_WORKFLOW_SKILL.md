# Blast Radius Workflow Skill (Agent + User)

Use this skill when you want an agent to answer: “If I make this change, what breaks?”

## Goal

Produce an evidence-backed blast radius report with:

- impacted files/symbols
- risk levels and confidence
- likely impacted tests
- assumptions and limitations

## Prerequisites

1. Blast Radius MCP server is installed from [blast_radius](../blast_radius).
2. MCP is configured in your client (VS Code/OpenCode) per [blast_radius/README.md](../blast_radius/README.md).
3. `BLAST_RADIUS_REPO_ROOT` points to the target repository.
4. Target file paths in tool inputs are repo-relative.

## Recommended User Prompt Format

Give the agent these 4 pieces:

1. **Intent**: what is changing
2. **Target area**: route/module/symbol
3. **Risk focus**: what breakage to prioritize
4. **Instruction**: explicitly use blast_radius tools

Example:

"Rename `user_id` to `account_id` in order creation flow. Focus on API payload breakage and impacted tests. Use blast_radius tools and return risk/confidence."

## Workflow (User-facing)

1. User gives natural-language change intent.
2. Agent calls Blast Radius MCP tools.
3. Agent merges tool evidence.
4. Agent returns a prioritized impact report.
5. User refines prompt and reruns as needed.

## Workflow (Agent internal)

### Phase 1: Scope the change

- Extract intent, operation (rename/remove/add/type change), and probable field/path.
- Collect optional anchors (route, symbol, file).
- Include unified diff if available for precision.

### Phase 2: Execute tool sequence

Run tools in this order:

1. `get_ast_dependencies` (always)
2. `trace_data_shape` (for API/field changes with entry points)
3. `find_semantic_neighbors` (always)
4. `get_historical_coupling` (when git history exists)
5. `get_covering_tests` (when tests exist)

### Phase 3: Merge and score

- Treat Tool 1 and Tool 2 as strongest structural evidence.
- Treat Tool 3 as suggestive unless corroborated.
- Use Tool 4 for co-change risk ranking.
- Use Tool 5 for test execution priority.

### Phase 4: Report

Return:

- top impacted files/symbols
- risk level per item (`high`/`medium`/`low`/`unknown`)
- confidence and short evidence notes
- recommended tests to run first
- assumptions/limitations

## Prompt Templates

### Template A: Rename field

"Rename `<old_field>` to `<new_field>` in `<route_or_module>`. Use blast_radius tools. Highlight read/write sites, validators/transforms, and covering tests."

### Template B: Remove field

"Remove `<field>` from `<API route or payload>`. Use blast_radius. Report breakage hotspots and test impact first."

### Template C: Type change

"Change `<field>` type from `<old_type>` to `<new_type>` in `<scope>`. Use blast_radius and identify validators, casts, and high-risk callers."

## Fast Troubleshooting

- No semantic embeddings: Tool 3 falls back to BM25 (expected if provider keys are missing).
- Weak temporal coupling: likely low commit history support.
- Empty Tool 2 result: add clear entry-point anchors (e.g., `POST /orders` or `symbol:...`).
- Over-broad results: provide diff or concrete file/symbol anchors.

## One-Call Orchestrator Option

For a single API call that runs plan + merge + report, use `run_blast_radius(...)` in [blast_radius/orchestrator/__init__.py](../blast_radius/orchestrator/__init__.py).

Minimal example:

```python
import asyncio
from orchestrator import run_blast_radius

async def main():
    report = await run_blast_radius(
        intent="Rename user_id to account_id in order creation flow",
        repo_root="/abs/path/to/target_repo",
        anchors=["symbol:app/api/orders.py:create_order", "POST /orders"],
        diff="",
    )
    print(report)

asyncio.run(main())
```

## Definition of Done (per run)

- At least one structural tool succeeded.
- Report includes impacts + risks + confidence + tests.
- Assumptions/limitations are explicit.
- User can choose immediate next actions (code edits/tests).
