"""Comprehensive tests for Tool 1 — AST Structural Engine."""

from __future__ import annotations

import ast
import re
import textwrap

import pytest

from blast_radius_mcp.schemas.common import Position, Range
from blast_radius_mcp.schemas.tool1_ast import (
    ASTEdge,
    ASTNode,
    CallMetadata,
    CacheStats,
    Diagnostic,
    EdgeMetadata,
    EdgeResolution,
    FileInfo,
    ImportMetadata,
    InheritanceMetadata,
    NodeAttributes,
    TargetRef,
    Tool1Options,
    Tool1Request,
    Tool1Result,
    Tool1Stats,
)
from blast_radius_mcp.tools import tool1_ast_engine
from blast_radius_mcp.tools.tool1_ast_engine import (
    _build_import_alias_map,
    _compute_edge_id,
    _compute_node_id,
    _extract_signature,
    _file_path_to_module,
    build_cross_file_index,
    build_symbol_table,
    emit_edges,
    finalize_and_sort,
    load_and_hash_files,
    parse_python_file,
    resolve_cross_file_edges,
    run_tool1,
)

# ── Helpers ──────────────────────────────────────────────────────────

NODE_ID_RE = re.compile(r"^sym_[0-9a-f]{16}$")
EDGE_ID_RE = re.compile(r"^edge_[0-9a-f]{16}$")


def _parse_and_build(source: str, file_path: str = "test_mod.py"):
    """Parse source and build symbol table; return (tree, nodes, source_lines)."""
    tree, diag = parse_python_file(source, file_path)
    assert tree is not None
    assert diag is None
    source_lines = source.splitlines()
    nodes = build_symbol_table(tree, file_path, source_lines)
    return tree, nodes, source_lines


# ═══════════════════════════════════════════════════════════════════════
# 1. TestModulePaths
# ═══════════════════════════════════════════════════════════════════════


class TestModulePaths:
    """_file_path_to_module conversion tests."""

    def test_simple_module(self):
        assert _file_path_to_module("foo/bar.py") == "foo.bar"

    def test_init_module(self):
        assert _file_path_to_module("foo/__init__.py") == "foo"

    def test_single_file(self):
        assert _file_path_to_module("single.py") == "single"

    def test_deep_path(self):
        assert _file_path_to_module("a/b/c/deep.py") == "a.b.c.deep"

    def test_backslash_normalisation(self):
        assert _file_path_to_module("a\\b\\c.py") == "a.b.c"

    def test_nested_init(self):
        assert _file_path_to_module("a/b/__init__.py") == "a.b"


# ═══════════════════════════════════════════════════════════════════════
# 2. TestNodeIds
# ═══════════════════════════════════════════════════════════════════════


class TestNodeIds:
    """_compute_node_id determinism and format tests."""

    def test_deterministic(self):
        id1 = _compute_node_id("foo.bar", "foo/bar.py", 10)
        id2 = _compute_node_id("foo.bar", "foo/bar.py", 10)
        assert id1 == id2

    def test_different_inputs_produce_different_ids(self):
        id1 = _compute_node_id("foo.bar", "foo/bar.py", 10)
        id2 = _compute_node_id("foo.baz", "foo/baz.py", 20)
        assert id1 != id2

    def test_format(self):
        nid = _compute_node_id("mod.Class", "mod.py", 1)
        assert NODE_ID_RE.match(nid), f"Expected sym_ + 16 hex, got {nid!r}"
        assert len(nid) == 20

    def test_different_line_produces_different_id(self):
        id1 = _compute_node_id("foo.bar", "foo.py", 1)
        id2 = _compute_node_id("foo.bar", "foo.py", 2)
        assert id1 != id2


