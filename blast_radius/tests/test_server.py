"""Tests for server execute_tool flow."""

from __future__ import annotations

import json

import pytest

import blast_radius_mcp.server as server
from blast_radius_mcp.cache.keys import build_cache_key
from blast_radius_mcp.ids import compute_diff_hash, compute_run_id, normalize_intent


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Use a temporary cache DB and reset server cache singleton."""
    db_path = str(tmp_path / "cache.db")
    monkeypatch.setattr(server.settings, "CACHE_DB_PATH", db_path)
    server._cache_db = None
    yield
    server._cache_db = None


def _build_tool2_request(
    repo_root: str,
    intent: str,
    anchors: list[str],
    diff: str,
) -> dict:
    return {
        "schema_version": "v1",
        "repo_root": repo_root,
        "inputs": {
            "field_path": "OrderRequest.user_id",
            "entry_points": ["route:POST /orders"],
            "options": {
                "direction": "both",
                "max_call_depth": 2,
                "max_sites": 200,
                "include_writes": True,
            },
        },
        "anchors": anchors,
        "diff": diff,
        "options": {"intent": intent},
    }


def _build_tool2_result(validated_inputs, repo_root: str) -> dict:
    return {
        "changed_field": validated_inputs.field_path,
        "entry_points_resolved": [],
        "read_sites": [],
        "write_sites": [],
        "validations": [],
        "transforms": [],
        "diagnostics": [],
        "stats": {
            "files_scanned": 0,
            "sites_emitted": 0,
            "truncated": False,
        },
    }


@pytest.mark.asyncio
async def test_execute_tool_run_id_is_deterministic_and_persisted(isolated_cache, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("x = 1\n", encoding="utf-8")

    request = _build_tool2_request(
        repo_root=str(repo_root),
        intent="  Remove   USER_ID  ",
        anchors=["route:POST /orders"],
        diff="- user_id\r\n+ account_id\r\n",
    )

    response = json.loads(
        await server.execute_tool(
            "trace_data_shape",
            "1.0.0",
            request,
            _build_tool2_result,
        )
    )

    fp_hash = response["repo_fingerprint"]["fingerprint_hash"]
    expected_run_id = compute_run_id(
        "v1",
        normalize_intent(request["options"]["intent"]),
        sorted(request["anchors"]),
        compute_diff_hash(request["diff"]),
        fp_hash,
    )

    assert response["run_id"] == expected_run_id
    assert response["cached"] is False

    cache = server._get_cache()
    stats = cache.get_stats()
    assert stats["runs"] == 1
    assert stats["tool_results"] == 1

    cache_key = build_cache_key(
        tool_name="trace_data_shape",
        schema_version="v1",
        request=request["inputs"],
        repo_fingerprint_hash=fp_hash,
        tool_impl_version="1.0.0",
    )
    cached = cache.get_cached_result(cache_key)
    assert cached is not None
    assert cached["run_id"] == expected_run_id


@pytest.mark.asyncio
async def test_execute_tool_cache_hit_uses_current_run_id_and_persists_new_run(
    isolated_cache,
    tmp_path,
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("x = 1\n", encoding="utf-8")

    request_one = _build_tool2_request(
        repo_root=str(repo_root),
        intent="remove user id",
        anchors=["anchor:a"],
        diff="- user_id\n",
    )
    request_two = _build_tool2_request(
        repo_root=str(repo_root),
        intent="rename user id",
        anchors=["anchor:b"],
        diff="+ account_id\n",
    )

    response_one = json.loads(
        await server.execute_tool(
            "trace_data_shape",
            "1.0.0",
            request_one,
            _build_tool2_result,
        )
    )
    response_two = json.loads(
        await server.execute_tool(
            "trace_data_shape",
            "1.0.0",
            request_two,
            _build_tool2_result,
        )
    )

    fp_hash = response_one["repo_fingerprint"]["fingerprint_hash"]
    expected_run_id_one = compute_run_id(
        "v1",
        normalize_intent(request_one["options"]["intent"]),
        sorted(request_one["anchors"]),
        compute_diff_hash(request_one["diff"]),
        fp_hash,
    )
    expected_run_id_two = compute_run_id(
        "v1",
        normalize_intent(request_two["options"]["intent"]),
        sorted(request_two["anchors"]),
        compute_diff_hash(request_two["diff"]),
        fp_hash,
    )

    assert response_one["run_id"] == expected_run_id_one
    assert response_two["run_id"] == expected_run_id_two
    assert response_one["run_id"] != response_two["run_id"]
    assert response_one["query_id"] == response_two["query_id"]
    assert response_two["cached"] is True

    stats = server._get_cache().get_stats()
    assert stats["runs"] == 2
    assert stats["tool_results"] == 1


@pytest.mark.asyncio
async def test_execute_tool_tool3_builder_handles_validated_model(isolated_cache, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "module.py").write_text(
        "def search_users(query):\n    return query\n",
        encoding="utf-8",
    )

    request = {
        "schema_version": "v1",
        "repo_root": str(repo_root),
        "inputs": {
            "query_text": "search users query",
            "scope": {"paths": ["module.py"]},
            "options": {"mode": "bm25", "min_score": 0.0},
        },
        "anchors": [],
        "diff": "",
        "options": {"intent": "find semantic neighbors"},
    }

    response = json.loads(
        await server.execute_tool(
            "find_semantic_neighbors",
            server.TOOL3_IMPL_VERSION,
            request,
            server._build_tool3_result,
        )
    )

    assert response["errors"] == []
    assert response["result"]["retrieval_mode"] in {
        "embedding_primary",
        "bm25_fallback",
    }
