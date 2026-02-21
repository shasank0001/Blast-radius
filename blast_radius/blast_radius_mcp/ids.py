"""Deterministic ID generation for runs, queries, and cache keys."""

from __future__ import annotations

import hashlib
import json


def canonical_json(obj: dict) -> str:
    """Sort keys, no whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(*parts: str) -> str:
    """Compute SHA-256 hex digest of concatenated parts."""
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
    return h.hexdigest()


def compute_run_id(
    schema_version: str,
    intent_norm: str,
    anchors_norm: list[str],
    diff_hash: str,
    repo_fingerprint_hash: str,
) -> str:
    """run_id = sha256('run' + schema_version + intent_norm + json(sorted(anchors)) + diff_hash + repo_fp_hash)"""
    anchors_json = json.dumps(sorted(anchors_norm), separators=(",", ":"))
    return _sha256_hex("run", schema_version, intent_norm, anchors_json, diff_hash, repo_fingerprint_hash)


def compute_query_id(
    tool_name: str,
    canonical_request: str,
    repo_fingerprint_hash: str,
) -> str:
    """query_id = sha256('query' + tool_name + canonical_request + repo_fp_hash)"""
    return _sha256_hex("query", tool_name, canonical_request, repo_fingerprint_hash)


def compute_cache_key(
    tool_name: str,
    schema_version: str,
    canonical_request: str,
    repo_fingerprint_hash: str,
    tool_impl_version: str,
) -> str:
    """cache_key = sha256(tool_name + schema_version + canonical_request + repo_fp_hash + tool_impl_version)"""
    return _sha256_hex(tool_name, schema_version, canonical_request, repo_fingerprint_hash, tool_impl_version)


def normalize_intent(intent: str) -> str:
    """Trim whitespace, collapse multiple spaces, lowercase."""
    return " ".join(intent.split()).lower()


def compute_diff_hash(diff: str) -> str:
    """sha256 of line-ending-normalized diff."""
    normalized = diff.replace("\r\n", "\n").replace("\r", "\n")
    return _sha256_hex(normalized)
