"""Semantic index layer — BM25 fallback + OpenAI/Pinecone embedding backend.

Provides:
- ``CodeChunk`` dataclass representing a single function/method body.
- ``chunk_code_files()`` to parse Python files and produce chunks.
- ``build_bm25_index()`` / ``query_bm25()`` for keyword-based retrieval.
- ``OpenAIEmbeddingProvider`` for dense vector embeddings via OpenAI.
- ``PineconeVectorStore`` for vector upsert/query via Pinecone.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from rank_bm25 import BM25Okapi

from blast_radius_mcp.repo.io import glob_python_files, safe_read_file

logger = logging.getLogger(__name__)

# ── Tokenization ────────────────────────────────────────────────────

_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "and", "but", "or",
    "not", "no", "if", "then", "else", "this", "that", "it", "its",
    "self", "def", "class", "return", "import", "from", "none", "true", "false",
})

_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def _tokenize(text: str) -> list[str]:
    """Split *text* into lowercase identifier tokens, removing stopwords.

    Extracts runs of ``[a-zA-Z_][a-zA-Z0-9_]*``, lowercases them, and
    filters out stopwords and single-character tokens.
    """
    words = _TOKEN_RE.findall(text.lower())
    return [w for w in words if len(w) > 1 and w not in _STOPWORDS]


# ── CodeChunk ────────────────────────────────────────────────────────


@dataclass
class CodeChunk:
    """A single function/method extracted from a Python source file.

    Attributes:
        chunk_id:   Deterministic ID ``chunk_`` + sha256(file:symbol:start)[:16].
        file:       Repo-relative path (forward slashes).
        symbol:     Qualified name (e.g. ``MyClass.my_method``).
        source:     Raw source text of the function/method body.
        start_line: 1-based start line.
        end_line:   1-based end line (inclusive).
        start_col:  0-based start column.
        end_col:    0-based end column.
        tokens:     Pre-computed BM25 token list.
    """

    chunk_id: str
    file: str
    symbol: str
    source: str
    start_line: int
    end_line: int
    start_col: int
    end_col: int
    tokens: list[str] = field(default_factory=list)


def _chunk_id(file: str, qualified_name: str, start_line: int) -> str:
    """Deterministic chunk identifier.

    Returns ``chunk_`` + first 16 hex chars of
    ``sha256(file + ":" + qualified_name + ":" + start_line)``.
    """
    raw = f"{file}:{qualified_name}:{start_line}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"chunk_{digest}"


# ── AST extraction helpers ──────────────────────────────────────────


def _qualified_name(node: ast.FunctionDef | ast.AsyncFunctionDef, parents: list[str]) -> str:
    """Build a dotted qualified name for *node* given its parent class names."""
    parts = parents + [node.name]
    return ".".join(parts)


def _extract_functions(
    tree: ast.AST,
    source_lines: list[str],
    file_path: str,
) -> list[CodeChunk]:
    """Walk *tree* and extract ``CodeChunk`` for every function/method.

    Handles top-level functions and methods nested one level inside classes.
    Deeper nesting is also captured (class → inner-class → method) via a
    simple recursive visitor.
    """
    chunks: list[CodeChunk] = []

    def _visit(node: ast.AST, parents: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef,)):
                _visit(child, parents + [child.name])
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = _qualified_name(child, parents)
                start_line = child.lineno          # 1-based
                end_line = child.end_lineno or child.lineno  # 1-based
                start_col = child.col_offset       # 0-based
                end_col = child.end_col_offset or 0  # 0-based

                # Extract source text (1-based → 0-based indexing)
                body_lines = source_lines[start_line - 1 : end_line]
                source_text = "\n".join(body_lines)

                cid = _chunk_id(file_path, qname, start_line)
                tokens = _tokenize(source_text)

                chunks.append(
                    CodeChunk(
                        chunk_id=cid,
                        file=file_path,
                        symbol=qname,
                        source=source_text,
                        start_line=start_line,
                        end_line=end_line,
                        start_col=start_col,
                        end_col=end_col,
                        tokens=tokens,
                    )
                )
                # Also descend into nested functions/classes inside the function
                _visit(child, parents + [child.name])

    _visit(tree, [])
    return chunks


# ── Chunking pipeline ───────────────────────────────────────────────


def _resolve_scope_files(
    repo_root: str,
    scope_paths: list[str],
    scope_globs: list[str],
) -> list[str]:
    """Resolve scope constraints to a list of repo-relative Python file paths.

    If both ``scope_paths`` and ``scope_globs`` are empty, all Python files
    in the repo are returned via :func:`glob_python_files`.

    ``scope_paths`` entries may be files (kept if they exist and end with
    ``.py``) or directories (recursively globbed for ``*.py``).

    ``scope_globs`` entries are resolved with :meth:`pathlib.Path.glob`
    relative to *repo_root*.
    """
    root = Path(repo_root).resolve()

    # No scope constraints → all Python files
    if not scope_paths and not scope_globs:
        return glob_python_files(repo_root)

    seen: set[str] = set()
    result: list[str] = []

    def _add(rel: str) -> None:
        normed = rel.replace("\\", "/")
        if normed not in seen:
            seen.add(normed)
            result.append(normed)

    # Explicit paths
    for p in scope_paths:
        target = (root / p).resolve()
        if not str(target).startswith(str(root)):
            logger.warning("Scope path %r escapes repo root — skipped", p)
            continue
        if target.is_file() and target.suffix == ".py":
            _add(str(target.relative_to(root)))
        elif target.is_dir():
            for py in sorted(target.rglob("*.py")):
                rel = str(py.relative_to(root))
                _add(rel)

    # Glob patterns
    for pattern in scope_globs:
        for match in sorted(root.glob(pattern)):
            if match.is_file() and match.suffix == ".py":
                try:
                    rel = str(match.relative_to(root))
                    _add(rel)
                except ValueError:
                    pass

    result.sort()
    return result


def chunk_code_files(
    repo_root: str,
    scope_paths: list[str] | None = None,
    scope_globs: list[str] | None = None,
) -> list[CodeChunk]:
    """Parse Python files within *scope* and return ``CodeChunk`` list.

    Each function/method in matching files yields one chunk.  Files that
    fail to parse (``SyntaxError``) are silently skipped with a warning.

    Args:
        repo_root:    Absolute path to the repository root.
        scope_paths:  Explicit paths to include (files or directories).
        scope_globs:  Glob patterns relative to *repo_root*.

    Returns:
        List of :class:`CodeChunk` objects, sorted by ``(file, start_line)``.
    """
    scope_paths = scope_paths or []
    scope_globs = scope_globs or []

    py_files = _resolve_scope_files(repo_root, scope_paths, scope_globs)
    logger.debug("Semantic index: %d Python files in scope", len(py_files))

    all_chunks: list[CodeChunk] = []

    for rel_path in py_files:
        try:
            raw = safe_read_file(repo_root, rel_path)
            source = raw.decode("utf-8")
        except (FileNotFoundError, ValueError, UnicodeDecodeError) as exc:
            logger.warning("Skipping %s: %s", rel_path, exc)
            continue

        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError as exc:
            logger.warning("Skipping %s (SyntaxError): %s", rel_path, exc)
            continue

        source_lines = source.splitlines()
        chunks = _extract_functions(tree, source_lines, rel_path)
        all_chunks.extend(chunks)

    # Stable sort by (file, start_line)
    all_chunks.sort(key=lambda c: (c.file, c.start_line))
    logger.debug("Semantic index: %d chunks extracted", len(all_chunks))
    return all_chunks


# ── BM25 index ──────────────────────────────────────────────────────


def build_bm25_index(chunks: list[CodeChunk]) -> BM25Okapi:
    """Build a BM25Okapi index from pre-tokenized chunks.

    Args:
        chunks: List of :class:`CodeChunk` with populated ``tokens`` field.

    Returns:
        A :class:`BM25Okapi` instance ready for querying.

    Raises:
        ValueError: If *chunks* is empty.
    """
    if not chunks:
        raise ValueError("Cannot build BM25 index from empty chunk list")

    corpus = [c.tokens for c in chunks]
    return BM25Okapi(corpus)


def query_bm25(
    query_text: str,
    bm25_index: BM25Okapi,
    chunks: list[CodeChunk],
    top_k: int = 25,
    min_score: float = 0.0,
) -> list[tuple[CodeChunk, float]]:
    """Query the BM25 index and return ``(chunk, normalised_score)`` pairs.

    Scores are normalised to ``[0, 1]`` by dividing by the maximum score
    in the result set (if the max is positive).

    Args:
        query_text: The natural-language or code query string.
        bm25_index: A :class:`BM25Okapi` instance built from *chunks*.
        chunks:     The same chunk list used to build *bm25_index*.
        top_k:      Maximum results to return.
        min_score:  Minimum normalised score to keep.

    Returns:
        List of ``(chunk, score)`` sorted by score descending, then by
        ``(file, start_line)`` ascending for ties.
    """
    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return []

    raw_scores = bm25_index.get_scores(query_tokens)
    max_score = float(max(raw_scores)) if len(raw_scores) > 0 else 0.0

    scored: list[tuple[CodeChunk, float]] = []
    for chunk, raw in zip(chunks, raw_scores):
        norm = float(raw) / max_score if max_score > 0 else 0.0
        if norm >= min_score:
            scored.append((chunk, norm))

    # Sort: score desc, then file asc, start_line asc for stability
    scored.sort(key=lambda pair: (-pair[1], pair[0].file, pair[0].start_line))

    return scored[:top_k]


# ── OpenAI Embedding Provider ───────────────────────────────────────


class OpenAIEmbeddingProvider:
    """Produces dense embeddings via the OpenAI Embeddings API.

    The ``openai`` client is lazily imported and initialised on first call
    to :meth:`embed` so that the module can be imported even when the
    ``openai`` package is absent or no API key is configured.

    Args:
        api_key: OpenAI API key.
        model:   Embedding model identifier (default ``text-embedding-3-small``).
    """

    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        self.api_key = api_key
        self.model = model
        self._client: object | None = None  # lazy

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts and return float vectors.

        Args:
            texts: A list of strings to embed.

        Returns:
            A list of embedding vectors (one per input text).

        Raises:
            ImportError: If the ``openai`` package is not installed.
            openai.OpenAIError: On API-level failures.
        """
        if not texts:
            return []

        if self._client is None:
            from openai import OpenAI  # lazy import
            self._client = OpenAI(api_key=self.api_key)

        response = self._client.embeddings.create(  # type: ignore[union-attr]
            input=texts,
            model=self.model,
        )
        return [item.embedding for item in response.data]


