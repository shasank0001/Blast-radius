"""Tool 1 — AST Structural Engine.

Parses Python source files, extracts AST nodes (modules, classes, functions,
methods) and relationship edges (imports, calls, inheritance) with evidence
spans for downstream change-impact analysis.
"""

from __future__ import annotations

import ast
import hashlib
import json
import time
from typing import Sequence

from blast_radius_mcp.repo.io import compute_file_hash, safe_read_file
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
    ReferenceMetadata,
    TargetRef,
    Tool1Options,
    Tool1Request,
    Tool1Result,
    Tool1Stats,
)

# ── Module-level constants ───────────────────────────────────────────

TOOL1_IMPL_VERSION = "1.0.0"

# ── Helpers ──────────────────────────────────────────────────────────


def _sha256_prefix(prefix: str, *parts: str, length: int = 16) -> str:
    """Return ``prefix`` + first *length* hex chars of the SHA-256 digest."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
    return prefix + h.hexdigest()[:length]


def _compute_node_id(qualified_name: str, file: str, start_line: int) -> str:
    """Deterministic node identifier."""
    return _sha256_prefix("sym_", "node", qualified_name, file, str(start_line))


def _compute_edge_id(
    source_id: str,
    edge_type: str,
    target_ref_str: str,
    start_line: int,
    start_col: int,
) -> str:
    """Deterministic edge identifier."""
    return _sha256_prefix(
        "edge_",
        "edge",
        source_id,
        edge_type,
        target_ref_str,
        str(start_line),
        str(start_col),
    )


def _file_path_to_module(file_path: str) -> str:
    """Convert a repo-relative file path to a dotted module name.

    ``foo/bar/baz.py``      → ``foo.bar.baz``
    ``foo/bar/__init__.py``  → ``foo.bar``
    """
    # Normalise separators
    fp = file_path.replace("\\", "/")
    if fp.endswith("/__init__.py"):
        fp = fp[: -len("/__init__.py")]
    elif fp.endswith(".py"):
        fp = fp[: -len(".py")]
    return fp.replace("/", ".")


def _snippet_from_lines(
    source_lines: list[str],
    start_line: int,
    end_line: int,
    max_chars: int,
) -> str:
    """Extract a source snippet from *start_line* to *end_line* (1-based, inclusive)."""
    # Clamp to valid range
    start = max(start_line - 1, 0)
    end = min(end_line, len(source_lines))
    text = "\n".join(source_lines[start:end])
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


# ── File loading ─────────────────────────────────────────────────────


def load_and_hash_files(
    repo_root: str,
    target_files: list[str],
) -> tuple[list[FileInfo], dict[str, str]]:
    """Read each target file, compute its hash, return metadata and sources.

    Returns:
        A tuple of ``(file_infos, sources)`` where *sources* maps each
        successfully-read repo-relative path to its decoded source text.
    """
    file_infos: list[FileInfo] = []
    sources: dict[str, str] = {}

    for rel_path in target_files:
        try:
            raw = safe_read_file(repo_root, rel_path)
        except (FileNotFoundError, ValueError) as exc:
            file_infos.append(
                FileInfo(
                    path=rel_path,
                    sha256="",
                    size_bytes=0,
                    parse_status="error",
                    syntax_error=str(exc),
                )
            )
            continue

        sha = compute_file_hash(raw)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            file_infos.append(
                FileInfo(
                    path=rel_path,
                    sha256=sha,
                    size_bytes=len(raw),
                    parse_status="error",
                    syntax_error=f"UnicodeDecodeError: {exc}",
                )
            )
            continue

        sources[rel_path] = text
        file_infos.append(
            FileInfo(
                path=rel_path,
                sha256=sha,
                size_bytes=len(raw),
                parse_status="ok",
            )
        )

    return file_infos, sources


# ── Parsing ──────────────────────────────────────────────────────────


def parse_python_file(
    source: str,
    file_path: str,
) -> tuple[ast.AST | None, Diagnostic | None]:
    """Parse *source* into an AST tree.

    Returns ``(tree, None)`` on success or ``(None, diagnostic)`` on
    ``SyntaxError``.
    """
    try:
        tree = ast.parse(source, filename=file_path)
        return tree, None
    except SyntaxError as exc:
        line = exc.lineno or 1
        col = exc.offset or 0
        # offset is 1-based in SyntaxError; convert to 0-based col
        col = max(col - 1, 0)
        diag = Diagnostic(
            file=file_path,
            severity="error",
            message=f"SyntaxError: {exc.msg}",
            range=Range(
                start=Position(line=line, col=col),
                end=Position(line=line, col=col),
            ),
        )
        return None, diag


def _tree_sitter_available() -> bool:
    """Return whether the ``tree_sitter`` dependency is importable."""
    try:
        __import__("tree_sitter")
        return True
    except Exception:
        return False


# ── Signature extraction ─────────────────────────────────────────────


def _extract_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str:
    """Best-effort function/method signature string."""
    args = node.args
    parts: list[str] = []

    # positional-only params
    posonlyargs = getattr(args, "posonlyargs", [])
    num_pos_defaults = len(args.defaults)
    pos_and_normal = list(posonlyargs) + list(args.args)
    total_positional = len(pos_and_normal)

    for idx, arg in enumerate(pos_and_normal):
        name = arg.arg
        # Check if this argument has a default
        default_index = idx - (total_positional - num_pos_defaults)
        if default_index >= 0:
            name += "=..."
        parts.append(name)
        # Insert `/` separator after positional-only args
        if posonlyargs and idx == len(posonlyargs) - 1:
            parts.append("/")

    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    elif args.kwonlyargs:
        parts.append("*")

    for i, kwarg in enumerate(args.kwonlyargs):
        name = kwarg.arg
        if i < len(args.kw_defaults) and args.kw_defaults[i] is not None:
            name += "=..."
        parts.append(name)

    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")

    return "(" + ", ".join(parts) + ")"


# ── Symbol table construction ────────────────────────────────────────


def _node_end_line(node: ast.AST) -> int:
    """Return the end line of an AST node (1-based)."""
    return getattr(node, "end_lineno", getattr(node, "lineno", 1)) or 1


def _has_yield(node: ast.AST) -> bool:
    """Check whether a function body contains Yield or YieldFrom.

    Uses a recursive walker that stops descending into nested
    FunctionDef, AsyncFunctionDef, and Lambda nodes so that yields
    inside nested scopes are not attributed to the outer function.
    """

    def _walk(nodes: list[ast.AST]) -> bool:
        for n in nodes:
            if isinstance(n, (ast.Yield, ast.YieldFrom)):
                return True
            # Don't descend into nested function / lambda scopes
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if _walk(list(ast.iter_child_nodes(n))):
                return True
        return False

    # Start from the children of the node (the function body) so we
    # don't immediately skip the top-level function node itself.
    return _walk(list(ast.iter_child_nodes(node)))


def _decorator_names(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Extract decorator names as strings."""
    names: list[str] = []
    for dec in node.decorator_list:
        try:
            names.append(ast.unparse(dec))
        except Exception:
            names.append("<unknown>")
    return names


