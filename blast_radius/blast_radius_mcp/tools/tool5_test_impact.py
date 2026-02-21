"""Tool 5 — Test Impact Analyzer.

Given a set of impacted code nodes (files, symbols), discovers test files in
the repository, builds an import/reference index for each test, scores every
test against the impacted nodes, and returns a ranked minimal test set likely
to validate those impacts.

The implementation is entirely static — no test execution or coverage data is
required (``coverage_mode="off"``).  All outputs are deterministic: identical
inputs always produce identical output.
"""

from __future__ import annotations

import ast
import configparser
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from blast_radius_mcp.repo.io import glob_python_files, safe_read_file
from blast_radius_mcp.schemas.tool5_tests import (
    ImpactedNode,
    SelectionStats,
    TestItem,
    TestReason,
    Tool5Diagnostic,
    Tool5Options,
    Tool5Request,
    Tool5Result,
    UnmatchedImpact,
)

# ── Module-level constants ───────────────────────────────────────────

TOOL5_IMPL_VERSION = "1.0.0"

# Scoring weights for each reason type.
_WEIGHT_DIRECT_IMPORT = 1.0
_WEIGHT_FROM_IMPORT_SYMBOL = 1.0
_WEIGHT_TRANSITIVE_IMPORT = 0.5  # divided by depth >= 1
_WEIGHT_SYMBOL_REFERENCE = 0.4
_WEIGHT_FIELD_LITERAL_MATCH = 0.2


# ── Helpers ──────────────────────────────────────────────────────────


def _sha256_prefix(prefix: str, *parts: str, length: int = 16) -> str:
    """Return *prefix* + first *length* hex chars of the SHA-256 digest.

    Used for deterministic, collision-resistant identifiers.
    """
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
    return prefix + h.hexdigest()[:length]


def _compute_test_id(nodeid: str, file: str) -> str:
    """Deterministic test identifier.

    ``test_id = "test_" + sha256("test" + nodeid + file)[:16]``
    """
    return _sha256_prefix("test_", "test", nodeid, file)


def _file_path_to_module(file_path: str) -> str:
    """Convert a repo-relative file path to a dotted Python module name.

    Examples::

        foo/bar/baz.py      → foo.bar.baz
        foo/bar/__init__.py  → foo.bar
        src/app.py           → src.app

    Args:
        file_path: Forward-slash repo-relative path.

    Returns:
        Dotted module name.
    """
    path = file_path.replace(os.sep, "/")
    if path.endswith("/__init__.py"):
        path = path[: -len("/__init__.py")]
    elif path.endswith(".py"):
        path = path[: -len(".py")]
    return path.replace("/", ".")


def _is_test_filename(filename: str) -> bool:
    """Return ``True`` if *filename* follows pytest naming conventions.

    Matches ``test_*.py`` and ``*_test.py``.
    """
    base = os.path.basename(filename)
    return base.endswith(".py") and (base.startswith("test_") or base[:-3].endswith("_test"))


# ── Internal data structures ─────────────────────────────────────────


@dataclass
class _TestFileInfo:
    """Intermediate representation of a parsed test file."""

    rel_path: str
    nodeids: list[str] = field(default_factory=list)
    imported_modules: set[str] = field(default_factory=set)
    imported_symbols: set[tuple[str, str]] = field(default_factory=set)
    name_references: set[str] = field(default_factory=set)
    string_literals: set[str] = field(default_factory=set)


# ── Phase 6.1 — Test Discovery ───────────────────────────────────────


def _parse_testpaths_from_pyproject(repo_root: str) -> list[str] | None:
    """Extract ``testpaths`` from ``pyproject.toml`` if available.

    Looks for ``[tool.pytest.ini_options]`` or ``[tool.pytest]`` sections.
    Returns ``None`` when ``pyproject.toml`` is absent or has no pytest config.
    """
    pyproject = Path(repo_root) / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        # Try tomllib (Python 3.11+), fall back to tomli
        try:
            import tomllib  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        ini_opts = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
        if not ini_opts:
            ini_opts = data.get("tool", {}).get("pytest", {})
        testpaths = ini_opts.get("testpaths")
        if isinstance(testpaths, list) and testpaths:
            return [str(p) for p in testpaths]
    except Exception:  # noqa: BLE001
        pass
    return None


