---
name: blast-radius-workflow
description: Evidence-first workflow for Blast Radius impact analysis using MCP tools and orchestrator. Use when users ask what might break from code changes (rename, remove, add, type change), need impacted files/symbols/tests, or want risk and confidence summaries for a target repository.
---

# Blast Radius Workflow

Use this workflow to produce a deterministic, evidence-backed blast radius result.

## Execute setup checks

1. Confirm Blast Radius MCP server is available.
2. Confirm `BLAST_RADIUS_REPO_ROOT` or request `repo_root` points to the target repository.
3. Confirm target paths are repo-relative inside tool inputs.

If any setup check fails, stop and ask only for the missing input.

## Collect and normalize inputs

1. Capture `intent` in one sentence.
2. Capture optional `anchors` (file, symbol, route).
3. Capture optional unified `diff`.
4. Normalize route-like anchors to `route:METHOD /path`.
5. Keep symbol anchors in `symbol:...` form when available.

If no anchors exist, infer minimal anchors from intent and changed files.

## Run tool sequence

Run in this order and keep outputs isolated by tool name.

1. `get_ast_dependencies` (always)
   - Build `target_files` from diff changed files and file anchors.
2. `trace_data_shape` (conditional)
   - Run only for API/field changes with both `field_path` and `entry_points`.
3. `find_semantic_neighbors` (always)
   - Use intent-derived `query_text`; scope to target files when possible.
4. `get_historical_coupling` (conditional)
   - Run only when `.git` history exists and target files are known.
5. `get_covering_tests` (conditional)
   - Run only when tests exist and impacted nodes can be formed.

On validation failure, fix shape errors once and retry once.

## Merge evidence with strict weighting

1. Treat Tool 1 and Tool 2 as primary structural evidence.
2. Treat Tool 3 as suggestive; if uncorroborated, mark as unknown risk zone.
3. Use Tool 4 to rank likelihood via co-change support.
4. Use Tool 5 to rank test execution order.
5. Explicitly separate facts, assumptions, and limitations.

## Return report format

Return a concise report with:

1. Top impacted files/symbols
2. Risk per item: `high | medium | low | unknown`
3. Confidence per item: `high | medium | low`
4. Evidence summary (which tools support each item)
5. Prioritized tests to run first
6. Assumptions and limitations

## Escalation rules

1. If only semantic evidence exists, do not over-assert breakage.
2. If diff is missing and results are broad, request a diff or concrete anchors.
3. If Tool 2 yields no sites for field changes, request explicit entry points.

## Load references when needed

- For ready-to-use prompts and output skeletons, read `references/prompt-and-output-templates.md`.
