"""Unit tests for orchestrator functions: normalize_intent, parse_unified_diff,
merge_evidence, and prune_candidates."""

from __future__ import annotations

import pytest

from orchestrator.diff_parser import DiffResult, parse_unified_diff
from orchestrator.merge_evidence import (
    ImpactCandidate,
    ChangeSpec,
    merge_evidence,
    prune_candidates,
)
from orchestrator.normalize import normalize_intent


# =========================================================================
# Helpers
# =========================================================================

_EMPTY_CHANGE_SPEC = ChangeSpec(
    change_class="structural_change",
    entity_kind="function",
    entity_id="unknown",
    operation="refactor",
)


def _make_candidate(
    file: str = "a.py",
    symbol: str | None = "sym",
    confidence: str = "high",
    corroborated: bool = True,
    tool: str = "tool1_ast",
    impact_risk: str = "behavior_change",
    impact_surface: str = "unknown",
    reason: str = "",
    suggested_action: str = "",
) -> ImpactCandidate:
    return ImpactCandidate(
        file=file,
        symbol=symbol,
        confidence=confidence,
        corroborated=corroborated,
        impact_risk=impact_risk,
        impact_surface=impact_surface,
        reason=reason,
        suggested_action=suggested_action,
        evidence=[{"tool": tool, "query_id": "q1", "detail": {}}],
    )


# =========================================================================
# 1. TestNormalizeIntent
# =========================================================================


class TestNormalizeIntent:
    """Tests for normalize_intent(intent, anchors, diff) → ChangeSpec."""

    def test_remove_field_from_api_route(self):
        spec = normalize_intent("Remove user_id from POST /orders", [], "")
        assert spec.change_class == "api_change"
        assert spec.operation == "remove"
        assert spec.entity_id == "POST /orders"
        assert spec.entity_kind == "field"

    def test_rename_field(self):
        spec = normalize_intent("Rename field email to email_address", [], "")
        assert spec.operation == "rename"
        assert spec.entity_kind == "field"
        assert spec.change_class == "api_change"

    def test_add_new_field(self):
        spec = normalize_intent("Add new field phone to User model", [], "")
        assert spec.operation == "add"
        # "field" keyword should set entity_kind to "field"
        assert spec.entity_kind == "field"

    def test_refactor_function(self):
        spec = normalize_intent("Refactor parse_user_id function", [], "")
        assert spec.change_class == "structural_change"
        assert spec.operation == "refactor"
        assert spec.entity_kind == "function"

    def test_type_change_operation(self):
        spec = normalize_intent(
            "Change type of price from int to Decimal", [], ""
        )
        assert spec.operation == "type_change"

    def test_ambiguous_defaults_to_structural_refactor(self):
        spec = normalize_intent("do something unclear here", [], "")
        assert spec.change_class == "structural_change"
        assert spec.entity_kind == "function"
        assert spec.operation == "refactor"

    def test_anchors_provide_entity_id(self):
        spec = normalize_intent(
            "refactor this thing", ["OrderService.handle_payment"], ""
        )
        assert spec.entity_id == "OrderService.handle_payment"


# =========================================================================
# 2. TestParseUnifiedDiff
# =========================================================================

_SINGLE_FILE_DIFF = """\
diff --git a/app/orders.py b/app/orders.py
--- a/app/orders.py
+++ b/app/orders.py
@@ -10,3 +10,4 @@ class Order:
     name: str
     total: int
+    phone: str
"""

_MULTI_FILE_DIFF = """\
diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1,2 +1,3 @@
 x = 1
+y = 2
diff --git a/bar.py b/bar.py
--- a/bar.py
+++ b/bar.py
@@ -5,3 +5,2 @@
 a = 1
-b = 2
"""

_DEV_NULL_DIFF = """\
diff --git a/new_file.py b/new_file.py
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,3 @@
+def hello():
+    pass
"""

_DELETED_FILE_DIFF = """\
diff --git a/old_file.py b/old_file.py
--- a/old_file.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def goodbye():
-    pass
"""

_DEF_CLASS_DIFF = """\
diff --git a/module.py b/module.py
--- a/module.py
+++ b/module.py
@@ -1,3 +1,5 @@
+def process_data():
+    pass
+class UserManager:
+    pass
"""


