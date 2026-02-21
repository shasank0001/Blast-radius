"""Blast Radius MCP Server — registers 5 analysis tools."""

from __future__ import annotations

import json
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

from blast_radius_mcp.ids import canonical_json, compute_diff_hash, compute_query_id
from blast_radius_mcp.logging_config import get_logger, setup_logging
from blast_radius_mcp.schemas.common import (
    RepoFingerprint,
    StructuredError,
    ToolResponseEnvelope,
)
from blast_radius_mcp.schemas.tool1_ast import (
    CacheStats,
    Tool1Request,
    Tool1Result,
    Tool1Stats,
)
from blast_radius_mcp.schemas.tool2_lineage import Tool2Request, Tool2Result, Tool2Stats
from blast_radius_mcp.schemas.tool3_semantic import (
    IndexStats,
    Tool3Request,
    Tool3Result,
)
from blast_radius_mcp.schemas.tool4_coupling import (
    HistoryStats,
    Tool4Request,
    Tool4Result,
)
from blast_radius_mcp.schemas.tool5_tests import (
    SelectionStats,
    Tool5Request,
    Tool5Result,
)
from blast_radius_mcp.settings import settings
from blast_radius_mcp.validation.validate import (
    make_validation_error_response,
    validate_request,
    validate_tool_inputs,
)

logger = get_logger("server")

mcp = FastMCP("blast-radius")

# Placeholder repo fingerprint for stubs
_STUB_FINGERPRINT = RepoFingerprint(
    git_head=None,
    dirty=True,
    fingerprint_hash="stub",
)


def _build_stub_response(
    tool_name: str,
    result_dict: dict[str, Any],
    timing_ms: int,
    repo_fingerprint: RepoFingerprint | None = None,
    errors: list[StructuredError] | None = None,
) -> dict[str, Any]:
    """Build a minimal valid ToolResponseEnvelope dict."""
    fp = repo_fingerprint or _STUB_FINGERPRINT
    query_id = compute_query_id(tool_name, canonical_json(result_dict), fp.fingerprint_hash)
    envelope = ToolResponseEnvelope(
        schema_version=settings.SCHEMA_VERSION,
        tool_name=tool_name,
        run_id="stub_run_id",
        query_id=query_id,
        repo_fingerprint=fp,
        cached=False,
        timing_ms=timing_ms,
        result=result_dict,
        errors=errors or [],
    )
    return json.loads(envelope.model_dump_json(by_alias=True))


def _parse_envelope(raw: str | dict) -> dict[str, Any]:
    """Parse raw input into a dict."""
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


# ── Tool 1: AST Structural Engine ───────────────────────────────────

@mcp.tool(
    name="get_ast_dependencies",
    description="Analyze Python source files and return AST nodes (modules, classes, functions, methods) and edges (imports, calls, inheritance, references) with evidence spans.",
)
async def get_ast_dependencies(request: str) -> str:
    """Get AST-based structural dependencies for Python files."""
    start = time.perf_counter()
    try:
        envelope_dict = _parse_envelope(request)
        envelope = validate_request(envelope_dict, "get_ast_dependencies")
        validated_inputs = validate_tool_inputs(envelope.inputs, "get_ast_dependencies")

        # Stub result
        result = Tool1Result(
            language="python",
            repo_root=envelope.repo_root,
            files=[],
            nodes=[],
            edges=[],
            diagnostics=[],
            stats=Tool1Stats(
                target_files=0,
                parsed_ok=0,
                parsed_error=0,
                nodes=0,
                edges=0,
                duration_ms=0,
                cache=CacheStats(hits=0, misses=0),
            ),
        )
        timing_ms = int((time.perf_counter() - start) * 1000)
        response = _build_stub_response(
            "get_ast_dependencies",
            json.loads(result.model_dump_json(by_alias=True)),
            timing_ms,
        )
        return json.dumps(response)

    except Exception as e:
        timing_ms = int((time.perf_counter() - start) * 1000)
        error = make_validation_error_response(e, "get_ast_dependencies")
        response = _build_stub_response(
            "get_ast_dependencies", {}, timing_ms, errors=[error]
        )
        return json.dumps(response)


# ── Tool 2: Data Lineage Engine ─────────────────────────────────────

