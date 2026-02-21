"""Tool 2 — Data Lineage Engine (``trace_data_shape``).

Traces field/path usage through API handlers in Python (FastAPI/Pydantic)
codebases.  Given a ``field_path`` (e.g. ``OrderRequest.user_id``) and one
or more entry points (routes or symbols), the engine:

1. Builds a route index (FastAPI decorators / ``add_api_route`` calls).
2. Builds a Pydantic model index (``BaseModel`` subclasses, fields, validators).
3. Resolves the requested entry points.
4. Traces field reads, writes, validations, and transforms through handler
   bodies (with bounded inter-procedural expansion).
5. Assembles a deterministic ``Tool2Result``.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Sequence

from blast_radius_mcp.repo.io import (
    compute_file_hash,
    glob_python_files,
    safe_read_file,
)
from blast_radius_mcp.schemas.common import Location, Position, Range
from blast_radius_mcp.schemas.tool2_lineage import (
    Breakage,
    EntryPointResolved,
    ReadWriteSite,
    Tool2Diagnostic,
    Tool2Options,
    Tool2Request,
    Tool2Result,
    Tool2Stats,
    Transform,
    Validation,
)

logger = logging.getLogger(__name__)

# ── Module-level constants ───────────────────────────────────────────

TOOL2_IMPL_VERSION = "1.0.0"

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "trace"})

# ── Deterministic ID helpers ─────────────────────────────────────────


def _sha256_prefix(prefix: str, *parts: str, length: int = 16) -> str:
    """Return *prefix* followed by the first *length* hex chars of a SHA-256
    digest computed from the concatenation of *parts*."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
    return prefix + h.hexdigest()[:length]


def _compute_site_id(
    field_path: str,
    symbol: str,
    file: str,
    line: int,
    col: int,
    pattern: str,
) -> str:
    """Deterministic site identifier."""
    return _sha256_prefix(
        "site_", field_path, symbol, file, str(line), str(col), pattern,
    )


def _compute_validation_id(
    kind: str,
    field_path: str,
    file: str,
    line: int,
) -> str:
    """Deterministic validation identifier."""
    return _sha256_prefix("val_", kind, field_path, file, str(line))


def _compute_transform_id(
    kind: str,
    field_path: str,
    file: str,
    line: int,
    col: int,
) -> str:
    """Deterministic transform identifier."""
    return _sha256_prefix("xform_", kind, field_path, file, str(line), str(col))


def _compute_symbol_id(qualified_name: str, file: str, start_line: int) -> str:
    """Deterministic symbol identifier (mirrors Tool 1 ``sym_`` prefix)."""
    return _sha256_prefix("sym_", "node", qualified_name, file, str(start_line))


# ── Snippet helper ───────────────────────────────────────────────────


def _snippet_from_lines(
    source_lines: list[str],
    start_line: int,
    end_line: int,
    max_chars: int = 120,
) -> str:
    """Extract a source snippet (1-based inclusive lines), capped at *max_chars*."""
    start = max(start_line - 1, 0)
    end = min(end_line, len(source_lines))
    text = "\n".join(source_lines[start:end])
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


# ── Location helper ──────────────────────────────────────────────────


def _loc(file: str, node: ast.AST) -> Location:
    """Build a ``Location`` from an AST node."""
    start_line = getattr(node, "lineno", 1) or 1
    start_col = getattr(node, "col_offset", 0) or 0
    end_line = getattr(node, "end_lineno", start_line) or start_line
    end_col = getattr(node, "end_col_offset", start_col) or start_col
    return Location(
        file=file,
        range=Range(
            start=Position(line=start_line, col=start_col),
            end=Position(line=end_line, col=end_col),
        ),
    )


def _loc_from_lines(file: str, start_line: int, start_col: int,
                     end_line: int, end_col: int) -> Location:
    """Build a ``Location`` from explicit line/col values."""
    return Location(
        file=file,
        range=Range(
            start=Position(line=start_line, col=start_col),
            end=Position(line=end_line, col=end_col),
        ),
    )


# ── Safe AST parsing ────────────────────────────────────────────────


def _safe_parse(source: str, file_path: str) -> ast.Module | None:
    """Parse *source* into an AST module, returning ``None`` on syntax error."""
    try:
        return ast.parse(source, filename=file_path)
    except SyntaxError:
        return None


def _safe_unparse(node: ast.AST) -> str:
    """Best-effort ``ast.unparse`` that never raises."""
    try:
        return ast.unparse(node)
    except Exception:
        return "<unknown>"


# ── Internal data structures ─────────────────────────────────────────


@dataclass
class RouteEntry:
    """An indexed FastAPI/Starlette route."""
    method: str          # e.g. "POST"
    path: str            # e.g. "/orders"
    handler_name: str    # Python function name
    handler_qname: str   # Qualified name e.g. "app.api.orders.create_order"
    file: str            # Repo-relative file path
    line: int            # 1-based start line of handler
    end_line: int        # 1-based end line
    col: int             # 0-based column offset


@dataclass
class PydanticField:
    """A field inside a Pydantic model."""
    name: str
    annotation: str       # Best-effort type string
    alias: str | None     # Value of Field(alias="…")
    has_default: bool
    line: int
    col: int


@dataclass
class PydanticValidator:
    """A validator method on a Pydantic model."""
    name: str
    target_fields: list[str]      # Fields referenced by @validator / @field_validator
    kind: str                     # "pydantic_validator" | "pydantic_field_constraint"
    line: int
    col: int
    rule_summary: str


@dataclass
class PydanticModelEntry:
    """An indexed Pydantic BaseModel subclass."""
    class_name: str
    file: str
    line: int
    end_line: int
    col: int
    fields: dict[str, PydanticField] = field(default_factory=dict)
    validators: list[PydanticValidator] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)


@dataclass
class FunctionEntry:
    """A discovered function/method for call-graph traversal."""
    name: str
    qname: str
    file: str
    line: int
    end_line: int
    col: int
    node: ast.FunctionDef | ast.AsyncFunctionDef


@dataclass
class FunctionIndex:
    """Function lookup index for inter-procedural tracing."""

    by_qname: dict[str, FunctionEntry] = field(default_factory=dict)
    by_name: dict[str, list[FunctionEntry]] = field(default_factory=dict)


# ── File-path → module name ─────────────────────────────────────────


def _file_path_to_module(file_path: str) -> str:
    """Convert a repo-relative file path to a dotted module name."""
    fp = file_path.replace("\\", "/")
    if fp.endswith("/__init__.py"):
        fp = fp[: -len("/__init__.py")]
    elif fp.endswith(".py"):
        fp = fp[: -len(".py")]
    return fp.replace("/", ".")


# ── Phase 5.1 — Route Index ─────────────────────────────────────────