def _parse_testpaths_from_pytest_ini(repo_root: str) -> list[str] | None:
    """Extract ``testpaths`` from ``pytest.ini``."""
    ini_file = Path(repo_root) / "pytest.ini"
    if not ini_file.is_file():
        return None
    try:
        cfg = configparser.ConfigParser()
        cfg.read(str(ini_file), encoding="utf-8")
        if cfg.has_option("pytest", "testpaths"):
            raw = cfg.get("pytest", "testpaths")
            return raw.split()
    except Exception:  # noqa: BLE001
        pass
    return None


def _parse_testpaths_from_setup_cfg(repo_root: str) -> list[str] | None:
    """Extract ``testpaths`` from ``setup.cfg [tool:pytest]``."""
    setup_cfg = Path(repo_root) / "setup.cfg"
    if not setup_cfg.is_file():
        return None
    try:
        cfg = configparser.ConfigParser()
        cfg.read(str(setup_cfg), encoding="utf-8")
        if cfg.has_option("tool:pytest", "testpaths"):
            raw = cfg.get("tool:pytest", "testpaths")
            return raw.split()
    except Exception:  # noqa: BLE001
        pass
    return None


def _collect_test_files_from_dirs(
    repo_root: str, dirs: list[str], all_py: list[str],
) -> list[str]:
    """Filter *all_py* to those inside *dirs* that match test naming."""
    result: list[str] = []
    for py in all_py:
        for d in dirs:
            d_norm = d.rstrip("/") + "/"
            if py.startswith(d_norm) and _is_test_filename(py):
                result.append(py)
                break
    return sorted(set(result))


def discover_tests(
    repo_root: str,
) -> tuple[list[str], list[Tool5Diagnostic]]:
    """Discover test files in the repository.

    Strategy (in priority order):

    1. Check for ``pytest.ini``, ``pyproject.toml [tool.pytest.ini_options]``,
       ``setup.cfg [tool:pytest]`` for explicit ``testpaths``.
    2. Fall back to conventional directories (``tests/``, ``test/``).
    3. As a last resort, scan all Python files for ``test_*.py`` /
       ``*_test.py`` naming.
    4. Emit a ``tests_not_found`` diagnostic when nothing is found.

    Args:
        repo_root: Absolute or relative path to the repository root.

    Returns:
        A tuple of ``(test_file_paths, diagnostics)`` where paths are
        repo-relative with forward slashes.
    """
    diagnostics: list[Tool5Diagnostic] = []
    all_py = glob_python_files(repo_root)

    # ── 1. Configured testpaths ──────────────────────────────────────
    configured_paths = (
        _parse_testpaths_from_pytest_ini(repo_root)
        or _parse_testpaths_from_pyproject(repo_root)
        or _parse_testpaths_from_setup_cfg(repo_root)
    )
    if configured_paths:
        found = _collect_test_files_from_dirs(repo_root, configured_paths, all_py)
        if found:
            return found, diagnostics

    # ── 2. Convention directories ────────────────────────────────────
    conventional_dirs: list[str] = []
    root = Path(repo_root).resolve()
    for candidate in ("tests", "test"):
        if (root / candidate).is_dir():
            conventional_dirs.append(candidate)

    if conventional_dirs:
        found = _collect_test_files_from_dirs(repo_root, conventional_dirs, all_py)
        if found:
            return found, diagnostics

    # ── 3. Anywhere in repo ──────────────────────────────────────────
    found = sorted(p for p in all_py if _is_test_filename(p))
    if found:
        return found, diagnostics

    # ── 4. Nothing ───────────────────────────────────────────────────
    diagnostics.append(
        Tool5Diagnostic(
            severity="warning",
            code="tests_not_found",
            message="No test files discovered in the repository.",
        )
    )
    return [], diagnostics


# ── Phase 6.2 — Test Import/Reference Index ──────────────────────────


