"""Comprehensive tests for Tool 3 — Semantic Neighbor Search."""

from __future__ import annotations

import re
import textwrap

import pytest

from blast_radius_mcp.schemas.tool3_semantic import (
    IndexStats,
    Neighbor,
    Span,
    Tool3Diagnostic,
    Tool3Result,
)
from blast_radius_mcp.tools.tool3_semantic_neighbors import (
    TOOL3_IMPL_VERSION,
    run_tool3,
)
from blast_radius_mcp.indices.semantic_index import (
    CodeChunk,
    _tokenize,
    build_bm25_index,
    chunk_code_files,
    query_bm25,
)

# ── Helpers ──────────────────────────────────────────────────────────

CHUNK_ID_RE = re.compile(r"^chunk_[0-9a-f]{16}$")
NB_ID_RE = re.compile(r"^nb_[0-9a-f]{16}$")


def _write_py(tmp_path, relpath: str, source: str) -> str:
    """Write a Python source file under *tmp_path* and return *relpath*."""
    full = tmp_path / relpath
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(textwrap.dedent(source), encoding="utf-8")
    return relpath


# ═══════════════════════════════════════════════════════════════════════
# 1. TestTokenize
# ═══════════════════════════════════════════════════════════════════════


class TestTokenize:
    """Tests for _tokenize text processing."""

    def test_tokenize_basic(self):
        """Splits identifiers and lowercases them."""
        tokens = _tokenize("Hello World foo_bar")
        assert "hello" in tokens
        assert "world" in tokens
        assert "foo_bar" in tokens

    def test_tokenize_removes_stopwords(self):
        """Common stopwords like 'the', 'is', 'def' are filtered."""
        tokens = _tokenize("the class is not a def return")
        # All tokens here are stopwords
        assert "the" not in tokens
        assert "is" not in tokens
        assert "def" not in tokens
        assert "return" not in tokens
        assert "class" not in tokens

    def test_tokenize_removes_short(self):
        """Single-character tokens are filtered out."""
        tokens = _tokenize("x = a + b")
        assert "x" not in tokens
        assert "a" not in tokens
        assert "b" not in tokens

    def test_tokenize_camelcase(self):
        """CamelCase identifiers are preserved as lowercase tokens."""
        tokens = _tokenize("processDataHandler calculateScore")
        # The regex matches full identifiers, so camelCase stays as one token
        assert "processdatahandler" in tokens
        assert "calculatescore" in tokens

    def test_tokenize_underscored_identifiers(self):
        """Snake_case identifiers are kept as-is."""
        tokens = _tokenize("get_user_name set_value")
        assert "get_user_name" in tokens
        assert "set_value" in tokens

    def test_tokenize_numbers_in_identifiers(self):
        """Identifiers with numbers are kept."""
        tokens = _tokenize("value2 item3_count")
        assert "value2" in tokens
        assert "item3_count" in tokens

    def test_tokenize_empty_string(self):
        """Empty input returns empty list."""
        assert _tokenize("") == []

    def test_tokenize_only_stopwords(self):
        """Input with only stopwords returns empty list."""
        tokens = _tokenize("the is are not if")
        assert tokens == []

    def test_tokenize_code_snippet(self):
        """A realistic code snippet produces expected tokens."""
        code = "def calculate_total(items, tax_rate):\n    return sum(items) * tax_rate"
        tokens = _tokenize(code)
        assert "calculate_total" in tokens
        assert "items" in tokens
        assert "tax_rate" in tokens
        assert "sum" in tokens
        # 'def' and 'return' are stopwords
        assert "def" not in tokens
        assert "return" not in tokens


# ═══════════════════════════════════════════════════════════════════════
# 2. TestChunkCodeFiles
# ═══════════════════════════════════════════════════════════════════════


