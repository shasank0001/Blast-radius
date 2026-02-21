"""Orchestrator — Evidence Merge & Pruning.

Merges results from all five blast-radius tools into a unified list of
``ImpactCandidate`` objects, then prunes / sorts them for consumption by the
report renderer.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from orchestrator.normalize import ChangeSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_CORROBORATED: int = 50
_MAX_UNCORROBORATED: int = 20

# Edge-type → impact_surface mapping for Tool 1
_EDGE_SURFACE_MAP: dict[str, str] = {
    "imports": "api",
    "calls": "business_logic",
    "inherits": "contract_compatibility",
    "references": "data_handling",
}

# Confidence float thresholds → literal labels
_CONF_HIGH = 0.8
_CONF_MED = 0.5


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class ImpactCandidate(BaseModel):
    """A single candidate location that may be impacted by a change."""

    model_config = ConfigDict(extra="forbid")

    file: str
    symbol: str | None = None
    kind: str | None = None
    impact_risk: Literal["breaking", "behavior_change", "unknown"] = "unknown"
    impact_surface: Literal[
        "api",
        "business_logic",
        "data_handling",
        "contract_compatibility",
        "tests",
        "docs",
        "unknown",
    ] = "unknown"
    reason: str = ""
    evidence: list[dict] = []  # list of {tool, query_id, detail}
    confidence: Literal["high", "medium", "low"] = "low"
    suggested_action: str = ""
    corroborated: bool = False  # True if backed by Tool 1 or Tool 2


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _float_to_confidence(score: float) -> Literal["high", "medium", "low"]:
    """Map a 0-1 float to a confidence bucket."""
    if score >= _CONF_HIGH:
        return "high"
    if score >= _CONF_MED:
        return "medium"
    return "low"


def _candidate_key(c: ImpactCandidate) -> tuple[str, str | None]:
    return (c.file, c.symbol)


def _merge_into(existing: ImpactCandidate, incoming: ImpactCandidate) -> None:
    """Merge *incoming* evidence into *existing* candidate **in-place**."""
    existing.evidence.extend(incoming.evidence)

    # Promote corroboration
    if incoming.corroborated:
        existing.corroborated = True

    # Promote risk: breaking > behavior_change > unknown
    _risk_rank = {"breaking": 2, "behavior_change": 1, "unknown": 0}
    if _risk_rank.get(incoming.impact_risk, 0) > _risk_rank.get(
        existing.impact_risk, 0
    ):
        existing.impact_risk = incoming.impact_risk

    # Promote confidence: high > medium > low
    _conf_rank = {"high": 2, "medium": 1, "low": 0}
    if _conf_rank.get(incoming.confidence, 0) > _conf_rank.get(
        existing.confidence, 0
    ):
        existing.confidence = incoming.confidence

    # Prefer a concrete surface over "unknown"
    if existing.impact_surface == "unknown" and incoming.impact_surface != "unknown":
        existing.impact_surface = incoming.impact_surface

    # Keep the more informative reason
    if incoming.reason and (
        not existing.reason or existing.reason == "unknown"
    ):
        existing.reason = incoming.reason

    # Keep kind if missing
    if existing.kind is None and incoming.kind is not None:
        existing.kind = incoming.kind

    # Keep suggested_action if missing
    if not existing.suggested_action and incoming.suggested_action:
        existing.suggested_action = incoming.suggested_action


def _safe_get(d: dict[str, Any], key: str, default: Any = None) -> Any:
    """Fault-tolerant dict access."""
    if not isinstance(d, dict):
        return default
    return d.get(key, default)


# ---------------------------------------------------------------------------
# Step 1 — Tool 1 (AST) edges → candidates
# ---------------------------------------------------------------------------


def _candidates_from_tool1(
    tool1: dict[str, Any],
) -> list[ImpactCandidate]:
    candidates: list[ImpactCandidate] = []
    edges = _safe_get(tool1, "edges", [])
    nodes_by_id: dict[str, dict[str, Any]] = {}
    for n in _safe_get(tool1, "nodes", []):
        nid = _safe_get(n, "id")
        if nid:
            nodes_by_id[nid] = n

    for edge in edges:
        edge_type = _safe_get(edge, "type", "references")
        target_id = _safe_get(edge, "target", "")
        source_id = _safe_get(edge, "source", "")
        confidence = _safe_get(edge, "confidence", 0.5)

        # Resolve target node for file/symbol info
        target_node = nodes_by_id.get(target_id, {})
        source_node = nodes_by_id.get(source_id, {})

        # Prefer target node metadata; fall back to target_ref
        target_ref = _safe_get(edge, "target_ref", {})
        file = (
            _safe_get(target_node, "file")
            or _safe_get(target_ref, "file")
            or _safe_get(source_node, "file", "")
        )
        symbol = (
            _safe_get(target_node, "qualified_name")
            or _safe_get(target_ref, "qualified_name")
            or _safe_get(target_node, "name")
            or target_id
        )
        kind = _safe_get(target_node, "kind")

        surface = _EDGE_SURFACE_MAP.get(edge_type, "unknown")

        # Call edges → behavior_change risk; inherits → breaking
        if edge_type == "inherits":
            risk: Literal["breaking", "behavior_change", "unknown"] = "breaking"
        elif edge_type in ("calls", "imports"):
            risk = "behavior_change"
        else:
            risk = "unknown"

        candidates.append(
            ImpactCandidate(
                file=file,
                symbol=symbol,
                kind=kind,
                impact_risk=risk,
                impact_surface=surface,
                reason=f"Tool 1 {edge_type} edge from {source_id}",
                evidence=[
                    {
                        "tool": "tool1_ast",
                        "query_id": _safe_get(edge, "id", ""),
                        "detail": {
                            "edge_type": edge_type,
                            "source": source_id,
                            "target": target_id,
                            "confidence": confidence,
                            "snippet": _safe_get(edge, "snippet"),
                        },
                    }
                ],
                confidence=_float_to_confidence(confidence),
                suggested_action=f"Review {edge_type} dependency",
                corroborated=True,
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Step 2 — Tool 2 (Data Lineage) read/write sites → candidates
# ---------------------------------------------------------------------------


def _candidates_from_tool2(
    tool2: dict[str, Any],
) -> list[ImpactCandidate]:
    candidates: list[ImpactCandidate] = []
    changed_field = _safe_get(tool2, "changed_field", "")

    for site_key in ("read_sites", "write_sites"):
        sites = _safe_get(tool2, site_key, [])
        for site in sites:
            location = _safe_get(site, "location", {})
            file = _safe_get(location, "file", "")
            symbol = _safe_get(site, "enclosing_symbol_id", None)
            field_path = _safe_get(site, "field_path", "")
            breakage = _safe_get(site, "breakage", {})
            conf = _safe_get(site, "confidence", "low")

            # Determine risk from breakage flags
            if _safe_get(breakage, "if_removed") or _safe_get(
                breakage, "if_renamed"
            ):
                risk: Literal["breaking", "behavior_change", "unknown"] = "breaking"
            elif _safe_get(breakage, "if_type_changed"):
                risk = "behavior_change"
            else:
                risk = "behavior_change"

            surface: Literal[
                "api",
                "business_logic",
                "data_handling",
                "contract_compatibility",
                "tests",
                "docs",
                "unknown",
            ] = "data_handling"
            if site_key == "read_sites":
                surface = "api"

            candidates.append(
                ImpactCandidate(
                    file=file,
                    symbol=symbol,
                    kind="field",
                    impact_risk=risk,
                    impact_surface=surface,
                    reason=(
                        f"Tool 2 {site_key.rstrip('s')} for field "
                        f"'{field_path}' (changed: '{changed_field}')"
                    ),
                    evidence=[
                        {
                            "tool": "tool2_lineage",
                            "query_id": _safe_get(site, "site_id", ""),
                            "detail": {
                                "site_type": site_key,
                                "field_path": field_path,
                                "access_pattern": _safe_get(
                                    site, "access_pattern"
                                ),
                                "breakage": breakage,
                                "snippet": _safe_get(site, "evidence_snippet"),
                            },
                        }
                    ],
                    confidence=conf if conf in ("high", "medium", "low") else "medium",
                    suggested_action=(
                        "Verify data field access after change"
                        if risk != "breaking"
                        else "BREAKING — update or guard field access"
                    ),
                    corroborated=True,
                )
            )

    # Also include validations and transforms as supplementary evidence
    for val in _safe_get(tool2, "validations", []):
        location = _safe_get(val, "location", {})
        file = _safe_get(location, "file", "")
        symbol = _safe_get(val, "enclosing_symbol_id", None)
        candidates.append(
            ImpactCandidate(
                file=file,
                symbol=symbol,
                kind="validator",
                impact_risk="behavior_change",
                impact_surface="contract_compatibility",
                reason=f"Validation rule: {_safe_get(val, 'rule_summary', '')}",
                evidence=[
                    {
                        "tool": "tool2_lineage",
                        "query_id": _safe_get(val, "validation_id", ""),
                        "detail": {
                            "kind": _safe_get(val, "kind"),
                            "field_path": _safe_get(val, "field_path"),
                            "rule_summary": _safe_get(val, "rule_summary"),
                        },
                    }
                ],
                confidence=_safe_get(val, "confidence", "medium"),
                suggested_action="Review validation rule for compatibility",
                corroborated=True,
            )
        )

    for tfm in _safe_get(tool2, "transforms", []):
        location = _safe_get(tfm, "location", {})
        file = _safe_get(location, "file", "")
        symbol = _safe_get(tfm, "enclosing_symbol_id", None)
        candidates.append(
            ImpactCandidate(
                file=file,
                symbol=symbol,
                kind="function",
                impact_risk="behavior_change",
                impact_surface="data_handling",
                reason=(
                    f"Transform ({_safe_get(tfm, 'kind', '')}): "
                    f"{_safe_get(tfm, 'from_field', '')} → {_safe_get(tfm, 'to_field', '')}"
                ),
                evidence=[
                    {
                        "tool": "tool2_lineage",
                        "query_id": _safe_get(tfm, "transform_id", ""),
                        "detail": {
                            "kind": _safe_get(tfm, "kind"),
                            "from_field": _safe_get(tfm, "from_field"),
                            "to_field": _safe_get(tfm, "to_field"),
                        },
                    }
                ],
                confidence=_safe_get(tfm, "confidence", "medium"),
                suggested_action="Review data transform for compatibility",
                corroborated=True,
            )
        )

    return candidates


# ---------------------------------------------------------------------------
# Step 3 — Tool 4 (Temporal Coupling) → review suggestions
# ---------------------------------------------------------------------------


def _candidates_from_tool4(
    tool4: dict[str, Any],
) -> list[ImpactCandidate]:
    candidates: list[ImpactCandidate] = []
    for coupling in _safe_get(tool4, "couplings", []):
        weight = _safe_get(coupling, "weight", 0.0)
        support = _safe_get(coupling, "support", 0)
        coupled_file = _safe_get(coupling, "coupled_file", "")
        target_file = _safe_get(coupling, "target_file", "")

        example_commits = _safe_get(coupling, "example_commits", [])
        commit_detail = (
            [
                {"sha": _safe_get(c, "sha"), "message": _safe_get(c, "message")}
                for c in example_commits[:3]
            ]
            if example_commits
            else []
        )

        candidates.append(
            ImpactCandidate(
                file=coupled_file,
                symbol=None,
                kind=None,
                impact_risk="behavior_change" if weight >= 0.7 else "unknown",
                impact_surface="unknown",
                reason=(
                    f"Historically co-changed with {target_file} "
                    f"(weight={weight:.2f}, support={support})"
                ),
                evidence=[
                    {
                        "tool": "tool4_coupling",
                        "query_id": f"{target_file}::{coupled_file}",
                        "detail": {
                            "weight": weight,
                            "support": support,
                            "example_commits": commit_detail,
                        },
                    }
                ],
                confidence=_float_to_confidence(weight),
                suggested_action="Review for co-change pattern",
                corroborated=True,
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Step 4 — Tool 3 (Semantic) → uncorroborated neighbor zones
# ---------------------------------------------------------------------------


def _candidates_from_tool3(
    tool3: dict[str, Any],
) -> list[ImpactCandidate]:
    candidates: list[ImpactCandidate] = []
    for neighbor in _safe_get(tool3, "neighbors", []):
        score = _safe_get(neighbor, "score", 0.0)
        file = _safe_get(neighbor, "file", "")
        symbol = _safe_get(neighbor, "symbol", None)

        candidates.append(
            ImpactCandidate(
                file=file,
                symbol=symbol,
                kind=None,
                impact_risk="unknown",
                impact_surface="unknown",
                reason=(
                    f"Semantic neighbor (score={score:.2f}): "
                    f"{_safe_get(neighbor, 'rationale_snippet', '')}"
                ),
                evidence=[
                    {
                        "tool": "tool3_semantic",
                        "query_id": _safe_get(neighbor, "neighbor_id", ""),
                        "detail": {
                            "score": score,
                            "method": _safe_get(neighbor, "method"),
                            "rationale_snippet": _safe_get(
                                neighbor, "rationale_snippet"
                            ),
                        },
                    }
                ],
                confidence="low",
                suggested_action="Investigate semantic similarity",
                corroborated=False,
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Step 5 — Tool 5 (Test Impact) → test candidates
# ---------------------------------------------------------------------------


def _candidates_from_tool5(
    tool5: dict[str, Any],
) -> list[ImpactCandidate]:
    candidates: list[ImpactCandidate] = []
    for test in _safe_get(tool5, "tests", []):
        score = _safe_get(test, "score", 0.0)
        file = _safe_get(test, "file", "")
        nodeid = _safe_get(test, "nodeid", "")
        conf = _safe_get(test, "confidence", "low")
        reasons = _safe_get(test, "reasons", [])

        reason_strs = [
            f"{_safe_get(r, 'type', '')}: {_safe_get(r, 'evidence', '')}"
            for r in reasons[:3]
        ]

        candidates.append(
            ImpactCandidate(
                file=file,
                symbol=nodeid,
                kind="test",
                impact_risk="behavior_change",
                impact_surface="tests",
                reason=f"Test impacted: {'; '.join(reason_strs) or 'matched'}",
                evidence=[
                    {
                        "tool": "tool5_tests",
                        "query_id": _safe_get(test, "test_id", ""),
                        "detail": {
                            "nodeid": nodeid,
                            "score": score,
                            "rank": _safe_get(test, "rank"),
                            "reasons": reasons,
                        },
                    }
                ],
                confidence=conf if conf in ("high", "medium", "low") else "medium",
                suggested_action="Run this test to verify change",
                corroborated=True,  # tests are concrete evidence
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _deduplicate(candidates: list[ImpactCandidate]) -> list[ImpactCandidate]:
    """Deduplicate candidates by ``(file, symbol)`` key, merging evidence."""
    seen: dict[tuple[str, str | None], ImpactCandidate] = {}
    for c in candidates:
        key = _candidate_key(c)
        if key in seen:
            _merge_into(seen[key], c)
        else:
            # Deep-copy so we don't mutate the original list's objects
            seen[key] = c.model_copy(deep=True)
    return list(seen.values())


# ---------------------------------------------------------------------------
# Risk / Surface assignment
# ---------------------------------------------------------------------------


def assign_risk_surface(
    candidate: ImpactCandidate,
    change_spec: ChangeSpec,
) -> ImpactCandidate:
    """Refine ``impact_risk`` and ``impact_surface`` using change context.

    Rules:
    - Tool 2 breakage → breaking
    - Tool 1 call edge only → behavior_change
    - Tool 3 only → unknown
    - Read site evidence → api surface
    - Call edge evidence → business_logic
    - ``change_spec.change_class`` enriches the surface assignment
    """
    tools_present = {e.get("tool") for e in candidate.evidence if isinstance(e, dict)}
    has_tool1 = "tool1_ast" in tools_present
    has_tool2 = "tool2_lineage" in tools_present
    has_tool3 = "tool3_semantic" in tools_present
    has_tool5 = "tool5_tests" in tools_present

    # ---- impact_risk ----
    # Check for Tool 2 breakage flags in evidence
    found_breakage = False
    for ev in candidate.evidence:
        if not isinstance(ev, dict):
            continue
        detail = ev.get("detail", {})
        if not isinstance(detail, dict):
            continue
        breakage = detail.get("breakage", {})
        if isinstance(breakage, dict) and (
            breakage.get("if_removed") or breakage.get("if_renamed")
        ):
            candidate.impact_risk = "breaking"
            found_breakage = True
            break

    if not found_breakage:
        # No breakage found — apply fallback rules
        if has_tool1 and not has_tool2 and not has_tool3:
            # Only structural edge, check type
            edge_types = set()
            for ev in candidate.evidence:
                if isinstance(ev, dict) and ev.get("tool") == "tool1_ast":
                    detail = ev.get("detail", {})
                    if isinstance(detail, dict):
                        edge_types.add(detail.get("edge_type"))
            if edge_types <= {"calls", "references"}:
                candidate.impact_risk = "behavior_change"
            elif "inherits" in edge_types:
                candidate.impact_risk = "breaking"
        elif not has_tool1 and not has_tool2 and has_tool3:
            candidate.impact_risk = "unknown"

    # ---- impact_surface ----
    # Read-site evidence → api
    found_surface = False
    for ev in candidate.evidence:
        if not isinstance(ev, dict):
            continue
        detail = ev.get("detail", {})
        if isinstance(detail, dict) and detail.get("site_type") == "read_sites":
            candidate.impact_surface = "api"
            found_surface = True
            break

    if not found_surface:
        # Call edge → business_logic
        for ev in candidate.evidence:
            if not isinstance(ev, dict):
                continue
            detail = ev.get("detail", {})
            if isinstance(detail, dict) and detail.get("edge_type") == "calls":
                candidate.impact_surface = "business_logic"
                break

    # Test evidence overrides to "tests" surface
    if has_tool5 and candidate.impact_surface == "unknown":
        candidate.impact_surface = "tests"

    # Enrich from change_spec.change_class
    if change_spec.change_class == "api_change" and candidate.impact_surface == "unknown":
        candidate.impact_surface = "api"
    elif (
        change_spec.change_class == "behavior_change"
        and candidate.impact_surface == "unknown"
    ):
        candidate.impact_surface = "business_logic"
    elif (
        change_spec.change_class == "structural_change"
        and candidate.impact_surface == "unknown"
    ):
        candidate.impact_surface = "contract_compatibility"

    return candidate


# ---------------------------------------------------------------------------
# Public API — merge
# ---------------------------------------------------------------------------


def merge_evidence(
    tool1_result: dict[str, Any],
    tool2_result: dict[str, Any],
    tool3_result: dict[str, Any],
    tool4_result: dict[str, Any],
    tool5_result: dict[str, Any],
    change_spec: ChangeSpec,
) -> list[ImpactCandidate]:
    """Merge evidence from all five tools into a single candidate list.

    1. Tool 1 edges → corroborated structural impacts
    2. Tool 2 read/write sites → corroborated data-shape impacts
    3. Tool 4 couplings → corroborated review suggestions
    4. Tool 3 neighbors → uncorroborated semantic zones
    5. Tool 5 tests → corroborated test impacts
    6. Deduplicate by ``(file, symbol)``
    7. Assign refined risk / surface from change context
    """
    all_candidates: list[ImpactCandidate] = []

    # Step 1-5: gather from each tool
    all_candidates.extend(_candidates_from_tool1(tool1_result))
    all_candidates.extend(_candidates_from_tool2(tool2_result))
    all_candidates.extend(_candidates_from_tool4(tool4_result))
    all_candidates.extend(_candidates_from_tool3(tool3_result))
    all_candidates.extend(_candidates_from_tool5(tool5_result))

    # Step 6: deduplicate
    merged = _deduplicate(all_candidates)

    # Step 7: refine risk / surface
    for c in merged:
        assign_risk_surface(c, change_spec)

    return merged


# ---------------------------------------------------------------------------
# Public API — prune
# ---------------------------------------------------------------------------


def prune_candidates(
    candidates: list[ImpactCandidate],
    change_spec: ChangeSpec,
) -> list[ImpactCandidate]:
    """Prune and sort candidate list for report consumption.

    Rules:
    1. Drop low-confidence structural edges unless they match the changed
       field / path.
    2. Never promote semantic-only neighbors to "impacted" without Tool 1/2
       corroboration.
    3. For API changes, remove items not touching the changed ``field_path``
       unless they have strong evidence (corroborated + high/medium conf).
    4. Cap per-section counts: max *_MAX_CORROBORATED* corroborated,
       max *_MAX_UNCORROBORATED* uncorroborated.
    5. Sort by (corroborated DESC, confidence DESC, file ASC, symbol ASC).
    """
    kept: list[ImpactCandidate] = []
    changed_field = change_spec.field_path or ""

    for c in candidates:
        # Rule 1: drop low-confidence structural-only if not matching field
        if c.confidence == "low" and c.corroborated:
            tools_in_evidence = {
                e.get("tool") for e in c.evidence if isinstance(e, dict)
            }
            only_structural = tools_in_evidence <= {"tool1_ast"}
            if only_structural and not _matches_field(c, changed_field):
                continue

        # Rule 2: semantic-only stays uncorroborated — already enforced by
        # construction (tool3 sets corroborated=False), but guard anyway
        tools_in_evidence = {
            e.get("tool") for e in c.evidence if isinstance(e, dict)
        }
        semantic_only = tools_in_evidence == {"tool3_semantic"}
        if semantic_only:
            c.corroborated = False

        # Rule 3: API change — drop non-field items without strong evidence
        if change_spec.change_class == "api_change" and changed_field:
            if not _matches_field(c, changed_field):
                has_strong_evidence = c.corroborated and c.confidence in (
                    "high",
                    "medium",
                )
                if not has_strong_evidence:
                    continue

        kept.append(c)

    # Rule 4: cap per-section
    corroborated = [c for c in kept if c.corroborated]
    uncorroborated = [c for c in kept if not c.corroborated]

    corroborated = corroborated[:_MAX_CORROBORATED]
    uncorroborated = uncorroborated[:_MAX_UNCORROBORATED]

    final = corroborated + uncorroborated

    # Rule 5: deterministic sort
    _conf_order = {"high": 0, "medium": 1, "low": 2}
    final.sort(
        key=lambda c: (
            0 if c.corroborated else 1,
            _conf_order.get(c.confidence, 3),
            c.file,
            c.symbol or "",
        )
    )

    return final


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _matches_field(candidate: ImpactCandidate, field_path: str) -> bool:
    """Return True if any evidence touches *field_path*."""
    if not field_path:
        return True  # nothing to filter on
    fp_lower = field_path.lower()
    # Check symbol
    if candidate.symbol and fp_lower in candidate.symbol.lower():
        return True
    # Check evidence details
    for ev in candidate.evidence:
        if not isinstance(ev, dict):
            continue
        detail = ev.get("detail", {})
        if not isinstance(detail, dict):
            continue
        for key in ("field_path", "from_field", "to_field"):
            val = detail.get(key)
            if isinstance(val, str) and fp_lower in val.lower():
                return True
        # Check snippet
        snippet = detail.get("snippet") or detail.get("evidence_snippet") or ""
        if isinstance(snippet, str) and fp_lower in snippet.lower():
            return True
    return False
