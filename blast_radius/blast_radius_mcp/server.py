"""Blast Radius MCP Server — registers 5 analysis tools."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from blast_radius_mcp.cache.keys import build_cache_key
from blast_radius_mcp.cache.sqlite import CacheDB
from blast_radius_mcp.ids import canonical_json, compute_query_id
from blast_radius_mcp.logging_config import get_logger, setup_logging
from blast_radius_mcp.repo.fingerprint import compute_repo_fingerprint
from blast_radius_mcp.schemas.common import (
    RepoFingerprint,
    StructuredError,
    ToolResponseEnvelope,
)
from blast_radius_mcp.schemas.tool1_ast import (
    CacheStats,
    Tool1Result,
    Tool1Stats,
)
from blast_radius_mcp.schemas.tool2_lineage import Tool2Result, Tool2Stats
from blast_radius_mcp.schemas.tool3_semantic import (
    IndexStats,
    Tool3Result,
)
from blast_radius_mcp.schemas.tool4_coupling import (
    HistoryStats,
    Tool4Result,
)
from blast_radius_mcp.schemas.tool5_tests import (
    SelectionStats,
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

# Lazy-initialized cache singleton
_cache_db: CacheDB | None = None


def _get_cache() -> CacheDB:
    """Get or create the cache database singleton."""
    global _cache_db
    if _cache_db is None:
        _cache_db = CacheDB(settings.CACHE_DB_PATH)
    return _cache_db


def _parse_envelope(raw: str | dict) -> dict[str, Any]:
    """Parse raw input into a dict."""
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


async def execute_tool(
    tool_name: str,
    tool_impl_version: str,
    raw_request: str | dict,
    build_result: Callable[[Any, str], dict[str, Any]],
) -> str:
    """Shared tool execution flow with fingerprinting, caching, and IDs.

    Args:
        tool_name: MCP tool name.
        tool_impl_version: Version string for cache key scoping.
        raw_request: Raw request envelope (JSON string or dict).
        build_result: Callable(validated_inputs, repo_root) -> result dict.
            Called only on cache miss.

    Returns:
        JSON string of the ToolResponseEnvelope.
    """
    start = time.perf_counter()
    try:
        envelope_dict = _parse_envelope(raw_request)
        envelope = validate_request(envelope_dict, tool_name)
        validated_inputs = validate_tool_inputs(envelope.inputs, tool_name)

        # Compute repo fingerprint
        repo_fingerprint = compute_repo_fingerprint(envelope.repo_root)

        # Compute deterministic IDs
        canonical_req = canonical_json(envelope.inputs)
        query_id = compute_query_id(
            tool_name, canonical_req, repo_fingerprint.fingerprint_hash
        )
        cache_key = build_cache_key(
            tool_name=tool_name,
            schema_version=settings.SCHEMA_VERSION,
            request=envelope.inputs,
            repo_fingerprint_hash=repo_fingerprint.fingerprint_hash,
            tool_impl_version=tool_impl_version,
        )

        # Check cache
        cache = _get_cache()
        cached_response = cache.get_cached_result(cache_key)
        if cached_response is not None:
            # Cache hit — update timing and cached flag
            timing_ms = int((time.perf_counter() - start) * 1000)
            cached_response["cached"] = True
            cached_response["timing_ms"] = timing_ms
            logger.info(
                "Cache hit",
                extra={
                    "tool_name": tool_name,
                    "query_id": query_id,
                    "cached": True,
                    "timing_ms": timing_ms,
                },
            )
            return json.dumps(cached_response)

        # Cache miss — execute tool logic
        result_dict = build_result(validated_inputs, envelope.repo_root)

        timing_ms = int((time.perf_counter() - start) * 1000)

        response = ToolResponseEnvelope(
            schema_version=settings.SCHEMA_VERSION,
            tool_name=tool_name,
            run_id="pending",  # Will be set by orchestrator
            query_id=query_id,
            repo_fingerprint=repo_fingerprint,
            cached=False,
            timing_ms=timing_ms,
            result=result_dict,
            errors=[],
        )
        response_dict = json.loads(response.model_dump_json(by_alias=True))

        # Store in cache
        cache.store_result(
            cache_key=cache_key,
            tool_name=tool_name,
            query_id=query_id,
            run_id="pending",
            repo_fp_hash=repo_fingerprint.fingerprint_hash,
            request_json=canonical_req,
            response_json=json.dumps(response_dict),
            timing_ms=timing_ms,
        )

        logger.info(
            "Tool executed",
            extra={
                "tool_name": tool_name,
                "query_id": query_id,
                "cached": False,
                "timing_ms": timing_ms,
            },
        )
        return json.dumps(response_dict)

    except Exception as e:
        timing_ms = int((time.perf_counter() - start) * 1000)
        logger.error(
            f"Tool error: {e}",
            extra={"tool_name": tool_name, "timing_ms": timing_ms},
        )
        error = make_validation_error_response(e, tool_name)
        # Build minimal error response
        fallback_fp = RepoFingerprint(
            git_head=None, dirty=True, fingerprint_hash="error"
        )
        response = ToolResponseEnvelope(
            schema_version=settings.SCHEMA_VERSION,
            tool_name=tool_name,
            run_id="error",
            query_id="error",
            repo_fingerprint=fallback_fp,
            cached=False,
            timing_ms=timing_ms,
            result={},
            errors=[error],
        )
        return json.dumps(json.loads(response.model_dump_json(by_alias=True)))


# ── Tool implementation version constants ───────────────────────────

TOOL1_IMPL_VERSION = "1.0.0"
TOOL2_IMPL_VERSION = "1.0.0"
TOOL3_IMPL_VERSION = "1.0.0"
TOOL4_IMPL_VERSION = "1.0.0"
TOOL5_IMPL_VERSION = "1.0.0"


# ── Tool result builders (stub implementations) ────────────────────


def _build_tool1_result(validated_inputs: Any, repo_root: str) -> dict[str, Any]:
    """Build Tool 1 stub result."""
    result = Tool1Result(
        language="python",
        repo_root=repo_root,
        files=[],
        nodes=[],
        edges=[],
        diagnostics=[],
        stats=Tool1Stats(
            target_files=len(validated_inputs.target_files),
            parsed_ok=0,
            parsed_error=0,
            nodes=0,
            edges=0,
            duration_ms=0,
            cache=CacheStats(hits=0, misses=0),
        ),
    )
    return json.loads(result.model_dump_json(by_alias=True))


def _build_tool2_result(validated_inputs: Any, repo_root: str) -> dict[str, Any]:
    """Build Tool 2 stub result."""
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
    return json.loads(result.model_dump_json(by_alias=True))


def _build_tool3_result(validated_inputs: Any, repo_root: str) -> dict[str, Any]:
    """Build Tool 3 stub result."""
    result = Tool3Result(
        retrieval_mode="bm25_fallback",
        neighbors=[],
        index_stats=IndexStats(chunks_total=0, chunks_scanned=0, backend="bm25"),
        diagnostics=[],
    )
    return json.loads(result.model_dump_json(by_alias=True))


def _build_tool4_result(validated_inputs: Any, repo_root: str) -> dict[str, Any]:
    """Build Tool 4 stub result."""
    result = Tool4Result(
        targets=[],
        couplings=[],
        history_stats=HistoryStats(
            commits_scanned=0, commits_used=0, renames_followed=0
        ),
        diagnostics=[],
    )
    return json.loads(result.model_dump_json(by_alias=True))


def _build_tool5_result(validated_inputs: Any, repo_root: str) -> dict[str, Any]:
    """Build Tool 5 stub result."""
    result = Tool5Result(
        tests=[],
        unmatched_impacts=[],
        selection_stats=SelectionStats(
            tests_considered=0, tests_selected=0, high_confidence=0
        ),
        diagnostics=[],
    )
    return json.loads(result.model_dump_json(by_alias=True))


# ── Tool 1: AST Structural Engine ───────────────────────────────────


@mcp.tool(
    name="get_ast_dependencies",
    description="Analyze Python source files and return AST nodes (modules, classes, functions, methods) and edges (imports, calls, inheritance, references) with evidence spans.",
)
async def get_ast_dependencies(request: str) -> str:
    """Get AST-based structural dependencies for Python files."""
    return await execute_tool(
        "get_ast_dependencies", TOOL1_IMPL_VERSION, request, _build_tool1_result
    )


# ── Tool 2: Data Lineage Engine ─────────────────────────────────────


@mcp.tool(
    name="trace_data_shape",
    description="Trace data field/path usage through API handlers, detecting read sites, write sites, validations, and transforms with breakage flags.",
)
async def trace_data_shape(request: str) -> str:
    """Trace field/path lineage through API handlers."""
    return await execute_tool(
        "trace_data_shape", TOOL2_IMPL_VERSION, request, _build_tool2_result
    )


# ── Tool 3: Semantic Neighbor Search ────────────────────────────────


@mcp.tool(
    name="find_semantic_neighbors",
    description="Find semantically similar code chunks using embeddings or BM25 fallback. Results are uncorroborated by default.",
)
async def find_semantic_neighbors(request: str) -> str:
    """Find semantic neighbors for a query."""
    return await execute_tool(
        "find_semantic_neighbors", TOOL3_IMPL_VERSION, request, _build_tool3_result
    )


# ── Tool 4: Temporal Coupling ───────────────────────────────────────


@mcp.tool(
    name="get_historical_coupling",
    description="Analyze git history to find files that frequently co-change with target files (temporal coupling).",
)
async def get_historical_coupling(request: str) -> str:
    """Get historically coupled files from git history."""
    return await execute_tool(
        "get_historical_coupling", TOOL4_IMPL_VERSION, request, _build_tool4_result
    )


# ── Tool 5: Test Impact Analyzer ────────────────────────────────────


@mcp.tool(
    name="get_covering_tests",
    description="Find and rank tests that cover impacted code nodes, with evidence-based scoring.",
)
async def get_covering_tests(request: str) -> str:
    """Get ranked covering tests for impacted nodes."""
    return await execute_tool(
        "get_covering_tests", TOOL5_IMPL_VERSION, request, _build_tool5_result
    )


def main() -> None:
    """Start the Blast Radius MCP server."""
    setup_logging(settings.LOG_LEVEL)
    logger.info("Starting Blast Radius MCP server")
    mcp.run()