class TestChunkCodeFiles:
    """Tests for chunk_code_files AST-based chunking."""

    def test_chunk_extracts_functions(self, tmp_path):
        """Top-level functions are extracted as chunks."""
        _write_py(tmp_path, "mod.py", """\
            def greet(name):
                return f"Hello, {name}"

            def farewell(name):
                return f"Goodbye, {name}"
        """)
        chunks = chunk_code_files(str(tmp_path))

        symbols = [c.symbol for c in chunks]
        assert "greet" in symbols
        assert "farewell" in symbols
        assert len(chunks) == 2

    def test_chunk_extracts_methods(self, tmp_path):
        """Class methods are extracted with qualified names."""
        _write_py(tmp_path, "svc.py", """\
            class UserService:
                def get_user(self, user_id):
                    return {"id": user_id}

                def delete_user(self, user_id):
                    pass
        """)
        chunks = chunk_code_files(str(tmp_path))

        symbols = [c.symbol for c in chunks]
        assert "UserService.get_user" in symbols
        assert "UserService.delete_user" in symbols

    def test_chunk_deterministic_ids(self, tmp_path):
        """Chunk IDs are deterministic (same file → same IDs)."""
        _write_py(tmp_path, "det.py", """\
            def foo():
                pass

            def bar():
                pass
        """)
        chunks1 = chunk_code_files(str(tmp_path))
        chunks2 = chunk_code_files(str(tmp_path))

        ids1 = [c.chunk_id for c in chunks1]
        ids2 = [c.chunk_id for c in chunks2]
        assert ids1 == ids2

        for cid in ids1:
            assert CHUNK_ID_RE.match(cid), f"Expected chunk_ + 16 hex, got {cid!r}"

    def test_chunk_with_scope_paths(self, tmp_path):
        """scope_paths restricts chunking to specified paths."""
        _write_py(tmp_path, "included/a.py", """\
            def included_fn():
                pass
        """)
        _write_py(tmp_path, "excluded/b.py", """\
            def excluded_fn():
                pass
        """)

        chunks = chunk_code_files(
            str(tmp_path),
            scope_paths=["included"],
        )

        symbols = [c.symbol for c in chunks]
        assert "included_fn" in symbols
        assert "excluded_fn" not in symbols

    def test_chunk_with_scope_globs(self, tmp_path):
        """scope_globs restricts chunking via glob patterns."""
        _write_py(tmp_path, "src/api.py", """\
            def api_handler():
                pass
        """)
        _write_py(tmp_path, "tests/test_api.py", """\
            def test_handler():
                pass
        """)

        chunks = chunk_code_files(
            str(tmp_path),
            scope_globs=["src/**/*.py"],
        )

        symbols = [c.symbol for c in chunks]
        assert "api_handler" in symbols
        assert "test_handler" not in symbols

    def test_chunk_empty_repo(self, tmp_path):
        """No .py files → empty chunks."""
        # Create a non-Python file
        _write_py(tmp_path, "readme.md", "# Readme")
        (tmp_path / "readme.md").rename(tmp_path / "readme.txt")

        chunks = chunk_code_files(str(tmp_path))
        assert chunks == []

    def test_chunk_syntax_error_skipped(self, tmp_path):
        """Files with syntax errors are silently skipped."""
        _write_py(tmp_path, "good.py", """\
            def valid_fn():
                return 42
        """)
        _write_py(tmp_path, "bad.py", "def broken(:\n")

        chunks = chunk_code_files(str(tmp_path))

        symbols = [c.symbol for c in chunks]
        assert "valid_fn" in symbols
        # bad.py should not crash the pipeline

    def test_chunk_has_tokens(self, tmp_path):
        """Each chunk has pre-computed BM25 tokens."""
        _write_py(tmp_path, "tok.py", """\
            def compute_total(items, tax_rate):
                return sum(items) * tax_rate
        """)

        chunks = chunk_code_files(str(tmp_path))
        assert len(chunks) == 1
        assert len(chunks[0].tokens) > 0
        assert "compute_total" in chunks[0].tokens

    def test_chunk_file_field(self, tmp_path):
        """Chunk file field contains repo-relative path."""
        _write_py(tmp_path, "pkg/mod.py", """\
            def helper():
                pass
        """)

        chunks = chunk_code_files(str(tmp_path))
        assert len(chunks) == 1
        assert chunks[0].file == "pkg/mod.py"

    def test_chunk_line_numbers(self, tmp_path):
        """Chunk start_line and end_line are correct."""
        _write_py(tmp_path, "lines.py", """\
            def first():
                pass

            def second():
                return 1
        """)

        chunks = chunk_code_files(str(tmp_path))
        chunks_by_name = {c.symbol: c for c in chunks}

        first = chunks_by_name["first"]
        assert first.start_line == 1
        assert first.end_line == 2

        second = chunks_by_name["second"]
        assert second.start_line == 4
        assert second.end_line == 5


