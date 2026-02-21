"""Tool 3 — Semantic Neighbor Search (``find_semantic_neighbors``).

Given a natural-language or code query, retrieves the *k* most
semantically related code symbols in the repository.  Two retrieval
back-ends are supported:

* **embedding** — OpenAI embeddings indexed in Pinecone (high quality).
* **bm25** — BM25Okapi keyword search via ``rank_bm25`` (zero-config
  fallback, always available).

In ``auto`` mode (the default), the tool attempts the embedding path first
and silently falls back to BM25 if API keys are missing or any provider
error occurs.

The module never raises exceptions back to the caller — all errors are
surfaced as diagnostics inside a valid :class:`Tool3Result`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any

from blast_radius_mcp.indices.semantic_index import (
    CodeChunk,
    OpenAIEmbeddingProvider,
    PineconeVectorStore,
    build_bm25_index,
    chunk_code_files,
    query_bm25,
)
from blast_radius_mcp.schemas.common import Position
from blast_radius_mcp.schemas.tool3_semantic import (
    IndexStats,
    Neighbor,
    Span,
    Tool3Diagnostic,
    Tool3Result,
)
from blast_radius_mcp.settings import settings

logger = logging.getLogger(__name__)

# ── Module-level constants ───────────────────────────────────────────

TOOL3_IMPL_VERSION = "1.0.0"

# ── Pinecone index fingerprint cache ────────────────────────────────
# Tracks which repos have already been indexed for the current process.
# Keyed by absolute repo path → last-indexed fingerprint hash.
_INDEXED_FINGERPRINTS: dict[str, str] = {}


def _needs_reindex(repo_root: str, fingerprint_hash: str) -> bool:
    """Check if repo needs re-indexing based on fingerprint."""
    key = os.path.abspath(repo_root)
    if _INDEXED_FINGERPRINTS.get(key) == fingerprint_hash:
        return False
    return True


def _mark_indexed(repo_root: str, fingerprint_hash: str) -> None:
    """Mark repo as indexed with given fingerprint."""
    key = os.path.abspath(repo_root)
    _INDEXED_FINGERPRINTS[key] = fingerprint_hash


# ── Deterministic ID helper ─────────────────────────────────────────


def _sha256_prefix(prefix: str, *parts: str, length: int = 16) -> str:
    """Return *prefix* + first *length* hex chars of SHA-256 of *parts*.

    Parts are joined with ``|`` before hashing.
    """
    h = hashlib.sha256("|".join(parts).encode("utf-8"))
    return f"{prefix}{h.hexdigest()[:length]}"


def _neighbor_id(file: str, symbol: str, start_line: int) -> str:
    """Deterministic neighbor identifier."""
    return _sha256_prefix("nb_", file, symbol, str(start_line))


# ── Provider availability check ─────────────────────────────────────


def _embedding_providers_available() -> bool:
    """Return ``True`` when all four embedding env-vars are set."""
    return bool(
        settings.OPENAI_API_KEY
        and settings.PINECONE_API_KEY
        and settings.PINECONE_INDEX
        and settings.PINECONE_HOST
    )


# ── Snippet helper ──────────────────────────────────────────────────


def _rationale_snippet(source: str, max_chars: int = 200) -> str:
    """Extract the leading portion of *source* as a rationale snippet.

    Trims to at most *max_chars* characters and appends a trailing
    ellipsis when truncated.
    """
    text = source.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " …"


# ── Embedding retrieval path ────────────────────────────────────────


def _run_embedding_path(
    query_text: str,
    chunks: list[CodeChunk],
    top_k: int,
    min_score: float,
    diagnostics: list[Tool3Diagnostic],
    fingerprint_hash: str = "",
    repo_root: str = "",
) -> list[Neighbor] | None:
    """Attempt embedding-based retrieval.  Returns neighbours or ``None``.

    When ``None`` is returned the caller should fall back to BM25.  Any
    problems are appended to *diagnostics*.
    """
    if not _embedding_providers_available():
        diagnostics.append(
            Tool3Diagnostic(
                severity="warning",
                code="semantic_provider_unavailable",
                message=(
                    "Embedding provider not configured — missing one or "
                    "more of OPENAI_API_KEY, PINECONE_API_KEY, "
                    "PINECONE_INDEX, PINECONE_HOST."
                ),
            )
        )
        return None

    try:
        embedder = OpenAIEmbeddingProvider(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_EMBEDDING_MODEL,
        )
        store = PineconeVectorStore(
            api_key=settings.PINECONE_API_KEY,
            index_name=settings.PINECONE_INDEX,
            host=settings.PINECONE_HOST,
        )

        # — Embed & upsert chunks (skip if already indexed) ──────────
        needs_upsert = _needs_reindex(repo_root, fingerprint_hash) if (repo_root and fingerprint_hash) else True
        if chunks and needs_upsert:
            chunk_texts = [c.source for c in chunks]
            chunk_ids = [c.chunk_id for c in chunks]
            metadata = [
                {
                    "file": c.file,
                    "symbol": c.symbol,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "start_col": c.start_col,
                    "end_col": c.end_col,
                }
                for c in chunks
            ]
            vectors = embedder.embed(chunk_texts)
            store.upsert(chunk_ids, vectors, metadata)
            logger.debug("Upserted %d chunk vectors to Pinecone", len(chunks))
            if repo_root and fingerprint_hash:
                _mark_indexed(repo_root, fingerprint_hash)
        elif chunks:
            logger.debug(
                "Skipping Pinecone upsert — repo already indexed (fingerprint=%s)",
                fingerprint_hash,
            )

        # — Embed query & search ─────────────────────────────────────
        query_vec = embedder.embed([query_text])[0]
        matches = store.query(query_vec, top_k=top_k)

        # Map matches → Neighbor
        neighbors: list[Neighbor] = []
        for match in matches:
            score = float(match.score) if hasattr(match, "score") else 0.0
            if score < min_score:
                continue

            meta = match.metadata or {}
            file = meta.get("file", "")
            symbol = meta.get("symbol", "")
            start_line = int(meta.get("start_line", 1))
            end_line = int(meta.get("end_line", 1))
            start_col = int(meta.get("start_col", 0))
            end_col = int(meta.get("end_col", 0))

            # Attempt to find matching chunk for snippet
            snippet = ""
            for c in chunks:
                if c.chunk_id == match.id:
                    snippet = _rationale_snippet(c.source)
                    break
            if not snippet:
                snippet = f"{symbol} in {file}"

            neighbors.append(
                Neighbor(
                    neighbor_id=_neighbor_id(file, symbol, start_line),
                    file=file,
                    symbol=symbol,
                    span=Span(
                        start=Position(line=start_line, col=start_col),
                        end=Position(line=end_line, col=end_col),
                    ),
                    score=min(score, 1.0),
                    method="openai_pinecone",
                    rationale_snippet=snippet,
                    uncorroborated=True,
                )
            )

        return neighbors

    except Exception as exc:  # noqa: BLE001 — graceful degradation
        logger.warning("Embedding path failed, falling back to BM25: %s", exc)
        diagnostics.append(
            Tool3Diagnostic(
                severity="warning",
                code="semantic_provider_unavailable",
                message=f"Embedding retrieval failed: {exc!s}",
            )
        )
        return None


# ── BM25 retrieval path ─────────────────────────────────────────────


def _run_bm25_path(
    query_text: str,
    chunks: list[CodeChunk],
    top_k: int,
    min_score: float,
    diagnostics: list[Tool3Diagnostic],
) -> list[Neighbor]:
    """BM25-based retrieval.  Always returns a list (possibly empty)."""
    if not chunks:
        return []

    try:
        bm25_index = build_bm25_index(chunks)
    except ValueError:
        return []

    results = query_bm25(
        query_text=query_text,
        bm25_index=bm25_index,
        chunks=chunks,
        top_k=top_k,
        min_score=min_score,
    )

    neighbors: list[Neighbor] = []
    for chunk, score in results:
        neighbors.append(
            Neighbor(
                neighbor_id=_neighbor_id(chunk.file, chunk.symbol, chunk.start_line),
                file=chunk.file,
                symbol=chunk.symbol,
                span=Span(
                    start=Position(line=chunk.start_line, col=chunk.start_col),
                    end=Position(line=chunk.end_line, col=chunk.end_col),
                ),
                score=round(score, 6),
                method="bm25",
                rationale_snippet=_rationale_snippet(chunk.source),
                uncorroborated=True,
            )
        )

    return neighbors


# ── Deduplication & sorting ──────────────────────────────────────────


def _dedup_neighbors(neighbors: list[Neighbor]) -> list[Neighbor]:
    """Remove duplicate neighbours keyed by ``(file, symbol)``.

    When duplicates exist the entry with the highest score is kept.
    """
    best: dict[tuple[str, str], Neighbor] = {}
    for nb in neighbors:
        key = (nb.file, nb.symbol)
        existing = best.get(key)
        if existing is None or nb.score > existing.score:
            best[key] = nb
    return list(best.values())


def _sort_neighbors(neighbors: list[Neighbor]) -> list[Neighbor]:
    """Stable sort: ``(score desc, file asc, span.start.line asc)``."""
    return sorted(
        neighbors,
        key=lambda n: (-n.score, n.file, n.span.start.line),
    )


# ── Main entry point ────────────────────────────────────────────────


def run_tool3(validated_inputs: dict[str, Any], repo_root: str, fingerprint_hash: str = "") -> dict:
    """Execute the full Tool 3 (Semantic Neighbor Search) pipeline.

    Steps:
      1. Extract ``query_text``, ``scope``, and ``options`` from inputs.
      2. Determine retrieval mode (``auto`` / ``embedding`` / ``bm25``).
      3. Chunk code files within scope.
      4. Run the selected retrieval path(s).
      5. Deduplicate and stable-sort results.
      6. Mark all results as ``uncorroborated``.
      7. Build ``IndexStats`` and ``Tool3Result``.
      8. Return ``result.model_dump(by_alias=True)``.

    Args:
        validated_inputs: Dict with keys ``query_text``, ``scope``, ``options``.
        repo_root:        Absolute path to the repository root.

    Returns:
        A dict suitable for JSON serialisation, conforming to
        :class:`Tool3Result`.
    """
    diagnostics: list[Tool3Diagnostic] = []

    # ── 1. Parse inputs ──────────────────────────────────────────────
    query_text: str = validated_inputs.get("query_text", "")
    scope_raw: dict = validated_inputs.get("scope", {})
    options_raw: dict = validated_inputs.get("options", {})

    scope_paths: list[str] = scope_raw.get("paths", [])
    scope_globs: list[str] = scope_raw.get("globs", [])

    top_k: int = options_raw.get("top_k", 25)
    min_score: float = options_raw.get("min_score", 0.35)
    mode: str = options_raw.get("mode", "auto")

    # ── 2. Chunk code files ──────────────────────────────────────────
    try:
        chunks = chunk_code_files(
            repo_root=repo_root,
            scope_paths=scope_paths,
            scope_globs=scope_globs,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to chunk code files: %s", exc)
        chunks = []
        diagnostics.append(
            Tool3Diagnostic(
                severity="error",
                code="semantic_index_empty",
                message=f"Failed to chunk code files: {exc!s}",
            )
        )

    chunks_total = len(chunks)

    if not chunks:
        # Edge case: empty corpus
        if not any(d.code == "semantic_index_empty" for d in diagnostics):
            diagnostics.append(
                Tool3Diagnostic(
                    severity="warning",
                    code="semantic_index_empty",
                    message="No Python functions found within the specified scope.",
                )
            )

        backend: str = "bm25"
        retrieval_mode: str = "bm25_fallback"
        return Tool3Result(
            retrieval_mode=retrieval_mode,  # type: ignore[arg-type]
            neighbors=[],
            index_stats=IndexStats(
                chunks_total=0,
                chunks_scanned=0,
                indexed_files=0,
                backend=backend,  # type: ignore[arg-type]
            ),
            diagnostics=diagnostics,
        ).model_dump(by_alias=True)

    # ── 3. Retrieval ─────────────────────────────────────────────────
    neighbors: list[Neighbor] = []
    retrieval_mode = "bm25_fallback"
    backend = "bm25"
    chunks_scanned = chunks_total

    if mode == "embedding":
        # Embedding only — fail if unavailable
        result = _run_embedding_path(
            query_text, chunks, top_k, min_score, diagnostics,
            fingerprint_hash=fingerprint_hash, repo_root=repo_root,
        )
        if result is not None:
            neighbors = result
            retrieval_mode = "embedding_primary"
            backend = "openai_pinecone"
        else:
            # Explicitly requested embedding but unavailable — still
            # return valid result with diagnostics (no BM25 fallback).
            neighbors = []
            retrieval_mode = "bm25_fallback"
            backend = "bm25"

    elif mode == "bm25":
        # BM25 only
        neighbors = _run_bm25_path(
            query_text, chunks, top_k, min_score, diagnostics,
        )
        retrieval_mode = "bm25_fallback"
        backend = "bm25"

    else:
        # auto: try embedding first, fallback to BM25
        result = _run_embedding_path(
            query_text, chunks, top_k, min_score, diagnostics,
            fingerprint_hash=fingerprint_hash, repo_root=repo_root,
        )
        if result is not None:
            neighbors = result
            retrieval_mode = "embedding_primary"
            backend = "openai_pinecone"
        else:
            neighbors = _run_bm25_path(
                query_text, chunks, top_k, min_score, diagnostics,
            )
            retrieval_mode = "bm25_fallback"
            backend = "bm25"

    # ── 4. Post-processing ───────────────────────────────────────────

    # Deduplicate by (file, symbol)
    neighbors = _dedup_neighbors(neighbors)

    # Stable sort: score desc, file asc, span.start.line asc
    neighbors = _sort_neighbors(neighbors)

    # Enforce top_k after dedup
    neighbors = neighbors[:top_k]

    # Mark ALL as uncorroborated
    for nb in neighbors:
        nb.uncorroborated = True

    # Check if everything was filtered
    if not neighbors and chunks_total > 0:
        if not any(d.code == "threshold_filtered_all" for d in diagnostics):
            diagnostics.append(
                Tool3Diagnostic(
                    severity="info",
                    code="threshold_filtered_all",
                    message=(
                        f"All {chunks_total} candidate chunks scored below "
                        f"the min_score threshold ({min_score})."
                    ),
                )
            )

    # ── 5. Assemble result ───────────────────────────────────────────
    indexed_files = len({c.file for c in chunks})
    index_stats = IndexStats(
        chunks_total=chunks_total,
        chunks_scanned=chunks_scanned,
        indexed_files=indexed_files,
        backend=backend,  # type: ignore[arg-type]
    )

    tool3_result = Tool3Result(
        retrieval_mode=retrieval_mode,  # type: ignore[arg-type]
        neighbors=neighbors,
        index_stats=index_stats,
        diagnostics=diagnostics,
    )

    return tool3_result.model_dump(by_alias=True)
