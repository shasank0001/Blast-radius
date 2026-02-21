"""Golden fixture tests for all 5 tool schemas + common types."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from blast_radius_mcp.schemas.common import (
    Location,
    Position,
    Range,
    RepoFingerprint,
    StructuredError,
    ToolRequestEnvelope,
    ToolResponseEnvelope,
)
from blast_radius_mcp.schemas.tool1_ast import (
    ASTEdge,
    ASTNode,
    EdgeMetadata,
    EdgeResolution,
    FileInfo,
    Tool1Request,
    Tool1Result,
    Tool1Stats,
    CacheStats,
    TargetRef,
)
from blast_radius_mcp.schemas.tool2_lineage import (
    Tool2Request,
    Tool2Result,
    Tool2Stats,
    EntryPointResolved,
    ReadWriteSite,
    Breakage,
)
from blast_radius_mcp.schemas.tool3_semantic import (
    Tool3Request,
    Tool3Result,
    Neighbor,
    IndexStats,
    Span,
)
from blast_radius_mcp.schemas.tool4_coupling import (
    Tool4Request,
    Tool4Result,
    Coupling,
    CouplingTarget,
    ExampleCommit,
    HistoryStats,
)
from blast_radius_mcp.schemas.tool5_tests import (
    Tool5Request,
    Tool5Result,
    TestItem,
    TestReason,
    SelectionStats,
    ImpactedNode,
)
from blast_radius_mcp.validation.validate import (
    validate_request,
    validate_tool_inputs,
    validate_response,
    VALID_TOOL_NAMES,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file."""
    return json.loads((FIXTURES_DIR / name).read_text())


# ── Common schema tests ─────────────────────────────────────────────


class TestCommonSchemas:
    def test_position_valid(self):
        p = Position(line=1, col=0)
        assert p.line == 1
        assert p.col == 0
        assert p.offset == -1

    def test_position_with_offset(self):
        p = Position(line=10, col=4, offset=120)
        assert p.offset == 120

    def test_range_valid(self):
        r = Range(
            start=Position(line=1, col=0),
            end=Position(line=10, col=0),
        )
        assert r.start.line == 1
        assert r.end.line == 10

    def test_location_valid(self):
        loc = Location(
            file="app/main.py",
            range=Range(
                start=Position(line=1, col=0),
                end=Position(line=10, col=0),
            ),
        )
        assert loc.file == "app/main.py"

    def test_repo_fingerprint(self):
        fp = RepoFingerprint(git_head="abc123", dirty=False, fingerprint_hash="hash")
        assert fp.git_head == "abc123"

    def test_repo_fingerprint_no_git(self):
        fp = RepoFingerprint(git_head=None, dirty=True, fingerprint_hash="hash")
        assert fp.git_head is None

    def test_structured_error(self):
        err = StructuredError(code="validation_error", message="bad input")
        assert err.retryable is False

    def test_envelope_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            ToolRequestEnvelope(
                repo_root=".",
                inputs={},
                unknown_field="bad",
            )

    def test_response_envelope_rejects_extra(self):
        with pytest.raises(ValidationError):
            ToolResponseEnvelope(
                tool_name="x",
                run_id="x",
                query_id="x",
                repo_fingerprint=RepoFingerprint(
                    git_head=None, dirty=True, fingerprint_hash="h"
                ),
                cached=False,
                timing_ms=0,
                result={},
                extra_bad="no",
            )


# ── Tool 1 fixture tests ────────────────────────────────────────────


class TestTool1Fixtures:
    def test_request_parses(self):
        data = load_fixture("tool1_request.json")
        envelope = ToolRequestEnvelope.model_validate(data)
        inputs = Tool1Request.model_validate(envelope.inputs)
        assert len(inputs.target_files) == 2
        assert inputs.options.parse_mode == "python_ast"

    def test_response_parses(self):
        data = load_fixture("tool1_response.json")
        envelope = ToolResponseEnvelope.model_validate(data)
        result = Tool1Result.model_validate(envelope.result)
        assert result.language == "python"
        assert len(result.files) == 1
        assert len(result.nodes) == 1
        assert len(result.edges) == 1
        assert result.stats.target_files == 2

    def test_response_round_trip(self):
        data = load_fixture("tool1_response.json")
        envelope = ToolResponseEnvelope.model_validate(data)
        result = Tool1Result.model_validate(envelope.result)
        # Re-serialize and re-parse
        reserialized = json.loads(result.model_dump_json(by_alias=True))
        result2 = Tool1Result.model_validate(reserialized)
        assert result == result2

    def test_request_rejects_extra_field(self):
        data = load_fixture("tool1_request.json")
        data["inputs"]["bad_field"] = True
        envelope = ToolRequestEnvelope.model_validate(data)
        with pytest.raises(ValidationError):
            Tool1Request.model_validate(envelope.inputs)

    def test_request_rejects_bad_type(self):
        with pytest.raises(ValidationError):
            Tool1Request(target_files="not_a_list")


