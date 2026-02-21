"""Orchestrator main pipeline — ties together all 5 tools into a single blast-radius report."""

from __future__ import annotations

import json
import logging
from typing import Any

from blast_radius_mcp.ids import (
    canonical_json,
    compute_diff_hash,
    compute_query_id,
    compute_run_id,
    normalize_intent as _normalize_intent_id,
)
from blast_radius_mcp.repo.fingerprint import compute_repo_fingerprint
from blast_radius_mcp.server import (
    TOOL1_IMPL_VERSION,
    TOOL2_IMPL_VERSION,
    TOOL3_IMPL_VERSION,
    TOOL4_IMPL_VERSION,
    TOOL5_IMPL_VERSION,
    _build_tool1_result,
    _build_tool2_result,
    _build_tool3_result,
    _build_tool4_result,
    _build_tool5_result,
    execute_tool,
)
from blast_radius_mcp.settings import settings

from orchestrator.diff_parser import DiffResult, parse_unified_diff
from orchestrator.merge_evidence import (
    ImpactCandidate,
    assign_risk_surface,
    merge_evidence,
    prune_candidates,
)
from orchestrator.normalize import ChangeSpec, build_tool_plan, normalize_intent
from orchestrator.report_render import render_report

logger = logging.getLogger("orchestrator")

# ── Mapping from tool names to their impl versions + builders ───────

_TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "get_ast_dependencies": {
        "impl_version": TOOL1_IMPL_VERSION,
        "build_fn": _build_tool1_result,
    },
    "trace_data_shape": {
        "impl_version": TOOL2_IMPL_VERSION,
        "build_fn": _build_tool2_result,
    },
    "find_semantic_neighbors": {
        "impl_version": TOOL3_IMPL_VERSION,
        "build_fn": _build_tool3_result,
    },
    "get_historical_coupling": {
        "impl_version": TOOL4_IMPL_VERSION,
        "build_fn": _build_tool4_result,
    },
    "get_covering_tests": {
        "impl_version": TOOL5_IMPL_VERSION,
        "build_fn": _build_tool5_result,
    },
}


# ── Helper: call a single tool via server.execute_tool ──────────────


