"""Tests for orchestrator planner/schema normalization contract."""

from __future__ import annotations

from blast_radius_mcp.schemas.tool1_ast import Tool1Request
from blast_radius_mcp.schemas.tool2_lineage import Tool2Request
from blast_radius_mcp.schemas.tool3_semantic import Tool3Request
from blast_radius_mcp.schemas.tool4_coupling import Tool4Request
from blast_radius_mcp.schemas.tool5_tests import Tool5Request
from orchestrator.diff_parser import DiffResult
from orchestrator.normalize import ChangeSpec, build_tool_plan


TOOL1 = "get_ast_dependencies"
TOOL2 = "trace_data_shape"
TOOL3 = "find_semantic_neighbors"
TOOL4 = "get_historical_coupling"
TOOL5 = "get_covering_tests"


_REQUEST_MODELS = {
    TOOL1: Tool1Request,
    TOOL2: Tool2Request,
    TOOL3: Tool3Request,
    TOOL4: Tool4Request,
    TOOL5: Tool5Request,
}


def _by_tool_name(plan: list[dict]) -> dict[str, dict]:
    return {entry["tool_name"]: entry for entry in plan}


def test_build_tool_plan_inputs_validate_against_tool_request_schemas(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "tests").mkdir()

    change_spec = ChangeSpec(
        change_class="api_change",
        entity_kind="field",
        entity_id="POST /orders",
        operation="remove",
        field_path="request.user_id",
    )
    diff_result = DiffResult(changed_files=["api/orders.py"])
    anchors = ["POST /orders", "/health", "api/orders.py"]

    plan = build_tool_plan(change_spec, diff_result, anchors, str(tmp_path))
    by_tool_name = _by_tool_name(plan)

    assert {TOOL1, TOOL2, TOOL3, TOOL4, TOOL5}.issubset(set(by_tool_name.keys()))

    validated_tool1 = Tool1Request.model_validate(by_tool_name[TOOL1]["inputs"])
    validated_tool2 = Tool2Request.model_validate(by_tool_name[TOOL2]["inputs"])
    validated_tool3 = Tool3Request.model_validate(by_tool_name[TOOL3]["inputs"])
    validated_tool4 = Tool4Request.model_validate(by_tool_name[TOOL4]["inputs"])
    validated_tool5 = Tool5Request.model_validate(by_tool_name[TOOL5]["inputs"])

    assert validated_tool1.target_files == ["api/orders.py"]
    assert all(entry_point.startswith("route:") for entry_point in validated_tool2.entry_points)
    assert "route:POST /orders" in validated_tool2.entry_points
    assert "route:GET /health" in validated_tool2.entry_points
    assert validated_tool3.scope.paths == ["api/orders.py"]
    assert validated_tool4.file_paths == ["api/orders.py"]
    assert [node.file for node in validated_tool5.impacted_nodes] == ["api/orders.py"]


def test_build_tool_plan_skips_tool2_when_field_path_missing(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "tests").mkdir()

    change_spec = ChangeSpec(
        change_class="api_change",
        entity_kind="field",
        entity_id="POST /orders",
        operation="remove",
        field_path=None,
    )
    diff_result = DiffResult(changed_files=["api/orders.py"])
    anchors = ["POST /orders", "api/orders.py"]

    plan = build_tool_plan(change_spec, diff_result, anchors, str(tmp_path))
    tool_names = [entry["tool_name"] for entry in plan]

    assert TOOL2 not in tool_names



def test_build_tool_plan_skips_tool4_and_tool5_when_target_files_empty(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "tests").mkdir()

    change_spec = ChangeSpec(
        change_class="api_change",
        entity_kind="field",
        entity_id="POST /orders",
        operation="remove",
        field_path="request.user_id",
    )
    diff_result = None
    anchors = ["POST /orders"]

    plan = build_tool_plan(change_spec, diff_result, anchors, str(tmp_path))
    tool_names = [entry["tool_name"] for entry in plan]

    assert TOOL2 in tool_names
    assert TOOL4 not in tool_names
    assert TOOL5 not in tool_names

    for entry in plan:
        model = _REQUEST_MODELS.get(entry["tool_name"])
        if model is not None:
            model.model_validate(entry["inputs"])
