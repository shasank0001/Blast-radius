"""ChangeSpec normalization and tool-call planning for the Blast Radius orchestrator.

Phase 4.1 — ChangeSpec Normalization:
    Parses a natural-language intent string (plus optional anchors and a unified
    diff) into a structured ``ChangeSpec`` that the rest of the pipeline can
    reason about deterministically.

Phase 4.3 — Tool Call Planner:
    Given a ``ChangeSpec``, an optional ``DiffResult``, a list of anchors, and
    the repository root, produces an ordered plan of MCP tool invocations with
    their inputs and priorities.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from orchestrator.diff_parser import DiffResult


# ---------------------------------------------------------------------------
# 4.1  ChangeSpec model
# ---------------------------------------------------------------------------


class ChangeSpec(BaseModel):
    """Structured representation of a developer's intended change.

    Attributes:
        change_class: High-level category of the change — one of
            ``"api_change"``, ``"behavior_change"``, ``"structural_change"``.
        entity_kind: The kind of code entity involved — one of
            ``"field"``, ``"function"``, ``"validator"``, ``"schema"``,
            ``"route"``, ``"module"``.
        entity_id: Human-readable identifier such as ``"POST /orders"`` or
            ``"OrderRequest.user_id"``.
        operation: The mutation being applied — one of ``"add"``, ``"remove"``,
            ``"rename"``, ``"type_change"``, ``"relax"``, ``"tighten"``,
            ``"refactor"``.
        field_path: Dotted path to a field if applicable (e.g.
            ``"request.user_id"``).  ``None`` when not relevant.
        from_type: Original type before a ``type_change`` operation.
        to_type: Target type after a ``type_change`` operation.
        notes: Free-form notes captured during normalisation.
    """

    model_config = ConfigDict(extra="forbid")

    change_class: Literal["api_change", "behavior_change", "structural_change"]
    entity_kind: Literal["field", "function", "validator", "schema", "route", "module"]
    entity_id: str
    operation: Literal[
        "add", "remove", "rename", "type_change", "relax", "tighten", "refactor"
    ]
    field_path: str | None = None
    from_type: str | None = None
    to_type: str | None = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Keyword mappings used by the heuristic parser
# ---------------------------------------------------------------------------

_OPERATION_KEYWORDS: list[tuple[list[str], str]] = [
    (["remove", "delete"], "remove"),
    (["rename"], "rename"),
    (["add", "new", "create"], "add"),
    (["type", "change type", "retype"], "type_change"),
    (["relax", "optional", "make optional"], "relax"),
    (["tighten", "required", "strict", "make required"], "tighten"),
    (["refactor", "signature"], "refactor"),
]

_ENTITY_KIND_KEYWORDS: list[tuple[list[str], str, str | None]] = [
    # (keywords, entity_kind, change_class_override)
    (["field", "payload", "request", "response"], "field", "api_change"),
    (["validation", "validator"], "validator", "behavior_change"),
    (["route", "endpoint", "api"], "route", None),
    (["schema", "model"], "schema", None),
    (["module", "package"], "module", None),
    (["function", "method", "def"], "function", None),
]

# Regex helpers
_HTTP_METHOD_PATTERN = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S+)", re.IGNORECASE
)
_DOTTED_ID_PATTERN = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b")
_SIMPLE_ID_PATTERN = re.compile(r"\b([A-Za-z_]\w+)\b")


# ---------------------------------------------------------------------------
# 4.1  normalize_intent
# ---------------------------------------------------------------------------


def normalize_intent(
    intent: str,
    anchors: list[str],
    diff: str,
) -> ChangeSpec:
    """Parse a natural-language *intent* into a :class:`ChangeSpec`.

    The function applies heuristic keyword matching against *intent* to derive
    the ``operation``, ``entity_kind``, and ``change_class``.  It then attempts
    to extract ``entity_id`` and ``field_path`` from *anchors* and, when
    anchors are insufficient, falls back to patterns found in *diff*.

    Parameters
    ----------
    intent:
        Free-text description of the intended change (e.g.
        ``"Remove user_id from POST /orders"``).
    anchors:
        File paths, symbol names, or route strings that the caller has already
        identified as relevant.
    diff:
        A unified-diff string (may be empty).

    Returns
    -------
    ChangeSpec
        The normalised change specification.

    Examples
    --------
    >>> spec = normalize_intent("Remove user_id from POST /orders", [], "")
    >>> spec.operation
    'remove'
    >>> spec.change_class
    'api_change'

    >>> spec2 = normalize_intent("Change signature of parse_user_id", [], "")
    >>> spec2.operation
    'refactor'
    >>> spec2.entity_kind
    'function'
    """

    intent_lower = intent.lower()

    # --- 1. Determine operation -------------------------------------------
    operation: str = "refactor"  # fallback
    for keywords, op in _OPERATION_KEYWORDS:
        if any(kw in intent_lower for kw in keywords):
            operation = op
            break

    # --- 2. Determine entity_kind & change_class --------------------------
    entity_kind: str = "function"  # fallback
    change_class: str = "structural_change"  # fallback

    for keywords, ek, cc_override in _ENTITY_KIND_KEYWORDS:
        if any(kw in intent_lower for kw in keywords):
            entity_kind = ek
            if cc_override is not None:
                change_class = cc_override
            break

    # Structural overrides for specific operation keywords
    if operation == "refactor" and entity_kind == "function":
        change_class = "structural_change"
    if operation in ("relax", "tighten") and change_class == "structural_change":
        change_class = "api_change"
        if entity_kind == "function":
            entity_kind = "field"

    # --- 3. Extract entity_id ---------------------------------------------
    entity_id = ""
    field_path: str | None = None

    # Try to find an HTTP method + path in the intent (e.g. "POST /orders")
    http_match = _HTTP_METHOD_PATTERN.search(intent)
    if http_match:
        entity_id = f"{http_match.group(1).upper()} {http_match.group(2)}"
        # If the operation implies work *on a field within* the route, keep
        # entity_kind as "field"; otherwise default to "route".
        if entity_kind not in ("route", "field", "validator", "schema"):
            if operation in ("remove", "add", "type_change", "relax", "tighten"):
                entity_kind = "field"
            else:
                entity_kind = "route"
        if change_class == "structural_change":
            change_class = "api_change"

    # Try to extract a dotted identifier (e.g. "OrderRequest.user_id")
    dotted_match = _DOTTED_ID_PATTERN.search(intent)
    if dotted_match:
        dotted = dotted_match.group(1)
        if not entity_id:
            entity_id = dotted
        # Derive field_path from dotted id if it looks like a qualified field
        if "." in dotted:
            field_path = field_path or dotted

    # Fall back: use anchors to derive entity_id & field_path
    if anchors:
        if not entity_id:
            # Use the first anchor that looks like an identifier
            for anchor in anchors:
                anchor_stripped = anchor.strip()
                if anchor_stripped:
                    entity_id = anchor_stripped
                    break
        if field_path is None:
            for anchor in anchors:
                if "." in anchor and not anchor.endswith((".py", ".ts", ".js")):
                    field_path = anchor
                    break

    # Extract a simple identifier from the intent for entity_id if still
    # empty.
    if not entity_id:
        simple_ids = _SIMPLE_ID_PATTERN.findall(intent)
        # Filter out common English noise words and the keywords we matched
        _noise = {
            "the", "a", "an", "from", "to", "in", "of", "for", "is", "and",
            "or", "it", "this", "that", "with", "on", "at", "by", "as",
            "be", "are", "was", "were", "been", "will", "would", "should",
            "can", "could", "may", "might", "do", "does", "did", "has",
            "have", "had", "not", "but", "if", "than", "then", "so",
            "remove", "delete", "rename", "add", "new", "change", "type",
            "relax", "optional", "tighten", "required", "strict", "refactor",
            "signature", "field", "payload", "request", "response",
            "validation", "validator", "route", "endpoint", "api",
            "make", "update", "modify", "get", "set",
        }
        candidates = [w for w in simple_ids if w.lower() not in _noise and len(w) > 1]
        if candidates:
            entity_id = candidates[0]

    # --- 4. Extract extra context from the diff ---------------------------
    if diff and not entity_id:
        # Try HTTP pattern in diff
        diff_http = _HTTP_METHOD_PATTERN.search(diff)
        if diff_http:
            entity_id = f"{diff_http.group(1).upper()} {diff_http.group(2)}"
        else:
            # Pull the first non-trivial identifier from changed lines
            for line in diff.splitlines():
                if line.startswith(("+", "-")) and not line.startswith(
                    ("+++", "---")
                ):
                    ids = _SIMPLE_ID_PATTERN.findall(line.lstrip("+-"))
                    if ids:
                        entity_id = ids[0]
                        break

    if not entity_id:
        entity_id = "unknown"

    # --- 5. Derive field_path heuristic from intent -----------------------
    if field_path is None and entity_kind == "field":
        # Look for a bare word that could be a field name.
        # e.g. "Remove user_id from POST /orders" → field_path=request.user_id
        # Heuristic: pick the first identifier that is NOT the entity_id.
        simple_ids = _SIMPLE_ID_PATTERN.findall(intent)
        _noise_fields = {
            "the", "a", "an", "from", "to", "in", "of", "for", "is",
            "remove", "delete", "rename", "add", "new", "change", "type",
            "relax", "optional", "tighten", "required", "strict",
            "make", "update", "modify",
        }
        for word in simple_ids:
            if word.lower() not in _noise_fields and word not in entity_id:
                # Assume request context for removed/added/changed fields
                if operation in (
                    "remove", "add", "type_change", "relax", "tighten",
                ):
                    field_path = f"request.{word}"
                else:
                    field_path = word
                break

    return ChangeSpec(
        change_class=change_class,  # type: ignore[arg-type]
        entity_kind=entity_kind,  # type: ignore[arg-type]
        entity_id=entity_id,
        operation=operation,  # type: ignore[arg-type]
        field_path=field_path,
        from_type=None,
        to_type=None,
        notes="",
    )


# ---------------------------------------------------------------------------
# 4.3  Tool Call Planner
# ---------------------------------------------------------------------------

_TOOL1_NAME = "get_ast_dependencies"
_TOOL2_NAME = "trace_data_shape"
_TOOL3_NAME = "find_semantic_neighbors"
_TOOL4_NAME = "get_historical_coupling"
_TOOL5_NAME = "get_covering_tests"


def _files_from_anchors(anchors: list[str]) -> list[str]:
    """Return anchors that look like file paths (based on extension)."""
    file_exts = {
        ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs",
        ".rb", ".cs", ".cpp", ".c", ".h", ".hpp",
    }
    result: list[str] = []
    for anchor in anchors:
        if any(anchor.endswith(ext) for ext in file_exts):
            result.append(anchor)
    return result


def _entry_points_from_anchors(anchors: list[str]) -> list[str]:
    """Heuristically identify entry-point identifiers among *anchors*.

    An anchor is considered an entry point if it contains an HTTP method token
    (e.g. ``"POST /orders"``) or looks like a route path (starts with ``/``).
    """
    entry_points: list[str] = []
    for anchor in anchors:
        anchor_stripped = anchor.strip()
        if _HTTP_METHOD_PATTERN.search(anchor_stripped):
            entry_points.append(anchor_stripped)
        elif anchor_stripped.startswith("/"):
            entry_points.append(anchor_stripped)
    return entry_points


def _has_git_dir(repo_root: str) -> bool:
    """Return ``True`` if a ``.git`` directory exists at *repo_root*."""
    return os.path.isdir(os.path.join(repo_root, ".git"))


def _has_tests(repo_root: str) -> bool:
    """Return ``True`` if a ``tests/`` or ``test/`` directory (or any top-level
    test file) exists under *repo_root*.
    """
    for candidate in ("tests", "test"):
        if os.path.isdir(os.path.join(repo_root, candidate)):
            return True
    # Fallback: scan top-level for test_*.py / *_test.py
    try:
        for name in os.listdir(repo_root):
            if name.startswith("test_") or name.endswith("_test.py"):
                return True
    except OSError:
        pass
    return False


def build_tool_plan(
    change_spec: ChangeSpec,
    diff_result: DiffResult | None,
    anchors: list[str],
    repo_root: str,
) -> list[dict]:
    """Build an ordered plan of MCP tool invocations.

    The planner decides *which* of the five Blast Radius tools to call, in
    what order, and with what inputs, based on the normalised change
    specification, the optional parsed diff, the anchor list, and repository
    metadata.

    **Inclusion rules:**

    * **Tool 1** (``get_ast_dependencies``): **always** included.
    * **Tool 2** (``trace_data_shape``): only when
      ``change_spec.change_class == "api_change"`` **and** entry points can be
      derived from anchors or ``entity_id``.
    * **Tool 3** (``find_semantic_neighbors``): **always** included (cheap).
    * **Tool 4** (``get_historical_coupling``): only when a ``.git`` directory
      exists at *repo_root*.
    * **Tool 5** (``get_covering_tests``): only when a test directory or test
      files exist under *repo_root*.

    Parameters
    ----------
    change_spec:
        The normalised change specification produced by
        :func:`normalize_intent`.
    diff_result:
        Parsed unified-diff (may be ``None`` when no diff was supplied).
    anchors:
        File paths, symbols, or route strings that the caller has identified
        as relevant.
    repo_root:
        Absolute path to the root of the repository being analysed.

    Returns
    -------
    list[dict]
        Ordered list of tool-call descriptors.  Each dict has keys:

        * ``tool_name`` — canonical name of the MCP tool.
        * ``inputs``    — dict of input parameters for the tool.
        * ``priority``  — integer (1 = highest priority / run first).
    """

    plan: list[dict] = []

    # --- Derive target files -----------------------------------------------
    target_files: list[str] = []
    if diff_result is not None:
        target_files.extend(diff_result.changed_files)
    target_files.extend(_files_from_anchors(anchors))
    # De-duplicate while preserving order
    seen: set[str] = set()
    unique_target_files: list[str] = []
    for f in target_files:
        if f not in seen:
            seen.add(f)
            unique_target_files.append(f)
    target_files = unique_target_files

    # --- Tool 1: get_ast_dependencies — ALWAYS -----------------------------
    plan.append(
        {
            "tool_name": _TOOL1_NAME,
            "inputs": {
                "repo_root": repo_root,
                "target_files": target_files,
                "entity_id": change_spec.entity_id,
            },
            "priority": 1,
        }
    )

    # --- Tool 2: trace_data_shape — only for api_change with entry points --
    if change_spec.change_class == "api_change":
        entry_points = _entry_points_from_anchors(anchors)
        # Also pull an entry point from entity_id if it looks like a route
        if _HTTP_METHOD_PATTERN.search(change_spec.entity_id):
            if change_spec.entity_id not in entry_points:
                entry_points.append(change_spec.entity_id)
        if entry_points:
            plan.append(
                {
                    "tool_name": _TOOL2_NAME,
                    "inputs": {
                        "repo_root": repo_root,
                        "entry_points": entry_points,
                        "field_path": change_spec.field_path,
                        "target_files": target_files,
                    },
                    "priority": 2,
                }
            )

    # --- Tool 3: find_semantic_neighbors — ALWAYS (cheap) ------------------
    plan.append(
        {
            "tool_name": _TOOL3_NAME,
            "inputs": {
                "repo_root": repo_root,
                "entity_id": change_spec.entity_id,
                "target_files": target_files,
            },
            "priority": 3,
        }
    )

    # --- Tool 4: get_historical_coupling — only if .git exists -------------
    if _has_git_dir(repo_root):
        plan.append(
            {
                "tool_name": _TOOL4_NAME,
                "inputs": {
                    "repo_root": repo_root,
                    "target_files": target_files,
                },
                "priority": 4,
            }
        )

    # --- Tool 5: get_covering_tests — only if tests exist ------------------
    if _has_tests(repo_root):
        plan.append(
            {
                "tool_name": _TOOL5_NAME,
                "inputs": {
                    "repo_root": repo_root,
                    "target_files": target_files,
                    "entity_id": change_spec.entity_id,
                },
                "priority": 5,
            }
        )

    # Ensure plan is sorted by priority
    plan.sort(key=lambda t: t["priority"])
    return plan
