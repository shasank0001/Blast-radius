from __future__ import annotations

from collections import Counter
from typing import Literal

from orchestrator.merge_evidence import ImpactCandidate
from orchestrator.normalize import ChangeSpec

# ---------------------------------------------------------------------------
# Confidence helpers
# ---------------------------------------------------------------------------

_CONFIDENCE_RANK: dict[str, int] = {"high": 3, "medium": 2, "low": 1}
_RISK_RANK: dict[str, int] = {"breaking": 3, "behavior_change": 2, "unknown": 1}
_CONF_ABBREV: dict[str, str] = {"high": "H", "medium": "M", "low": "L"}


def _overall_confidence(impacts: list[ImpactCandidate]) -> Literal["High", "Medium", "Low"]:
    """Derive overall confidence from the distribution of impacts.

    Rules:
    - Any breaking impact with high confidence → "High"
    - Mixed → "Medium"
    - Only low → "Low"
    - No impacts → "Low"
    """
    if not impacts:
        return "Low"

    has_breaking_high = any(
        c.impact_risk == "breaking" and c.confidence == "high" for c in impacts
    )
    if has_breaking_high:
        return "High"

    confidence_values = {c.confidence for c in impacts}
    if confidence_values == {"low"}:
        return "Low"

    return "Medium"


def _sort_key(c: ImpactCandidate) -> tuple[int, int]:
    """Sort candidates by confidence (desc), then risk (desc)."""
    return (_CONFIDENCE_RANK.get(c.confidence, 0), _RISK_RANK.get(c.impact_risk, 0))


def _top_risks(impacts: list[ImpactCandidate], n: int = 3) -> list[ImpactCandidate]:
    """Return the top-n highest-confidence, most impactful candidates."""
    return sorted(impacts, key=_sort_key, reverse=True)[:n]


def _evidence_to_str(e: dict) -> str:
    """Convert an evidence dict to a human-readable string."""
    detail = e.get("detail", "")
    if isinstance(detail, dict):
        # Extract a useful snippet from structured detail
        parts: list[str] = []
        if "edge_type" in detail:
            parts.append(detail["edge_type"])
        if "snippet" in detail and detail["snippet"]:
            parts.append(str(detail["snippet"]))
        if "access_pattern" in detail:
            parts.append(detail["access_pattern"])
        return " — ".join(parts) if parts else e.get("tool", "evidence")
    if isinstance(detail, str) and detail:
        return detail
    return e.get("tool", "evidence")


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def _render_executive_summary(
    intent: str,
    anchors: list[str],
    impacts: list[ImpactCandidate],
) -> str:
    overall = _overall_confidence(impacts)
    anchor_str = ", ".join(anchors) if anchors else "N/A"

    top = _top_risks(impacts)
    if top:
        risk_bullets = "\n".join(
            f"  - **{c.impact_risk}** in `{c.file}`"
            + (f":`{c.symbol}`" if c.symbol else "")
            + f" — {c.reason}"
            for c in top
        )
    else:
        risk_bullets = "  - No risks identified"

    return (
        "## Executive summary\n"
        f"- **Intent:** {intent}\n"
        f"- **Anchor(s):** {anchor_str}\n"
        f"- **Top risks:**\n{risk_bullets}\n"
        f"- **Overall confidence:** {overall}\n"
    )


def _render_direct_impacts(impacts: list[ImpactCandidate]) -> str:
    corroborated = [c for c in impacts if c.corroborated]
    header = "## Direct structural impacts (AST)\n"

    if not corroborated:
        return header + "No direct impacts detected.\n"

    table_header = (
        "| Impact | Impact risk | Impact surface | Location | Why | Evidence | Confidence |\n"
        "|---|---|---|---|---|---|---|\n"
    )
    rows: list[str] = []
    for c in corroborated:
        impact_label = c.symbol or c.file
        location = f"`{c.file}`" + (f":`{c.symbol}`" if c.symbol else "")
        evidence_str = "; ".join(
            _evidence_to_str(e) for e in c.evidence
        ) if c.evidence else "AST edge(s)"
        rows.append(
            f"| {impact_label} | {c.impact_risk} | {c.impact_surface} "
            f"| {location} | {c.reason} | {evidence_str} | {_CONF_ABBREV.get(c.confidence, '?')} |"
        )

    return header + table_header + "\n".join(rows) + "\n"