# ═══════════════════════════════════════════════════════════════════════
# 3. TestEdgeIds
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeIds:
    """_compute_edge_id determinism and format tests."""

    def test_deterministic(self):
        eid1 = _compute_edge_id("sym_abc", "calls", "foo.bar", 10, 4)
        eid2 = _compute_edge_id("sym_abc", "calls", "foo.bar", 10, 4)
        assert eid1 == eid2

    def test_format(self):
        eid = _compute_edge_id("sym_abc", "imports", "os", 1, 0)
        assert EDGE_ID_RE.match(eid), f"Expected edge_ + 16 hex, got {eid!r}"
        assert len(eid) == 21

    def test_different_inputs(self):
        eid1 = _compute_edge_id("sym_a", "calls", "x", 1, 0)
        eid2 = _compute_edge_id("sym_b", "calls", "y", 2, 5)
        assert eid1 != eid2


# ═══════════════════════════════════════════════════════════════════════
# 4. TestParsePythonFile
# ═══════════════════════════════════════════════════════════════════════


class TestParsePythonFile:
    """parse_python_file success and failure tests."""

    def test_valid_source(self):
        tree, diag = parse_python_file("x = 1\n", "test.py")
        assert tree is not None
        assert diag is None

    def test_syntax_error(self):
        tree, diag = parse_python_file("def (broken:\n", "bad.py")
        assert tree is None
        assert diag is not None
        assert isinstance(diag, Diagnostic)
        assert diag.severity == "error"
        assert "SyntaxError" in diag.message
        assert diag.file == "bad.py"

    def test_empty_string(self):
        tree, diag = parse_python_file("", "empty.py")
        assert tree is not None
        assert diag is None

    def test_comment_only(self):
        tree, diag = parse_python_file("# just a comment\n", "comment.py")
        assert tree is not None
        assert diag is None


# ═══════════════════════════════════════════════════════════════════════
# 5. TestLoadAndHashFiles
# ═══════════════════════════════════════════════════════════════════════


