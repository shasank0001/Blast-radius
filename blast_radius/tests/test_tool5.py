"""Comprehensive tests for Tool 5 — Test Impact Analyzer."""

from __future__ import annotations

import re
import textwrap

import pytest

from blast_radius_mcp.schemas.tool5_tests import (
    ImpactedNode,
    Tool5Options,
    Tool5Request,
    Tool5Result,
    TestItem,
    TestReason,
    UnmatchedImpact,
    SelectionStats,
    Tool5Diagnostic,
)
from blast_radius_mcp.tools.tool5_test_impact import (
    TOOL5_IMPL_VERSION,
    _file_path_to_module,
    _is_test_filename,
    _compute_test_id,
    _sha256_prefix,
    discover_tests,
    build_test_index,
    build_module_graph,
    get_transitive_imports,
    score_tests,
    run_tool5,
)


# ── Helpers ──────────────────────────────────────────────────────────

TEST_ID_RE = re.compile(r"^test_[0-9a-f]{16}$")
SHA_PREFIX_RE = re.compile(r"^[0-9a-f]{16}$")


def _write_py(tmp_path, relpath: str, source: str) -> str:
    """Write a Python source file under *tmp_path* and return *relpath*."""
    full = tmp_path / relpath
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(textwrap.dedent(source), encoding="utf-8")
    return relpath


# ═══════════════════════════════════════════════════════════════════════
# 1. TestHelpers
# ═══════════════════════════════════════════════════════════════════════


class TestHelpers:
    """Tests for module-level helper functions."""

    def test_file_path_to_module_simple(self):
        assert _file_path_to_module("app/api/orders.py") == "app.api.orders"

    def test_file_path_to_module_init(self):
        assert _file_path_to_module("app/__init__.py") == "app"

    def test_file_path_to_module_nested_init(self):
        assert _file_path_to_module("app/api/__init__.py") == "app.api"

    def test_file_path_to_module_top_level(self):
        assert _file_path_to_module("main.py") == "main"

    def test_is_test_filename_test_prefix(self):
        assert _is_test_filename("test_foo.py") is True

    def test_is_test_filename_test_suffix(self):
        assert _is_test_filename("foo_test.py") is True

    def test_is_test_filename_not_test(self):
        assert _is_test_filename("foo.py") is False

    def test_is_test_filename_conftest(self):
        assert _is_test_filename("conftest.py") is False

    def test_compute_test_id_deterministic(self):
        id1 = _compute_test_id("tests/test_a.py::test_x", "tests/test_a.py")
        id2 = _compute_test_id("tests/test_a.py::test_x", "tests/test_a.py")
        assert id1 == id2
        assert TEST_ID_RE.match(id1)

    def test_compute_test_id_different_inputs(self):
        id1 = _compute_test_id("tests/test_a.py::test_x", "tests/test_a.py")
        id2 = _compute_test_id("tests/test_b.py::test_y", "tests/test_b.py")
        assert id1 != id2

    def test_sha256_prefix_format(self):
        result = _sha256_prefix("pfx_", "a", "b", "c")
        assert result.startswith("pfx_")
        suffix = result[len("pfx_"):]
        assert len(suffix) == 16
        assert SHA_PREFIX_RE.match(suffix)


# ═══════════════════════════════════════════════════════════════════════
# 2. TestDiscoverTests
# ═══════════════════════════════════════════════════════════════════════