class _ImportVisitor(ast.NodeVisitor):
    """AST visitor that extracts imports from a module.

    After visiting, ``imported_modules`` contains dotted module names imported
    via ``import X`` or the module portion of ``from X import Y``, and
    ``imported_symbols`` contains ``(module, name)`` pairs for every
    ``from X import Y`` entry.
    """

    def __init__(self) -> None:
        self.imported_modules: set[str] = set()
        self.imported_symbols: set[tuple[str, str]] = set()

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self.imported_modules.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        if not module:
            return
        for alias in node.names:
            # ``from app.api import orders`` → imported module is
            # ``app.api.orders`` (best-effort: we treat the name as a sub-module
            # unless we can prove otherwise).
            self.imported_symbols.add((module, alias.name))
            # Also register the fully-qualified sub-module path as a module
            # import so that ``direct_import`` matching can see it.
            self.imported_modules.add(f"{module}.{alias.name}")
            # Keep the parent as well for broader matching.
            self.imported_modules.add(module)
        self.generic_visit(node)


class _TestNodeidVisitor(ast.NodeVisitor):
    """Extract pytest-compatible node IDs from a test module AST.

    Detects:
    * Module-level functions whose name starts with ``test_``.
    * Methods named ``test_*`` inside any class (including ``unittest.TestCase``
      subclasses).

    Node IDs follow pytest conventions::

        tests/test_foo.py::test_bar
        tests/test_foo.py::TestFoo::test_bar
    """

    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.nodeids: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        if node.name.startswith("test_"):
            self.nodeids.append(f"{self.rel_path}::{node.name}")
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # async test functions

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        for item in ast.walk(node):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name.startswith("test_"):
                    self.nodeids.append(
                        f"{self.rel_path}::{node.name}::{item.name}"
                    )
        # Do NOT call generic_visit here — we already walked the class body
        # above.  Calling generic_visit would re-visit module-level style and
        # could cause duplicates for nested functions named test_*.


class _ReferenceVisitor(ast.NodeVisitor):
    """Collect lightweight reference signals from a module AST.

    Gathers:
    * All ``ast.Name`` identifiers (variable/function references).
    * All ``ast.Attribute`` final attribute names (e.g. ``self.foo`` → ``foo``).
    * All string literal values (``ast.Constant`` with ``str`` value).
    """

    def __init__(self) -> None:
        self.name_refs: set[str] = set()
        self.string_literals: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        self.name_refs.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        self.name_refs.add(node.attr)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        if isinstance(node.value, str) and node.value:
            self.string_literals.add(node.value)
        self.generic_visit(node)


def _parse_test_file(
    repo_root: str, rel_path: str,
) -> tuple[_TestFileInfo | None, Tool5Diagnostic | None]:
    """Parse a single test file and extract its index information.

    If the file cannot be read or parsed, a diagnostic is returned and the
    info is ``None``.
    """
    try:
        raw = safe_read_file(repo_root, rel_path)
        source = raw.decode("utf-8", errors="replace")
    except (FileNotFoundError, ValueError, OSError) as exc:
        return None, Tool5Diagnostic(
            severity="warning",
            code="test_parse_error",
            message=f"Cannot read test file {rel_path}: {exc}",
        )

    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError as exc:
        return None, Tool5Diagnostic(
            severity="warning",
            code="test_parse_error",
            message=f"Syntax error in {rel_path}: {exc}",
        )

    # Imports
    import_visitor = _ImportVisitor()
    import_visitor.visit(tree)

    # Test node IDs
    nodeid_visitor = _TestNodeidVisitor(rel_path)
    nodeid_visitor.visit(tree)

    # Name / attribute / string-literal references
    ref_visitor = _ReferenceVisitor()
    ref_visitor.visit(tree)

    info = _TestFileInfo(
        rel_path=rel_path,
        nodeids=sorted(nodeid_visitor.nodeids),
        imported_modules=import_visitor.imported_modules,
        imported_symbols=import_visitor.imported_symbols,
        name_references=ref_visitor.name_refs,
        string_literals=ref_visitor.string_literals,
    )
    return info, None


def build_test_index(
    repo_root: str, test_files: list[str],
) -> tuple[dict[str, _TestFileInfo], list[Tool5Diagnostic]]:
    """Build a per-test-file index of imports, nodeids, and references.

    Args:
        repo_root: Repository root path.
        test_files: List of repo-relative test file paths.

    Returns:
        A tuple of ``(index_dict, diagnostics)`` where ``index_dict`` maps
        each test file path to its ``_TestFileInfo``.
    """
    index: dict[str, _TestFileInfo] = {}
    diagnostics: list[Tool5Diagnostic] = []
    for tf in test_files:
        info, diag = _parse_test_file(repo_root, tf)
        if diag is not None:
            diagnostics.append(diag)
        if info is not None:
            index[tf] = info
    return index, diagnostics