# ── Pinecone Vector Store ───────────────────────────────────────────


class PineconeVectorStore:
    """Thin wrapper around a Pinecone index for upsert/query.

    The ``pinecone`` client is lazily imported and initialised on first call
    to avoid hard dependency when the embedding path is not used.

    Args:
        api_key:    Pinecone API key.
        index_name: Name of the Pinecone index.
        host:       Pinecone index host URL.
    """

    _BATCH_SIZE: int = 100

    def __init__(self, api_key: str, index_name: str, host: str) -> None:
        self.api_key = api_key
        self.index_name = index_name
        self.host = host
        self._index: object | None = None  # lazy

    def _get_index(self) -> object:
        """Return (and cache) the Pinecone ``Index`` handle."""
        if self._index is None:
            from pinecone import Pinecone  # lazy import
            pc = Pinecone(api_key=self.api_key)
            self._index = pc.Index(self.index_name, host=self.host)
        return self._index

    def upsert(
        self,
        ids: list[str],
        vectors: list[list[float]],
        metadata_list: list[dict],
    ) -> None:
        """Upsert vectors into the Pinecone index in batches.

        Args:
            ids:           Vector IDs.
            vectors:       Dense embedding vectors.
            metadata_list: Per-vector metadata dicts.
        """
        index = self._get_index()
        records = list(zip(ids, vectors, metadata_list))
        for i in range(0, len(records), self._BATCH_SIZE):
            batch = records[i : i + self._BATCH_SIZE]
            index.upsert(vectors=batch)  # type: ignore[union-attr]

    def query(
        self,
        vector: list[float],
        top_k: int,
        filter_dict: dict | None = None,
    ) -> list:
        """Query the Pinecone index and return matches.

        Args:
            vector:      Query vector.
            top_k:       Maximum results.
            filter_dict: Optional metadata filter.

        Returns:
            A list of Pinecone ``ScoredVector`` match objects.
        """
        index = self._get_index()
        result = index.query(  # type: ignore[union-attr]
            vector=vector,
            top_k=top_k,
            include_metadata=True,
            filter=filter_dict,
        )
        return result.matches  # type: ignore[union-attr]
