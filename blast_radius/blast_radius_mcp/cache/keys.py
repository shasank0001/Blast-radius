"""Cache key construction utilities."""

from __future__ import annotations

from blast_radius_mcp.ids import canonical_json, compute_cache_key


def build_cache_key(
    tool_name: str,
    schema_version: str,
    request: dict,
    repo_fingerprint_hash: str,
    tool_impl_version: str,
) -> str:
    """Build a cache key from tool request parameters.

    Wraps ids.compute_cache_key with canonical_json serialization of
    the request dict for deterministic hashing.

    Args:
        tool_name: Name of the tool (e.g., "get_ast_dependencies").
        schema_version: Schema version string (e.g., "v1").
        request: The tool-specific request inputs dict.
        repo_fingerprint_hash: Hash from RepoFingerprint.
        tool_impl_version: Implementation version of the tool.

    Returns:
        SHA-256 hex digest cache key.
    """
    canonical_request = canonical_json(request)
    return compute_cache_key(
        tool_name=tool_name,
        schema_version=schema_version,
        canonical_request=canonical_request,
        repo_fingerprint_hash=repo_fingerprint_hash,
        tool_impl_version=tool_impl_version,
    )