# ── Module graph (for transitive imports) ─────────────────────────────


def _parse_imports_from_file(
    repo_root: str, rel_path: str,
) -> set[str]:
    """Return the set of modules imported by *rel_path*.

    Silently returns an empty set on any read/parse failure.
    """
    try:
        raw = safe_read_file(repo_root, rel_path)
        source = raw.decode("utf-8", errors="replace")
        tree = ast.parse(source, filename=rel_path)
    except Exception:  # noqa: BLE001
        return set()

    visitor = _ImportVisitor()
    visitor.visit(tree)
    return visitor.imported_modules


def build_module_graph(
    repo_root: str,
) -> dict[str, set[str]]:
    """Build a directed module-import graph for all Python files in the repo.

    The keys are dotted module names; the values are sets of modules that the
    key module directly imports.

    Args:
        repo_root: Repository root path.

    Returns:
        Adjacency-set mapping ``module → {imported_modules}``.
    """
    all_py = glob_python_files(repo_root)
    graph: dict[str, set[str]] = {}
    for py_file in all_py:
        mod_name = _file_path_to_module(py_file)
        imported = _parse_imports_from_file(repo_root, py_file)
        graph[mod_name] = imported
    return graph


def get_transitive_imports(
    module: str,
    graph: dict[str, set[str]],
    max_depth: int,
) -> dict[str, int]:
    """Return all modules reachable from *module* within *max_depth* hops.

    Uses BFS.  The returned dict maps ``reachable_module → depth``.
    *module* itself is **not** included.

    Args:
        module: Starting module name.
        graph: Adjacency-set mapping from :func:`build_module_graph`.
        max_depth: Maximum BFS depth (0 means only direct imports).

    Returns:
        ``{module_name: depth}`` for all transitively reachable modules.
    """
    if max_depth <= 0:
        return {}

    visited: dict[str, int] = {}
    frontier: list[tuple[str, int]] = [(module, 0)]
    while frontier:
        current, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        for neighbour in sorted(graph.get(current, [])):
            if neighbour not in visited and neighbour != module:
                visited[neighbour] = depth + 1
                frontier.append((neighbour, depth + 1))
    return visited


# ── Phase 6.3 — Scoring & Ranking ────────────────────────────────────


def _score_single_test(
    test_info: _TestFileInfo,
    nodeid: str,
    impacted_nodes: list[ImpactedNode],
    module_graph: dict[str, set[str]],
    options: Tool5Options,
) -> tuple[float, list[TestReason]]:
    """Compute the aggregated score and evidence list for one test nodeid.

    Iterates over every impacted node and collects matching reasons, then
    sums weights (capped at 1.0).

    Args:
        test_info: Parsed index information of the test file.
        nodeid: The specific test node ID being scored.
        impacted_nodes: The full list of impacted code nodes.
        module_graph: Module import graph for transitive analysis.
        options: Tool 5 options controlling transitive depth, etc.

    Returns:
        ``(score, reasons)`` tuple.
    """
    reasons: list[TestReason] = []
    total_weight: float = 0.0

    for node in impacted_nodes:
        impacted_module = _file_path_to_module(node.file)

        # ── direct_import ────────────────────────────────────────────
        if impacted_module in test_info.imported_modules:
            reason = TestReason(
                type="direct_import",
                evidence=f"imports {impacted_module}",
            )
            if reason not in reasons:
                reasons.append(reason)
                total_weight += _WEIGHT_DIRECT_IMPORT

        # ── from_import_symbol ───────────────────────────────────────
        if node.symbol:
            for mod, sym in test_info.imported_symbols:
                if mod == impacted_module and sym == node.symbol:
                    reason = TestReason(
                        type="from_import_symbol",
                        evidence=f"from {mod} import {sym}",
                    )
                    if reason not in reasons:
                        reasons.append(reason)
                        total_weight += _WEIGHT_FROM_IMPORT_SYMBOL
                    break
                # Also check if the symbol is imported as a sub-module
                # (e.g. ``from app.api import orders`` where ``orders`` is
                # part of the impacted module path).
                full_path = f"{mod}.{sym}"
                if full_path == impacted_module:
                    reason = TestReason(
                        type="from_import_symbol",
                        evidence=f"from {mod} import {sym}",
                    )
                    if reason not in reasons:
                        reasons.append(reason)
                        total_weight += _WEIGHT_FROM_IMPORT_SYMBOL
                    break

        # ── transitive_import ────────────────────────────────────────
        if options.include_transitive and options.transitive_depth > 0:
            # For each module that the test file imports, check if that module
            # transitively imports the impacted module.
            for test_imported_mod in sorted(test_info.imported_modules):
                reachable = get_transitive_imports(
                    test_imported_mod, module_graph, options.transitive_depth,
                )
                if impacted_module in reachable:
                    depth = reachable[impacted_module]
                    weight = _WEIGHT_TRANSITIVE_IMPORT / max(depth, 1)
                    reason = TestReason(
                        type="transitive_import",
                        evidence=(
                            f"{test_imported_mod} transitively imports "
                            f"{impacted_module} (depth {depth})"
                        ),
                    )
                    if reason not in reasons:
                        reasons.append(reason)
                        total_weight += weight
                    # Only count the shallowest transitive path for this node
                    break

        # ── symbol_reference ─────────────────────────────────────────
        if node.symbol and node.symbol in test_info.name_references:
            reason = TestReason(
                type="symbol_reference",
                evidence=f"references {node.symbol}",
            )
            if reason not in reasons:
                reasons.append(reason)
                total_weight += _WEIGHT_SYMBOL_REFERENCE

        # ── field_literal_match ──────────────────────────────────────
        if (
            options.include_literal_field_matches
            and node.symbol
            and node.kind == "field"
            and node.symbol in test_info.string_literals
        ):
            reason = TestReason(
                type="field_literal_match",
                evidence=f'string literal "{node.symbol}" found in test',
            )
            if reason not in reasons:
                reasons.append(reason)
                total_weight += _WEIGHT_FIELD_LITERAL_MATCH

    return min(total_weight, 1.0), reasons