class TestDiscoverTests:
    """Tests for discover_tests() discovery strategies."""

    def test_discover_from_pytest_ini(self, tmp_path):
        (tmp_path / "pytest.ini").write_text(
            "[pytest]\ntestpaths = mytests\n", encoding="utf-8",
        )
        _write_py(tmp_path, "mytests/test_alpha.py", "def test_a(): pass\n")
        test_files, diags = discover_tests(str(tmp_path))
        assert any("mytests/test_alpha.py" in f for f in test_files)
        assert not diags

    def test_discover_from_pyproject_toml(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            textwrap.dedent("""\
                [tool.pytest.ini_options]
                testpaths = ["suite"]
            """),
            encoding="utf-8",
        )
        _write_py(tmp_path, "suite/test_beta.py", "def test_b(): pass\n")
        test_files, diags = discover_tests(str(tmp_path))
        assert any("suite/test_beta.py" in f for f in test_files)
        assert not diags

    def test_discover_from_setup_cfg(self, tmp_path):
        (tmp_path / "setup.cfg").write_text(
            "[tool:pytest]\ntestpaths = stests\n", encoding="utf-8",
        )
        _write_py(tmp_path, "stests/test_gamma.py", "def test_g(): pass\n")
        test_files, diags = discover_tests(str(tmp_path))
        assert any("stests/test_gamma.py" in f for f in test_files)
        assert not diags

    def test_discover_conventional_tests_dir(self, tmp_path):
        _write_py(tmp_path, "tests/test_one.py", "def test_1(): pass\n")
        test_files, diags = discover_tests(str(tmp_path))
        assert any("tests/test_one.py" in f for f in test_files)
        assert not diags

    def test_discover_conventional_test_dir(self, tmp_path):
        _write_py(tmp_path, "test/test_two.py", "def test_2(): pass\n")
        test_files, diags = discover_tests(str(tmp_path))
        assert any("test/test_two.py" in f for f in test_files)
        assert not diags

    def test_discover_fallback_anywhere(self, tmp_path):
        _write_py(tmp_path, "src/test_scattered.py", "def test_s(): pass\n")
        _write_py(tmp_path, "lib/another_test.py", "def test_a(): pass\n")
        test_files, diags = discover_tests(str(tmp_path))
        assert len(test_files) >= 2
        names = [f.split("/")[-1] for f in test_files]
        assert "test_scattered.py" in names
        assert "another_test.py" in names
        assert not diags

    def test_discover_no_tests(self, tmp_path):
        # Empty repo — no Python files at all
        test_files, diags = discover_tests(str(tmp_path))
        assert test_files == []
        assert len(diags) == 1
        assert diags[0].code == "tests_not_found"

    def test_discover_ignores_non_test_files(self, tmp_path):
        _write_py(tmp_path, "tests/helper.py", "x = 1\n")
        _write_py(tmp_path, "tests/conftest.py", "import pytest\n")
        _write_py(tmp_path, "tests/test_real.py", "def test_r(): pass\n")
        test_files, diags = discover_tests(str(tmp_path))
        basenames = [f.split("/")[-1] for f in test_files]
        assert "test_real.py" in basenames
        assert "helper.py" not in basenames
        assert "conftest.py" not in basenames


# ═══════════════════════════════════════════════════════════════════════
# 3. TestBuildTestIndex
# ═══════════════════════════════════════════════════════════════════════