async def _call_tool(
    tool_name: str,
    impl_version: str,
    inputs: dict[str, Any],
    repo_root: str,
    anchors: list[str],
    diff: str,
    build_result_fn: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Call a tool via the server's ``execute_tool`` and extract the result + query_id.

    Returns:
        A ``(result_dict, query_id)`` tuple.  Both are ``None`` when the tool
        fails for any reason.
    """
    envelope: dict[str, Any] = {
        "schema_version": settings.SCHEMA_VERSION,
        "repo_root": repo_root,
        "inputs": inputs,
        "anchors": anchors,
        "diff": diff,
    }
    try:
        response_json: str = await execute_tool(
            tool_name, impl_version, envelope, build_result_fn
        )
        response: dict[str, Any] = json.loads(response_json)
        return response.get("result"), response.get("query_id")
    except Exception as exc:
        logger.warning("Tool %s failed: %s", tool_name, exc, exc_info=True)
        return None, None


# ── Main pipeline ───────────────────────────────────────────────────


async def run_blast_radius(
    intent: str,
    repo_root: str,
    anchors: list[str] | None = None,
    diff: str = "",
    run_id: str | None = None,
) -> str:
    """Run the full blast-radius analysis pipeline and return a Markdown report.

    End-to-end flow:
    1. Normalize intent → ``ChangeSpec``
    2. Parse diff → ``DiffResult`` (if diff is provided)
    3. Compute repo fingerprint
    4. Compute ``run_id`` (if not supplied)
    5. Build tool-call plan
    6. Execute each tool, collecting results and query IDs
    7. Merge evidence from all tools
    8. Prune low-signal candidates
    9. Assign risk surfaces
    10. Build assumptions / limitations
    11. Render and return the Markdown report
    """
    if anchors is None:
        anchors = []

    # ── 1. Normalize intent ─────────────────────────────────────────
    change_spec: ChangeSpec = normalize_intent(intent, anchors, diff)

    # ── 2. Parse diff ───────────────────────────────────────────────
    diff_result: DiffResult | None = parse_unified_diff(diff) if diff else None

    # ── 3. Repo fingerprint ─────────────────────────────────────────
    repo_fingerprint = compute_repo_fingerprint(repo_root)

    # ── 4. Deterministic run_id ─────────────────────────────────────
    if run_id is None:
        intent_norm = _normalize_intent_id(intent)
        anchors_norm = sorted(anchors)
        diff_hash = compute_diff_hash(diff)
        run_id = compute_run_id(
            settings.SCHEMA_VERSION,
            intent_norm,
            anchors_norm,
            diff_hash,
            repo_fingerprint.fingerprint_hash,
        )

    # ── 5. Build tool plan ──────────────────────────────────────────
    tool_plan: list[dict[str, Any]] = build_tool_plan(
        change_spec, diff_result, anchors, repo_root
    )

    # ── 6. Execute tools ────────────────────────────────────────────
    tool_results: dict[str, dict[str, Any] | None] = {}
    query_ids: dict[str, str | None] = {}
    tool_errors: list[str] = []

    for plan_entry in tool_plan:
        tool_name: str = plan_entry["tool_name"]
        inputs: dict[str, Any] = plan_entry.get("inputs", {})

        registry = _TOOL_REGISTRY.get(tool_name)
        if registry is None:
            logger.warning("Unknown tool in plan: %s — skipping", tool_name)
            tool_errors.append(f"Tool {tool_name} skipped: not registered")
            tool_results[tool_name] = None
            query_ids[tool_name] = None
            continue

        result, qid = await _call_tool(
            tool_name=tool_name,
            impl_version=registry["impl_version"],
            inputs=inputs,
            repo_root=repo_root,
            anchors=anchors,
            diff=diff,
            build_result_fn=registry["build_fn"],
        )
        tool_results[tool_name] = result
        query_ids[tool_name] = qid

        if result is None:
            tool_errors.append(f"Tool {tool_name} failed/skipped")

    # ── 7. Merge evidence ───────────────────────────────────────────
    candidates: list[ImpactCandidate] = merge_evidence(
        tool1_result=tool_results.get("get_ast_dependencies"),
        tool2_result=tool_results.get("trace_data_shape"),
        tool3_result=tool_results.get("find_semantic_neighbors"),
        tool4_result=tool_results.get("get_historical_coupling"),
        tool5_result=tool_results.get("get_covering_tests"),
        change_spec=change_spec,
    )

    # ── 8. Prune candidates ─────────────────────────────────────────
    pruned: list[ImpactCandidate] = prune_candidates(candidates, change_spec)

    # ── 9. Assign risk surfaces ─────────────────────────────────────
    impacts: list[ImpactCandidate] = assign_risk_surface(pruned)

    # ── 10. Build assumptions & limitations ─────────────────────────
    assumptions: list[str] = _build_assumptions(diff, anchors, tool_errors)
    limitations: list[str] = _build_limitations()

    # ── 11. Render report ───────────────────────────────────────────
    report: str = render_report(
        intent=intent,
        anchors=anchors,
        change_spec=change_spec,
        impacts=impacts,
        tool_results=tool_results,
        query_ids=query_ids,
        assumptions=assumptions,
        limitations=limitations,
    )

    logger.info(
        "Pipeline complete",
        extra={
            "run_id": run_id,
            "tools_planned": len(tool_plan),
            "tools_succeeded": sum(1 for v in tool_results.values() if v is not None),
            "impacts": len(impacts),
        },
    )

    return report


# ── Internal helpers ────────────────────────────────────────────────


def _build_assumptions(
    diff: str,
    anchors: list[str],
    tool_errors: list[str],
) -> list[str]:
    """Build the list of assumptions for the report."""
    assumptions: list[str] = []

    if not diff:
        assumptions.append(
            "Analysis performed with natural language intent only (no diff provided)"
        )

    if not anchors:
        assumptions.append(
            "No anchors provided \u2014 analysis scope may be broader"
        )

    for err in tool_errors:
        assumptions.append(err)

    # Semantic-only caveat is always relevant when tool 3 ran
    assumptions.append(
        "Semantic-only results are marked as 'unknown risk zones' and require corroboration"
    )

    return assumptions


def _build_limitations() -> list[str]:
    """Build the static list of known limitations for v1."""
    return [
        "Python-only analysis (v1)",
        "Static analysis may miss dynamic dispatch patterns",
        "Cross-file resolution limited to direct imports",
    ]


__all__ = [
    "run_blast_radius",
]