# ── Tool 2 fixture tests ────────────────────────────────────────────


class TestTool2Fixtures:
    def test_request_parses(self):
        data = load_fixture("tool2_request.json")
        envelope = ToolRequestEnvelope.model_validate(data)
        inputs = Tool2Request.model_validate(envelope.inputs)
        assert inputs.field_path == "OrderRequest.user_id"
        assert len(inputs.entry_points) == 1

    def test_response_parses(self):
        data = load_fixture("tool2_response.json")
        envelope = ToolResponseEnvelope.model_validate(data)
        result = Tool2Result.model_validate(envelope.result)
        assert result.changed_field == "OrderRequest.user_id"
        assert len(result.entry_points_resolved) == 1
        assert len(result.read_sites) == 1
        assert result.read_sites[0].breakage.if_removed is True

    def test_response_round_trip(self):
        data = load_fixture("tool2_response.json")
        envelope = ToolResponseEnvelope.model_validate(data)
        result = Tool2Result.model_validate(envelope.result)
        reserialized = json.loads(result.model_dump_json(by_alias=True))
        result2 = Tool2Result.model_validate(reserialized)
        assert result == result2

    def test_request_rejects_empty_entry_points(self):
        with pytest.raises(ValidationError):
            Tool2Request(field_path="X.y", entry_points=[])


# ── Tool 3 fixture tests ────────────────────────────────────────────


class TestTool3Fixtures:
    def test_request_parses(self):
        data = load_fixture("tool3_request.json")
        envelope = ToolRequestEnvelope.model_validate(data)
        inputs = Tool3Request.model_validate(envelope.inputs)
        assert "user_id" in inputs.query_text
        assert inputs.options.top_k == 25

    def test_response_parses(self):
        data = load_fixture("tool3_response.json")
        envelope = ToolResponseEnvelope.model_validate(data)
        result = Tool3Result.model_validate(envelope.result)
        assert result.retrieval_mode == "bm25_fallback"
        assert len(result.neighbors) == 1
        assert result.neighbors[0].uncorroborated is True

    def test_response_round_trip(self):
        data = load_fixture("tool3_response.json")
        envelope = ToolResponseEnvelope.model_validate(data)
        result = Tool3Result.model_validate(envelope.result)
        reserialized = json.loads(result.model_dump_json(by_alias=True))
        result2 = Tool3Result.model_validate(reserialized)
        assert result == result2

    def test_request_rejects_short_query(self):
        with pytest.raises(ValidationError):
            Tool3Request(query_text="ab")


# ── Tool 4 fixture tests ────────────────────────────────────────────


class TestTool4Fixtures:
    def test_request_parses(self):
        data = load_fixture("tool4_request.json")
        envelope = ToolRequestEnvelope.model_validate(data)
        inputs = Tool4Request.model_validate(envelope.inputs)
        assert len(inputs.file_paths) == 1
        assert inputs.options.window_commits == 500

    def test_response_parses(self):
        data = load_fixture("tool4_response.json")
        envelope = ToolResponseEnvelope.model_validate(data)
        result = Tool4Result.model_validate(envelope.result)
        assert len(result.targets) == 1
        assert len(result.couplings) == 1
        assert result.couplings[0].weight == 0.78

    def test_response_round_trip(self):
        data = load_fixture("tool4_response.json")
        envelope = ToolResponseEnvelope.model_validate(data)
        result = Tool4Result.model_validate(envelope.result)
        reserialized = json.loads(result.model_dump_json(by_alias=True))
        result2 = Tool4Result.model_validate(reserialized)
        assert result == result2

    def test_request_rejects_empty_file_paths(self):
        with pytest.raises(ValidationError):
            Tool4Request(file_paths=[])


# ── Tool 5 fixture tests ────────────────────────────────────────────


class TestTool5Fixtures:
    def test_request_parses(self):
        data = load_fixture("tool5_request.json")
        envelope = ToolRequestEnvelope.model_validate(data)
        inputs = Tool5Request.model_validate(envelope.inputs)
        assert len(inputs.impacted_nodes) == 1
        assert inputs.impacted_nodes[0].symbol == "create_order"

    def test_response_parses(self):
        data = load_fixture("tool5_response.json")
        envelope = ToolResponseEnvelope.model_validate(data)
        result = Tool5Result.model_validate(envelope.result)
        assert len(result.tests) == 1
        assert result.tests[0].rank == 1
        assert result.tests[0].confidence == "high"
        assert len(result.tests[0].reasons) == 2

    def test_response_round_trip(self):
        data = load_fixture("tool5_response.json")
        envelope = ToolResponseEnvelope.model_validate(data)
        result = Tool5Result.model_validate(envelope.result)
        reserialized = json.loads(result.model_dump_json(by_alias=True))
        result2 = Tool5Result.model_validate(reserialized)
        assert result == result2

    def test_request_rejects_empty_impacted_nodes(self):
        with pytest.raises(ValidationError):
            Tool5Request(impacted_nodes=[])


# ── Validation layer tests ──────────────────────────────────────────