def _extract_decorator_route(
    decorator: ast.expr,
) -> tuple[str, str] | None:
    """Extract (HTTP method, path) from a FastAPI-style decorator.

    Handles patterns like ``@app.post("/orders")``, ``@router.get("/items/{id}")``.
    Returns ``None`` if the decorator is not a recognised route decorator.
    """
    if not isinstance(decorator, ast.Call):
        return None

    func = decorator.func
    # Expect ``app.get``, ``router.post``, etc.
    if not isinstance(func, ast.Attribute):
        return None

    method = func.attr.lower()
    if method not in _HTTP_METHODS:
        return None

    # First positional argument is the path
    if not decorator.args:
        return None

    path_arg = decorator.args[0]
    if isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str):
        return method.upper(), path_arg.value

    return None


def _extract_add_api_route(node: ast.Expr) -> tuple[str, str, str] | None:
    """Detect ``app.add_api_route("/path", handler, methods=["POST"])``."""
    if not isinstance(node.value, ast.Call):
        return None
    call = node.value
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "add_api_route"):
        return None

    # args[0] = path, args[1] = handler
    if len(call.args) < 2:
        return None

    path_node = call.args[0]
    handler_node = call.args[1]

    if not (isinstance(path_node, ast.Constant) and isinstance(path_node.value, str)):
        return None

    handler_name = _safe_unparse(handler_node)
    path = path_node.value

    # Try to extract method from ``methods=`` keyword
    method = "GET"
    for kw in call.keywords:
        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
            for elt in kw.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    method = elt.value.upper()
                    break

    return method, path, handler_name


def _find_router_prefix(tree: ast.Module) -> str:
    """Best-effort extraction of an ``APIRouter(prefix="/…")`` prefix.

    Scans top-level assignments for patterns like:
      ``router = APIRouter(prefix="/v1/items")``
    Returns the prefix string, or ``""`` if not found.
    """
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        call = node.value
        callee = _safe_unparse(call.func)
        if "APIRouter" not in callee:
            continue
        for kw in call.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value
    return ""


def build_route_index(
    repo_root: str,
    target_files: list[str],
    sources: dict[str, str],
    trees: dict[str, ast.Module],
) -> dict[str, RouteEntry]:
    """Build an index mapping ``"METHOD /path"`` → :class:`RouteEntry`.

    Scans all *target_files* for FastAPI-style route decorators and
    ``add_api_route`` calls.
    """
    index: dict[str, RouteEntry] = {}

    for rel_path in target_files:
        tree = trees.get(rel_path)
        if tree is None:
            continue

        module_name = _file_path_to_module(rel_path)
        prefix = _find_router_prefix(tree)

        for node in ast.iter_child_nodes(tree):
            # Decorated function definitions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    result = _extract_decorator_route(dec)
                    if result is None:
                        continue
                    method, path = result
                    full_path = prefix + path if prefix else path
                    key = f"{method} {full_path}"
                    qname = f"{module_name}.{node.name}"
                    end_line = getattr(node, "end_lineno", node.lineno) or node.lineno
                    index[key] = RouteEntry(
                        method=method,
                        path=full_path,
                        handler_name=node.name,
                        handler_qname=qname,
                        file=rel_path,
                        line=node.lineno,
                        end_line=end_line,
                        col=node.col_offset,
                    )

            # ``app.add_api_route(...)`` at module level
            if isinstance(node, ast.Expr):
                result3 = _extract_add_api_route(node)
                if result3 is None:
                    continue
                method, path, handler_name = result3
                full_path = prefix + path if prefix else path
                key = f"{method} {full_path}"
                # Try to find the handler function in the same file
                handler_line = node.lineno
                handler_end_line = handler_line
                handler_col = node.col_offset
                for child in ast.iter_child_nodes(tree):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if child.name == handler_name:
                            handler_line = child.lineno
                            handler_end_line = getattr(child, "end_lineno", child.lineno) or child.lineno
                            handler_col = child.col_offset
                            break
                qname = f"{module_name}.{handler_name}"
                index[key] = RouteEntry(
                    method=method,
                    path=full_path,
                    handler_name=handler_name,
                    handler_qname=qname,
                    file=rel_path,
                    line=handler_line,
                    end_line=handler_end_line,
                    col=handler_col,
                )

    return index


# ── Phase 5.2 — Pydantic Model Index ────────────────────────────────


_BASEMODEL_NAMES = frozenset({
    "BaseModel", "pydantic.BaseModel", "BaseSettings",
    "pydantic.BaseSettings",
})


def _is_basemodel_subclass(node: ast.ClassDef, class_bases_map: dict[str, list[str]]) -> bool:
    """Check if *node* transitively inherits from ``BaseModel`` (or similar).

    Uses *class_bases_map* (class_name → list of base class names) to walk the
    inheritance chain so that indirect subclasses such as
    ``OrderRequest(BaseRequest)`` where ``BaseRequest(BaseModel)`` are detected.
    A *visited* set prevents infinite loops from circular inheritance.
    """
    visited: set[str] = set()
    queue = [_safe_unparse(b) for b in node.bases]
    while queue:
        base = queue.pop()
        if base in _BASEMODEL_NAMES or base.endswith("BaseModel"):
            return True
        if base in visited:
            continue
        visited.add(base)
        if base in class_bases_map:
            queue.extend(class_bases_map[base])
    return False


def _extract_field_alias(value_node: ast.expr) -> str | None:
    """If *value_node* is ``Field(alias="...")``, return the alias string."""
    if not isinstance(value_node, ast.Call):
        return None
    callee = _safe_unparse(value_node.func)
    if callee not in ("Field", "pydantic.Field"):
        return None
    for kw in value_node.keywords:
        if kw.arg == "alias" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def _has_default_value(stmt: ast.AnnAssign) -> bool:
    """Return whether an annotated assignment has a default value."""
    if stmt.value is None:
        return False
    # ``Field(...)`` without ``default=`` is *not* treated as having a default
    if isinstance(stmt.value, ast.Call):
        callee = _safe_unparse(stmt.value.func)
        if callee in ("Field", "pydantic.Field"):
            for kw in stmt.value.keywords:
                if kw.arg in ("default", "default_factory"):
                    return True
            # If first positional arg exists → it's the default
            if stmt.value.args:
                # Ellipsis (``...``) means *required*
                first = stmt.value.args[0]
                if isinstance(first, ast.Constant) and first.value is ...:
                    return False
                return True
            return False
    return True


def _extract_validator_fields(decorator: ast.expr) -> tuple[list[str], str]:
    """Extract field names from ``@validator("f1", "f2")`` / ``@field_validator(...)``
    and return ``(field_names, kind)``."""
    if not isinstance(decorator, ast.Call):
        # Bare ``@model_validator`` or similar
        name = _safe_unparse(decorator)
        if "model_validator" in name:
            return ["__all__"], "pydantic_validator"
        return [], "pydantic_validator"

    callee = _safe_unparse(decorator.func)
    fields: list[str] = []
    for arg in decorator.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            fields.append(arg.value)

    if "model_validator" in callee:
        return fields or ["__all__"], "pydantic_validator"

    return fields, "pydantic_validator"