class TestBuildTestIndex:
    """Tests for build_test_index() parsing and extraction."""

    def test_index_extracts_imports(self, tmp_path):
        _write_py(tmp_path, "tests/test_imp.py", """\
            import foo
            from bar import baz

            def test_something():
                pass
        """)
        idx, diags = build_test_index(str(tmp_path), ["tests/test_imp.py"])
        assert not diags
        info = idx["tests/test_imp.py"]
        assert "foo" in info.imported_modules
        assert "bar" in info.imported_modules
        assert ("bar", "baz") in info.imported_symbols

    def test_index_extracts_nodeids_functions(self, tmp_path):
        _write_py(tmp_path, "tests/test_funcs.py", """\
            def test_alpha():
                pass

            def test_beta():
                pass

            def helper():
                pass
        """)
        idx, diags = build_test_index(str(tmp_path), ["tests/test_funcs.py"])
        assert not diags
        info = idx["tests/test_funcs.py"]
        assert "tests/test_funcs.py::test_alpha" in info.nodeids
        assert "tests/test_funcs.py::test_beta" in info.nodeids
        # helper is not a test
        assert all("helper" not in nid for nid in info.nodeids)

    def test_index_extracts_nodeids_class_methods(self, tmp_path):
        _write_py(tmp_path, "tests/test_cls.py", """\
            class TestFoo:
                def test_bar(self):
                    pass

                def test_baz(self):
                    pass
        """)
        idx, diags = build_test_index(str(tmp_path), ["tests/test_cls.py"])
        assert not diags
        info = idx["tests/test_cls.py"]
        assert "tests/test_cls.py::TestFoo::test_bar" in info.nodeids
        assert "tests/test_cls.py::TestFoo::test_baz" in info.nodeids

    def test_index_extracts_async_tests(self, tmp_path):
        _write_py(tmp_path, "tests/test_async.py", """\
            async def test_async_one():
                pass
        """)
        idx, diags = build_test_index(str(tmp_path), ["tests/test_async.py"])
        assert not diags
        info = idx["tests/test_async.py"]
        assert "tests/test_async.py::test_async_one" in info.nodeids

    def test_index_extracts_name_references(self, tmp_path):
        _write_py(tmp_path, "tests/test_refs.py", """\
            import foo

            def test_ref():
                result = foo.compute()
                assert result is not None
        """)
        idx, diags = build_test_index(str(tmp_path), ["tests/test_refs.py"])
        assert not diags
        info = idx["tests/test_refs.py"]
        # "foo" and "result" and "compute" should appear as name references
        assert "foo" in info.name_references
        assert "result" in info.name_references
        assert "compute" in info.name_references

    def test_index_extracts_string_literals(self, tmp_path):
        _write_py(tmp_path, "tests/test_strings.py", """\
            def test_lit():
                assert "email" in data
                assert "username" in data
        """)
        idx, diags = build_test_index(str(tmp_path), ["tests/test_strings.py"])
        assert not diags
        info = idx["tests/test_strings.py"]
        assert "email" in info.string_literals
        assert "username" in info.string_literals

    def test_index_handles_syntax_error(self, tmp_path):
        bad = tmp_path / "tests" / "test_bad.py"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("def test_oops(\n", encoding="utf-8")  # broken syntax
        idx, diags = build_test_index(str(tmp_path), ["tests/test_bad.py"])
        assert "tests/test_bad.py" not in idx
        assert len(diags) == 1
        assert diags[0].code == "test_parse_error"

    def test_index_handles_missing_file(self, tmp_path):
        idx, diags = build_test_index(
            str(tmp_path), ["tests/test_nonexistent.py"],
        )
        assert "tests/test_nonexistent.py" not in idx
        assert len(diags) == 1
        assert diags[0].code == "test_parse_error"


# ═══════════════════════════════════════════════════════════════════════
# 4. TestModuleGraph
# ═══════════════════════════════════════════════════════════════════════


class TestModuleGraph:
    """Tests for build_module_graph() and get_transitive_imports()."""

    def test_build_module_graph_simple(self, tmp_path):
        _write_py(tmp_path, "a.py", "import b\n")
        _write_py(tmp_path, "b.py", "x = 1\n")
        graph = build_module_graph(str(tmp_path))
        assert "b" in graph.get("a", set())

    def test_transitive_imports_depth_1(self, tmp_path):
        graph = {"a": {"b"}, "b": {"c"}, "c": set()}
        result = get_transitive_imports("a", graph, max_depth=1)
        assert "b" in result
        assert result["b"] == 1
        assert "c" not in result

    def test_transitive_imports_depth_2(self, tmp_path):
        graph = {"a": {"b"}, "b": {"c"}, "c": set()}
        result = get_transitive_imports("a", graph, max_depth=2)
        assert result["b"] == 1
        assert result["c"] == 2

    def test_transitive_imports_depth_0(self, tmp_path):
        graph = {"a": {"b"}, "b": {"c"}, "c": set()}
        result = get_transitive_imports("a", graph, max_depth=0)
        assert result == {}

    def test_transitive_no_cycle(self, tmp_path):
        graph = {"a": {"b"}, "b": {"a"}}
        # Should terminate without infinite loop
        result = get_transitive_imports("a", graph, max_depth=5)
        assert "b" in result
        # "a" should not be in the result (it's the starting module)
        assert "a" not in result


# ═══════════════════════════════════════════════════════════════════════
# 5. TestScoring
# ═══════════════════════════════════════════════════════════════════════


