"""Tests for SQLite cache layer."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from blast_radius_mcp.cache.keys import build_cache_key
from blast_radius_mcp.cache.sqlite import CacheDB


@pytest.fixture
def cache_db(tmp_path):
    """Create a temporary cache database."""
    db_path = str(tmp_path / "test_cache.db")
    return CacheDB(db_path)


class TestCacheDB:
    def test_cache_miss_returns_none(self, cache_db):
        result = cache_db.get_cached_result("nonexistent_key")
        assert result is None

    def test_store_and_retrieve(self, cache_db):
        response = {"tool_name": "test", "result": {"data": 42}}
        cache_db.store_result(
            cache_key="key1",
            tool_name="test_tool",
            query_id="q1",
            run_id="r1",
            repo_fp_hash="fp1",
            request_json='{"a":1}',
            response_json=json.dumps(response),
            timing_ms=100,
        )
        result = cache_db.get_cached_result("key1")
        assert result is not None
        assert result["result"]["data"] == 42

    def test_cache_hit_returns_stored_data(self, cache_db):
        response = {"schema_version": "v1", "cached": False}
        cache_db.store_result(
            cache_key="key2",
            tool_name="tool1",
            query_id="q2",
            run_id="r2",
            repo_fp_hash="fp2",
            request_json='{"b":2}',
            response_json=json.dumps(response),
            timing_ms=50,
        )
        # Same key → hit
        result = cache_db.get_cached_result("key2")
        assert result == response

    def test_different_keys_independent(self, cache_db):
        cache_db.store_result(
            cache_key="keyA",
            tool_name="tool1",
            query_id="qA",
            run_id="rA",
            repo_fp_hash="fpA",
            request_json='{"x":1}',
            response_json='{"val":"A"}',
            timing_ms=10,
        )
        cache_db.store_result(
            cache_key="keyB",
            tool_name="tool1",
            query_id="qB",
            run_id="rB",
            repo_fp_hash="fpB",
            request_json='{"x":2}',
            response_json='{"val":"B"}',
            timing_ms=20,
        )
        assert cache_db.get_cached_result("keyA")["val"] == "A"
        assert cache_db.get_cached_result("keyB")["val"] == "B"

    def test_store_run(self, cache_db):
        # Should not raise
        cache_db.store_run(
            run_id="run1",
            repo_root="/tmp/repo",
            repo_fp={"git_head": None, "dirty": True, "fingerprint_hash": "h"},
            intent="remove field",
            anchors=["anchor1"],
            diff_hash="dh1",
        )
        stats = cache_db.get_stats()
        assert stats["runs"] == 1

    def test_store_run_idempotent(self, cache_db):
        for _ in range(3):
            cache_db.store_run(
                run_id="run_same",
                repo_root="/tmp/repo",
                repo_fp={"git_head": None, "dirty": True, "fingerprint_hash": "h"},
                intent="intent",
                anchors=[],
                diff_hash="dh",
            )
        stats = cache_db.get_stats()
        assert stats["runs"] == 1

    def test_store_artifact(self, cache_db):
        cache_db.store_artifact(
            artifact_id="art1",
            kind="ast_index",
            repo_fp_hash="fp1",
            path_or_blob="/tmp/index.json",
        )
        stats = cache_db.get_stats()
        assert stats["artifacts"] == 1

    def test_replace_on_duplicate_key(self, cache_db):
        cache_db.store_result(
            cache_key="dup",
            tool_name="t",
            query_id="q",
            run_id="r",
            repo_fp_hash="fp",
            request_json="{}",
            response_json='{"version":1}',
            timing_ms=10,
        )
        cache_db.store_result(
            cache_key="dup",
            tool_name="t",
            query_id="q",
            run_id="r",
            repo_fp_hash="fp",
            request_json="{}",
            response_json='{"version":2}',
            timing_ms=20,
        )
        result = cache_db.get_cached_result("dup")
        assert result["version"] == 2

    def test_get_stats(self, cache_db):
        stats = cache_db.get_stats()
        assert stats["runs"] == 0
        assert stats["tool_results"] == 0
        assert stats["artifacts"] == 0

    def test_cleanup_removes_nothing_when_fresh(self, cache_db):
        cache_db.store_result(
            cache_key="fresh",
            tool_name="t",
            query_id="q",
            run_id="r",
            repo_fp_hash="fp",
            request_json="{}",
            response_json='{"data":1}',
            timing_ms=10,
        )
        removed = cache_db.cleanup(max_age_days=30)
        assert removed == 0
        assert cache_db.get_cached_result("fresh") is not None


class TestBuildCacheKey:
    def test_deterministic(self):
        k1 = build_cache_key("tool1", "v1", {"a": 1}, "fp", "1.0.0")
        k2 = build_cache_key("tool1", "v1", {"a": 1}, "fp", "1.0.0")
        assert k1 == k2

    def test_key_order_irrelevant(self):
        """Dict key order shouldn't matter due to canonical_json sorting."""
        k1 = build_cache_key("tool1", "v1", {"b": 2, "a": 1}, "fp", "1.0.0")
        k2 = build_cache_key("tool1", "v1", {"a": 1, "b": 2}, "fp", "1.0.0")
        assert k1 == k2

    def test_differs_on_fingerprint(self):
        k1 = build_cache_key("tool1", "v1", {"a": 1}, "fp1", "1.0.0")
        k2 = build_cache_key("tool1", "v1", {"a": 1}, "fp2", "1.0.0")
        assert k1 != k2

    def test_differs_on_version(self):
        k1 = build_cache_key("tool1", "v1", {"a": 1}, "fp", "1.0.0")
        k2 = build_cache_key("tool1", "v1", {"a": 1}, "fp", "2.0.0")
        assert k1 != k2