class TestParseUnifiedDiff:
    """Tests for parse_unified_diff(diff) → DiffResult."""

    def test_single_file_diff(self):
        result = parse_unified_diff(_SINGLE_FILE_DIFF)
        assert "app/orders.py" in result.changed_files
        assert result.added_lines.get("app/orders.py") == [12]

    def test_multi_file_diff(self):
        result = parse_unified_diff(_MULTI_FILE_DIFF)
        assert sorted(result.changed_files) == ["bar.py", "foo.py"]
        assert result.added_lines.get("foo.py") == [2]
        assert result.removed_lines.get("bar.py") == [6]

    def test_empty_diff_returns_empty(self):
        result = parse_unified_diff("")
        assert result.changed_files == []
        assert result.added_lines == {}
        assert result.removed_lines == {}
        assert result.key_identifiers == []

    def test_strips_a_b_prefixes(self):
        result = parse_unified_diff(_SINGLE_FILE_DIFF)
        for f in result.changed_files:
            assert not f.startswith("a/")
            assert not f.startswith("b/")

    def test_handles_dev_null_new_file(self):
        result = parse_unified_diff(_DEV_NULL_DIFF)
        assert "new_file.py" in result.changed_files

    def test_handles_dev_null_deleted_file(self):
        result = parse_unified_diff(_DELETED_FILE_DIFF)
        assert "old_file.py" in result.changed_files

    def test_extracts_key_identifiers_from_def_class(self):
        result = parse_unified_diff(_DEF_CLASS_DIFF)
        assert "process_data" in result.key_identifiers
        assert "UserManager" in result.key_identifiers


# =========================================================================
# 3. TestMergeEvidence
# =========================================================================

def _empty_tool_result() -> dict:
    return {}


def _tool1_result_with_edge(
    source: str = "src_node",
    target: str = "tgt_node",
    edge_type: str = "calls",
    file: str = "app/service.py",
) -> dict:
    return {
        "nodes": [
            {"id": source, "file": "app/main.py", "name": source, "kind": "function"},
            {"id": target, "file": file, "name": target, "kind": "function", "qualified_name": target},
        ],
        "edges": [
            {
                "id": "e1",
                "source": source,
                "target": target,
                "type": edge_type,
                "confidence": 0.9,
            }
        ],
    }


def _tool3_result_with_neighbor(
    file: str = "app/utils.py",
    symbol: str = "helper_fn",
    score: float = 0.75,
) -> dict:
    return {
        "neighbors": [
            {
                "neighbor_id": "n1",
                "file": file,
                "symbol": symbol,
                "score": score,
                "method": "cosine",
                "rationale_snippet": "similar code",
            }
        ]
    }