class TestScoring:
    """Tests for score_tests() scoring, confidence, and ranking logic."""

    def _make_test_index(self, tmp_path, test_source: str, rel_path: str = "tests/test_s.py"):
        """Helper: write a test file, build its index, and return the index dict."""
        _write_py(tmp_path, rel_path, test_source)
        idx, _ = build_test_index(str(tmp_path), [rel_path])
        return idx

    def test_direct_import_scores_1(self, tmp_path):
        idx = self._make_test_index(tmp_path, """\
            import app.api.orders

            def test_orders():
                pass
        """)
        nodes = [ImpactedNode(file="app/api/orders.py")]
        options = Tool5Options(include_transitive=False)
        tests, _ = score_tests(nodes, idx, {}, options)
        assert len(tests) >= 1
        assert tests[0].score == 1.0
        reasons = [r.type for r in tests[0].reasons]
        assert "direct_import" in reasons

    def test_from_import_symbol_scores_1(self, tmp_path):
        idx = self._make_test_index(tmp_path, """\
            from app.api.orders import create_order

            def test_create():
                pass
        """)
        nodes = [ImpactedNode(file="app/api/orders.py", symbol="create_order")]
        options = Tool5Options(include_transitive=False)
        tests, _ = score_tests(nodes, idx, {}, options)
        assert len(tests) >= 1
        # Should have from_import_symbol and/or direct_import reasons
        reasons = [r.type for r in tests[0].reasons]
        assert "from_import_symbol" in reasons

    def test_symbol_reference_scores_0_4(self, tmp_path):
        idx = self._make_test_index(tmp_path, """\
            def test_ref():
                result = create_order()
        """)
        nodes = [ImpactedNode(file="app/api/orders.py", symbol="create_order")]
        options = Tool5Options(include_transitive=False)
        tests, _ = score_tests(nodes, idx, {}, options)
        assert len(tests) >= 1
        reasons = [r.type for r in tests[0].reasons]
        assert "symbol_reference" in reasons
        assert tests[0].score == pytest.approx(0.4, abs=0.01)

    def test_field_literal_match_scores_0_2(self, tmp_path):
        idx = self._make_test_index(tmp_path, """\
            def test_field():
                assert "email" in payload
        """)
        nodes = [ImpactedNode(file="app/models.py", symbol="email", kind="field")]
        options = Tool5Options(include_transitive=False)
        tests, _ = score_tests(nodes, idx, {}, options)
        assert len(tests) >= 1
        reasons = [r.type for r in tests[0].reasons]
        assert "field_literal_match" in reasons
        assert tests[0].score == pytest.approx(0.2, abs=0.01)

    def test_score_capped_at_1(self, tmp_path):
        # A test that matches on multiple signals: direct_import (1.0) +
        # symbol_reference (0.4) → should be capped at 1.0.
        idx = self._make_test_index(tmp_path, """\
            import app.api.orders

            def test_cap():
                create_order()
        """)
        nodes = [ImpactedNode(file="app/api/orders.py", symbol="create_order")]
        options = Tool5Options(include_transitive=False)
        tests, _ = score_tests(nodes, idx, {}, options)
        assert len(tests) >= 1
        assert tests[0].score <= 1.0

    def test_confidence_high(self, tmp_path):
        idx = self._make_test_index(tmp_path, """\
            import app.core

            def test_high():
                pass
        """)
        nodes = [ImpactedNode(file="app/core.py")]
        options = Tool5Options(include_transitive=False)
        tests, _ = score_tests(nodes, idx, {}, options)
        assert len(tests) >= 1
        # direct_import gives score 1.0 → high confidence
        assert tests[0].confidence == "high"

    def test_confidence_medium(self, tmp_path):
        # symbol_reference alone gives 0.4 → medium
        idx = self._make_test_index(tmp_path, """\
            def test_med():
                do_work()
        """)
        nodes = [ImpactedNode(file="app/worker.py", symbol="do_work")]
        options = Tool5Options(include_transitive=False)
        tests, _ = score_tests(nodes, idx, {}, options)
        assert len(tests) >= 1
        assert tests[0].confidence == "medium"

    def test_confidence_low(self, tmp_path):
        # field_literal_match alone gives 0.2 → low
        idx = self._make_test_index(tmp_path, """\
            def test_low():
                assert "status" in resp
        """)
        nodes = [ImpactedNode(file="app/models.py", symbol="status", kind="field")]
        options = Tool5Options(include_transitive=False)
        tests, _ = score_tests(nodes, idx, {}, options)
        assert len(tests) >= 1
        assert tests[0].confidence == "low"

    def test_deterministic_ranking(self, tmp_path):
        _write_py(tmp_path, "tests/test_a.py", textwrap.dedent("""\
            import app.core

            def test_a1():
                pass

            def test_a2():
                pass
        """))
        _write_py(tmp_path, "tests/test_b.py", textwrap.dedent("""\
            import app.core

            def test_b1():
                pass
        """))
        idx, _ = build_test_index(
            str(tmp_path), ["tests/test_a.py", "tests/test_b.py"],
        )
        nodes = [ImpactedNode(file="app/core.py")]
        options = Tool5Options(include_transitive=False, max_tests=10)

        tests1, _ = score_tests(nodes, idx, {}, options)
        tests2, _ = score_tests(nodes, idx, {}, options)

        assert len(tests1) == len(tests2)
        for t1, t2 in zip(tests1, tests2):
            assert t1.nodeid == t2.nodeid
            assert t1.rank == t2.rank
            assert t1.score == t2.score

    def test_max_tests_trim(self, tmp_path):
        # Create many test functions that all match
        funcs = "\n".join(f"def test_{i}(): pass" for i in range(20))
        source = "import app.core\n\n" + funcs
        _write_py(tmp_path, "tests/test_many.py", source)
        idx, _ = build_test_index(str(tmp_path), ["tests/test_many.py"])
        nodes = [ImpactedNode(file="app/core.py")]
        options = Tool5Options(include_transitive=False, max_tests=5)

        tests, _ = score_tests(nodes, idx, {}, options)
        assert len(tests) == 5
        # Ranks should be 1..5
        for i, t in enumerate(tests, start=1):
            assert t.rank == i

    def test_unmatched_impacts(self, tmp_path):
        idx = self._make_test_index(tmp_path, """\
            import app.core

            def test_core():
                pass
        """)
        nodes = [
            ImpactedNode(file="app/core.py"),
            ImpactedNode(file="app/unrelated.py", symbol="something"),
        ]
        options = Tool5Options(include_transitive=False)
        tests, unmatched = score_tests(nodes, idx, {}, options)
        assert len(tests) >= 1
        unmatched_files = [u.file for u in unmatched]
        assert "app/unrelated.py" in unmatched_files

    def test_empty_test_index(self, tmp_path):
        nodes = [
            ImpactedNode(file="app/core.py"),
            ImpactedNode(file="app/api/orders.py", symbol="create"),
        ]
        options = Tool5Options(include_transitive=False)
        tests, unmatched = score_tests(nodes, {}, {}, options)
        assert tests == []
        assert len(unmatched) == 2
        for u in unmatched:
            assert u.reason == "test_discovery_empty"