class TestValidation:
    def test_validate_request_tool1(self):
        data = load_fixture("tool1_request.json")
        envelope = validate_request(data, "get_ast_dependencies")
        assert envelope.schema_version == "v1"

    def test_validate_tool_inputs_tool1(self):
        data = load_fixture("tool1_request.json")
        inputs = validate_tool_inputs(data["inputs"], "get_ast_dependencies")
        assert hasattr(inputs, "target_files")

    def test_validate_request_unknown_tool(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            validate_request({}, "nonexistent_tool")

    def test_validate_tool_inputs_unknown_tool(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            validate_tool_inputs({}, "nonexistent_tool")

    def test_validate_request_invalid_envelope(self):
        with pytest.raises(ValidationError):
            validate_request({"bad": "data"}, "get_ast_dependencies")

    def test_validate_response_tool1(self):
        data = load_fixture("tool1_response.json")
        envelope = validate_response(data, "get_ast_dependencies")
        assert envelope.tool_name == "get_ast_dependencies"

    def test_validate_response_tool_name_mismatch(self):
        data = load_fixture("tool1_response.json")
        with pytest.raises(ValueError, match="tool_name mismatch"):
            validate_response(data, "trace_data_shape")

    def test_validate_response_result_schema_mismatch(self):
        data = load_fixture("tool2_response.json")
        data["tool_name"] = "get_ast_dependencies"
        with pytest.raises(ValidationError):
            validate_response(data, "get_ast_dependencies")

    def test_all_tool_names_registered(self):
        expected = {
            "get_ast_dependencies",
            "trace_data_shape",
            "find_semantic_neighbors",
            "get_historical_coupling",
            "get_covering_tests",
        }
        assert VALID_TOOL_NAMES == expected


# ── IDs tests ────────────────────────────────────────────────────────


class TestIDs:
    def test_canonical_json_deterministic(self):
        from blast_radius_mcp.ids import canonical_json
        obj = {"b": 2, "a": 1}
        assert canonical_json(obj) == '{"a":1,"b":2}'

    def test_compute_run_id_deterministic(self):
        from blast_radius_mcp.ids import compute_run_id
        id1 = compute_run_id("v1", "remove user_id", ["anchor1"], "diff_hash", "fp_hash")
        id2 = compute_run_id("v1", "remove user_id", ["anchor1"], "diff_hash", "fp_hash")
        assert id1 == id2

    def test_compute_run_id_differs_on_input(self):
        from blast_radius_mcp.ids import compute_run_id
        id1 = compute_run_id("v1", "remove user_id", ["anchor1"], "diff_hash", "fp_hash")
        id2 = compute_run_id("v1", "remove user_id", ["anchor2"], "diff_hash", "fp_hash")
        assert id1 != id2

    def test_compute_query_id_deterministic(self):
        from blast_radius_mcp.ids import compute_query_id
        id1 = compute_query_id("tool1", '{"a":1}', "fp")
        id2 = compute_query_id("tool1", '{"a":1}', "fp")
        assert id1 == id2

    def test_normalize_intent(self):
        from blast_radius_mcp.ids import normalize_intent
        assert normalize_intent("  Remove   USER_ID  ") == "remove user_id"

    def test_compute_diff_hash_normalizes_line_endings(self):
        from blast_radius_mcp.ids import compute_diff_hash
        h1 = compute_diff_hash("line1\nline2\n")
        h2 = compute_diff_hash("line1\r\nline2\r\n")
        assert h1 == h2

    def test_compute_cache_key_deterministic(self):
        from blast_radius_mcp.ids import compute_cache_key
        k1 = compute_cache_key("tool1", "v1", '{"a":1}', "fp", "1.0.0")
        k2 = compute_cache_key("tool1", "v1", '{"a":1}', "fp", "1.0.0")
        assert k1 == k2

    def test_compute_cache_key_differs_on_version(self):
        from blast_radius_mcp.ids import compute_cache_key
        k1 = compute_cache_key("tool1", "v1", '{"a":1}', "fp", "1.0.0")
        k2 = compute_cache_key("tool1", "v1", '{"a":1}', "fp", "2.0.0")
        assert k1 != k2


# ── Settings tests ───────────────────────────────────────────────────


class TestSettings:
    def test_settings_load_defaults(self):
        from blast_radius_mcp.settings import Settings
        s = Settings()
        assert s.SCHEMA_VERSION == "v1"
        assert s.LOG_LEVEL == "INFO"
        assert s.OPENAI_EMBEDDING_MODEL == "text-embedding-3-small"


# ── JSON Schema export tests ────────────────────────────────────────


class TestJsonSchemaExport:
    @pytest.mark.parametrize("model_cls", [
        Tool1Request, Tool1Result,
        Tool2Request, Tool2Result,
        Tool3Request, Tool3Result,
        Tool4Request, Tool4Result,
        Tool5Request, Tool5Result,
    ])
    def test_json_schema_export(self, model_cls):
        schema = model_cls.model_json_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema or "$defs" in schema