def _assign_confidence(score: float) -> str:
    """Map numeric score to a confidence label.

    * ``>= 0.7`` → ``"high"``
    * ``>= 0.4`` → ``"medium"``
    * ``< 0.4``  → ``"low"``
    """
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def score_tests(
    impacted_nodes: list[ImpactedNode],
    test_index: dict[str, _TestFileInfo],
    module_graph: dict[str, set[str]],
    options: Tool5Options,
) -> tuple[list[TestItem], list[UnmatchedImpact]]:
    """Score every discovered test against the impacted nodes.

    Produces a sorted, ranked, trimmed list of :class:`TestItem` and a list
    of :class:`UnmatchedImpact` for nodes with no matching tests.

    Ranking is deterministic:

    1. Sort by ``(score desc, file asc, nodeid asc)``.
    2. Assign contiguous ``rank`` starting from 1.
    3. Trim to ``options.max_tests``.
    4. Assign confidence label.

    Args:
        impacted_nodes: Impacted code nodes from the request.
        test_index: Mapping of test files to their parsed information.
        module_graph: Module import graph.
        options: Tool 5 options.

    Returns:
        ``(test_items, unmatched_impacts)`` tuple.
    """
    # ── Collect all (nodeid, test_info) pairs ────────────────────────
    scored: list[tuple[str, str, float, list[TestReason]]] = []
    # (nodeid, file, score, reasons)

    for _file, info in sorted(test_index.items()):
        for nodeid in info.nodeids:
            score, reasons = _score_single_test(
                test_info=info,
                nodeid=nodeid,
                impacted_nodes=impacted_nodes,
                module_graph=module_graph,
                options=options,
            )
            if score > 0.0:
                scored.append((nodeid, info.rel_path, score, reasons))

    # ── Deterministic sort ───────────────────────────────────────────
    scored.sort(key=lambda t: (-t[2], t[1], t[0]))

    # ── Build TestItem list ──────────────────────────────────────────
    tests: list[TestItem] = []
    for rank, (nodeid, file, score, reasons) in enumerate(scored, start=1):
        if rank > options.max_tests:
            break
        tests.append(
            TestItem(
                test_id=_compute_test_id(nodeid, file),
                nodeid=nodeid,
                file=file,
                score=round(score, 4),
                rank=rank,
                confidence=_assign_confidence(score),
                reasons=reasons,
            )
        )

    # ── Unmatched impacts ────────────────────────────────────────────
    # An impacted node is "unmatched" if no selected test scored > 0 against it.
    matched_modules: set[str] = set()
    matched_symbols: set[str] = set()
    for _nodeid, _file, _score, reasons in scored:
        for r in reasons:
            # Extract the module or symbol from evidence text
            # We just check if any reason references the impacted module/symbol.
            matched_modules.add(r.evidence)

    unmatched: list[UnmatchedImpact] = []
    for node in impacted_nodes:
        impacted_module = _file_path_to_module(node.file)
        # Check if any test scored > 0 and had a reason involving this node.
        node_matched = False
        for _nodeid, _file, _score, reasons in scored:
            for r in reasons:
                # Check if this reason references the impacted module or symbol
                if impacted_module in r.evidence:
                    node_matched = True
                    break
                if node.symbol and node.symbol in r.evidence:
                    node_matched = True
                    break
            if node_matched:
                break

        if not node_matched:
            if not test_index:
                reason_code = "test_discovery_empty"
            else:
                reason_code = "no_test_reference"
            unmatched.append(
                UnmatchedImpact(
                    file=node.file,
                    symbol=node.symbol,
                    reason=reason_code,
                )
            )

    return tests, unmatched