# ═══════════════════════════════════════════════════════════════════════
# 6. TestRunTool5Integration
# ═══════════════════════════════════════════════════════════════════════


class TestRunTool5Integration:
    """Integration tests for run_tool5() full pipeline."""

    def test_run_tool5_basic(self, tmp_path):
        _write_py(tmp_path, "app/core.py", """\
            def compute():
                return 42
        """)
        _write_py(tmp_path, "tests/test_core.py", """\
            import app.core

            def test_compute():
                assert app.core.compute() == 42
        """)
        request = {
            "impacted_nodes": [{"file": "app/core.py", "symbol": "compute"}],
        }
        result = run_tool5(request, str(tmp_path))
        # Validate via schema
        parsed = Tool5Result(**result)
        assert len(parsed.tests) >= 1
        assert parsed.selection_stats.tests_selected >= 1
        assert parsed.tests[0].rank == 1
        assert parsed.tests[0].score > 0

    def test_run_tool5_no_tests(self, tmp_path):
        _write_py(tmp_path, "app/core.py", "x = 1\n")
        request = {
            "impacted_nodes": [{"file": "app/core.py"}],
        }
        result = run_tool5(request, str(tmp_path))
        parsed = Tool5Result(**result)
        assert parsed.tests == []
        assert len(parsed.unmatched_impacts) == 1
        assert parsed.unmatched_impacts[0].reason == "test_discovery_empty"
        diag_codes = [d.code for d in parsed.diagnostics]
        assert "tests_not_found" in diag_codes

    def test_run_tool5_deterministic(self, tmp_path):
        _write_py(tmp_path, "app/service.py", """\
            def process():
                return True
        """)
        _write_py(tmp_path, "tests/test_service.py", """\
            import app.service

            def test_process():
                assert app.service.process()
        """)
        request = {
            "impacted_nodes": [{"file": "app/service.py", "symbol": "process"}],
        }
        r1 = run_tool5(request, str(tmp_path))
        r2 = run_tool5(request, str(tmp_path))
        assert r1 == r2

    def test_run_tool5_max_tests_truncation(self, tmp_path):
        _write_py(tmp_path, "app/core.py", "val = 1\n")
        # Create enough test functions to trigger truncation
        funcs = "\n".join(f"def test_{i}(): pass" for i in range(15))
        source = "import app.core\n\n" + funcs
        _write_py(tmp_path, "tests/test_lots.py", source)
        request = {
            "impacted_nodes": [{"file": "app/core.py"}],
            "options": {"max_tests": 3, "include_transitive": False},
        }
        result = run_tool5(request, str(tmp_path))
        parsed = Tool5Result(**result)
        assert parsed.selection_stats.tests_selected <= 3
        diag_codes = [d.code for d in parsed.diagnostics]
        assert "selection_truncated" in diag_codes

    def test_run_tool5_syntax_error_in_test(self, tmp_path):
        _write_py(tmp_path, "app/core.py", "x = 1\n")
        # Good test file
        _write_py(tmp_path, "tests/test_ok.py", """\
            import app.core

            def test_ok():
                pass
        """)
        # Bad test file with syntax error
        bad = tmp_path / "tests" / "test_broken.py"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("def test_broken(\n", encoding="utf-8")

        request = {
            "impacted_nodes": [{"file": "app/core.py"}],
        }
        result = run_tool5(request, str(tmp_path))
        parsed = Tool5Result(**result)
        # Should not crash; the good test should still be found
        assert len(parsed.tests) >= 1
        diag_codes = [d.code for d in parsed.diagnostics]
        assert "test_parse_error" in diag_codes

    def test_run_tool5_transitive(self, tmp_path):
        # app.core imports app.db; impacted node is app.db;
        # test imports app.core → should find via transitive import.
        _write_py(tmp_path, "app/__init__.py", "")
        _write_py(tmp_path, "app/db.py", """\
            def query():
                return []
        """)
        _write_py(tmp_path, "app/core.py", """\
            import app.db

            def process():
                return app.db.query()
        """)
        _write_py(tmp_path, "tests/test_core.py", """\
            import app.core

            def test_process():
                assert app.core.process() == []
        """)
        request = {
            "impacted_nodes": [{"file": "app/db.py"}],
            "options": {"include_transitive": True, "transitive_depth": 2},
        }
        result = run_tool5(request, str(tmp_path))
        parsed = Tool5Result(**result)
        assert len(parsed.tests) >= 1
        # Should have a transitive_import reason
        all_reasons = [r.type for t in parsed.tests for r in t.reasons]
        assert "transitive_import" in all_reasons

    def test_run_tool5_coverage_mode_optional_emits_coverage_unavailable(self, tmp_path):
        _write_py(tmp_path, "app/core.py", "x = 1\n")
        _write_py(tmp_path, "tests/test_core.py", "def test_x():\n    assert True\n")

        request = {
            "impacted_nodes": [{"file": "app/core.py"}],
            "options": {"coverage_mode": "optional"},
        }
        parsed = Tool5Result(**run_tool5(request, str(tmp_path)))
        diag_codes = [d.code for d in parsed.diagnostics]
        assert "coverage_unavailable" in diag_codes

    def test_run_tool5_coverage_mode_off_emits_no_coverage_unavailable(self, tmp_path):
        _write_py(tmp_path, "app/core.py", "x = 1\n")
        _write_py(tmp_path, "tests/test_core.py", "def test_x():\n    assert True\n")

        request = {
            "impacted_nodes": [{"file": "app/core.py"}],
            "options": {"coverage_mode": "off"},
        }
        parsed = Tool5Result(**run_tool5(request, str(tmp_path)))
        diag_codes = [d.code for d in parsed.diagnostics]
        assert "coverage_unavailable" not in diag_codes