def _render_data_shape(
    change_spec: ChangeSpec,
    tool_results: dict[str, dict],
) -> str:
    header = "## Data-shape impacts (payload lineage)\n"
    result = tool_results.get("trace_data_shape")

    if not result:
        return header + "Tool not executed or no data available.\n"

    field_path = change_spec.field_path or change_spec.entity_id
    lines = [header, f"**Changed field/path:** `{field_path}`\n"]

    # Read sites
    read_sites: list[dict] = result.get("read_sites", [])
    lines.append("### Read sites that will break if removed/renamed\n")
    if read_sites:
        for site in read_sites:
            loc = site.get("location", {})
            file_ = loc.get("file", site.get("file", "?"))
            symbol = site.get("enclosing_symbol_id", site.get("symbol", "?"))
            field = site.get("field_path", field_path)
            access = site.get("access_pattern", "attr/dict access")
            snippet = site.get("evidence_snippet", "")
            breakage = site.get("breakage", {})
            breakage_flags: list[str] = []
            if breakage.get("if_removed"):
                breakage_flags.append("breaks if removed")
            if breakage.get("if_renamed"):
                breakage_flags.append("breaks if renamed")
            suffix = f" [{', '.join(breakage_flags)}]" if breakage_flags else ""
            lines.append(f"- `{file_}`:`{symbol}` — reads `{field}` via `{access}`{suffix}")
    else:
        lines.append("- No read sites identified.")

    lines.append("")

    # Transformations
    transforms: list[dict] = result.get("transforms", [])
    lines.append("### Transformations\n")
    if transforms:
        for t in transforms:
            loc = t.get("location", {})
            file_ = loc.get("file", t.get("file", "?"))
            symbol = t.get("enclosing_symbol_id", t.get("symbol", "?"))
            kind = t.get("kind", "transform")
            if kind == "rename":
                from_name = t.get("from_field", "?")
                to_name = t.get("to_field", "?")
                lines.append(f"- `{file_}`:`{symbol}` — renames `{from_name}` → `{to_name}`")
            elif kind == "cast":
                from_type = t.get("from_type", "?")
                to_type = t.get("to_type", "?")
                lines.append(f"- `{file_}`:`{symbol}` — casts `{from_type}` → `{to_type}`")
            else:
                lines.append(f"- `{file_}`:`{symbol}` — {kind}")
    else:
        lines.append("- No transformations identified.")

    lines.append("")
    return "\n".join(lines)


def _render_unknown_risk_zones(impacts: list[ImpactCandidate]) -> str:
    header = "## Unknown risk zones (semantic neighbors)\n"
    uncorroborated = [c for c in impacts if not c.corroborated]

    if not uncorroborated:
        return header + "No unknown risk zones detected.\n"

    lines = [header]
    for c in uncorroborated:
        similarity = ""
        for e in c.evidence:
            if "similarity" in e:
                similarity = f" (similarity: {e['similarity']:.2f})"
                break
        symbol_label = f"`{c.file}`" + (f":`{c.symbol}`" if c.symbol else "")
        lines.append(f"- {symbol_label}{similarity} — {c.reason}")

    lines.append("")
    return "\n".join(lines)


def _render_temporal_coupling(tool_results: dict[str, dict]) -> str:
    header = "## Implicit dependencies (temporal coupling)\n"
    result = tool_results.get("get_historical_coupling")

    if not result:
        return header + "Tool not executed or no data available.\n"

    couplings: list[dict] = result.get("couplings") or result.get("coupled_files", [])
    if not couplings:
        return header + "No temporal coupling detected.\n"

    lines = [header]
    for entry in couplings:
        file_ = entry.get("coupled_file") or entry.get("file", "?")
        weight = entry.get("weight", 0)
        if isinstance(weight, float) and weight <= 1.0:
            weight_str = f"{weight * 100:.0f}%"
        else:
            weight_str = f"{weight}%"
        lines.append(f"- `{file_}` (weight: {weight_str}) — often changes with the target")

    lines.append("")
    return "\n".join(lines)


def _render_tests(tool_results: dict[str, dict]) -> str:
    header = "## Tests to run (impact prover)\n"
    result = tool_results.get("get_covering_tests")

    if not result:
        return header + "Tool not executed or no data available.\n"

    tests: list[dict] = result.get("tests", [])
    if not tests:
        return header + "No covering tests identified.\n"

    lines = [header, "Ranked list:"]
    for i, t in enumerate(tests, 1):
        node = t.get("nodeid") or t.get("node_id") or t.get("test") or "?"

        reason = "covers the impacted path"
        reasons = t.get("reasons", [])
        if reasons and isinstance(reasons[0], dict):
            reason = (
                reasons[0].get("evidence")
                or reasons[0].get("reason")
                or reasons[0].get("type")
                or reason
            )
        else:
            reason = t.get("reason", reason)

        lines.append(f"{i}. `{node}` — {reason}")

    lines.append("")
    return "\n".join(lines)