# ── Phase 6.4 — Main Entry Point ─────────────────────────────────────


def run_tool5(validated_inputs: dict, repo_root: str) -> dict:
    """Execute Tool 5 — Test Impact Analyzer.

    Orchestrates the full pipeline:

    1. Discover test files in the repository.
    2. Build a per-test import/reference index.
    3. Build a module-level import graph (if ``include_transitive`` is on).
    4. Score and rank tests against the impacted nodes.
    5. Assemble the result payload.

    Args:
        validated_inputs: Dict with keys matching :class:`Tool5Request` fields.
        repo_root: Absolute or relative path to the repository root.

    Returns:
        A ``dict`` matching ``Tool5Result.model_dump(by_alias=True)``.
    """
    request = Tool5Request.model_validate(validated_inputs)
    all_diagnostics: list[Tool5Diagnostic] = []
    options = request.options

    # ── 1. Discover tests ────────────────────────────────────────────
    test_files, disc_diags = discover_tests(repo_root)
    all_diagnostics.extend(disc_diags)

    # Early exit: no tests → all impacts unmatched.
    if not test_files:
        unmatched = [
            UnmatchedImpact(
                file=n.file,
                symbol=n.symbol,
                reason="test_discovery_empty",
            )
            for n in request.impacted_nodes
        ]
        result = Tool5Result(
            tests=[],
            unmatched_impacts=unmatched,
            selection_stats=SelectionStats(
                tests_considered=0,
                tests_selected=0,
                high_confidence=0,
            ),
            diagnostics=all_diagnostics,
        )
        return result.model_dump(by_alias=True)

    # ── 2. Build test index ──────────────────────────────────────────
    test_index, idx_diags = build_test_index(repo_root, test_files)
    all_diagnostics.extend(idx_diags)

    # ── 3. Build module graph (if transitive enabled) ────────────────
    module_graph: dict[str, set[str]] = {}
    if options.include_transitive and options.transitive_depth > 0:
        module_graph = build_module_graph(repo_root)

    # ── 4. Score & rank ──────────────────────────────────────────────
    tests, unmatched = score_tests(
        impacted_nodes=request.impacted_nodes,
        test_index=test_index,
        module_graph=module_graph,
        options=options,
    )

    # Emit truncation diagnostic if we had to trim.
    total_considered = sum(len(info.nodeids) for info in test_index.values())
    if len(tests) < total_considered and total_considered > options.max_tests:
        all_diagnostics.append(
            Tool5Diagnostic(
                severity="info",
                code="selection_truncated",
                message=(
                    f"Returned {len(tests)} of {total_considered} candidate "
                    f"tests (max_tests={options.max_tests})."
                ),
            )
        )

    # ── 5. Assemble result ───────────────────────────────────────────
    high_count = sum(1 for t in tests if t.confidence == "high")
    result = Tool5Result(
        tests=tests,
        unmatched_impacts=unmatched,
        selection_stats=SelectionStats(
            tests_considered=total_considered,
            tests_selected=len(tests),
            high_confidence=high_count,
        ),
        diagnostics=all_diagnostics,
    )
    return result.model_dump(by_alias=True)
