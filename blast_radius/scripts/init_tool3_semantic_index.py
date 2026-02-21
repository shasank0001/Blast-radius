"""Initialize Tool 3 semantic vector index for a target repository."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from blast_radius_mcp.repo.fingerprint import compute_repo_fingerprint
from blast_radius_mcp.schemas.tool3_semantic import Tool3Request, Tool3Result
from blast_radius_mcp.settings import settings
from blast_radius_mcp.tools.tool3_semantic_neighbors import run_tool3


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize Blast Radius Tool 3 semantic index using embeddings.",
    )
    parser.add_argument(
        "--repo-root",
        required=True,
        help="Absolute or relative path to the target repository.",
    )
    parser.add_argument(
        "--query-text",
        default="initialize semantic index for repository codebase",
        help="Warm-up semantic query text (minimum length 3).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of neighbors to retrieve for warm-up.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Minimum score threshold for warm-up retrieval.",
    )
    parser.add_argument(
        "--scope-path",
        action="append",
        default=[],
        help="Optional repo-relative file path to limit indexing scope. Repeatable.",
    )
    parser.add_argument(
        "--scope-glob",
        action="append",
        default=[],
        help="Optional glob to limit indexing scope. Repeatable.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full diagnostics JSON.",
    )
    return parser.parse_args()


def _missing_embedding_settings() -> list[str]:
    required = {
        "BLAST_RADIUS_OPENAI_API_KEY": settings.OPENAI_API_KEY,
        "BLAST_RADIUS_PINECONE_API_KEY": settings.PINECONE_API_KEY,
        "BLAST_RADIUS_PINECONE_INDEX": settings.PINECONE_INDEX,
        "BLAST_RADIUS_PINECONE_HOST": settings.PINECONE_HOST,
    }
    return [name for name, value in required.items() if not str(value).strip()]


def _build_request_inputs(args: argparse.Namespace) -> dict[str, Any]:
    request = Tool3Request.model_validate(
        {
            "query_text": args.query_text,
            "scope": {
                "paths": args.scope_path,
                "globs": args.scope_glob,
            },
            "options": {
                "top_k": args.top_k,
                "min_score": args.min_score,
                "mode": "embedding",
            },
        }
    )
    return request.model_dump(by_alias=True)


def main() -> int:
    args = _parse_args()
    repo_root = str(Path(args.repo_root).expanduser().resolve())
    if not Path(repo_root).is_dir():
        print(f"ERROR: repo root not found: {repo_root}", file=sys.stderr)
        return 2

    missing = _missing_embedding_settings()
    if missing:
        print("ERROR: missing required embedding settings:", file=sys.stderr)
        for key in missing:
            print(f"- {key}", file=sys.stderr)
        return 2

    try:
        validated_inputs = _build_request_inputs(args)
    except Exception as exc:
        print(f"ERROR: invalid Tool 3 request: {exc}", file=sys.stderr)
        return 2

    try:
        fingerprint = compute_repo_fingerprint(repo_root)
        result_dict = run_tool3(
            validated_inputs,
            repo_root,
            fingerprint_hash=fingerprint.fingerprint_hash,
        )
        result = Tool3Result.model_validate(result_dict)
    except Exception as exc:
        print(f"ERROR: semantic init failed: {exc}", file=sys.stderr)
        return 1

    has_error_diag = any(d.severity == "error" for d in result.diagnostics)
    success = result.retrieval_mode == "embedding_primary" and not has_error_diag

    print("Tool3 semantic index init summary")
    print(f"repo_root: {repo_root}")
    print(f"retrieval_mode: {result.retrieval_mode}")
    print(f"backend: {result.index_stats.backend}")
    print(f"chunks_total: {result.index_stats.chunks_total}")
    print(f"indexed_files: {result.index_stats.indexed_files}")
    print(f"neighbors_returned: {len(result.neighbors)}")
    if result.diagnostics:
        print("diagnostics:")
        for diag in result.diagnostics:
            print(f"- [{diag.severity}] {diag.code}: {diag.message}")
    if args.verbose:
        print("raw_result:")
        print(json.dumps(result.model_dump(by_alias=True), indent=2))

    if success:
        print("STATUS: success (embedding index initialized)")
        return 0

    print("STATUS: failed (embedding mode not active; check diagnostics)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())