class TestMergeEvidence:
    """Tests for merge_evidence(...)."""

    def test_tool1_only_produces_corroborated_candidates(self):
        result = merge_evidence(
            tool1_result=_tool1_result_with_edge(),
            tool2_result=_empty_tool_result(),
            tool3_result=_empty_tool_result(),
            tool4_result=_empty_tool_result(),
            tool5_result=_empty_tool_result(),
            change_spec=_EMPTY_CHANGE_SPEC,
        )
        assert len(result) >= 1
        for c in result:
            assert c.corroborated is True

    def test_tool3_only_produces_uncorroborated_candidates(self):
        result = merge_evidence(
            tool1_result=_empty_tool_result(),
            tool2_result=_empty_tool_result(),
            tool3_result=_tool3_result_with_neighbor(),
            tool4_result=_empty_tool_result(),
            tool5_result=_empty_tool_result(),
            change_spec=_EMPTY_CHANGE_SPEC,
        )
        assert len(result) >= 1
        for c in result:
            assert c.corroborated is False

    def test_none_like_tool_results_handled_gracefully(self):
        result = merge_evidence(
            tool1_result={},
            tool2_result={},
            tool3_result={},
            tool4_result={},
            tool5_result={},
            change_spec=_EMPTY_CHANGE_SPEC,
        )
        assert result == []

    def test_deduplication_by_file_symbol(self):
        # Two edges pointing to the same (file, symbol) should be merged.
        tool1 = {
            "nodes": [
                {"id": "a", "file": "x.py", "name": "a", "kind": "function"},
                {"id": "b", "file": "y.py", "name": "target_fn", "kind": "function",
                 "qualified_name": "target_fn"},
            ],
            "edges": [
                {"id": "e1", "source": "a", "target": "b", "type": "calls", "confidence": 0.6},
                {"id": "e2", "source": "a", "target": "b", "type": "imports", "confidence": 0.9},
            ],
        }
        result = merge_evidence(
            tool1_result=tool1,
            tool2_result=_empty_tool_result(),
            tool3_result=_empty_tool_result(),
            tool4_result=_empty_tool_result(),
            tool5_result=_empty_tool_result(),
            change_spec=_EMPTY_CHANGE_SPEC,
        )
        # Both edges target the same (file=y.py, symbol=target_fn), so they merge.
        matching = [c for c in result if c.file == "y.py" and c.symbol == "target_fn"]
        assert len(matching) == 1
        # Evidence list should contain entries from both edges
        assert len(matching[0].evidence) == 2

    def test_merge_promotes_higher_risk_and_confidence(self):
        # Create two candidates for same (file, symbol) with different levels
        tool1 = {
            "nodes": [
                {"id": "s", "file": "s.py", "name": "s", "kind": "function"},
                {"id": "t", "file": "t.py", "name": "t_fn", "kind": "function",
                 "qualified_name": "t_fn"},
            ],
            "edges": [
                {"id": "e1", "source": "s", "target": "t", "type": "calls", "confidence": 0.4},
                {"id": "e2", "source": "s", "target": "t", "type": "inherits", "confidence": 0.95},
            ],
        }
        result = merge_evidence(
            tool1_result=tool1,
            tool2_result=_empty_tool_result(),
            tool3_result=_empty_tool_result(),
            tool4_result=_empty_tool_result(),
            tool5_result=_empty_tool_result(),
            change_spec=_EMPTY_CHANGE_SPEC,
        )
        matching = [c for c in result if c.file == "t.py" and c.symbol == "t_fn"]
        assert len(matching) == 1
        # inherits → "breaking" should win over calls → "behavior_change"
        assert matching[0].impact_risk == "breaking"
        # 0.95 → "high" should win over 0.4 → "low"
        assert matching[0].confidence == "high"


# =========================================================================
# 4. TestPruneCandidates
# =========================================================================


class TestPruneCandidates:
    """Tests for prune_candidates(candidates, change_spec)."""

    def test_removes_low_confidence_structural_only(self):
        """Low-confidence, corroborated, Tool-1-only candidates that don't
        match the changed field should be pruned."""
        spec = ChangeSpec(
            change_class="api_change",
            entity_kind="field",
            entity_id="POST /orders",
            operation="remove",
            field_path="request.user_id",
        )
        low_structural = _make_candidate(
            file="unrelated.py",
            symbol="unrelated_fn",
            confidence="low",
            corroborated=True,
            tool="tool1_ast",
        )
        result = prune_candidates([low_structural], spec)
        assert len(result) == 0

    def test_keeps_high_confidence_candidates(self):
        spec = ChangeSpec(
            change_class="structural_change",
            entity_kind="function",
            entity_id="parse_user_id",
            operation="refactor",
        )
        high = _make_candidate(confidence="high", corroborated=True)
        result = prune_candidates([high], spec)
        assert len(result) == 1

    def test_semantic_only_forced_uncorroborated(self):
        """Candidates backed only by Tool 3 must have corroborated=False."""
        spec = _EMPTY_CHANGE_SPEC
        semantic = _make_candidate(
            corroborated=True,  # intentionally wrong — prune should fix
            tool="tool3_semantic",
        )
        result = prune_candidates([semantic], spec)
        assert len(result) == 1
        assert result[0].corroborated is False

    def test_deterministic_sort_order(self):
        """Sorted by (corroborated DESC, confidence DESC, file ASC, symbol ASC)."""
        spec = _EMPTY_CHANGE_SPEC
        c1 = _make_candidate(file="b.py", symbol="z", confidence="medium", corroborated=True)
        c2 = _make_candidate(file="a.py", symbol="a", confidence="high", corroborated=True)
        c3 = _make_candidate(file="c.py", symbol="x", confidence="low", corroborated=False,
                             tool="tool3_semantic")

        result = prune_candidates([c1, c2, c3], spec)
        # Corroborated first, then by confidence desc, then file asc
        assert result[0].file == "a.py"   # corroborated + high
        assert result[1].file == "b.py"   # corroborated + medium
        assert result[2].file == "c.py"   # uncorroborated