class TestLoadAndHashFiles:
    """load_and_hash_files with tmp_path fixture."""

    def test_basic_load(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello')\n", encoding="utf-8")

        infos, sources = load_and_hash_files(str(tmp_path), ["hello.py"])

        assert len(infos) == 1
        assert infos[0].path == "hello.py"
        assert infos[0].parse_status == "ok"
        assert infos[0].sha256 != ""
        assert infos[0].size_bytes > 0
        assert "hello.py" in sources

    def test_missing_file(self, tmp_path):
        infos, sources = load_and_hash_files(str(tmp_path), ["nonexistent.py"])

        assert len(infos) == 1
        assert infos[0].parse_status == "error"
        assert infos[0].sha256 == ""
        assert "nonexistent.py" not in sources

    def test_hashes_deterministic(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("x = 42\n", encoding="utf-8")

        infos1, _ = load_and_hash_files(str(tmp_path), ["mod.py"])
        infos2, _ = load_and_hash_files(str(tmp_path), ["mod.py"])
        assert infos1[0].sha256 == infos2[0].sha256

    def test_multiple_files(self, tmp_path):
        (tmp_path / "a.py").write_text("a = 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("b = 2\n", encoding="utf-8")

        infos, sources = load_and_hash_files(str(tmp_path), ["a.py", "b.py"])
        assert len(infos) == 2
        assert len(sources) == 2

    def test_mixed_valid_and_missing(self, tmp_path):
        (tmp_path / "exists.py").write_text("ok = True\n", encoding="utf-8")

        infos, sources = load_and_hash_files(
            str(tmp_path), ["exists.py", "missing.py"]
        )
        assert len(infos) == 2
        ok_info = [i for i in infos if i.path == "exists.py"][0]
        err_info = [i for i in infos if i.path == "missing.py"][0]
        assert ok_info.parse_status == "ok"
        assert err_info.parse_status == "error"


# ═══════════════════════════════════════════════════════════════════════
# 6. TestBuildSymbolTable
# ═══════════════════════════════════════════════════════════════════════


MULTI_SYMBOL_SOURCE = textwrap.dedent("""\
import os

class MyClass(BaseModel):
    \"\"\"A class docstring.\"\"\"

    def method(self, x: int, y: str = "hi") -> bool:
        return True

    @property
    def name(self) -> str:
        return "name"

async def top_level_func(a, b, *args, **kwargs):
    yield a + b

def simple():
    pass
""")


class TestBuildSymbolTable:
    """build_symbol_table with a multi-symbol source."""

    @pytest.fixture()
    def nodes(self):
        _, nodes, _ = _parse_and_build(MULTI_SYMBOL_SOURCE, "test_mod.py")
        return nodes

    def _find(self, nodes: list[ASTNode], name: str) -> ASTNode:
        for n in nodes:
            if n.name == name:
                return n
        raise AssertionError(f"Node {name!r} not found in {[n.name for n in nodes]}")

    # ── individual symbols ──────────────────────────────────────────

    def test_module_node(self, nodes):
        mod = self._find(nodes, "test_mod")
        assert mod.kind == "module"

    def test_class_node(self, nodes):
        cls = self._find(nodes, "MyClass")
        assert cls.kind == "class"
        assert "BaseModel" in cls.bases
        assert cls.docstring is not None
        assert "class docstring" in cls.docstring

    def test_method_node(self, nodes):
        m = self._find(nodes, "method")
        assert m.kind == "method"
        assert m.signature is not None
        assert "self" in m.signature

    def test_property_node(self, nodes):
        prop = self._find(nodes, "name")
        assert prop.kind == "method"
        assert prop.attributes.is_property is True

    def test_async_generator_function(self, nodes):
        fn = self._find(nodes, "top_level_func")
        assert fn.kind == "function"
        assert fn.attributes.is_async is True
        assert fn.attributes.is_generator is True
        assert fn.signature is not None
        assert "**kwargs" in fn.signature

    def test_simple_function(self, nodes):
        fn = self._find(nodes, "simple")
        assert fn.kind == "function"

    # ── cross-cutting checks ────────────────────────────────────────

    def test_all_ids_valid(self, nodes):
        for n in nodes:
            assert NODE_ID_RE.match(n.id), f"Bad id: {n.id}"

    def test_qualified_names(self, nodes):
        qnames = {n.name: n.qualified_name for n in nodes}
        assert qnames["MyClass"] == "test_mod.MyClass"
        assert qnames["method"] == "test_mod.MyClass.method"
        assert qnames["top_level_func"] == "test_mod.top_level_func"
        assert qnames["simple"] == "test_mod.simple"

    def test_node_count(self, nodes):
        # module + MyClass + method + name + top_level_func + simple = 6
        assert len(nodes) == 6


# ═══════════════════════════════════════════════════════════════════════
# 7. TestEmitEdges
# ═══════════════════════════════════════════════════════════════════════


EDGE_SOURCE = textwrap.dedent("""\
from os.path import join
import json

class Child(Parent):
    pass

def handler():
    join("a", "b")
    json.loads("{}")
""")


class TestEmitEdges:
    """emit_edges with imports, calls, and inheritance."""

    @pytest.fixture()
    def edges_and_nodes(self):
        tree, nodes, source_lines = _parse_and_build(EDGE_SOURCE, "edge_mod.py")
        options = Tool1Options()
        edges = emit_edges(tree, "edge_mod.py", nodes, options, source_lines)
        return edges, nodes

    def _edges_of_type(self, edges: list[ASTEdge], edge_type: str) -> list[ASTEdge]:
        return [e for e in edges if e.type == edge_type]

    # ── import edges ────────────────────────────────────────────────

    def test_import_edges_exist(self, edges_and_nodes):
        edges, _ = edges_and_nodes
        import_edges = self._edges_of_type(edges, "imports")
        assert len(import_edges) >= 2  # join and json
        targets = {e.target_ref.qualified_name for e in import_edges}
        assert "os.path.join" in targets
        assert "json" in targets

    # ── inheritance edges ───────────────────────────────────────────

    def test_inheritance_edge(self, edges_and_nodes):
        edges, _ = edges_and_nodes
        inherit_edges = self._edges_of_type(edges, "inherits")
        assert len(inherit_edges) >= 1
        base_texts = {
            e.metadata.inheritance.base_text
            for e in inherit_edges
            if e.metadata.inheritance
        }
        assert "Parent" in base_texts

    # ── call edges ──────────────────────────────────────────────────

    def test_call_edges(self, edges_and_nodes):
        edges, _ = edges_and_nodes
        call_edges = self._edges_of_type(edges, "calls")
        assert len(call_edges) >= 2
        callees = {
            e.metadata.call.callee_text for e in call_edges if e.metadata.call
        }
        assert "join" in callees
        assert "json.loads" in callees

    # ── cross-cutting ───────────────────────────────────────────────

    def test_all_edge_ids_valid(self, edges_and_nodes):
        edges, _ = edges_and_nodes
        for e in edges:
            assert EDGE_ID_RE.match(e.id), f"Bad edge id: {e.id}"

    def test_snippets_present(self, edges_and_nodes):
        edges, _ = edges_and_nodes
        for e in edges:
            assert e.snippet is not None
            assert len(e.snippet) > 0

    def test_confidence_in_range(self, edges_and_nodes):
        edges, _ = edges_and_nodes
        for e in edges:
            assert 0.0 <= e.confidence <= 1.0, f"Confidence {e.confidence} out of range"

    def test_reference_edges_emit_metadata(self):
        source = textwrap.dedent("""\
        x = 1

        def f():
            y = x
            del y
        """)
        tree, nodes, source_lines = _parse_and_build(source, "refs.py")
        options = Tool1Options(
            include_import_edges=False,
            include_call_edges=False,
            include_inheritance_edges=False,
            include_references=True,
        )

        edges = emit_edges(tree, "refs.py", nodes, options, source_lines)
        ref_edges = [e for e in edges if e.type == "references"]

        assert len(ref_edges) >= 4
        contexts = {
            e.metadata.reference.context
            for e in ref_edges
            if e.metadata.reference is not None
        }
        assert {"load", "store", "del"}.issubset(contexts)
        for edge in ref_edges:
            assert edge.metadata.reference is not None
            assert edge.metadata.reference.name

    def test_reference_edges_deterministic_order(self):
        source = textwrap.dedent("""\
        x = 1

        def f():
            y = x
            del y
        """)
        options = Tool1Options(
            include_import_edges=False,
            include_call_edges=False,
            include_inheritance_edges=False,
            include_references=True,
        )

        tree1, nodes1, source_lines1 = _parse_and_build(source, "refs.py")
        edges1 = emit_edges(tree1, "refs.py", nodes1, options, source_lines1)
        refs1 = [
            (
                e.id,
                e.range.start.line,
                e.range.start.col,
                e.metadata.reference.name if e.metadata.reference else "",
                e.metadata.reference.context if e.metadata.reference else "",
            )
            for e in edges1
            if e.type == "references"
        ]

        tree2, nodes2, source_lines2 = _parse_and_build(source, "refs.py")
        edges2 = emit_edges(tree2, "refs.py", nodes2, options, source_lines2)
        refs2 = [
            (
                e.id,
                e.range.start.line,
                e.range.start.col,
                e.metadata.reference.name if e.metadata.reference else "",
                e.metadata.reference.context if e.metadata.reference else "",
            )
            for e in edges2
            if e.type == "references"
        ]

        assert refs1 == refs2


# ═══════════════════════════════════════════════════════════════════════
# 8. TestCrossFileResolution
# ═══════════════════════════════════════════════════════════════════════


class TestCrossFileResolution:
    """Cross-file resolution via run_tool1 with two temp files."""

    def test_cross_file_import_resolves(self, tmp_path):
        utils = tmp_path / "utils.py"
        utils.write_text(
            textwrap.dedent("""\
            def helper():
                pass
            """),
            encoding="utf-8",
        )
        main = tmp_path / "main.py"
        main.write_text(
            textwrap.dedent("""\
            from utils import helper

            def run():
                helper()
            """),
            encoding="utf-8",
        )

        req = Tool1Request(target_files=["utils.py", "main.py"])
        result_dict = run_tool1(req, str(tmp_path))
        result = Tool1Result(**result_dict)

        # Find import edge from main that references helper
        import_edges = [
            e
            for e in result.edges
            if e.type == "imports"
            and "helper" in e.target_ref.qualified_name
        ]
        assert len(import_edges) >= 1
        resolved = [e for e in import_edges if e.resolution.status == "resolved"]
        assert len(resolved) >= 1
        assert resolved[0].target_ref.symbol_id != ""

        # Also verify call edge to helper resolves
        call_edges = [
            e
            for e in result.edges
            if e.type == "calls"
            and e.metadata.call
            and e.metadata.call.callee_text == "helper"
        ]
        assert len(call_edges) >= 1
        resolved_calls = [e for e in call_edges if e.resolution.status == "resolved"]
        assert len(resolved_calls) >= 1


# ═══════════════════════════════════════════════════════════════════════
# 9. TestDeterminism
# ═══════════════════════════════════════════════════════════════════════


class TestDeterminism:
    """AST analysis must be fully deterministic across repeated runs."""

    def test_parse_deterministic(self):
        source = textwrap.dedent("""\
        import os

        class Foo:
            def bar(self):
                os.path.join("a", "b")
        """)

        tree1, nodes1, sl1 = _parse_and_build(source, "determ.py")
        tree2, nodes2, sl2 = _parse_and_build(source, "determ.py")

        assert [n.id for n in nodes1] == [n.id for n in nodes2]
        assert [n.qualified_name for n in nodes1] == [n.qualified_name for n in nodes2]

    def test_edges_deterministic(self):
        source = textwrap.dedent("""\
        from os.path import join

        def go():
            join("a", "b")
        """)
        options = Tool1Options()

        tree1, nodes1, sl1 = _parse_and_build(source, "det.py")
        edges1 = emit_edges(tree1, "det.py", nodes1, options, sl1)

        tree2, nodes2, sl2 = _parse_and_build(source, "det.py")
        edges2 = emit_edges(tree2, "det.py", nodes2, options, sl2)

        assert [e.id for e in edges1] == [e.id for e in edges2]
        assert [e.type for e in edges1] == [e.type for e in edges2]

    def test_run_tool1_deterministic(self, tmp_path):
        (tmp_path / "mod.py").write_text("x = 1\ndef f(): pass\n", encoding="utf-8")

        req = Tool1Request(target_files=["mod.py"])
        r1 = run_tool1(req, str(tmp_path))
        r2 = run_tool1(req, str(tmp_path))

        # Compare everything except timing
        def strip_timing(d):
            d = dict(d)
            d["stats"] = {k: v for k, v in d["stats"].items() if k != "duration_ms"}
            return d

        assert strip_timing(r1) == strip_timing(r2)


class TestParseModes:
    def test_tree_sitter_unavailable_falls_back_with_warning(self, tmp_path, monkeypatch):
        (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(tool1_ast_engine, "_tree_sitter_available", lambda: False)

        req = Tool1Request(
            target_files=["mod.py"],
            options=Tool1Options(parse_mode="tree_sitter"),
        )
        result_dict = run_tool1(req, str(tmp_path))
        result = Tool1Result(**result_dict)

        warnings = [d for d in result.diagnostics if d.severity == "warning"]
        assert len(warnings) >= 1
        assert "falling back to 'python_ast'" in warnings[0].message
        assert result.stats.parsed_ok == 1


# ═══════════════════════════════════════════════════════════════════════
# 10. TestRunTool1Integration
# ═══════════════════════════════════════════════════════════════════════


class TestRunTool1Integration:
    """Integration test for the full run_tool1 pipeline."""

    def _create_project(self, tmp_path):
        """Create a small multi-file project."""
        (tmp_path / "models.py").write_text(
            textwrap.dedent("""\
            class User:
                \"\"\"A user model.\"\"\"
                def __init__(self, name: str):
                    self.name = name

                def greet(self) -> str:
                    return f"Hello, {self.name}"
            """),
            encoding="utf-8",
        )
        (tmp_path / "service.py").write_text(
            textwrap.dedent("""\
            from models import User

            def create_user(name: str) -> User:
                return User(name)

            def get_greeting(user: User) -> str:
                return user.greet()
            """),
            encoding="utf-8",
        )
        (tmp_path / "utils.py").write_text(
            textwrap.dedent("""\
            import json

            def serialize(obj) -> str:
                return json.dumps(obj)
            """),
            encoding="utf-8",
        )
        return ["models.py", "service.py", "utils.py"]

    def test_full_pipeline(self, tmp_path):
        target_files = self._create_project(tmp_path)
        req = Tool1Request(target_files=target_files)

        result_dict = run_tool1(req, str(tmp_path))
        result = Tool1Result(**result_dict)

        # Files
        assert len(result.files) == len(target_files)
        assert all(f.parse_status == "ok" for f in result.files)

        # Nodes
        assert result.stats.nodes > 0
        assert len(result.nodes) == result.stats.nodes

        # Edges
        assert result.stats.edges > 0
        assert len(result.edges) == result.stats.edges

        # Stats correctness
        assert result.stats.target_files == len(target_files)
        assert result.stats.parsed_ok == len(target_files)
        assert result.stats.parsed_error == 0
        assert result.stats.duration_ms >= 0

        # Language
        assert result.language == "python"
        assert result.repo_root == str(tmp_path)

    def test_result_validates_with_model(self, tmp_path):
        (tmp_path / "simple.py").write_text("x = 1\n", encoding="utf-8")
        req = Tool1Request(target_files=["simple.py"])
        result_dict = run_tool1(req, str(tmp_path))

        # Must not raise
        result = Tool1Result(**result_dict)
        assert result.language == "python"

    def test_with_syntax_error_file(self, tmp_path):
        (tmp_path / "good.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "bad.py").write_text("def (\n", encoding="utf-8")

        req = Tool1Request(target_files=["good.py", "bad.py"])
        result_dict = run_tool1(req, str(tmp_path))
        result = Tool1Result(**result_dict)

        assert result.stats.parsed_ok == 1
        assert result.stats.parsed_error == 1
        assert len(result.diagnostics) >= 1


# ═══════════════════════════════════════════════════════════════════════
# 11. TestEdgeCases
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge-case sources that should not crash."""

    def test_empty_file(self):
        source = ""
        tree, nodes, _ = _parse_and_build(source, "empty.py")
        # At least a module node
        assert len(nodes) >= 1
        assert nodes[0].kind == "module"

    def test_whitespace_and_comments_only(self):
        source = "# just a comment\n\n# another\n"
        tree, nodes, _ = _parse_and_build(source, "comments.py")
        assert len(nodes) >= 1
        assert nodes[0].kind == "module"

    def test_file_with_only_exports(self):
        source = '__all__ = ["foo", "bar"]\n'
        tree, nodes, _ = _parse_and_build(source, "exports.py")
        mod = [n for n in nodes if n.kind == "module"][0]
        assert mod.exports == ["foo", "bar"]

    def test_deeply_nested(self):
        source = textwrap.dedent("""\
        class Outer:
            class Inner:
                def deep_method(self):
                    pass
        """)
        tree, nodes, _ = _parse_and_build(source, "nested.py")
        names = [n.name for n in nodes]
        assert "Outer" in names
        assert "Inner" in names
        assert "deep_method" in names
        # Verify qualified name nesting
        deep = [n for n in nodes if n.name == "deep_method"][0]
        assert deep.qualified_name == "nested.Outer.Inner.deep_method"
        assert deep.kind == "method"

    def test_nested_function(self):
        source = textwrap.dedent("""\
        def outer():
            def inner():
                pass
        """)
        tree, nodes, _ = _parse_and_build(source, "nfunc.py")
        names = [n.name for n in nodes]
        assert "outer" in names
        assert "inner" in names
        inner = [n for n in nodes if n.name == "inner"][0]
        assert inner.qualified_name == "nfunc.outer.inner"
        # inner is NOT inside a class, so kind should be function
        assert inner.kind == "function"


# ═══════════════════════════════════════════════════════════════════════
# 12. TestFinalize
# ═══════════════════════════════════════════════════════════════════════


class TestFinalize:
    """finalize_and_sort ordering guarantees."""

    def test_nodes_sorted_by_id(self):
        nodes = [
            ASTNode(
                id="sym_zzzzzzzzzzzzzzzz",
                kind="function",
                name="z",
                qualified_name="z",
                file="z.py",
                range=Range(
                    start=Position(line=1, col=0),
                    end=Position(line=2, col=0),
                ),
            ),
            ASTNode(
                id="sym_aaaaaaaaaaaaaaaa",
                kind="function",
                name="a",
                qualified_name="a",
                file="a.py",
                range=Range(
                    start=Position(line=1, col=0),
                    end=Position(line=2, col=0),
                ),
            ),
        ]
        sorted_nodes, _, _ = finalize_and_sort(nodes, [], [])
        assert sorted_nodes[0].id < sorted_nodes[1].id
        assert sorted_nodes[0].id == "sym_aaaaaaaaaaaaaaaa"

    def test_edges_sorted_by_source_type_target_id(self):
        edge_a = ASTEdge(
            id="edge_aaaaaaaaaaaaaaaa",
            type="calls",
            source="sym_aaaaaaaaaaaaaaaa",
            target="sym_bbbbbbbbbbbbbbbb",
            target_ref=TargetRef(kind="symbol", qualified_name="b"),
            range=Range(
                start=Position(line=1, col=0),
                end=Position(line=1, col=5),
            ),
            confidence=0.9,
            resolution=EdgeResolution(status="resolved", strategy="local_scope"),
            metadata=EdgeMetadata(call=CallMetadata(callee_text="b")),
        )
        edge_b = ASTEdge(
            id="edge_bbbbbbbbbbbbbbbb",
            type="calls",
            source="sym_aaaaaaaaaaaaaaaa",
            target="sym_aaaaaaaaaaaaaaaa",
            target_ref=TargetRef(kind="symbol", qualified_name="a"),
            range=Range(
                start=Position(line=2, col=0),
                end=Position(line=2, col=5),
            ),
            confidence=0.9,
            resolution=EdgeResolution(status="resolved", strategy="local_scope"),
            metadata=EdgeMetadata(call=CallMetadata(callee_text="a")),
        )
        # edge_b has a smaller target (sym_aaa < sym_bbb), so should come first
        _, sorted_edges, _ = finalize_and_sort([], [edge_a, edge_b], [])
        assert sorted_edges[0].target < sorted_edges[1].target

    def test_diagnostics_sorted(self):
        d1 = Diagnostic(
            file="b.py",
            severity="error",
            message="err1",
            range=Range(
                start=Position(line=5, col=0),
                end=Position(line=5, col=0),
            ),
        )
        d2 = Diagnostic(
            file="a.py",
            severity="error",
            message="err2",
            range=Range(
                start=Position(line=1, col=0),
                end=Position(line=1, col=0),
            ),
        )
        _, _, sorted_diags = finalize_and_sort([], [], [d1, d2])
        assert sorted_diags[0].file == "a.py"
        assert sorted_diags[1].file == "b.py"


# ═══════════════════════════════════════════════════════════════════════
# Extra: TestExtractSignature
# ═══════════════════════════════════════════════════════════════════════


class TestExtractSignature:
    """_extract_signature behaviour."""

    def _sig(self, funcdef_source: str) -> str:
        tree = ast.parse(funcdef_source)
        func_node = tree.body[0]
        return _extract_signature(func_node)

    def test_no_args(self):
        sig = self._sig("def f(): pass")
        assert sig == "()"

    def test_self_and_defaults(self):
        sig = self._sig("def f(self, x, y=1): pass")
        assert "self" in sig
        assert "y=..." in sig

    def test_varargs_kwargs(self):
        sig = self._sig("def f(a, *args, **kwargs): pass")
        assert "*args" in sig
        assert "**kwargs" in sig

    def test_keyword_only(self):
        sig = self._sig("def f(a, *, key=1): pass")
        assert "key=..." in sig
        assert "*" in sig


# ═══════════════════════════════════════════════════════════════════════
# Extra: TestBuildImportAliasMap
# ═══════════════════════════════════════════════════════════════════════


class TestBuildImportAliasMap:
    """_build_import_alias_map tests."""

    def test_import_statement(self):
        tree = ast.parse("import os")
        amap = _build_import_alias_map(tree)
        assert "os" in amap
        assert amap["os"] == ("os", "")

    def test_from_import(self):
        tree = ast.parse("from os.path import join")
        amap = _build_import_alias_map(tree)
        assert "join" in amap
        assert amap["join"] == ("os.path", "join")

    def test_aliased_import(self):
        tree = ast.parse("from os.path import join as pjoin")
        amap = _build_import_alias_map(tree)
        assert "pjoin" in amap
        assert amap["pjoin"] == ("os.path", "join")

    def test_star_import_skipped(self):
        tree = ast.parse("from os import *")
        amap = _build_import_alias_map(tree)
        # Star imports should not appear in the map
        assert len(amap) == 0


# ═══════════════════════════════════════════════════════════════════════
# Extra: TestBuildCrossFileIndex
# ═══════════════════════════════════════════════════════════════════════


class TestBuildCrossFileIndex:
    """build_cross_file_index tests."""

    def test_basic_index(self):
        node = ASTNode(
            id="sym_0123456789abcdef",
            kind="function",
            name="helper",
            qualified_name="utils.helper",
            file="utils.py",
            range=Range(
                start=Position(line=1, col=0),
                end=Position(line=2, col=0),
            ),
        )
        index, ambiguities = build_cross_file_index({"utils.py": [node]})
        assert "utils.helper" in index
        file, nid, kind = index["utils.helper"]
        assert file == "utils.py"
        assert nid == "sym_0123456789abcdef"
        assert kind == "function"

    def test_multiple_files(self):
        n1 = ASTNode(
            id="sym_aaaaaaaaaaaaaaaa",
            kind="module",
            name="a",
            qualified_name="a",
            file="a.py",
            range=Range(
                start=Position(line=1, col=0),
                end=Position(line=1, col=0),
            ),
        )
        n2 = ASTNode(
            id="sym_bbbbbbbbbbbbbbbb",
            kind="function",
            name="go",
            qualified_name="b.go",
            file="b.py",
            range=Range(
                start=Position(line=1, col=0),
                end=Position(line=2, col=0),
            ),
        )
        index, ambiguities = build_cross_file_index({"a.py": [n1], "b.py": [n2]})
        assert "a" in index
        assert "b.go" in index
        assert ambiguities == []

    def test_duplicate_qualified_name(self):
        n1 = ASTNode(
            id="sym_aaaaaaaaaaaaaaaa",
            kind="function",
            name="helper",
            qualified_name="utils.helper",
            file="a.py",
            range=Range(
                start=Position(line=1, col=0),
                end=Position(line=2, col=0),
            ),
        )
        n2 = ASTNode(
            id="sym_bbbbbbbbbbbbbbbb",
            kind="function",
            name="helper",
            qualified_name="utils.helper",
            file="b.py",
            range=Range(
                start=Position(line=1, col=0),
                end=Position(line=2, col=0),
            ),
        )
        index, ambiguities = build_cross_file_index({"a.py": [n1], "b.py": [n2]})
        # First entry is kept
        file, nid, kind = index["utils.helper"]
        assert file == "a.py"
        assert nid == "sym_aaaaaaaaaaaaaaaa"
        # Ambiguity is reported
        assert len(ambiguities) == 1
        assert ambiguities[0]["qualified_name"] == "utils.helper"
        assert ambiguities[0]["file1"] == "a.py"
        assert ambiguities[0]["file2"] == "b.py"