def _base_names(node: ast.ClassDef) -> list[str]:
    """Extract base class names as strings."""
    bases: list[str] = []
    for base in node.bases:
        try:
            bases.append(ast.unparse(base))
        except Exception:
            bases.append("<unknown>")
    return bases


def _extract_exports(tree: ast.Module) -> list[str]:
    """Extract ``__all__`` if it is a simple list of string literals."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        return [
                            elt.value
                            for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        ]
    return []


def build_symbol_table(
    tree: ast.AST,
    file_path: str,
    source_lines: list[str],
) -> list[ASTNode]:
    """Walk *tree* and collect symbol nodes.

    Returns a list of :class:`ASTNode` for the module, its classes,
    functions and methods.
    """
    module_name = _file_path_to_module(file_path)
    total_lines = len(source_lines)
    nodes: list[ASTNode] = []

    # --- Module node ---
    module_end_line = total_lines if total_lines > 0 else 1
    module_node_id = _compute_node_id(module_name, file_path, 1)
    exports = _extract_exports(tree) if isinstance(tree, ast.Module) else []
    nodes.append(
        ASTNode(
            id=module_node_id,
            kind="module",
            name=module_name.rsplit(".", 1)[-1] if "." in module_name else module_name,
            qualified_name=module_name,
            file=file_path,
            range=Range(
                start=Position(line=1, col=0),
                end=Position(line=module_end_line, col=0),
            ),
            docstring=ast.get_docstring(tree) if isinstance(tree, ast.Module) else None,
            exports=exports,
        )
    )

    # --- Walk children ---
    def _visit(
        parent_node: ast.AST,
        scope_prefix: str,
        inside_class: bool,
    ) -> None:
        for child in ast.iter_child_nodes(parent_node):
            if isinstance(child, ast.ClassDef):
                qname = f"{scope_prefix}.{child.name}"
                start_line = child.lineno
                end_line = _node_end_line(child)
                nid = _compute_node_id(qname, file_path, start_line)
                decorators = _decorator_names(child)
                bases = _base_names(child)
                nodes.append(
                    ASTNode(
                        id=nid,
                        kind="class",
                        name=child.name,
                        qualified_name=qname,
                        file=file_path,
                        range=Range(
                            start=Position(line=start_line, col=child.col_offset),
                            end=Position(line=end_line, col=0),
                        ),
                        decorators=decorators,
                        bases=bases,
                        docstring=ast.get_docstring(child),
                    )
                )
                # Recurse into class body
                _visit(child, qname, inside_class=True)

            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qname = f"{scope_prefix}.{child.name}"
                start_line = child.lineno
                end_line = _node_end_line(child)
                nid = _compute_node_id(qname, file_path, start_line)
                kind = "method" if inside_class else "function"
                decorators = _decorator_names(child)
                is_async = isinstance(child, ast.AsyncFunctionDef)
                is_generator = _has_yield(child)
                is_property = "property" in decorators
                sig = _extract_signature(child)

                nodes.append(
                    ASTNode(
                        id=nid,
                        kind=kind,
                        name=child.name,
                        qualified_name=qname,
                        file=file_path,
                        range=Range(
                            start=Position(line=start_line, col=child.col_offset),
                            end=Position(line=end_line, col=0),
                        ),
                        signature=sig,
                        decorators=decorators,
                        docstring=ast.get_docstring(child),
                        attributes=NodeAttributes(
                            is_async=is_async,
                            is_generator=is_generator,
                            is_property=is_property,
                        ),
                    )
                )
                # Recurse into nested definitions (nested functions/classes)
                _visit(child, qname, inside_class=False)

    _visit(tree, module_name, inside_class=False)
    return nodes


# ── Import alias map ─────────────────────────────────────────────────


def _build_import_alias_map(
    tree: ast.AST,
) -> dict[str, tuple[str, str]]:
    """Build a mapping from local alias → (module_path, original_name).

    For ``import os.path``             → ``{"os": ("os", ""), "os.path": ("os.path", "")}``
    For ``from os.path import join``   → ``{"join": ("os.path", "join")}``
    For ``from os.path import join as pjoin`` → ``{"pjoin": ("os.path", "join")}``
    """
    alias_map: dict[str, tuple[str, str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name
                alias_map[local_name] = (alias.name, "")
                if alias.asname is None and "." in alias.name:
                    root_name = alias.name.split(".", 1)[0]
                    alias_map.setdefault(root_name, (root_name, ""))

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level or 0
            # Represent relative imports with leading dots
            prefix = "." * level + module
            for alias in node.names:
                local_name = alias.asname or alias.name
                if alias.name == "*":
                    # Star import — we can't resolve individual names
                    continue
                alias_map[local_name] = (prefix, alias.name)

    return alias_map


def _build_scope_parent_links(
    symbol_table: list[ASTNode],
) -> tuple[str, dict[str, str | None], dict[str, str]]:
    """Build deterministic parent links between scope nodes.

    Returns ``(module_scope_id, parent_by_scope, kind_by_scope)``.
    """
    if not symbol_table:
        return "", {}, {}

    scopes = [n for n in symbol_table if n.kind in {"module", "class", "function", "method"}]
    if not scopes:
        return "", {}, {}

    module_nodes = [n for n in scopes if n.kind == "module"]
    module_node = module_nodes[0] if module_nodes else scopes[0]
    module_scope_id = module_node.id

    parent_by_scope: dict[str, str | None] = {module_scope_id: None}
    kind_by_scope: dict[str, str] = {n.id: n.kind for n in scopes}

    for scope in scopes:
        if scope.id == module_scope_id:
            continue

        start_line = scope.range.start.line
        end_line = scope.range.end.line
        candidates: list[ASTNode] = []
        for container in scopes:
            if container.id == scope.id:
                continue
            c_start = container.range.start.line
            c_end = container.range.end.line
            if c_start <= start_line and c_end >= end_line:
                candidates.append(container)

        if candidates:
            candidates.sort(
                key=lambda n: (
                    n.range.end.line - n.range.start.line,
                    1 if n.kind == "module" else 0,
                    -n.range.start.line,
                    -n.range.start.col,
                    n.id,
                )
            )
            parent_by_scope[scope.id] = candidates[0].id
        else:
            parent_by_scope[scope.id] = module_scope_id

    return module_scope_id, parent_by_scope, kind_by_scope


def _build_import_alias_maps_by_scope(
    tree: ast.AST,
    symbol_table: list[ASTNode],
) -> tuple[
    dict[str, dict[str, tuple[str, str]]],
    dict[str, str | None],
    str,
    dict[str, str],
]:
    """Build per-scope alias maps and scope parent links."""
    module_scope_id, parent_by_scope, kind_by_scope = _build_scope_parent_links(symbol_table)

    alias_maps_by_scope: dict[str, dict[str, tuple[str, str]]] = {
        scope_id: {} for scope_id in parent_by_scope
    }
    if module_scope_id and module_scope_id not in alias_maps_by_scope:
        alias_maps_by_scope[module_scope_id] = {}

    import_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    import_nodes.sort(
        key=lambda n: (
            getattr(n, "lineno", 1),
            getattr(n, "col_offset", 0),
            0 if isinstance(n, ast.Import) else 1,
        )
    )

    for node in import_nodes:
        line = getattr(node, "lineno", 1)
        col = getattr(node, "col_offset", 0)
        scope = _find_enclosing_scope(symbol_table, line, col)
        scope_id = scope.id
        scope_aliases = alias_maps_by_scope.setdefault(scope_id, {})

        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name
                scope_aliases[local_name] = (alias.name, "")
                if alias.asname is None and "." in alias.name:
                    root_name = alias.name.split(".", 1)[0]
                    scope_aliases.setdefault(root_name, (root_name, ""))
            continue

        module = node.module or ""
        level = node.level or 0
        prefix = "." * level + module
        for alias in node.names:
            if alias.name == "*":
                continue
            local_name = alias.asname or alias.name
            scope_aliases[local_name] = (prefix, alias.name)

    return alias_maps_by_scope, parent_by_scope, module_scope_id, kind_by_scope


def _compose_alias_view(
    scope_id: str,
    alias_maps_by_scope: dict[str, dict[str, tuple[str, str]]],
    parent_by_scope: dict[str, str | None],
    kind_by_scope: dict[str, str],
) -> dict[str, tuple[str, str]]:
    """Compose visible aliases for a scope by walking parent links."""
    if not scope_id:
        return {}

    current_scope_id = scope_id
    if current_scope_id not in parent_by_scope:
        module_ids = [sid for sid, parent in parent_by_scope.items() if parent is None]
        if module_ids:
            current_scope_id = module_ids[0]
        else:
            return {}

    chain: list[str] = []
    seen: set[str] = set()
    cur: str | None = current_scope_id
    while cur is not None and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = parent_by_scope.get(cur)

    current_kind = kind_by_scope.get(current_scope_id, "")
    skip_class_ancestors = current_kind in {"function", "method"}

    merged: dict[str, tuple[str, str]] = {}
    for sid in reversed(chain):
        if skip_class_ancestors and sid != current_scope_id and kind_by_scope.get(sid) == "class":
            continue
        merged.update(alias_maps_by_scope.get(sid, {}))

    return merged


def _expand_name_via_alias_map(
    name: str,
    alias_map: dict[str, tuple[str, str]],
) -> str | None:
    """Resolve a name through an alias map into a candidate qualified name."""
    root_name = name.split(".")[0]
    if root_name not in alias_map:
        return None

    mod, orig = alias_map[root_name]
    qname = f"{mod}.{orig}" if orig else mod

    remaining = name.split(".", 1)
    if len(remaining) > 1:
        qname = f"{qname}.{remaining[1]}"

    return qname


# ── Edge emission ────────────────────────────────────────────────────


def _find_enclosing_scope(
    nodes: list[ASTNode],
    line: int,
    col: int,
) -> ASTNode:
    """Find the most specific (innermost) scope node for a given position.

    Falls back to the module node if nothing else matches.
    """
    best: ASTNode | None = None
    best_key: tuple[int, int, int, str] | None = None
    module: ASTNode | None = None

    for n in nodes:
        if n.kind == "module":
            module = n
            continue
        n_start = n.range.start.line
        n_end = n.range.end.line
        if n_start <= line <= n_end:
            size = n_end - n_start
            key = (size, -n_start, -n.range.start.col, n.id)
            if best_key is None or key < best_key:
                best_key = key
                best = n
    return best if best is not None else module  # type: ignore[return-value]


def _resolve_callee_text(call_node: ast.Call) -> str:
    """Best-effort callee text via ``ast.unparse``."""
    try:
        return ast.unparse(call_node.func)
    except Exception:
        return "<unknown>"


def _lookup_symbol(
    name: str,
    symbol_table: list[ASTNode],
    alias_map: dict[str, tuple[str, str]],
) -> tuple[TargetRef, float, str]:
    """Try to resolve *name* to a target symbol.

    Returns ``(target_ref, confidence, strategy)``.
    """
    # Direct match in local symbol table
    for sym in symbol_table:
        if sym.qualified_name == name or sym.name == name:
            return (
                TargetRef(
                    kind="symbol",
                    qualified_name=sym.qualified_name,
                    file=sym.file,
                    symbol_id=sym.id,
                ),
                0.9,
                "local_scope",
            )

    # Check import alias map
    qname = _expand_name_via_alias_map(name, alias_map)
    if qname is not None:
        return (
            TargetRef(
                kind="symbol",
                qualified_name=qname,
                file="",
            ),
            0.6,
            "import_table",
        )

    # Attribute chain heuristic
    if "." in name:
        return (
            TargetRef(kind="unresolved", qualified_name=name),
            0.6,
            "attribute_chain",
        )

    # Unresolved
    return (
        TargetRef(kind="unresolved", qualified_name=name),
        0.3,
        "unknown",
    )


def emit_edges(
    tree: ast.AST,
    file_path: str,
    symbol_table: list[ASTNode],
    options: Tool1Options,
    source_lines: list[str],
) -> list[ASTEdge]:
    """Walk *tree* and emit relationship edges."""
    edges: list[ASTEdge] = []
    alias_maps_by_scope, parent_by_scope, module_scope_id, kind_by_scope = (
        _build_import_alias_maps_by_scope(tree, symbol_table)
    )
    alias_view_cache: dict[str, dict[str, tuple[str, str]]] = {}

    def _alias_view_for_scope(scope_id: str) -> dict[str, tuple[str, str]]:
        resolved_scope = scope_id if scope_id in parent_by_scope else module_scope_id
        if resolved_scope not in alias_view_cache:
            alias_view_cache[resolved_scope] = _compose_alias_view(
                resolved_scope,
                alias_maps_by_scope,
                parent_by_scope,
                kind_by_scope,
            )
        return alias_view_cache[resolved_scope]

    # Find the module node for use as default scope
    module_node: ASTNode | None = None
    for n in symbol_table:
        if n.kind == "module":
            module_node = n
            break

    if module_node is None:
        return edges

    # ── Import edges ─────────────────────────────────────────────────
    if options.include_import_edges:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    line = node.lineno
                    col = node.col_offset
                    import_scope = _find_enclosing_scope(symbol_table, line, col)
                    target_module = alias.name
                    target_ref = TargetRef(
                        kind="module",
                        qualified_name=target_module,
                    )
                    eid = _compute_edge_id(
                        import_scope.id, "imports", target_module, line, col,
                    )
                    snippet = _snippet_from_lines(
                        source_lines, line, line, options.max_snippet_chars,
                    )
                    edges.append(
                        ASTEdge(
                            id=eid,
                            type="imports",
                            source=import_scope.id,
                            target_ref=target_ref,
                            range=Range(
                                start=Position(line=line, col=col),
                                end=Position(line=line, col=col + len(ast.unparse(node))),
                            ),
                            confidence=0.9,
                            resolution=EdgeResolution(
                                status="unresolved",
                                strategy="import_table",
                            ),
                            snippet=snippet,
                            metadata=EdgeMetadata(
                                import_=ImportMetadata(
                                    module=target_module,
                                    alias=alias.asname or "",
                                ),
                            ),
                        )
                    )

            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                level = node.level or 0
                line = node.lineno
                col = node.col_offset
                import_scope = _find_enclosing_scope(symbol_table, line, col)
                for alias_idx, alias in enumerate(node.names):
                    if alias.name == "*":
                        target_ref = TargetRef(
                            kind="module",
                            qualified_name=module_name,
                        )
                        ref_str = module_name
                    else:
                        ref_str = f"{module_name}.{alias.name}" if module_name else alias.name
                        target_ref = TargetRef(
                            kind="symbol",
                            qualified_name=ref_str,
                        )
                    eid = _compute_edge_id(
                        import_scope.id, "imports", ref_str, line, col + alias_idx,
                    )
                    snippet = _snippet_from_lines(
                        source_lines, line, line, options.max_snippet_chars,
                    )
                    edges.append(
                        ASTEdge(
                            id=eid,
                            type="imports",
                            source=import_scope.id,
                            target_ref=target_ref,
                            range=Range(
                                start=Position(line=line, col=col),
                                end=Position(
                                    line=getattr(node, "end_lineno", line) or line,
                                    col=getattr(node, "end_col_offset", col) or col,
                                ),
                            ),
                            confidence=0.9,
                            resolution=EdgeResolution(
                                status="unresolved",
                                strategy="import_table",
                            ),
                            snippet=snippet,
                            metadata=EdgeMetadata(
                                import_=ImportMetadata(
                                    module=module_name,
                                    name=alias.name,
                                    alias=alias.asname or "",
                                    level=level,
                                ),
                            ),
                        )
                    )

    # ── Call edges ───────────────────────────────────────────────────
    if options.include_call_edges:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                line = node.lineno
                col = node.col_offset
                callee_text = _resolve_callee_text(node)
                enclosing = _find_enclosing_scope(symbol_table, line, col)
                alias_view = _alias_view_for_scope(enclosing.id)
                target_ref, confidence, strategy = _lookup_symbol(
                    callee_text, symbol_table, alias_view,
                )
                eid = _compute_edge_id(
                    enclosing.id, "calls", callee_text, line, col,
                )
                snippet = _snippet_from_lines(
                    source_lines, line, line, options.max_snippet_chars,
                )
                edges.append(
                    ASTEdge(
                        id=eid,
                        type="calls",
                        source=enclosing.id,
                        target=target_ref.symbol_id,
                        target_ref=target_ref,
                        range=Range(
                            start=Position(line=line, col=col),
                            end=Position(
                                line=getattr(node, "end_lineno", line) or line,
                                col=getattr(node, "end_col_offset", col) or col,
                            ),
                        ),
                        confidence=confidence,
                        resolution=EdgeResolution(
                            status="resolved" if target_ref.kind != "unresolved" else "unresolved",
                            strategy=strategy,
                        ),
                        snippet=snippet,
                        metadata=EdgeMetadata(
                            call=CallMetadata(
                                callee_text=callee_text,
                                arg_count=len(node.args) + len(node.keywords),
                            ),
                        ),
                    )
                )

    # ── Inheritance edges ────────────────────────────────────────────
    if options.include_inheritance_edges:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Find the class node in symbol table
                class_node: ASTNode | None = None
                for n in symbol_table:
                    if (
                        n.kind == "class"
                        and n.name == node.name
                        and n.range.start.line == node.lineno
                    ):
                        class_node = n
                        break

                if class_node is None:
                    continue

                for base in node.bases:
                    try:
                        base_text = ast.unparse(base)
                    except Exception:
                        base_text = "<unknown>"

                    base_scope = parent_by_scope.get(class_node.id) or class_node.id
                    alias_view = _alias_view_for_scope(base_scope)
                    target_ref, confidence, strategy = _lookup_symbol(
                        base_text, symbol_table, alias_view,
                    )
                    line = base.lineno
                    col = base.col_offset
                    eid = _compute_edge_id(
                        class_node.id, "inherits", base_text, line, col,
                    )
                    snippet = _snippet_from_lines(
                        source_lines,
                        node.lineno,
                        node.lineno,
                        options.max_snippet_chars,
                    )
                    edges.append(
                        ASTEdge(
                            id=eid,
                            type="inherits",
                            source=class_node.id,
                            target=target_ref.symbol_id,
                            target_ref=target_ref,
                            range=Range(
                                start=Position(line=line, col=col),
                                end=Position(
                                    line=getattr(base, "end_lineno", line) or line,
                                    col=getattr(base, "end_col_offset", col) or col,
                                ),
                            ),
                            confidence=confidence,
                            resolution=EdgeResolution(
                                status="resolved"
                                if target_ref.kind != "unresolved"
                                else "unresolved",
                                strategy=strategy,
                            ),
                            snippet=snippet,
                            metadata=EdgeMetadata(
                                inheritance=InheritanceMetadata(base_text=base_text),
                            ),
                        )
                    )

    # ── Reference edges ──────────────────────────────────────────────
    if options.include_references:
        reference_edges: list[tuple[int, int, str, str, ASTEdge]] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Name):
                continue

            line = node.lineno
            col = node.col_offset
            ref_name = node.id

            if isinstance(node.ctx, ast.Store):
                ref_context = "store"
            elif isinstance(node.ctx, ast.Del):
                ref_context = "del"
            else:
                ref_context = "load"

            enclosing = _find_enclosing_scope(symbol_table, line, col)
            alias_view = _alias_view_for_scope(enclosing.id)
            target_ref, confidence, strategy = _lookup_symbol(
                ref_name, symbol_table, alias_view,
            )
            eid = _compute_edge_id(
                enclosing.id,
                "references",
                f"{ref_name}:{ref_context}",
                line,
                col,
            )
            snippet = _snippet_from_lines(
                source_lines, line, line, options.max_snippet_chars,
            )

            edge = ASTEdge(
                id=eid,
                type="references",
                source=enclosing.id,
                target=target_ref.symbol_id,
                target_ref=target_ref,
                range=Range(
                    start=Position(line=line, col=col),
                    end=Position(line=line, col=col + len(ref_name)),
                ),
                confidence=confidence,
                resolution=EdgeResolution(
                    status="resolved" if target_ref.kind != "unresolved" else "unresolved",
                    strategy=strategy,
                ),
                snippet=snippet,
                metadata=EdgeMetadata(
                    reference=ReferenceMetadata(name=ref_name, context=ref_context),
                ),
            )
            reference_edges.append((line, col, ref_name, ref_context, edge))

        reference_edges.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
        edges.extend(edge for _, _, _, _, edge in reference_edges)

    return edges


# ── Cross-file resolution ────────────────────────────────────────────


def build_cross_file_index(
    nodes_by_file: dict[str, list[ASTNode]],
) -> tuple[dict[str, tuple[str, str, str]], list[dict[str, str]]]:
    """Build a mapping: ``qualified_name → (file, node_id, kind)``.

    Used for cross-file edge resolution.

    Returns:
        A tuple of ``(index, ambiguities)`` where *ambiguities* is a list
        of dicts describing duplicate qualified-name definitions across files.
    """
    index: dict[str, tuple[str, str, str]] = {}
    ambiguities: list[dict[str, str]] = []
    for file_path, nodes in nodes_by_file.items():
        for n in nodes:
            if n.qualified_name in index:
                existing = index[n.qualified_name]
                ambiguities.append({
                    "qualified_name": n.qualified_name,
                    "file1": existing[0],
                    "file2": file_path,
                })
                # Keep first entry (don't overwrite)
                continue
            index[n.qualified_name] = (n.file, n.id, n.kind)
    return index, ambiguities


def resolve_cross_file_edges(
    edges: list[ASTEdge],
    cross_file_index: dict[str, tuple[str, str, str]],
    alias_maps_by_file: dict[str, dict[str, dict[str, tuple[str, str]]]],
    parent_scopes_by_file: dict[str, dict[str, str | None]],
    scope_kinds_by_file: dict[str, dict[str, str]],
    node_file_by_id: dict[str, str],
) -> list[ASTEdge]:
    """Attempt to resolve unresolved edges against the cross-file index.

    Mutates edges in place and returns them.
    """
    resolved_edges: list[ASTEdge] = []

    for edge in edges:
        if edge.resolution.status == "unresolved" and edge.target_ref.qualified_name:
            qname = edge.target_ref.qualified_name

            # Direct qualified name match
            if qname in cross_file_index:
                file, nid, kind = cross_file_index[qname]
                edge = edge.model_copy(
                    update={
                        "target": nid,
                        "target_ref": TargetRef(
                            kind="symbol" if kind != "module" else "module",
                            qualified_name=qname,
                            file=file,
                            symbol_id=nid,
                        ),
                        "resolution": EdgeResolution(
                            status="resolved",
                            strategy=edge.resolution.strategy,
                            candidates=[],
                        ),
                    }
                )
            else:
                source_file = node_file_by_id.get(edge.source, "")
                if source_file:
                    file_alias_maps = alias_maps_by_file.get(source_file, {})
                    file_parent_map = parent_scopes_by_file.get(source_file, {})
                    file_scope_kinds = scope_kinds_by_file.get(source_file, {})

                    if file_alias_maps and file_parent_map:
                        alias_view = _compose_alias_view(
                            edge.source,
                            file_alias_maps,
                            file_parent_map,
                            file_scope_kinds,
                        )
                        full_qname = _expand_name_via_alias_map(qname, alias_view)

                        if full_qname in cross_file_index:
                            file, nid, kind = cross_file_index[full_qname]
                            edge = edge.model_copy(
                                update={
                                    "target": nid,
                                    "target_ref": TargetRef(
                                        kind="symbol" if kind != "module" else "module",
                                        qualified_name=full_qname,
                                        file=file,
                                        symbol_id=nid,
                                    ),
                                    "resolution": EdgeResolution(
                                        status="resolved",
                                        strategy="import_table",
                                        candidates=[],
                                    ),
                                }
                            )

        resolved_edges.append(edge)

    return resolved_edges


# ── Sorting / finalisation ───────────────────────────────────────────


def finalize_and_sort(
    nodes: list[ASTNode],
    edges: list[ASTEdge],
    diagnostics: list[Diagnostic],
) -> tuple[list[ASTNode], list[ASTEdge], list[Diagnostic]]:
    """Sort nodes, edges and diagnostics into deterministic order."""
    sorted_nodes = sorted(nodes, key=lambda n: n.id)
    sorted_edges = sorted(edges, key=lambda e: (e.source, e.type, e.target, e.id))

    def _diag_key(d: Diagnostic) -> tuple[str, int, int, str, str]:
        if d.range is not None:
            return (d.file, d.range.start.line, d.range.start.col, d.code or "", d.message)
        return (d.file, 10**9, 10**9, d.code or "", d.message)

    sorted_diags = sorted(
        diagnostics,
        key=_diag_key,
    )
    return sorted_nodes, sorted_edges, sorted_diags


# ── Main entry point ─────────────────────────────────────────────────


def run_tool1(request: Tool1Request, repo_root: str) -> dict:
    """Execute the full Tool 1 pipeline and return the result as a dict."""
    t0 = time.monotonic()

    # Step 1: Load and hash files
    file_infos, sources = load_and_hash_files(repo_root, request.target_files)

    # Step 2 & 3: Parse files and build symbol tables
    all_nodes: list[ASTNode] = []
    all_edges: list[ASTEdge] = []
    diagnostics: list[Diagnostic] = []
    nodes_by_file: dict[str, list[ASTNode]] = {}
    alias_maps_by_file: dict[str, dict[str, dict[str, tuple[str, str]]]] = {}
    parent_scopes_by_file: dict[str, dict[str, str | None]] = {}
    scope_kinds_by_file: dict[str, dict[str, str]] = {}
    trees: dict[str, ast.AST] = {}
    parsed_ok = 0
    parsed_error = 0

    parse_mode = request.options.parse_mode
    if parse_mode == "tree_sitter" and not _tree_sitter_available():
        diagnostics.append(
            Diagnostic(
                file="",
                severity="warning",
                message=(
                    "parse_mode 'tree_sitter' requested but tree_sitter is unavailable; "
                    "falling back to 'python_ast'"
                ),
                range=Range(
                    start=Position(line=1, col=0),
                    end=Position(line=1, col=0),
                ),
            )
        )
        parse_mode = "python_ast"

    for fi in file_infos:
        if fi.parse_status == "error":
            parsed_error += 1
            continue

        source = sources[fi.path]
        if parse_mode == "tree_sitter":
            tree, diag = parse_python_file(source, fi.path)
        else:
            tree, diag = parse_python_file(source, fi.path)

        if diag is not None:
            diagnostics.append(diag)
            # Update file info parse_status
            fi_idx = file_infos.index(fi)
            file_infos[fi_idx] = fi.model_copy(
                update={
                    "parse_status": "error",
                    "syntax_error": diag.message,
                }
            )
            parsed_error += 1
            continue

        parsed_ok += 1
        assert tree is not None
        trees[fi.path] = tree
        source_lines = source.splitlines()

        # Step 3: Build symbol table
        nodes = build_symbol_table(tree, fi.path, source_lines)
        nodes_by_file[fi.path] = nodes
        all_nodes.extend(nodes)

        # Step 4: Build scope-aware import alias maps
        alias_maps, parent_scopes, _module_scope_id, scope_kinds = (
            _build_import_alias_maps_by_scope(tree, nodes)
        )
        alias_maps_by_file[fi.path] = alias_maps
        parent_scopes_by_file[fi.path] = parent_scopes
        scope_kinds_by_file[fi.path] = scope_kinds

    # Step 5: Emit edges for each file
    for fi in file_infos:
        if fi.path not in trees:
            continue
        source_lines = sources[fi.path].splitlines()
        file_edges = emit_edges(
            trees[fi.path],
            fi.path,
            nodes_by_file.get(fi.path, []),
            request.options,
            source_lines,
        )
        all_edges.extend(file_edges)

    # Step 6: Build cross-file index
    cross_file_index, ambiguities = build_cross_file_index(nodes_by_file)

    # Emit diagnostics for ambiguous qualified names
    for amb in ambiguities:
        diagnostics.append(
            Diagnostic(
                file=amb["file2"],
                severity="warning",
                message=(
                    f"Ambiguous symbol '{amb['qualified_name']}': "
                    f"already defined in {amb['file1']}"
                ),
                range=Range(
                    start=Position(line=1, col=0),
                    end=Position(line=1, col=0),
                ),
                code="ambiguous_symbol",
            )
        )

    # Step 7: Resolve cross-file edges
    node_file_by_id = {n.id: n.file for n in all_nodes}
    all_edges = resolve_cross_file_edges(
        all_edges,
        cross_file_index,
        alias_maps_by_file,
        parent_scopes_by_file,
        scope_kinds_by_file,
        node_file_by_id,
    )

    # Step 8: Finalize and sort
    all_nodes, all_edges, diagnostics = finalize_and_sort(
        all_nodes, all_edges, diagnostics,
    )

    # Step 9: Build stats
    duration_ms = int((time.monotonic() - t0) * 1000)
    stats = Tool1Stats(
        target_files=len(request.target_files),
        parsed_ok=parsed_ok,
        parsed_error=parsed_error,
        nodes=len(all_nodes),
        edges=len(all_edges),
        duration_ms=duration_ms,
    )

    # Step 10: Build and return result
    result = Tool1Result(
        repo_root=repo_root,
        files=file_infos,
        nodes=all_nodes,
        edges=all_edges,
        diagnostics=diagnostics,
        stats=stats,
    )

    return result.model_dump(by_alias=True)