def _field_constraint_summary(value_node: ast.expr) -> str | None:
    """Return a short summary of ``Field(ge=0, le=100)``-style constraints."""
    if not isinstance(value_node, ast.Call):
        return None
    callee = _safe_unparse(value_node.func)
    if callee not in ("Field", "pydantic.Field"):
        return None
    constraint_kws = {"ge", "gt", "le", "lt", "min_length", "max_length",
                      "regex", "pattern", "multiple_of", "strict"}
    parts: list[str] = []
    for kw in value_node.keywords:
        if kw.arg in constraint_kws:
            parts.append(f"{kw.arg}={_safe_unparse(kw.value)}")
    return ", ".join(parts) if parts else None


def build_model_index(
    repo_root: str,
    target_files: list[str],
    sources: dict[str, str],
    trees: dict[str, ast.Module],
) -> dict[str, PydanticModelEntry]:
    """Build an index mapping ``ModelName`` → :class:`PydanticModelEntry`.

    Scans for ``BaseModel`` subclasses, collects their fields, aliases,
    and validators.
    """
    index: dict[str, PydanticModelEntry] = {}

    # Build a mapping of class_name → base_class_names from ALL parsed
    # ClassDef nodes so that _is_basemodel_subclass can resolve transitive
    # inheritance (e.g. OrderRequest → BaseRequest → BaseModel).
    class_bases_map: dict[str, list[str]] = {}
    for rel_path in target_files:
        tree = trees.get(rel_path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_bases_map[node.name] = [_safe_unparse(b) for b in node.bases]

    for rel_path in target_files:
        tree = trees.get(rel_path)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not _is_basemodel_subclass(node, class_bases_map):
                continue

            end_line = getattr(node, "end_lineno", node.lineno) or node.lineno
            bases = [_safe_unparse(b) for b in node.bases]
            entry = PydanticModelEntry(
                class_name=node.name,
                file=rel_path,
                line=node.lineno,
                end_line=end_line,
                col=node.col_offset,
                bases=bases,
            )

            # Extract fields (annotated assignments)
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    field_name = stmt.target.id
                    ann_text = _safe_unparse(stmt.annotation)
                    alias = _extract_field_alias(stmt.value) if stmt.value else None
                    has_default = _has_default_value(stmt)
                    entry.fields[field_name] = PydanticField(
                        name=field_name,
                        annotation=ann_text,
                        alias=alias,
                        has_default=has_default,
                        line=stmt.lineno,
                        col=stmt.col_offset,
                    )

                    # Check for field-level constraints (emit as validator)
                    if stmt.value is not None:
                        constraint = _field_constraint_summary(stmt.value)
                        if constraint:
                            entry.validators.append(PydanticValidator(
                                name=f"{field_name}_constraint",
                                target_fields=[field_name],
                                kind="pydantic_field_constraint",
                                line=stmt.lineno,
                                col=stmt.col_offset,
                                rule_summary=constraint,
                            ))

            # Extract validators (@validator, @field_validator, @model_validator)
            for stmt in node.body:
                if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in stmt.decorator_list:
                    dec_text = _safe_unparse(dec)
                    if not any(kw in dec_text for kw in ("validator", "field_validator", "model_validator")):
                        continue
                    target_fields, kind = _extract_validator_fields(dec)
                    doc = ast.get_docstring(stmt) or ""
                    rule_summary = doc[:120] if doc else f"validator {stmt.name}"
                    entry.validators.append(PydanticValidator(
                        name=stmt.name,
                        target_fields=target_fields,
                        kind=kind,
                        line=stmt.lineno,
                        col=stmt.col_offset,
                        rule_summary=rule_summary,
                    ))

            index[node.name] = entry

    return index


# ── Function index (for inter-procedural tracing) ───────────────────


def _build_function_index(
    target_files: list[str],
    trees: dict[str, ast.Module],
) -> FunctionIndex:
    """Build :class:`FunctionIndex` for call-graph expansion."""
    index = FunctionIndex()

    for rel_path in target_files:
        tree = trees.get(rel_path)
        if tree is None:
            continue
        module_name = _file_path_to_module(rel_path)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            end_line = getattr(node, "end_lineno", node.lineno) or node.lineno
            qname = f"{module_name}.{node.name}"
            entry = FunctionEntry(
                name=node.name,
                qname=qname,
                file=rel_path,
                line=node.lineno,
                end_line=end_line,
                col=node.col_offset,
                node=node,
            )
            index.by_name.setdefault(node.name, []).append(entry)
            if qname not in index.by_qname:
                index.by_qname[qname] = entry

    return index


def _resolve_callee_entry(
    callee_name: str,
    caller_file: str,
    caller_qname: str,
    func_index: FunctionIndex,
) -> FunctionEntry | None:
    """Resolve a callee to a concrete function entry, if unambiguous."""
    direct = func_index.by_qname.get(callee_name)
    if direct is not None:
        return direct

    short_name = callee_name.rsplit(".", 1)[-1]
    candidates = func_index.by_name.get(short_name, [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    same_file = [c for c in candidates if c.file == caller_file]
    if len(same_file) == 1:
        return same_file[0]

    caller_module = caller_qname.rsplit(".", 1)[0] if "." in caller_qname else ""
    same_module = [
        c for c in candidates
        if c.qname.rsplit(".", 1)[0] == caller_module
    ]
    if len(same_module) == 1:
        return same_module[0]

    return None


# ── Phase 5.3 — Field Read/Write Site Detection ─────────────────────


def _matches_field(attr_name: str, field_name: str, model_name: str | None,
                   model_index: dict[str, PydanticModelEntry]) -> bool:
    """Check whether *attr_name* matches the target *field_name*.

    Also checks aliases when *model_name* is known.
    """
    if attr_name == field_name:
        return True

    # Check aliases
    if model_name and model_name in model_index:
        model = model_index[model_name]
        for f in model.fields.values():
            if f.name == field_name and f.alias == attr_name:
                return True

    return False


def _scan_function_body(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    field_name: str,
    model_name: str | None,
    file: str,
    source_lines: list[str],
    enclosing_qname: str,
    enclosing_line: int,
    model_index: dict[str, PydanticModelEntry],
    options: Tool2Options,
    field_path: str,
) -> tuple[list[ReadWriteSite], list[ReadWriteSite], list[Transform]]:
    """Scan a function body for field read/write sites and transforms.

    Returns ``(read_sites, write_sites, transforms)``.
    """
    reads: list[ReadWriteSite] = []
    writes: list[ReadWriteSite] = []
    transforms: list[Transform] = []

    enclosing_symbol_id = _compute_symbol_id(enclosing_qname, file, enclosing_line)

    for node in ast.walk(func_node):
        # ── ``obj.field_name`` (attribute access) ────────────────
        if isinstance(node, ast.Attribute):
            if not _matches_field(node.attr, field_name, model_name, model_index):
                continue

            line = node.lineno
            col = node.col_offset
            end_line = getattr(node, "end_lineno", line) or line
            end_col = getattr(node, "end_col_offset", col) or col
            snippet = _snippet_from_lines(source_lines, line, line)
            location = _loc_from_lines(file, line, col, end_line, end_col)

            # Determine if this is a write (target of assignment)
            is_write = _is_write_target(node, func_node)

            site = ReadWriteSite(
                site_id=_compute_site_id(field_path, enclosing_qname, file, line, col, "attribute"),
                field_path=field_path,
                location=location,
                enclosing_symbol_id=enclosing_symbol_id,
                access_pattern="attribute",
                breakage=Breakage(
                    if_removed=True,
                    if_renamed=True,
                    if_type_changed=None,
                ),
                confidence="high",
                evidence_snippet=snippet.strip(),
            )

            if is_write and options.include_writes:
                writes.append(site)
            elif not is_write:
                reads.append(site)

        # ── ``payload["field_name"]`` (dict subscript) ───────────
        if isinstance(node, ast.Subscript):
            key = _extract_string_key(node.slice)
            if key is None or not _matches_field(key, field_name, model_name, model_index):
                continue

            line = node.lineno
            col = node.col_offset
            end_line = getattr(node, "end_lineno", line) or line
            end_col = getattr(node, "end_col_offset", col) or col
            snippet = _snippet_from_lines(source_lines, line, line)
            location = _loc_from_lines(file, line, col, end_line, end_col)

            is_write = _is_write_target(node, func_node)

            site = ReadWriteSite(
                site_id=_compute_site_id(field_path, enclosing_qname, file, line, col, "dict_subscript"),
                field_path=field_path,
                location=location,
                enclosing_symbol_id=enclosing_symbol_id,
                access_pattern="dict_subscript",
                breakage=Breakage(
                    if_removed=True,
                    if_renamed=True,
                    if_type_changed=None,
                ),
                confidence="high",
                evidence_snippet=snippet.strip(),
            )

            if is_write and options.include_writes:
                writes.append(site)
            elif not is_write:
                reads.append(site)

        # ── ``.get("field_name")`` (dict get) ────────────────────
        if isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and node.args):
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                    if _matches_field(first_arg.value, field_name, model_name, model_index):
                        line = node.lineno
                        col = node.col_offset
                        end_line = getattr(node, "end_lineno", line) or line
                        end_col = getattr(node, "end_col_offset", col) or col
                        snippet = _snippet_from_lines(source_lines, line, line)
                        location = _loc_from_lines(file, line, col, end_line, end_col)

                        # .get() with a second arg means there's a default
                        has_default = len(node.args) >= 2
                        reads.append(ReadWriteSite(
                            site_id=_compute_site_id(field_path, enclosing_qname, file, line, col, "dict_get"),
                            field_path=field_path,
                            location=location,
                            enclosing_symbol_id=enclosing_symbol_id,
                            access_pattern="dict_get",
                            breakage=Breakage(
                                if_removed=not has_default,
                                if_renamed=True,
                                if_type_changed=None,
                            ),
                            confidence="high",
                            evidence_snippet=snippet.strip(),
                        ))

            # ── Transform: cast — ``UUID(obj.field)`` ────────────
            callee_text = _safe_unparse(node.func)
            if _is_type_cast_call(callee_text) and node.args:
                for arg in node.args:
                    if _node_references_field(arg, field_name):
                        line = node.lineno
                        col = node.col_offset
                        end_line = getattr(node, "end_lineno", line) or line
                        end_col = getattr(node, "end_col_offset", col) or col
                        location = _loc_from_lines(file, line, col, end_line, end_col)
                        transforms.append(Transform(
                            transform_id=_compute_transform_id("cast", field_path, file, line, col),
                            kind="cast",
                            from_field=field_path,
                            to_field=None,
                            from_type=None,
                            to_type=callee_text,
                            location=location,
                            enclosing_symbol_id=enclosing_symbol_id,
                            confidence="medium",
                        ))
                        break

            # ── Transform: ``.pop("field")`` → rename ───────────
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "pop"
                    and node.args):
                first_arg = node.args[0]
                if (isinstance(first_arg, ast.Constant)
                        and isinstance(first_arg.value, str)
                        and _matches_field(first_arg.value, field_name, model_name, model_index)):
                    line = node.lineno
                    col = node.col_offset
                    end_line = getattr(node, "end_lineno", line) or line
                    end_col = getattr(node, "end_col_offset", col) or col
                    location = _loc_from_lines(file, line, col, end_line, end_col)

                    # Try to determine the renamed-to target
                    to_field = _find_assignment_target(node, func_node)

                    transforms.append(Transform(
                        transform_id=_compute_transform_id("rename", field_path, file, line, col),
                        kind="rename",
                        from_field=field_path,
                        to_field=to_field,
                        location=location,
                        enclosing_symbol_id=enclosing_symbol_id,
                        confidence="medium",
                    ))

            # ── Transform: normalization — ``field.lower()`` etc. ─
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr in _NORMALIZATION_METHODS
                    and _node_references_field(node.func.value, field_name)):
                line = node.lineno
                col = node.col_offset
                end_line = getattr(node, "end_lineno", line) or line
                end_col = getattr(node, "end_col_offset", col) or col
                location = _loc_from_lines(file, line, col, end_line, end_col)
                transforms.append(Transform(
                    transform_id=_compute_transform_id("normalization", field_path, file, line, col),
                    kind="normalization",
                    from_field=field_path,
                    to_field=field_path,
                    location=location,
                    enclosing_symbol_id=enclosing_symbol_id,
                    confidence="medium",
                ))

        # ── Transform: defaulting — ``field or default`` ─────────
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            if any(_node_references_field(v, field_name) for v in node.values):
                line = node.lineno
                col = node.col_offset
                end_line = getattr(node, "end_lineno", line) or line
                end_col = getattr(node, "end_col_offset", col) or col
                location = _loc_from_lines(file, line, col, end_line, end_col)
                transforms.append(Transform(
                    transform_id=_compute_transform_id("defaulting", field_path, file, line, col),
                    kind="defaulting",
                    from_field=field_path,
                    to_field=field_path,
                    location=location,
                    enclosing_symbol_id=enclosing_symbol_id,
                    confidence="medium",
                ))

        # ── Transform: defaulting — ``field if field else default``
        if isinstance(node, ast.IfExp) and _node_references_field(node.test, field_name):
            line = node.lineno
            col = node.col_offset
            end_line = getattr(node, "end_lineno", line) or line
            end_col = getattr(node, "end_col_offset", col) or col
            location = _loc_from_lines(file, line, col, end_line, end_col)
            transforms.append(Transform(
                transform_id=_compute_transform_id("defaulting", field_path, file, line, col),
                kind="defaulting",
                from_field=field_path,
                to_field=field_path,
                location=location,
                enclosing_symbol_id=enclosing_symbol_id,
                confidence="medium",
            ))

    return reads, writes, transforms