# ═══════════════════════════════════════════════════════════════════════
# 3. TestBM25
# ═══════════════════════════════════════════════════════════════════════


class TestBM25:
    """Tests for build_bm25_index and query_bm25."""

    def _make_chunks(self) -> list[CodeChunk]:
        """Create a small set of code chunks for testing."""
        return [
            CodeChunk(
                chunk_id="chunk_aaa",
                file="math_utils.py",
                symbol="calculate_tax",
                source="def calculate_tax(amount, rate):\n    return amount * rate",
                start_line=1,
                end_line=2,
                start_col=0,
                end_col=0,
                tokens=_tokenize(
                    "def calculate_tax(amount, rate):\n    return amount * rate"
                ),
            ),
            CodeChunk(
                chunk_id="chunk_bbb",
                file="user_service.py",
                symbol="get_user_profile",
                source="def get_user_profile(user_id):\n    return db.query(user_id)",
                start_line=1,
                end_line=2,
                start_col=0,
                end_col=0,
                tokens=_tokenize(
                    "def get_user_profile(user_id):\n    return db.query(user_id)"
                ),
            ),
            CodeChunk(
                chunk_id="chunk_ccc",
                file="payment.py",
                symbol="process_payment",
                source="def process_payment(amount, card):\n    validate(card)\n    charge(amount)",
                start_line=1,
                end_line=3,
                start_col=0,
                end_col=0,
                tokens=_tokenize(
                    "def process_payment(amount, card):\n    validate(card)\n    charge(amount)"
                ),
            ),
        ]

    def test_bm25_basic_search(self):
        """Finds relevant chunks by keyword match."""
        chunks = self._make_chunks()
        index = build_bm25_index(chunks)

        results = query_bm25("calculate tax amount", index, chunks)

        assert len(results) > 0
        # The tax calculation chunk should rank first
        top_chunk, top_score = results[0]
        assert top_chunk.symbol == "calculate_tax"
        assert top_score > 0

    def test_bm25_min_score_filter(self):
        """Results below min_score are filtered out."""
        chunks = self._make_chunks()
        index = build_bm25_index(chunks)

        # Very high min_score should filter most/all results
        results = query_bm25(
            "calculate tax", index, chunks, min_score=0.99
        )

        # Only the top scorer (normalized to 1.0) might pass
        assert len(results) <= 1

    def test_bm25_top_k_limit(self):
        """top_k limits the number of returned results."""
        chunks = self._make_chunks()
        index = build_bm25_index(chunks)

        results = query_bm25(
            "amount", index, chunks, top_k=1, min_score=0.0
        )

        assert len(results) <= 1

    def test_bm25_empty_query(self):
        """Empty or all-stopword query returns no results."""
        chunks = self._make_chunks()
        index = build_bm25_index(chunks)

        # Empty string
        results = query_bm25("", index, chunks)
        assert results == []

        # Only stopwords / single chars
        results = query_bm25("the is a", index, chunks)
        assert results == []

    def test_bm25_empty_chunks_raises(self):
        """Building BM25 index from empty list raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            build_bm25_index([])

    def test_bm25_scores_normalized(self):
        """Scores are normalised to [0, 1]."""
        chunks = self._make_chunks()
        index = build_bm25_index(chunks)

        results = query_bm25("calculate tax amount", index, chunks, min_score=0.0)

        for _, score in results:
            assert 0.0 <= score <= 1.0

        # The top result should be normalised to 1.0
        if results:
            assert results[0][1] == 1.0

    def test_bm25_deterministic(self):
        """Same query on same data produces same results."""
        chunks = self._make_chunks()
        index = build_bm25_index(chunks)

        r1 = query_bm25("user profile query", index, chunks, min_score=0.0)
        r2 = query_bm25("user profile query", index, chunks, min_score=0.0)

        assert len(r1) == len(r2)
        for (c1, s1), (c2, s2) in zip(r1, r2):
            assert c1.chunk_id == c2.chunk_id
            assert s1 == s2

    def test_bm25_with_real_chunks(self, tmp_path):
        """BM25 works end-to-end with chunks from chunk_code_files."""
        _write_py(tmp_path, "search.py", """\
            def search_users(query_string):
                results = database.find(query_string)
                return results

            def search_products(keyword):
                return catalog.search(keyword)

            def delete_account(user_id):
                database.remove(user_id)
        """)

        chunks = chunk_code_files(str(tmp_path))
        assert len(chunks) == 3

        index = build_bm25_index(chunks)
        results = query_bm25("search query", index, chunks, min_score=0.0)

        # The search functions should rank higher than delete_account
        assert len(results) >= 2
        top_symbols = [r[0].symbol for r in results[:2]]
        assert "search_users" in top_symbols or "search_products" in top_symbols


# ═══════════════════════════════════════════════════════════════════════
# 4. TestRunTool3Integration
# ═══════════════════════════════════════════════════════════════════════


class TestRunTool3Integration:
    """End-to-end tests for run_tool3."""

    def test_run_tool3_bm25_mode(self, tmp_path):
        """Explicit bm25 mode works end-to-end."""
        _write_py(tmp_path, "handlers.py", """\
            def handle_login(username, password):
                user = authenticate(username, password)
                return create_session(user)

            def handle_logout(session_id):
                destroy_session(session_id)
        """)

        result = run_tool3(
            {
                "query_text": "user authentication login",
                "scope": {},
                "options": {"mode": "bm25", "min_score": 0.0},
            },
            str(tmp_path),
        )

        parsed = Tool3Result(**result)
        assert parsed.retrieval_mode == "bm25_fallback"
        assert parsed.index_stats.backend == "bm25"
        assert len(parsed.neighbors) > 0

        # The login handler should score well
        symbols = [n.symbol for n in parsed.neighbors]
        assert "handle_login" in symbols

    def test_run_tool3_auto_fallback(self, tmp_path):
        """Auto mode falls back to bm25 when no API keys are configured."""
        _write_py(tmp_path, "utils.py", """\
            def format_date(timestamp):
                return timestamp.strftime("%Y-%m-%d")
        """)

        result = run_tool3(
            {
                "query_text": "format date timestamp",
                "scope": {},
                "options": {"mode": "auto", "min_score": 0.0},
            },
            str(tmp_path),
        )

        parsed = Tool3Result(**result)
        # Without API keys, should fall back to BM25
        assert parsed.retrieval_mode == "bm25_fallback"
        assert parsed.index_stats.backend == "bm25"
        # Should have a diagnostic about missing provider
        codes = [d.code for d in parsed.diagnostics]
        assert "semantic_provider_unavailable" in codes

    def test_run_tool3_all_uncorroborated(self, tmp_path):
        """All results have uncorroborated=True."""
        _write_py(tmp_path, "service.py", """\
            def process_order(order_data):
                validate(order_data)
                save(order_data)
                return {"status": "ok"}

            def cancel_order(order_id):
                mark_cancelled(order_id)
        """)

        result = run_tool3(
            {
                "query_text": "process order validation",
                "scope": {},
                "options": {"mode": "bm25", "min_score": 0.0},
            },
            str(tmp_path),
        )

        parsed = Tool3Result(**result)
        for nb in parsed.neighbors:
            assert nb.uncorroborated is True

    def test_run_tool3_deterministic(self, tmp_path):
        """Two runs produce identical output."""
        _write_py(tmp_path, "calc.py", """\
            def add(a, b):
                return a + b

            def multiply(a, b):
                return a * b
        """)

        inputs = {
            "query_text": "add numbers together",
            "scope": {},
            "options": {"mode": "bm25", "min_score": 0.0},
        }

        result1 = run_tool3(inputs, str(tmp_path))
        result2 = run_tool3(inputs, str(tmp_path))

        assert result1 == result2

    def test_run_tool3_empty_repo(self, tmp_path):
        """No Python files → semantic_index_empty diagnostic."""
        # Create only a non-Python file
        (tmp_path / "readme.txt").write_text("no python here")

        result = run_tool3(
            {
                "query_text": "find something",
                "scope": {},
                "options": {"mode": "bm25"},
            },
            str(tmp_path),
        )

        parsed = Tool3Result(**result)
        codes = [d.code for d in parsed.diagnostics]
        assert "semantic_index_empty" in codes
        assert parsed.neighbors == []
        assert parsed.index_stats.chunks_total == 0

    def test_run_tool3_min_score_filters_all(self, tmp_path):
        """All chunks below threshold → threshold_filtered_all diagnostic."""
        _write_py(tmp_path, "misc.py", """\
            def completely_unrelated():
                pass
        """)

        result = run_tool3(
            {
                "query_text": "database migration schema",
                "scope": {},
                "options": {"mode": "bm25", "min_score": 0.99},
            },
            str(tmp_path),
        )

        parsed = Tool3Result(**result)
        codes = [d.code for d in parsed.diagnostics]
        assert "threshold_filtered_all" in codes
        assert parsed.neighbors == []

    def test_run_tool3_neighbor_structure(self, tmp_path):
        """Neighbor objects have correct structure and ID format."""
        _write_py(tmp_path, "api.py", """\
            def fetch_data(endpoint):
                response = http_get(endpoint)
                return response.json()
        """)

        result = run_tool3(
            {
                "query_text": "fetch data endpoint http",
                "scope": {},
                "options": {"mode": "bm25", "min_score": 0.0},
            },
            str(tmp_path),
        )

        parsed = Tool3Result(**result)
        assert len(parsed.neighbors) > 0

        nb = parsed.neighbors[0]
        assert NB_ID_RE.match(nb.neighbor_id), f"Expected nb_ + 16 hex, got {nb.neighbor_id!r}"
        assert nb.file == "api.py"
        assert nb.symbol == "fetch_data"
        assert nb.method == "bm25"
        assert 0.0 <= nb.score <= 1.0
        assert nb.span.start.line >= 1
        assert nb.span.end.line >= nb.span.start.line
        assert nb.rationale_snippet  # non-empty

    def test_run_tool3_top_k_respected(self, tmp_path):
        """top_k limits the number of returned neighbors."""
        # Create many functions
        funcs = "\n".join(
            f"def func_{i}(x):\n    return x + {i}\n"
            for i in range(10)
        )
        _write_py(tmp_path, "many.py", funcs)

        result = run_tool3(
            {
                "query_text": "func return",
                "scope": {},
                "options": {"mode": "bm25", "top_k": 3, "min_score": 0.0},
            },
            str(tmp_path),
        )

        parsed = Tool3Result(**result)
        assert len(parsed.neighbors) <= 3

    def test_run_tool3_scope_filtering(self, tmp_path):
        """Scope paths restrict which files are searched."""
        _write_py(tmp_path, "src/core.py", """\
            def core_logic():
                return compute()
        """)
        _write_py(tmp_path, "tests/test_core.py", """\
            def test_core():
                assert core_logic() is not None
        """)

        result = run_tool3(
            {
                "query_text": "core logic compute",
                "scope": {"paths": ["src"]},
                "options": {"mode": "bm25", "min_score": 0.0},
            },
            str(tmp_path),
        )

        parsed = Tool3Result(**result)
        files = {n.file for n in parsed.neighbors}
        assert "src/core.py" in files
        # test file should be excluded by scope
        assert "tests/test_core.py" not in files

    def test_run_tool3_index_stats(self, tmp_path):
        """IndexStats reports correct chunk counts."""
        _write_py(tmp_path, "a.py", """\
            def func_a():
                pass
        """)
        _write_py(tmp_path, "b.py", """\
            def func_b():
                pass

            def func_c():
                pass
        """)

        result = run_tool3(
            {
                "query_text": "function",
                "scope": {},
                "options": {"mode": "bm25", "min_score": 0.0},
            },
            str(tmp_path),
        )

        parsed = Tool3Result(**result)
        assert parsed.index_stats.chunks_total == 3
        assert parsed.index_stats.chunks_scanned == 3
        assert parsed.index_stats.backend == "bm25"