def _render_recommended_actions(impacts: list[ImpactCandidate]) -> str:
    header = "## Recommended engineer actions\n"

    if not impacts:
        return header + "No specific actions recommended.\n"

    schema_docs: list[str] = []
    consumers: list[str] = []
    run_tests: list[str] = []

    for c in impacts:
        action = c.suggested_action.lower()
        label = f"`{c.file}`" + (f":`{c.symbol}`" if c.symbol else "")

        if any(kw in action for kw in ("schema", "doc", "document", "update type")):
            schema_docs.append(f"{label} — {c.suggested_action}")
        elif any(kw in action for kw in ("consumer", "downstream", "caller", "client", "update")):
            consumers.append(f"{label} — {c.suggested_action}")
        elif any(kw in action for kw in ("test", "verify", "assert", "check")):
            run_tests.append(f"{label} — {c.suggested_action}")
        else:
            # Default bucket based on impact surface
            if c.impact_surface in ("api", "contract_compatibility"):
                consumers.append(f"{label} — {c.suggested_action}")
            elif c.impact_surface == "tests":
                run_tests.append(f"{label} — {c.suggested_action}")
            else:
                schema_docs.append(f"{label} — {c.suggested_action}")

    lines = [header]
    lines.append(
        "- **Update schema/docs:** "
        + (", ".join(schema_docs) if schema_docs else "None")
    )
    lines.append(
        "- **Update downstream consumers:** "
        + (", ".join(consumers) if consumers else "None")
    )
    lines.append(
        "- **Run tests:** "
        + (", ".join(run_tests) if run_tests else "None")
    )
    lines.append("")
    return "\n".join(lines)


def _render_evidence_appendix(query_ids: dict[str, str]) -> str:
    header = "## Evidence appendix (machine evidence references)\n"

    # Canonical tool label mapping
    tool_labels: dict[str, str] = {
        "get_ast_dependencies": "AST query id",
        "trace_data_shape": "Data lineage trace id",
        "find_semantic_neighbors": "Semantic query id",
        "get_historical_coupling": "Git coupling query id",
        "get_covering_tests": "Test impact query id",
    }

    if not query_ids:
        return header + "No evidence references available.\n"

    lines = [header]
    for tool_name, label in tool_labels.items():
        qid = query_ids.get(tool_name, "N/A")
        lines.append(f"- {label}: `{qid}`")

    # Include any extra tools not in the canonical list
    for tool_name, qid in query_ids.items():
        if tool_name not in tool_labels:
            lines.append(f"- {tool_name} query id: `{qid}`")

    lines.append("")
    return "\n".join(lines)


def _render_assumptions_limitations(
    assumptions: list[str],
    limitations: list[str],
) -> str:
    header = "## Assumptions & limitations\n"
    lines = [header]

    if assumptions:
        for a in assumptions:
            lines.append(f"- {a}")
    else:
        lines.append("- No assumptions recorded.")

    if limitations:
        for lim in limitations:
            lines.append(f"- {lim}")
    else:
        lines.append("- No limitations recorded.")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_report(
    intent: str,
    anchors: list[str],
    change_spec: ChangeSpec,
    impacts: list[ImpactCandidate],
    tool_results: dict[str, dict],   # tool_name → result dict
    query_ids: dict[str, str],       # tool_name → query_id
    assumptions: list[str],
    limitations: list[str],
) -> str:
    """Render a full Blast Radius Report as Markdown.

    Parameters
    ----------
    intent:
        Natural-language description of the change intent.
    anchors:
        List of anchor files/symbols/endpoints that were analysed.
    change_spec:
        Normalized change specification from the diff parser.
    impacts:
        Merged and deduplicated impact candidates from all tools.
    tool_results:
        Mapping of tool name → raw result dict (used for data-shape,
        temporal-coupling, and test-impact sections).
    query_ids:
        Mapping of tool name → query_id for evidence appendix.
    assumptions:
        List of assumption strings to include at the end.
    limitations:
        List of limitation strings to include at the end.

    Returns
    -------
    str
        Complete Markdown report.
    """
    sections: list[str] = [
        "# Blast Radius Report — Template (v1)\n",
        _render_executive_summary(intent, anchors, impacts),
        _render_direct_impacts(impacts),
        _render_data_shape(change_spec, tool_results),
        _render_unknown_risk_zones(impacts),
        _render_temporal_coupling(tool_results),
        _render_tests(tool_results),
        _render_recommended_actions(impacts),
        _render_evidence_appendix(query_ids),
        _render_assumptions_limitations(assumptions, limitations),
    ]

    return "\n".join(sections)