def _extract_string_key(slice_node: ast.expr) -> str | None:
    """Extract a string literal from a subscript slice."""
    # Python 3.9+: slice is the value directly
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
        return slice_node.value
    # Older Python: wrapped in ast.Index
    if isinstance(slice_node, ast.Index):  # type: ignore[attr-defined]
        return _extract_string_key(slice_node.value)  # type: ignore[attr-defined]
    return None


def _is_write_target(node: ast.AST, func_node: ast.AST) -> bool:
    """Return ``True`` if *node* appears as the target of an assignment
    anywhere inside *func_node*."""
    for stmt in ast.walk(func_node):
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if _ast_contains(target, node):
                    return True
        elif isinstance(stmt, ast.AugAssign):
            if _ast_contains(stmt.target, node):
                return True
        elif isinstance(stmt, ast.AnnAssign) and stmt.target is not None:
            if _ast_contains(stmt.target, node):
                return True
    return False


def _ast_contains(haystack: ast.AST, needle: ast.AST) -> bool:
    """Shallow check: does *haystack* contain *needle* by line/col identity?"""
    h_line = getattr(haystack, "lineno", -1)
    h_col = getattr(haystack, "col_offset", -1)
    n_line = getattr(needle, "lineno", -2)
    n_col = getattr(needle, "col_offset", -2)
    if h_line == n_line and h_col == n_col:
        return True
    for child in ast.walk(haystack):
        if child is haystack:
            continue
        cl = getattr(child, "lineno", -1)
        cc = getattr(child, "col_offset", -1)
        if cl == n_line and cc == n_col:
            return True
    return False