@mcp.tool(
    name="trace_data_shape",
    description="Trace data field/path usage through API handlers, detecting read sites, write sites, validations, and transforms with breakage flags.",
)
async def trace_data_shape(request: str) -> str:
    """Trace field/path lineage through API handlers."""
    start = time.perf_counter()
    try:
        envelope_dict = _parse_envelope(request)
        envelope = validate_request(envelope_dict, "trace_data_shape")
        validated_inputs = validate_tool_inputs(envelope.inputs, "trace_data_shape")

        result = Tool2Result(
            changed_field=validated_inputs.field_path,
            entry_points_resolved=[],
            read_sites=[],
            write_sites=[],
            validations=[],
            transforms=[],
            diagnostics=[],
            stats=Tool2Stats(files_scanned=0, sites_emitted=0, truncated=False),
        )
        timing_ms = int((time.perf_counter() - start) * 1000)
        response = _build_stub_response(
            "trace_data_shape",
            json.loads(result.model_dump_json(by_alias=True)),
            timing_ms,
        )
        return json.dumps(response)

    except Exception as e:
        timing_ms = int((time.perf_counter() - start) * 1000)
        error = make_validation_error_response(e, "trace_data_shape")
        response = _build_stub_response(
            "trace_data_shape", {}, timing_ms, errors=[error]
        )
        return json.dumps(response)


# ── Tool 3: Semantic Neighbor Search ────────────────────────────────

@mcp.tool(
    name="find_semantic_neighbors",
    description="Find semantically similar code chunks using embeddings or BM25 fallback. Results are uncorroborated by default.",
)
async def find_semantic_neighbors(request: str) -> str:
    """Find semantic neighbors for a query."""
    start = time.perf_counter()
    try:
        envelope_dict = _parse_envelope(request)
        envelope = validate_request(envelope_dict, "find_semantic_neighbors")
        validated_inputs = validate_tool_inputs(envelope.inputs, "find_semantic_neighbors")

        result = Tool3Result(
            retrieval_mode="bm25_fallback",
            neighbors=[],
            index_stats=IndexStats(chunks_total=0, chunks_scanned=0, backend="bm25"),
            diagnostics=[],
        )
        timing_ms = int((time.perf_counter() - start) * 1000)
        response = _build_stub_response(
            "find_semantic_neighbors",
            json.loads(result.model_dump_json(by_alias=True)),
            timing_ms,
        )
        return json.dumps(response)

    except Exception as e:
        timing_ms = int((time.perf_counter() - start) * 1000)
        error = make_validation_error_response(e, "find_semantic_neighbors")
        response = _build_stub_response(
            "find_semantic_neighbors", {}, timing_ms, errors=[error]
        )
        return json.dumps(response)


# ── Tool 4: Temporal Coupling ───────────────────────────────────────

@mcp.tool(
    name="get_historical_coupling",
    description="Analyze git history to find files that frequently co-change with target files (temporal coupling).",
)
async def get_historical_coupling(request: str) -> str:
    """Get historically coupled files from git history."""
    start = time.perf_counter()
    try:
        envelope_dict = _parse_envelope(request)
        envelope = validate_request(envelope_dict, "get_historical_coupling")
        validated_inputs = validate_tool_inputs(envelope.inputs, "get_historical_coupling")

        result = Tool4Result(
            targets=[],
            couplings=[],
            history_stats=HistoryStats(
                commits_scanned=0, commits_used=0, renames_followed=0
            ),
            diagnostics=[],
        )
        timing_ms = int((time.perf_counter() - start) * 1000)
        response = _build_stub_response(
            "get_historical_coupling",
            json.loads(result.model_dump_json(by_alias=True)),
            timing_ms,
        )
        return json.dumps(response)

    except Exception as e:
        timing_ms = int((time.perf_counter() - start) * 1000)
        error = make_validation_error_response(e, "get_historical_coupling")
        response = _build_stub_response(
            "get_historical_coupling", {}, timing_ms, errors=[error]
        )
        return json.dumps(response)


# ── Tool 5: Test Impact Analyzer ────────────────────────────────────

@mcp.tool(
    name="get_covering_tests",
    description="Find and rank tests that cover impacted code nodes, with evidence-based scoring.",
)
async def get_covering_tests(request: str) -> str:
    """Get ranked covering tests for impacted nodes."""
    start = time.perf_counter()
    try:
        envelope_dict = _parse_envelope(request)
        envelope = validate_request(envelope_dict, "get_covering_tests")
        validated_inputs = validate_tool_inputs(envelope.inputs, "get_covering_tests")

        result = Tool5Result(
            tests=[],
            unmatched_impacts=[],
            selection_stats=SelectionStats(
                tests_considered=0, tests_selected=0, high_confidence=0
            ),
            diagnostics=[],
        )
        timing_ms = int((time.perf_counter() - start) * 1000)
        response = _build_stub_response(
            "get_covering_tests",
            json.loads(result.model_dump_json(by_alias=True)),
            timing_ms,
        )
        return json.dumps(response)

    except Exception as e:
        timing_ms = int((time.perf_counter() - start) * 1000)
        error = make_validation_error_response(e, "get_covering_tests")
        response = _build_stub_response(
            "get_covering_tests", {}, timing_ms, errors=[error]
        )
        return json.dumps(response)


def main() -> None:
    """Start the Blast Radius MCP server."""
    setup_logging(settings.LOG_LEVEL)
    logger.info("Starting Blast Radius MCP server")
    mcp.run()
