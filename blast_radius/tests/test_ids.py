"""Tests for deterministic ID generation."""

from __future__ import annotations

from blast_radius_mcp.ids import (
    canonical_json,
    compute_cache_key,
    compute_diff_hash,
    compute_query_id,
    compute_run_id,
    normalize_intent,
)


class TestCanonicalJson:
    def test_sorts_keys(self):
        assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'

    def test_no_whitespace(self):
        result = canonical_json({"key": "value"})
        assert " " not in result

    def test_nested_objects_sorted(self):
        obj = {"z": {"b": 2, "a": 1}, "a": 0}
        result = canonical_json(obj)
        assert result.index('"a":0') < result.index('"z"')

    def test_unicode_preserved(self):
        result = canonical_json({"name": "café"})
        assert "café" in result

    def test_empty_dict(self):
        assert canonical_json({}) == "{}"

    def test_lists_preserved_order(self):
        result = canonical_json({"items": [3, 1, 2]})
        assert result == '{"items":[3,1,2]}'


class TestComputeRunId:
    def test_deterministic(self):
        args = ("v1", "remove user_id", ["anchor1"], "diff_hash", "fp_hash")
        assert compute_run_id(*args) == compute_run_id(*args)

    def test_differs_on_intent(self):
        id1 = compute_run_id("v1", "remove user_id", [], "dh", "fp")
        id2 = compute_run_id("v1", "add user_id", [], "dh", "fp")
        assert id1 != id2

    def test_differs_on_anchors(self):
        id1 = compute_run_id("v1", "intent", ["a"], "dh", "fp")
        id2 = compute_run_id("v1", "intent", ["b"], "dh", "fp")
        assert id1 != id2

    def test_anchor_order_irrelevant(self):
        """Anchors are sorted, so order shouldn't matter."""
        id1 = compute_run_id("v1", "intent", ["a", "b"], "dh", "fp")
        id2 = compute_run_id("v1", "intent", ["b", "a"], "dh", "fp")
        assert id1 == id2

    def test_differs_on_diff_hash(self):
        id1 = compute_run_id("v1", "intent", [], "diff1", "fp")
        id2 = compute_run_id("v1", "intent", [], "diff2", "fp")
        assert id1 != id2

    def test_differs_on_fingerprint(self):
        id1 = compute_run_id("v1", "intent", [], "dh", "fp1")
        id2 = compute_run_id("v1", "intent", [], "dh", "fp2")
        assert id1 != id2

    def test_is_hex_string(self):
        result = compute_run_id("v1", "intent", [], "dh", "fp")
        assert len(result) == 64
        int(result, 16)  # Should not raise


class TestComputeQueryId:
    def test_deterministic(self):
        id1 = compute_query_id("tool1", '{"a":1}', "fp")
        id2 = compute_query_id("tool1", '{"a":1}', "fp")
        assert id1 == id2

    def test_differs_on_tool_name(self):
        id1 = compute_query_id("tool1", '{"a":1}', "fp")
        id2 = compute_query_id("tool2", '{"a":1}', "fp")
        assert id1 != id2

    def test_differs_on_request(self):
        id1 = compute_query_id("tool1", '{"a":1}', "fp")
        id2 = compute_query_id("tool1", '{"a":2}', "fp")
        assert id1 != id2


class TestComputeCacheKey:
    def test_deterministic(self):
        k1 = compute_cache_key("t1", "v1", '{"a":1}', "fp", "1.0.0")
        k2 = compute_cache_key("t1", "v1", '{"a":1}', "fp", "1.0.0")
        assert k1 == k2

    def test_differs_on_impl_version(self):
        k1 = compute_cache_key("t1", "v1", '{"a":1}', "fp", "1.0.0")
        k2 = compute_cache_key("t1", "v1", '{"a":1}', "fp", "2.0.0")
        assert k1 != k2

    def test_differs_on_schema_version(self):
        k1 = compute_cache_key("t1", "v1", '{"a":1}', "fp", "1.0.0")
        k2 = compute_cache_key("t1", "v2", '{"a":1}', "fp", "1.0.0")
        assert k1 != k2


class TestNormalizeIntent:
    def test_lowercase(self):
        assert normalize_intent("REMOVE USER_ID") == "remove user_id"

    def test_collapse_whitespace(self):
        assert normalize_intent("  remove   user_id  ") == "remove user_id"

    def test_strip(self):
        assert normalize_intent(" hello ") == "hello"

    def test_tabs_and_newlines(self):
        assert normalize_intent("remove\tuser_id\nfrom") == "remove user_id from"


class TestComputeDiffHash:
    def test_normalizes_crlf(self):
        h1 = compute_diff_hash("line1\nline2\n")
        h2 = compute_diff_hash("line1\r\nline2\r\n")
        assert h1 == h2

    def test_normalizes_cr(self):
        h1 = compute_diff_hash("line1\nline2\n")
        h2 = compute_diff_hash("line1\rline2\r")
        assert h1 == h2

    def test_deterministic(self):
        h1 = compute_diff_hash("some diff content")
        h2 = compute_diff_hash("some diff content")
        assert h1 == h2

    def test_empty_diff(self):
        result = compute_diff_hash("")
        assert len(result) == 64