def _node_references_field(node: ast.AST, field_name: str) -> bool:
    """Check whether *node* (an expression) contains a reference to *field_name*
    — either as an attribute access or a string literal key."""
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr == field_name:
            return True
        if isinstance(child, ast.Constant) and child.value == field_name:
            return True
    return False


_CAST_NAMES = frozenset({
    "int", "float", "str", "bool", "list", "dict", "set", "tuple",
    "UUID", "uuid.UUID", "Decimal", "decimal.Decimal",
    "datetime", "date", "time", "timedelta",
})

_NORMALIZATION_METHODS = frozenset({
    "lower", "upper", "strip", "lstrip", "rstrip",
    "replace", "encode", "decode", "title", "capitalize",
})


def _is_type_cast_call(callee_text: str) -> bool:
    """Return ``True`` if *callee_text* looks like a type cast/constructor."""
    return callee_text in _CAST_NAMES


def _scan_custom_guards(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    field_name: str,
    field_path: str,
    file: str,
    source_lines: list[str],
    enclosing_qname: str,
    enclosing_line: int,
) -> list[Validation]:
    """Detect inline guard patterns like ``if not field: raise ValueError``."""
    validations: list[Validation] = []
    enclosing_symbol_id = _compute_symbol_id(enclosing_qname, file, enclosing_line)

    for node in ast.walk(func_node):
        if not isinstance(node, ast.If):
            continue
        # Check if the test references the field
        if not _node_references_field(node.test, field_name):
            continue
        # Check if the body contains a Raise statement
        has_raise = any(isinstance(stmt, ast.Raise) for stmt in ast.walk(node))
        if not has_raise:
            continue
        line = node.lineno
        col = node.col_offset
        snippet = _snippet_from_lines(source_lines, line, line)
        loc = _loc_from_lines(file, line, col, line, col)
        validations.append(Validation(
            validation_id=_compute_validation_id("custom_guard", field_path, file, line),
            kind="custom_guard",
            field_path=field_path,
            location=loc,
            enclosing_symbol_id=enclosing_symbol_id,
            rule_summary=snippet.strip()[:120],
            confidence="medium",
        ))

    return validations


def _find_assignment_target(call_node: ast.Call, func_node: ast.AST) -> str | None:
    """If *call_node* is on the RHS of an assignment like ``x = obj.pop(...)``,
    return the target name ``"x"``."""
    call_line = call_node.lineno
    call_col = call_node.col_offset
    for stmt in ast.walk(func_node):
        if isinstance(stmt, ast.Assign) and stmt.lineno == call_line:
            if len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                return stmt.targets[0].id
    return None


# ── Inter-procedural call expansion ─────────────────────────────────


def _find_callees_in_function(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """Return a list of callee names invoked inside *func_node*.

    Only captures simple calls (``foo()``, ``self.foo()``, ``module.func()``).
    """
    callees: list[str] = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            text = _safe_unparse(node.func)
            # Strip ``self.`` prefix for method calls
            if text.startswith("self."):
                text = text[5:]
            callees.append(text)
    return callees


def trace_field(
    field_path: str,
    handler_file: str,
    handler_func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    handler_qname: str,
    handler_line: int,
    source_lines: list[str],
    model_index: dict[str, PydanticModelEntry],
    func_index: FunctionIndex,
    sources: dict[str, str],
    options: Tool2Options,
    current_depth: int = 0,
    visited: set[str] | None = None,
) -> tuple[list[ReadWriteSite], list[ReadWriteSite], list[Transform]]:
    """Trace *field_path* through *handler_func_node* and its callees.

    Performs intra-procedural scanning with inter-procedural expansion
    bounded by ``options.max_call_depth``.

    Args:
        field_path: Full dotted field path, e.g. ``"OrderRequest.user_id"``.
        handler_file: Repo-relative path of the file containing the handler.
        handler_func_node: The AST node of the handler function.
        handler_qname: Qualified name of the handler.
        handler_line: Start line of the handler.
        source_lines: Lines of the handler's source file.
        model_index: Pydantic model index.
        func_index: Function index for callee lookup.
        sources: Mapping of file path → source text.
        options: Tool2 options.
        current_depth: Current call-graph depth (0 = handler itself).
        visited: Set of already-visited function qualified names (cycle guard).

    Returns:
        ``(read_sites, write_sites, transforms)``
    """
    if visited is None:
        visited = set()

    # Split field_path
    parts = field_path.rsplit(".", 1)
    model_name = parts[0] if len(parts) == 2 else None
    field_name = parts[-1]

    all_reads: list[ReadWriteSite] = []
    all_writes: list[ReadWriteSite] = []
    all_transforms: list[Transform] = []

    # Guard against cycles
    if handler_qname in visited:
        return all_reads, all_writes, all_transforms
    visited.add(handler_qname)

    # Intra-procedural scan
    reads, writes, transforms = _scan_function_body(
        func_node=handler_func_node,
        field_name=field_name,
        model_name=model_name,
        file=handler_file,
        source_lines=source_lines,
        enclosing_qname=handler_qname,
        enclosing_line=handler_line,
        model_index=model_index,
        options=options,
        field_path=field_path,
    )
    all_reads.extend(reads)
    all_writes.extend(writes)
    all_transforms.extend(transforms)

    # Inter-procedural expansion
    if current_depth < options.max_call_depth:
        callees = _find_callees_in_function(handler_func_node)
        for callee_name in callees:
            func_entry = _resolve_callee_entry(
                callee_name=callee_name,
                caller_file=handler_file,
                caller_qname=handler_qname,
                func_index=func_index,
            )
            if func_entry is None:
                continue
            if func_entry.qname in visited:
                continue

            # Load source lines for callee's file
            callee_source = sources.get(func_entry.file)
            if callee_source is None:
                continue
            callee_lines = callee_source.splitlines()

            r, w, t = trace_field(
                field_path=field_path,
                handler_file=func_entry.file,
                handler_func_node=func_entry.node,
                handler_qname=func_entry.qname,
                handler_line=func_entry.line,
                source_lines=callee_lines,
                model_index=model_index,
                func_index=func_index,
                sources=sources,
                options=options,
                current_depth=current_depth + 1,
                visited=visited,
            )
            all_reads.extend(r)
            all_writes.extend(w)
            all_transforms.extend(t)

    return all_reads, all_writes, all_transforms


# ── Entry-point resolution ───────────────────────────────────────────


def _resolve_entry_points(
    entry_points: list[str],
    route_index: dict[str, RouteEntry],
    func_index: FunctionIndex,
    sources: dict[str, str],
    trees: dict[str, ast.Module],
) -> tuple[list[EntryPointResolved], list[Tool2Diagnostic],
           list[tuple[str, str, ast.FunctionDef | ast.AsyncFunctionDef, str, int, list[str]]]]:
    """Resolve requested entry points to handler functions.

    Supports two formats:
      - ``route:METHOD /path``  — looks up the route index
      - ``symbol:path/to/file.py:symbol_name``  — direct symbol reference

    Returns:
        ``(resolved_list, diagnostics, handler_tuples)``
        where each handler_tuple is
        ``(file, handler_qname, func_node, handler_name, line, source_lines)``.
    """
    resolved: list[EntryPointResolved] = []
    diagnostics: list[Tool2Diagnostic] = []
    handler_tuples: list[tuple[str, str, ast.FunctionDef | ast.AsyncFunctionDef, str, int, list[str]]] = []

    for ep in entry_points:
        if ep.startswith("route:"):
            route_key = ep[len("route:"):]
            route = route_index.get(route_key)
            if route is None:
                diagnostics.append(Tool2Diagnostic(
                    severity="warning",
                    code="entry_point_unresolved",
                    message=f"Route '{route_key}' not found in codebase",
                ))
                continue

            symbol_id = _compute_symbol_id(route.handler_qname, route.file, route.line)
            location = _loc_from_lines(
                route.file, route.line, route.col, route.end_line, 0,
            )
            resolved.append(EntryPointResolved(
                anchor=ep,
                handler_symbol_id=symbol_id,
                location=location,
                confidence="high",
            ))

            # Find the function AST node
            tree = trees.get(route.file)
            source = sources.get(route.file)
            if tree and source:
                func_node = _find_function_node(tree, route.handler_name, route.line)
                if func_node:
                    handler_tuples.append((
                        route.file,
                        route.handler_qname,
                        func_node,
                        route.handler_name,
                        route.line,
                        source.splitlines(),
                    ))

        elif ep.startswith("symbol:"):
            symbol_ref = ep[len("symbol:"):]
            # Format: "path/to/file.py:symbol_name"
            if ":" in symbol_ref:
                file_part, sym_name = symbol_ref.rsplit(":", 1)
            else:
                # Just a symbol name — search all files
                file_part = None
                sym_name = symbol_ref

            found = False
            if file_part:
                tree = trees.get(file_part)
                source = sources.get(file_part)
                if tree and source:
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if node.name == sym_name:
                                module_name = _file_path_to_module(file_part)
                                qname = f"{module_name}.{sym_name}"
                                line = node.lineno
                                end_line = getattr(node, "end_lineno", line) or line
                                symbol_id = _compute_symbol_id(qname, file_part, line)
                                location = _loc_from_lines(file_part, line, node.col_offset, end_line, 0)
                                resolved.append(EntryPointResolved(
                                    anchor=ep,
                                    handler_symbol_id=symbol_id,
                                    location=location,
                                    confidence="high",
                                ))
                                handler_tuples.append((
                                    file_part, qname, node, sym_name, line,
                                    source.splitlines(),
                                ))
                                found = True
                                break
            else:
                candidates = sorted(
                    func_index.by_name.get(sym_name, []),
                    key=lambda c: (c.file, c.line, c.col),
                )
                if len(candidates) == 1:
                    candidate = candidates[0]
                    source = sources.get(candidate.file)
                    if source:
                        symbol_id = _compute_symbol_id(candidate.qname, candidate.file, candidate.line)
                        location = _loc_from_lines(
                            candidate.file,
                            candidate.line,
                            candidate.col,
                            candidate.end_line,
                            0,
                        )
                        resolved.append(EntryPointResolved(
                            anchor=ep,
                            handler_symbol_id=symbol_id,
                            location=location,
                            confidence="medium",
                        ))
                        handler_tuples.append((
                            candidate.file,
                            candidate.qname,
                            candidate.node,
                            candidate.name,
                            candidate.line,
                            source.splitlines(),
                        ))
                        found = True
                elif len(candidates) > 1:
                    diagnostics.append(Tool2Diagnostic(
                        severity="warning",
                        code="alias_ambiguous",
                        message=(
                            f"Symbol '{sym_name}' is ambiguous across "
                            f"{len(candidates)} files; specify 'symbol:file.py:{sym_name}'"
                        ),
                    ))
                    continue

            if not found:
                diagnostics.append(Tool2Diagnostic(
                    severity="warning",
                    code="entry_point_unresolved",
                    message=f"Symbol '{symbol_ref}' not found in codebase",
                ))
        else:
            diagnostics.append(Tool2Diagnostic(
                severity="warning",
                code="needs_anchor",
                message=f"Entry point '{ep}' has unrecognised format; expected 'route:METHOD /path' or 'symbol:file:name'",
            ))

    return resolved, diagnostics, handler_tuples


def _find_function_node(
    tree: ast.Module,
    func_name: str,
    expected_line: int,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find a function node by name and expected start line."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name and node.lineno == expected_line:
                return node
    # Fallback: match by name only
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return node
    return None


# ── Validation extraction ───────────────────────────────────────────


def _build_validations(
    field_path: str,
    model_index: dict[str, PydanticModelEntry],
) -> list[Validation]:
    """Build validation entries from the Pydantic model index for the
    target *field_path*."""
    parts = field_path.rsplit(".", 1)
    model_name = parts[0] if len(parts) == 2 else None
    field_name = parts[-1]

    validations: list[Validation] = []

    if model_name and model_name in model_index:
        model = model_index[model_name]
        enclosing_symbol_id = _compute_symbol_id(
            model.class_name, model.file, model.line,
        )
        for v in model.validators:
            if field_name in v.target_fields or "__all__" in v.target_fields:
                loc = _loc_from_lines(model.file, v.line, v.col, v.line, v.col)
                validations.append(Validation(
                    validation_id=_compute_validation_id(v.kind, field_path, model.file, v.line),
                    kind=v.kind,  # type: ignore[arg-type]
                    field_path=field_path,
                    location=loc,
                    enclosing_symbol_id=enclosing_symbol_id,
                    rule_summary=v.rule_summary,
                    confidence="high" if v.kind == "pydantic_field_constraint" else "medium",
                ))
    else:
        # If no model name given, search all models for the field
        for mname, model in sorted(model_index.items()):
            if field_name not in model.fields:
                continue
            enclosing_symbol_id = _compute_symbol_id(
                model.class_name, model.file, model.line,
            )
            for v in model.validators:
                if field_name in v.target_fields or "__all__" in v.target_fields:
                    loc = _loc_from_lines(model.file, v.line, v.col, v.line, v.col)
                    validations.append(Validation(
                        validation_id=_compute_validation_id(v.kind, field_path, model.file, v.line),
                        kind=v.kind,  # type: ignore[arg-type]
                        field_path=field_path,
                        location=loc,
                        enclosing_symbol_id=enclosing_symbol_id,
                        rule_summary=v.rule_summary,
                        confidence="low",
                    ))

    return validations


# ── Sorting helpers ──────────────────────────────────────────────────


def _sort_sites(sites: list[ReadWriteSite]) -> list[ReadWriteSite]:
    """Sort sites deterministically by (file, start.line, start.col, site_id)."""
    return sorted(
        sites,
        key=lambda s: (
            s.location.file,
            s.location.range.start.line,
            s.location.range.start.col,
            s.site_id,
        ),
    )


def _sort_validations(vals: list[Validation]) -> list[Validation]:
    """Sort validations deterministically."""
    return sorted(
        vals,
        key=lambda v: (
            v.location.file,
            v.location.range.start.line,
            v.location.range.start.col,
            v.validation_id,
        ),
    )


def _sort_transforms(xforms: list[Transform]) -> list[Transform]:
    """Sort transforms deterministically."""
    return sorted(
        xforms,
        key=lambda t: (
            t.location.file,
            t.location.range.start.line,
            t.location.range.start.col,
            t.transform_id,
        ),
    )


def _sort_diagnostics(diags: list[Tool2Diagnostic]) -> list[Tool2Diagnostic]:
    """Sort diagnostics deterministically."""
    return sorted(
        diags,
        key=lambda d: (
            d.location.file if d.location else "",
            d.location.range.start.line if d.location else 0,
            d.location.range.start.col if d.location else 0,
            d.message,
        ),
    )


# ── Deduplication ────────────────────────────────────────────────────


def _dedup_sites(sites: list[ReadWriteSite]) -> list[ReadWriteSite]:
    """Remove duplicate sites (same site_id)."""
    seen: set[str] = set()
    result: list[ReadWriteSite] = []
    for s in sites:
        if s.site_id not in seen:
            seen.add(s.site_id)
            result.append(s)
    return result


def _dedup_transforms(xforms: list[Transform]) -> list[Transform]:
    """Remove duplicate transforms (same transform_id)."""
    seen: set[str] = set()
    result: list[Transform] = []
    for t in xforms:
        if t.transform_id not in seen:
            seen.add(t.transform_id)
            result.append(t)
    return result


def _dedup_validations(vals: list[Validation]) -> list[Validation]:
    """Remove duplicate validations (same validation_id)."""
    seen: set[str] = set()
    result: list[Validation] = []
    for v in vals:
        if v.validation_id not in seen:
            seen.add(v.validation_id)
            result.append(v)
    return result


# ── Convenience wrappers for testing ─────────────────────────────────


def trace_field_in_function(
    tree: ast.Module,
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    field_name: str,
    file_path: str,
    source_lines: list[str],
    symbol_id: str,
    options: dict | None = None,
) -> dict:
    """Convenience wrapper around :func:`_scan_function_body` for testing.

    Accepts a simplified interface and returns a dict with keys
    ``read_sites``, ``write_sites``, ``transforms`` — each a list of dicts.
    """
    opts = Tool2Options(**(options or {}))
    field_path = field_name  # bare field path
    model_name = None

    reads, writes, transforms = _scan_function_body(
        func_node=func_node,
        field_name=field_name,
        model_name=model_name,
        file=file_path,
        source_lines=source_lines,
        enclosing_qname=symbol_id,
        enclosing_line=func_node.lineno,
        model_index={},
        options=opts,
        field_path=field_path,
    )

    return {
        "read_sites": [r.model_dump(by_alias=True) for r in reads],
        "write_sites": [w.model_dump(by_alias=True) for w in writes],
        "transforms": [t.model_dump(by_alias=True) for t in transforms],
    }


# ── File loading & parsing ───────────────────────────────────────────


def _load_sources(
    repo_root: str,
    target_files: list[str],
) -> tuple[dict[str, str], dict[str, ast.Module], int]:
    """Load and parse all target Python files.

    Returns:
        ``(sources, trees, error_count)`` where *sources* maps repo-relative
        paths to decoded text, *trees* maps paths to parsed ASTs, and
        *error_count* is the number of files that failed to load or parse.
    """
    sources: dict[str, str] = {}
    trees: dict[str, ast.Module] = {}
    errors = 0

    for rel_path in target_files:
        try:
            raw = safe_read_file(repo_root, rel_path)
        except (FileNotFoundError, ValueError):
            errors += 1
            continue

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            errors += 1
            continue

        sources[rel_path] = text
        tree = _safe_parse(text, rel_path)
        if tree is None:
            errors += 1
            continue
        trees[rel_path] = tree

    return sources, trees, errors


# ── Phase 5.4 — Output Assembly (main entry point) ──────────────────


def run_tool2(request: Tool2Request, repo_root: str) -> dict:
    """Execute the full Tool 2 pipeline and return the result as a dict.

    Steps:
      1. Glob all Python files in the repository.
      2. Load & parse every Python file.
      3. Build route index + Pydantic model index + function index.
      4. Resolve requested entry points.
      5. Trace field reads/writes through resolved handlers.
      6. Build validations from the model index.
      7. Sort, deduplicate, and truncate.
      8. Assemble ``Tool2Result``.
      9. Return ``result.model_dump(by_alias=True)``.

    Args:
        request: The ``Tool2Request`` payload.
        repo_root: Absolute path to the repository root.

    Returns:
        A dict suitable for JSON serialisation.
    """
    diagnostics: list[Tool2Diagnostic] = []

    # Step 1 — Glob all Python files
    target_files = glob_python_files(repo_root)

    # Step 2 — Load and parse
    sources, trees, _parse_errors = _load_sources(repo_root, target_files)

    files_scanned = len(sources)

    # Step 3 — Build indices
    route_index = build_route_index(repo_root, target_files, sources, trees)
    model_index = build_model_index(repo_root, target_files, sources, trees)
    func_index = _build_function_index(target_files, trees)

    # Step 4 — Resolve entry points
    resolved, ep_diags, handler_tuples = _resolve_entry_points(
        request.entry_points, route_index, func_index, sources, trees,
    )
    diagnostics.extend(ep_diags)

    if not handler_tuples and not resolved:
        # Nothing resolved — emit diagnostic
        diagnostics.append(Tool2Diagnostic(
            severity="error",
            code="entry_point_unresolved",
            message="No entry points could be resolved; cannot trace data lineage",
        ))

    # Step 5 — Trace field through each resolved handler
    all_reads: list[ReadWriteSite] = []
    all_writes: list[ReadWriteSite] = []
    all_transforms: list[Transform] = []

    for handler_file, handler_qname, func_node, handler_name, handler_line, handler_lines in handler_tuples:
        r, w, t = trace_field(
            field_path=request.field_path,
            handler_file=handler_file,
            handler_func_node=func_node,
            handler_qname=handler_qname,
            handler_line=handler_line,
            source_lines=handler_lines,
            model_index=model_index,
            func_index=func_index,
            sources=sources,
            options=request.options,
        )
        all_reads.extend(r)
        all_writes.extend(w)
        all_transforms.extend(t)

    # Step 5b — Emit model_field sites for Pydantic field definitions
    fp_parts = request.field_path.rsplit(".", 1)
    _fp_model = fp_parts[0] if len(fp_parts) == 2 else None
    _fp_field = fp_parts[-1]

    if _fp_model and _fp_model in model_index:
        _model = model_index[_fp_model]
        if _fp_field in _model.fields:
            pf = _model.fields[_fp_field]
            _src = sources.get(_model.file)
            _snippet = ""
            if _src:
                _snippet = _snippet_from_lines(_src.splitlines(), pf.line, pf.line).strip()
            loc = _loc_from_lines(_model.file, pf.line, pf.col, pf.line, pf.col)
            encl_sym = _compute_symbol_id(_model.class_name, _model.file, _model.line)
            all_reads.append(ReadWriteSite(
                site_id=_compute_site_id(request.field_path, _model.class_name, _model.file, pf.line, pf.col, "model_field"),
                field_path=request.field_path,
                location=loc,
                enclosing_symbol_id=encl_sym,
                access_pattern="model_field",
                breakage=Breakage(if_removed=True, if_renamed=True, if_type_changed=True),
                confidence="high",
                evidence_snippet=_snippet or None,
            ))

    # Step 5c — Emit serializer sites for @field_serializer / @serializer methods
    if _fp_model and _fp_model in model_index:
        _model = model_index[_fp_model]
        _tree = trees.get(_model.file)
        _src = sources.get(_model.file)
        if _tree and _src:
            _src_lines = _src.splitlines()
            for cls_node in ast.walk(_tree):
                if not (isinstance(cls_node, ast.ClassDef) and cls_node.name == _fp_model):
                    continue
                for stmt in cls_node.body:
                    if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    _is_ser = False
                    for dec in stmt.decorator_list:
                        dec_text = _safe_unparse(dec)
                        if any(kw in dec_text for kw in ("field_serializer", "serializer", "model_serializer")):
                            # Check if this serializer targets our field
                            if isinstance(dec, ast.Call):
                                for arg in dec.args:
                                    if isinstance(arg, ast.Constant) and arg.value == _fp_field:
                                        _is_ser = True
                                        break
                            # model_serializer applies to all fields
                            if "model_serializer" in dec_text:
                                _is_ser = True
                            break
                    if _is_ser:
                        line = stmt.lineno
                        col = stmt.col_offset
                        snippet = _snippet_from_lines(_src_lines, line, line).strip()
                        encl_sym = _compute_symbol_id(_model.class_name, _model.file, _model.line)
                        loc = _loc_from_lines(_model.file, line, col, line, col)
                        all_reads.append(ReadWriteSite(
                            site_id=_compute_site_id(request.field_path, _model.class_name, _model.file, line, col, "serializer"),
                            field_path=request.field_path,
                            location=loc,
                            enclosing_symbol_id=encl_sym,
                            access_pattern="serializer",
                            breakage=Breakage(if_removed=True, if_renamed=True, if_type_changed=None),
                            confidence="high",
                            evidence_snippet=snippet or None,
                        ))

    # Step 5d — Scan handlers for custom_guard validations
    custom_guard_vals: list[Validation] = []
    for handler_file, handler_qname, func_node, handler_name, handler_line, handler_lines in handler_tuples:
        custom_guard_vals.extend(_scan_custom_guards(
            func_node=func_node,
            field_name=_fp_field,
            field_path=request.field_path,
            file=handler_file,
            source_lines=handler_lines,
            enclosing_qname=handler_qname,
            enclosing_line=handler_line,
        ))

    # Step 5e — Check for alias_ambiguous diagnostics
    _alias_seen: dict[str, list[str]] = {}  # alias → list of field qualified names
    for mname, mentry in model_index.items():
        for fname, fld in mentry.fields.items():
            if fld.alias:
                _alias_seen.setdefault(fld.alias, []).append(f"{mname}.{fname}")
    for alias_val, field_list in _alias_seen.items():
        if len(field_list) > 1:
            diagnostics.append(Tool2Diagnostic(
                severity="warning",
                code="alias_ambiguous",
                message=f"Alias '{alias_val}' is shared by multiple fields: {', '.join(sorted(field_list))}",
                location=None,
            ))

    # Step 6 — Build validations
    validations = _build_validations(request.field_path, model_index)
    validations.extend(custom_guard_vals)

    # Step 7a — Filter by direction
    if request.options.direction == "request":
        all_writes = []
    elif request.options.direction == "response":
        all_reads = []
    # "both" keeps everything

    # Step 7b — Deduplicate
    all_reads = _dedup_sites(all_reads)
    all_writes = _dedup_sites(all_writes)
    all_transforms = _dedup_transforms(all_transforms)
    validations = _dedup_validations(validations)

    # Step 7c — Sort
    all_reads = _sort_sites(all_reads)
    all_writes = _sort_sites(all_writes)
    validations = _sort_validations(validations)
    all_transforms = _sort_transforms(all_transforms)
    diagnostics = _sort_diagnostics(diagnostics)

    # Step 7d — Truncate
    total_sites = len(all_reads) + len(all_writes)
    truncated = total_sites > request.options.max_sites
    if truncated:
        # Proportional truncation
        max_s = request.options.max_sites
        if all_reads and all_writes:
            read_budget = max(1, int(max_s * len(all_reads) / total_sites))
            write_budget = max_s - read_budget
            all_reads = all_reads[:read_budget]
            all_writes = all_writes[:write_budget]
        else:
            all_reads = all_reads[:max_s]
            all_writes = all_writes[:max_s]

        diagnostics.append(Tool2Diagnostic(
            severity="info",
            code="lineage_truncated",
            message=f"Output truncated to {request.options.max_sites} sites (total found: {total_sites})",
        ))

    sites_emitted = len(all_reads) + len(all_writes)

    # Step 8 — Assemble result
    stats = Tool2Stats(
        files_scanned=files_scanned,
        sites_emitted=sites_emitted,
        truncated=truncated,
    )

    result = Tool2Result(
        changed_field=request.field_path,
        entry_points_resolved=resolved,
        read_sites=all_reads,
        write_sites=all_writes,
        validations=validations,
        transforms=all_transforms,
        diagnostics=diagnostics,
        stats=stats,
    )

    return result.model_dump(by_alias=True)
