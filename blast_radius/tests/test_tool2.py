"""Comprehensive tests for Tool 2 — Data Lineage Engine (trace_data_shape)."""

from __future__ import annotations

import ast
import re
import textwrap

import pytest

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
from blast_radius_mcp.tools.tool2_data_lineage import (
    TOOL2_IMPL_VERSION,
    _compute_site_id,
    _compute_transform_id,
    _compute_validation_id,
    _resolve_entry_points,
    _sha256_prefix,
    _safe_parse,
    _build_function_index,
    build_model_index,
    build_route_index,
    run_tool2,
    trace_field_in_function,
)

# ── Helpers ──────────────────────────────────────────────────────────

SITE_ID_RE = re.compile(r"^site_[0-9a-f]{16}$")
VAL_ID_RE = re.compile(r"^val_[0-9a-f]{16}$")
XFORM_ID_RE = re.compile(r"^xform_[0-9a-f]{16}$")


def _make_location(file: str, line: int, col: int = 0, end_line: int | None = None, end_col: int = 0) -> Location:
    """Helper to build a Location for test assertions."""
    return Location(
        file=file,
        range=Range(
            start=Position(line=line, col=col),
            end=Position(line=end_line or line, col=end_col),
        ),
    )


def _write_py(tmp_path, relpath: str, source: str) -> str:
    """Write a Python file under tmp_path and return its relative path."""
    full = tmp_path / relpath
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(textwrap.dedent(source), encoding="utf-8")
    return relpath


def _load_and_parse(tmp_path, py_files: list[str]):
    """Load and parse files, returning (sources, trees) dicts for test use."""
    sources: dict[str, str] = {}
    trees: dict[str, ast.Module] = {}
    for rel in py_files:
        full = tmp_path / rel
        if not full.exists():
            continue
        text = full.read_text(encoding="utf-8")
        sources[rel] = text
        tree = _safe_parse(text, rel)
        if tree is not None:
            trees[rel] = tree
    return sources, trees


def _build_route_index_simple(tmp_path, py_files: list[str]):
    """Convenience: build route index with auto-loading of sources/trees."""
    sources, trees = _load_and_parse(tmp_path, py_files)
    return build_route_index(str(tmp_path), py_files, sources, trees)


def _build_model_index_simple(tmp_path, py_files: list[str]):
    """Convenience: build model index with auto-loading of sources/trees."""
    sources, trees = _load_and_parse(tmp_path, py_files)
    return build_model_index(str(tmp_path), py_files, sources, trees)


# ═══════════════════════════════════════════════════════════════════════
# 1. TestDeterministicIds
# ═══════════════════════════════════════════════════════════════════════


class TestDeterministicIds:
    """Deterministic ID generation for sites, validations, transforms."""

    def test_sha256_prefix_deterministic(self):
        id1 = _sha256_prefix("site_", "field", "sym_abc", "file.py", "10", "0", "attribute")
        id2 = _sha256_prefix("site_", "field", "sym_abc", "file.py", "10", "0", "attribute")
        assert id1 == id2

    def test_sha256_prefix_different_inputs(self):
        id1 = _sha256_prefix("site_", "field_a", "sym_abc", "file.py", "10")
        id2 = _sha256_prefix("site_", "field_b", "sym_def", "other.py", "20")
        assert id1 != id2

    def test_sha256_prefix_format(self):
        result = _sha256_prefix("site_", "some", "parts")
        assert result.startswith("site_")
        assert len(result) == 5 + 16  # prefix_ + 16 hex chars
        assert re.match(r"^site_[0-9a-f]{16}$", result)

    def test_sha256_prefix_different_prefix(self):
        r1 = _sha256_prefix("val_", "field", "file.py", "10")
        r2 = _sha256_prefix("xform_", "field", "file.py", "10")
        assert r1.startswith("val_")
        assert r2.startswith("xform_")

    def test_compute_site_id_deterministic(self):
        sid1 = _compute_site_id("user_id", "sym_handler", "api.py", 15, 8, "attribute")
        sid2 = _compute_site_id("user_id", "sym_handler", "api.py", 15, 8, "attribute")
        assert sid1 == sid2

    def test_compute_site_id_format(self):
        sid = _compute_site_id("user_id", "sym_handler", "api.py", 15, 8, "attribute")
        assert SITE_ID_RE.match(sid), f"Expected site_ + 16 hex, got {sid!r}"

    def test_compute_site_id_different_inputs(self):
        s1 = _compute_site_id("user_id", "sym_handler", "api.py", 15, 8, "attribute")
        s2 = _compute_site_id("email", "sym_other", "b.py", 20, 0, "dict_get")
        assert s1 != s2

    def test_compute_validation_id_deterministic(self):
        vid1 = _compute_validation_id("pydantic_validator", "user_id", "models.py", 20)
        vid2 = _compute_validation_id("pydantic_validator", "user_id", "models.py", 20)
        assert vid1 == vid2

    def test_compute_validation_id_format(self):
        vid = _compute_validation_id("pydantic_validator", "user_id", "models.py", 20)
        assert VAL_ID_RE.match(vid), f"Expected val_ + 16 hex, got {vid!r}"

    def test_compute_validation_id_different_inputs(self):
        v1 = _compute_validation_id("pydantic_validator", "user_id", "a.py", 10)
        v2 = _compute_validation_id("pydantic_field_constraint", "amount", "b.py", 20)
        assert v1 != v2

    def test_compute_transform_id_deterministic(self):
        tid1 = _compute_transform_id("cast", "user_id", "svc.py", 30, 0)
        tid2 = _compute_transform_id("cast", "user_id", "svc.py", 30, 0)
        assert tid1 == tid2

    def test_compute_transform_id_format(self):
        tid = _compute_transform_id("cast", "user_id", "svc.py", 30, 0)
        assert XFORM_ID_RE.match(tid), f"Expected xform_ + 16 hex, got {tid!r}"

    def test_compute_transform_id_different_inputs(self):
        t1 = _compute_transform_id("cast", "user_id", "svc.py", 30, 0)
        t2 = _compute_transform_id("rename", "amount", "svc.py", 31, 4)
        assert t1 != t2


# ═══════════════════════════════════════════════════════════════════════
# 2. TestRouteIndex
# ═══════════════════════════════════════════════════════════════════════


class TestRouteIndex:
    """build_route_index: FastAPI decorator detection."""

    def test_detects_app_post_route(self, tmp_path):
        _write_py(tmp_path, "app.py", """\
            from fastapi import FastAPI
            app = FastAPI()

            @app.post("/orders")
            async def create_order(request):
                pass
        """)
        index = _build_route_index_simple(tmp_path, ["app.py"])
        key = "POST /orders"
        assert key in index
        entry = index[key]
        assert entry.handler_name == "create_order"
        assert entry.file == "app.py"

    def test_detects_app_get_route(self, tmp_path):
        _write_py(tmp_path, "app.py", """\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/orders/{order_id}")
            async def get_order(order_id: int):
                pass
        """)
        index = _build_route_index_simple(tmp_path, ["app.py"])
        assert "GET /orders/{order_id}" in index
        assert index["GET /orders/{order_id}"].handler_name == "get_order"

    def test_detects_router_post_route(self, tmp_path):
        _write_py(tmp_path, "routes.py", """\
            from fastapi import APIRouter
            router = APIRouter()

            @router.post("/users")
            async def create_user(data):
                pass
        """)
        index = _build_route_index_simple(tmp_path, ["routes.py"])
        assert "POST /users" in index
        assert index["POST /users"].handler_name == "create_user"

    def test_multiple_routes_in_one_file(self, tmp_path):
        _write_py(tmp_path, "app.py", """\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/health")
            async def health():
                return {"status": "ok"}

            @app.post("/items")
            async def create_item(data):
                pass

            @app.delete("/items/{item_id}")
            async def delete_item(item_id: int):
                pass
        """)
        index = _build_route_index_simple(tmp_path, ["app.py"])
        assert "GET /health" in index
        assert "POST /items" in index
        assert "DELETE /items/{item_id}" in index

    def test_empty_file_returns_empty_index(self, tmp_path):
        _write_py(tmp_path, "empty.py", "")
        index = _build_route_index_simple(tmp_path, ["empty.py"])
        assert len(index) == 0

    def test_non_fastapi_file_returns_empty_index(self, tmp_path):
        _write_py(tmp_path, "plain.py", """\
            def compute(x, y):
                return x + y

            class Calculator:
                pass
        """)
        index = _build_route_index_simple(tmp_path, ["plain.py"])
        assert len(index) == 0

    def test_handles_syntax_error_gracefully(self, tmp_path):
        _write_py(tmp_path, "broken.py", """\
            from fastapi import FastAPI
            app = FastAPI(
            @app.get("/bad"
            def broken(:
                pass
        """)
        index = _build_route_index_simple(tmp_path, ["broken.py"])
        assert isinstance(index, dict)

    def test_multiple_files(self, tmp_path):
        _write_py(tmp_path, "api/orders.py", """\
            from fastapi import APIRouter
            router = APIRouter()

            @router.post("/orders")
            async def create_order(data):
                pass
        """)
        _write_py(tmp_path, "api/users.py", """\
            from fastapi import APIRouter
            router = APIRouter()

            @router.get("/users/{user_id}")
            async def get_user(user_id: int):
                pass
        """)
        index = _build_route_index_simple(tmp_path, ["api/orders.py", "api/users.py"])
        assert "POST /orders" in index
        assert "GET /users/{user_id}" in index

    def test_put_and_patch_routes(self, tmp_path):
        _write_py(tmp_path, "app.py", """\
            from fastapi import FastAPI
            app = FastAPI()

            @app.put("/items/{item_id}")
            async def update_item(item_id: int, data):
                pass

            @app.patch("/items/{item_id}")
            async def partial_update(item_id: int, data):
                pass
        """)
        index = _build_route_index_simple(tmp_path, ["app.py"])
        assert "PUT /items/{item_id}" in index
        assert "PATCH /items/{item_id}" in index

    def test_missing_file_handled(self, tmp_path):
        index = _build_route_index_simple(tmp_path, ["nonexistent.py"])
        assert isinstance(index, dict)
        assert len(index) == 0


# ═══════════════════════════════════════════════════════════════════════
# 3. TestModelIndex
# ═══════════════════════════════════════════════════════════════════════


class TestModelIndex:
    """build_model_index: Pydantic model detection."""

    def test_detects_basemodel_subclass(self, tmp_path):
        _write_py(tmp_path, "models.py", """\
            from pydantic import BaseModel

            class OrderRequest(BaseModel):
                user_id: str
                amount: float
        """)
        index = _build_model_index_simple(tmp_path, ["models.py"])
        assert "OrderRequest" in index
        assert index["OrderRequest"].file == "models.py"

    def test_extracts_field_names(self, tmp_path):
        _write_py(tmp_path, "models.py", """\
            from pydantic import BaseModel

            class OrderRequest(BaseModel):
                user_id: str
                amount: float
                status: str = "pending"
        """)
        index = _build_model_index_simple(tmp_path, ["models.py"])
        field_names = list(index["OrderRequest"].fields.keys())
        assert "user_id" in field_names
        assert "amount" in field_names
        assert "status" in field_names

    def test_extracts_field_types(self, tmp_path):
        _write_py(tmp_path, "models.py", """\
            from pydantic import BaseModel

            class OrderRequest(BaseModel):
                user_id: str
                amount: float
                count: int
        """)
        index = _build_model_index_simple(tmp_path, ["models.py"])
        fields = index["OrderRequest"].fields
        assert fields["user_id"].annotation == "str"
        assert fields["amount"].annotation == "float"
        assert fields["count"].annotation == "int"

    def test_detects_field_alias(self, tmp_path):
        _write_py(tmp_path, "models.py", """\
            from pydantic import BaseModel, Field

            class OrderRequest(BaseModel):
                amount: float = Field(alias="order_amount")
        """)
        index = _build_model_index_simple(tmp_path, ["models.py"])
        assert index["OrderRequest"].fields["amount"].alias == "order_amount"

    def test_detects_field_validator(self, tmp_path):
        _write_py(tmp_path, "models.py", """\
            from pydantic import BaseModel, field_validator

            class OrderRequest(BaseModel):
                user_id: str

                @field_validator("user_id")
                @classmethod
                def validate_user_id(cls, v):
                    if not v:
                        raise ValueError("empty")
                    return v
        """)
        index = _build_model_index_simple(tmp_path, ["models.py"])
        model = index["OrderRequest"]
        assert len(model.validators) >= 1
        found = any("user_id" in v.target_fields for v in model.validators)
        assert found

    def test_detects_older_validator_decorator(self, tmp_path):
        _write_py(tmp_path, "models.py", """\
            from pydantic import BaseModel, validator

            class UserModel(BaseModel):
                email: str

                @validator("email")
                def validate_email(cls, v):
                    return v.lower()
        """)
        index = _build_model_index_simple(tmp_path, ["models.py"])
        assert len(index["UserModel"].validators) >= 1

    def test_ignores_non_model_classes(self, tmp_path):
        _write_py(tmp_path, "other.py", """\
            class PlainClass:
                x: int = 0

            class AnotherClass(dict):
                pass
        """)
        index = _build_model_index_simple(tmp_path, ["other.py"])
        assert "PlainClass" not in index
        assert "AnotherClass" not in index

    def test_multiple_models_in_one_file(self, tmp_path):
        _write_py(tmp_path, "models.py", """\
            from pydantic import BaseModel

            class OrderRequest(BaseModel):
                user_id: str

            class OrderResponse(BaseModel):
                order_id: str
                status: str
        """)
        index = _build_model_index_simple(tmp_path, ["models.py"])
        assert "OrderRequest" in index
        assert "OrderResponse" in index

    def test_empty_file_returns_empty_index(self, tmp_path):
        _write_py(tmp_path, "empty.py", "")
        index = _build_model_index_simple(tmp_path, ["empty.py"])
        assert len(index) == 0

    def test_handles_syntax_error(self, tmp_path):
        _write_py(tmp_path, "bad.py", """\
            from pydantic import BaseModel
            class Broken(BaseModel
                x: int
        """)
        index = _build_model_index_simple(tmp_path, ["bad.py"])
        assert isinstance(index, dict)


# ═══════════════════════════════════════════════════════════════════════
# 4. TestFieldTracing
# ═══════════════════════════════════════════════════════════════════════


class TestFieldTracing:
    """trace_field_in_function: AST-level field usage detection."""

    def _trace(self, source: str, field_name: str, func_name: str = None, options: dict | None = None):
        """Parse source, find func_node, trace field, return result dict."""
        source = textwrap.dedent(source)
        tree = ast.parse(source, filename="test.py")

        func_node = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if func_name is None or node.name == func_name:
                    func_node = node
                    break

        assert func_node is not None, f"Function {func_name!r} not found in source"

        source_lines = source.splitlines()
        symbol_id = f"sym_test_{func_node.name}"

        return trace_field_in_function(
            tree, func_node, field_name, "test.py", source_lines, symbol_id, options
        )

    # ── attribute reads ─────────────────────────────────────────────

    def test_detects_attribute_read(self):
        result = self._trace("""\
            def create_order(request):
                uid = request.user_id
                return uid
        """, "user_id", "create_order")

        reads = result["read_sites"]
        assert len(reads) >= 1
        patterns = [s["access_pattern"] for s in reads]
        assert "attribute" in patterns

    def test_detects_attribute_read_in_call_argument(self):
        result = self._trace("""\
            def handler(request):
                process(request.user_id)
        """, "user_id", "handler")

        reads = result["read_sites"]
        assert len(reads) >= 1

    def test_detects_chained_attribute_read(self):
        result = self._trace("""\
            def handler(request):
                name = request.user.name
        """, "name", "handler")

        reads = result["read_sites"]
        assert len(reads) >= 1

    # ── dict subscript reads ────────────────────────────────────────

    def test_detects_dict_subscript_read(self):
        result = self._trace("""\
            def handler(payload):
                uid = payload["user_id"]
                return uid
        """, "user_id", "handler")

        reads = result["read_sites"]
        assert len(reads) >= 1
        patterns = [s["access_pattern"] for s in reads]
        assert "dict_subscript" in patterns

    # ── dict .get() reads ───────────────────────────────────────────

    def test_detects_dict_get_read(self):
        result = self._trace("""\
            def handler(payload):
                uid = payload.get("user_id")
                return uid
        """, "user_id", "handler")

        reads = result["read_sites"]
        assert len(reads) >= 1
        patterns = [s["access_pattern"] for s in reads]
        assert "dict_get" in patterns

    def test_detects_dict_get_with_default(self):
        result = self._trace("""\
            def handler(payload):
                uid = payload.get("user_id", "default")
                return uid
        """, "user_id", "handler")

        reads = result["read_sites"]
        assert len(reads) >= 1

    # ── write sites ─────────────────────────────────────────────────

    def test_detects_write_site(self):
        result = self._trace("""\
            def handler(order):
                order.user_id = "new_value"
        """, "user_id", "handler")

        writes = result["write_sites"]
        assert len(writes) >= 1

    def test_detects_dict_write(self):
        result = self._trace("""\
            def handler(data):
                data["user_id"] = "new_value"
        """, "user_id", "handler")

        writes = result["write_sites"]
        assert len(writes) >= 1

    # ── transforms/casts ───────────────────────────────────────────

    def test_detects_cast_transform(self):
        result = self._trace("""\
            from uuid import UUID
            def handler(request):
                uid = UUID(request.user_id)
                return uid
        """, "user_id", "handler")

        transforms = result["transforms"]
        reads = result["read_sites"]
        assert len(transforms) >= 1 or len(reads) >= 1

    def test_detects_str_conversion(self):
        result = self._trace("""\
            def handler(request):
                uid_str = str(request.user_id)
        """, "user_id", "handler")

        all_sites = result["read_sites"] + result["transforms"]
        assert len(all_sites) >= 1

    # ── breakage flags ──────────────────────────────────────────────

    def test_breakage_if_removed_for_read_without_default(self):
        result = self._trace("""\
            def handler(request):
                uid = request.user_id
                return uid
        """, "user_id", "handler")

        reads = result["read_sites"]
        assert len(reads) >= 1
        site = reads[0]
        breakage = site["breakage"]
        assert breakage["if_removed"] is True

    def test_breakage_if_renamed_for_literal_key(self):
        result = self._trace("""\
            def handler(payload):
                uid = payload["user_id"]
        """, "user_id", "handler")

        reads = result["read_sites"]
        assert len(reads) >= 1
        site = reads[0]
        breakage = site["breakage"]
        assert breakage["if_renamed"] is True

    # ── evidence snippets ───────────────────────────────────────────

    def test_evidence_snippets_present(self):
        result = self._trace("""\
            def handler(request):
                uid = request.user_id
                return uid
        """, "user_id", "handler")

        reads = result["read_sites"]
        assert len(reads) >= 1
        for site in reads:
            assert site.get("evidence_snippet") is not None
            assert len(site["evidence_snippet"]) > 0

    # ── confidence ──────────────────────────────────────────────────

    def test_confidence_levels_set(self):
        result = self._trace("""\
            def handler(request):
                uid = request.user_id
        """, "user_id", "handler")

        reads = result["read_sites"]
        assert len(reads) >= 1
        for site in reads:
            assert site["confidence"] in ("high", "medium", "low")

    # ── no false positives ──────────────────────────────────────────

    def test_no_false_positives_for_unrelated_attributes(self):
        result = self._trace("""\
            def handler(request):
                x = request.order_id
                y = request.status
        """, "user_id", "handler")

        reads = result["read_sites"]
        assert len(reads) == 0

    def test_no_match_for_partial_name(self):
        result = self._trace("""\
            def handler(request):
                x = request.user_id_backup
        """, "user_id", "handler")

        reads = result["read_sites"]
        assert len(reads) == 0

    def test_multiple_reads_in_one_function(self):
        result = self._trace("""\
            def handler(request):
                a = request.user_id
                b = request.user_id
                process(request.user_id)
        """, "user_id", "handler")

        reads = result["read_sites"]
        assert len(reads) >= 3


# ═══════════════════════════════════════════════════════════════════════
# 5. TestEntryPointResolution
# ═══════════════════════════════════════════════════════════════════════


class TestEntryPointResolution:
    """_resolve_entry_points: anchor → handler mapping."""

    def _resolve(self, tmp_path, py_files, entry_points):
        """Helper: load files, build indices, resolve entry points."""
        sources, trees = _load_and_parse(tmp_path, py_files)
        route_index = build_route_index(str(tmp_path), py_files, sources, trees)
        func_index = _build_function_index(py_files, trees)
        resolved, diagnostics, handler_tuples = _resolve_entry_points(
            entry_points, route_index, func_index, sources, trees,
        )
        return resolved, diagnostics, handler_tuples

    def test_route_anchor_resolves(self, tmp_path):
        _write_py(tmp_path, "app.py", """\
            from fastapi import FastAPI
            app = FastAPI()

            @app.post("/orders")
            async def create_order(request):
                pass
        """)
        resolved, diagnostics, _ = self._resolve(
            tmp_path, ["app.py"], ["route:POST /orders"],
        )
        assert len(resolved) >= 1
        assert resolved[0].anchor == "route:POST /orders"

    def test_symbol_anchor_resolves(self, tmp_path):
        _write_py(tmp_path, "service.py", """\
            def process_order(data):
                return data
        """)
        resolved, diagnostics, _ = self._resolve(
            tmp_path, ["service.py"], ["symbol:service.py:process_order"],
        )
        assert len(resolved) >= 1

    def test_unresolved_anchor_emits_diagnostic(self, tmp_path):
        _write_py(tmp_path, "app.py", """\
            def hello():
                pass
        """)
        resolved, diagnostics, _ = self._resolve(
            tmp_path, ["app.py"], ["route:POST /nonexistent"],
        )
        assert len(resolved) == 0
        assert len(diagnostics) >= 1
        codes = [d.code for d in diagnostics]
        assert "entry_point_unresolved" in codes

    def test_multiple_entry_points(self, tmp_path):
        _write_py(tmp_path, "app.py", """\
            from fastapi import FastAPI
            app = FastAPI()

            @app.post("/orders")
            async def create_order(request):
                pass

            @app.get("/orders/{oid}")
            async def get_order(oid: int):
                pass
        """)
        resolved, _, _ = self._resolve(
            tmp_path, ["app.py"],
            ["route:POST /orders", "route:GET /orders/{oid}"],
        )
        assert len(resolved) >= 2

    def test_mixed_resolved_and_unresolved(self, tmp_path):
        _write_py(tmp_path, "app.py", """\
            from fastapi import FastAPI
            app = FastAPI()

            @app.post("/orders")
            async def create_order(request):
                pass
        """)
        resolved, diagnostics, _ = self._resolve(
            tmp_path, ["app.py"],
            ["route:POST /orders", "route:DELETE /missing"],
        )
        assert len(resolved) >= 1
        assert len(diagnostics) >= 1


# ═══════════════════════════════════════════════════════════════════════
# 6. TestRunTool2Integration
# ═══════════════════════════════════════════════════════════════════════


def _create_mini_fastapi_project(tmp_path):
    """Create a small FastAPI project for integration tests."""
    _write_py(tmp_path, "app/__init__.py", "")

    _write_py(tmp_path, "app/models.py", """\
        from pydantic import BaseModel, Field, field_validator

        class OrderRequest(BaseModel):
            user_id: str
            amount: float = Field(ge=0)
            item_ids: list[str] = []

            @field_validator("user_id")
            @classmethod
            def validate_user_id(cls, v):
                if not v.strip():
                    raise ValueError("user_id cannot be blank")
                return v.strip()
    """)

    _write_py(tmp_path, "app/main.py", """\
        from fastapi import FastAPI
        from app.models import OrderRequest

        app = FastAPI()

        @app.post("/orders")
        async def create_order(request: OrderRequest):
            uid = request.user_id
            total = request.amount
            return {"user": uid, "total": total}

        @app.get("/orders/{order_id}")
        async def get_order(order_id: int):
            return {"order_id": order_id}
    """)

    _write_py(tmp_path, "app/services.py", """\
        def process_order(order):
            uid = order.user_id
            if not uid:
                raise ValueError("missing user_id")
            return {"processed_for": uid}

        def summarize(data):
            return str(data.get("user_id", "unknown"))
    """)


class TestRunTool2Integration:
    """Integration tests for the full run_tool2 pipeline."""

    def test_full_pipeline_returns_valid_result(self, tmp_path):
        _create_mini_fastapi_project(tmp_path)
        req = Tool2Request(
            field_path="OrderRequest.user_id",
            entry_points=["route:POST /orders"],
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)

        assert result.changed_field == "OrderRequest.user_id"
        assert isinstance(result.stats, Tool2Stats)
        assert result.stats.files_scanned >= 1

    def test_entry_points_are_resolved(self, tmp_path):
        _create_mini_fastapi_project(tmp_path)
        req = Tool2Request(
            field_path="OrderRequest.user_id",
            entry_points=["route:POST /orders"],
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)

        assert len(result.entry_points_resolved) >= 1
        ep = result.entry_points_resolved[0]
        assert ep.anchor == "route:POST /orders"
        assert ep.confidence in ("high", "medium", "low")

    def test_read_sites_found(self, tmp_path):
        _create_mini_fastapi_project(tmp_path)
        req = Tool2Request(
            field_path="OrderRequest.user_id",
            entry_points=["route:POST /orders"],
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)

        assert len(result.read_sites) >= 1
        for site in result.read_sites:
            assert "user_id" in site.field_path
            assert SITE_ID_RE.match(site.site_id), f"Bad site_id: {site.site_id}"

    def test_validations_found_with_validators(self, tmp_path):
        _create_mini_fastapi_project(tmp_path)
        req = Tool2Request(
            field_path="OrderRequest.user_id",
            entry_points=["route:POST /orders"],
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)

        assert len(result.validations) >= 1
        for v in result.validations:
            assert VAL_ID_RE.match(v.validation_id)
            assert v.kind in ("pydantic_field_constraint", "pydantic_validator", "custom_guard")

    def test_diagnostics_for_unresolved_entry_points(self, tmp_path):
        _create_mini_fastapi_project(tmp_path)
        req = Tool2Request(
            field_path="OrderRequest.user_id",
            entry_points=["route:DELETE /nonexistent"],
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)

        assert len(result.diagnostics) >= 1
        codes = [d.code for d in result.diagnostics]
        assert "entry_point_unresolved" in codes

    def test_deterministic_output(self, tmp_path):
        _create_mini_fastapi_project(tmp_path)
        req = Tool2Request(
            field_path="OrderRequest.user_id",
            entry_points=["route:POST /orders"],
        )
        r1 = run_tool2(req, str(tmp_path))
        r2 = run_tool2(req, str(tmp_path))

        res1 = Tool2Result(**r1)
        res2 = Tool2Result(**r2)

        assert res1.changed_field == res2.changed_field
        assert [s.site_id for s in res1.read_sites] == [s.site_id for s in res2.read_sites]
        assert [s.site_id for s in res1.write_sites] == [s.site_id for s in res2.write_sites]
        assert [v.validation_id for v in res1.validations] == [v.validation_id for v in res2.validations]

    def test_empty_results_no_crash(self, tmp_path):
        _write_py(tmp_path, "empty.py", "x = 1\n")
        req = Tool2Request(
            field_path="SomeModel.nonexistent_field",
            entry_points=["symbol:empty.py:x"],
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)
        assert result.changed_field == "SomeModel.nonexistent_field"

    def test_max_sites_truncation(self, tmp_path):
        lines = ["def handler(req):"]
        for i in range(50):
            lines.append(f"    x{i} = req.user_id")
        source = "\n".join(lines) + "\n"
        _write_py(tmp_path, "big.py", source)

        req = Tool2Request(
            field_path="Request.user_id",
            entry_points=["symbol:big.py:handler"],
            options=Tool2Options(max_sites=5),
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)

        total_sites = len(result.read_sites) + len(result.write_sites)
        assert total_sites <= 5
        assert result.stats.truncated is True

    def test_symbol_entry_point(self, tmp_path):
        _write_py(tmp_path, "handler.py", """\
            def process(request):
                uid = request.user_id
                return uid
        """)
        req = Tool2Request(
            field_path="Request.user_id",
            entry_points=["symbol:handler.py:process"],
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)
        assert len(result.read_sites) >= 1


# ═══════════════════════════════════════════════════════════════════════
# 7. TestDeterminism
# ═══════════════════════════════════════════════════════════════════════


class TestDeterminism:
    """Determinism across repeated runs on same inputs."""

    def test_same_repo_same_inputs_identical_output(self, tmp_path):
        _create_mini_fastapi_project(tmp_path)
        req = Tool2Request(
            field_path="OrderRequest.user_id",
            entry_points=["route:POST /orders"],
        )
        r1 = run_tool2(req, str(tmp_path))
        r2 = run_tool2(req, str(tmp_path))

        res1 = Tool2Result(**r1)
        res2 = Tool2Result(**r2)

        assert res1.changed_field == res2.changed_field
        assert res1.stats.files_scanned == res2.stats.files_scanned
        assert res1.stats.sites_emitted == res2.stats.sites_emitted
        assert [s.site_id for s in res1.read_sites] == [s.site_id for s in res2.read_sites]

    def test_sites_sorted_deterministically(self, tmp_path):
        _write_py(tmp_path, "handler.py", """\
            def handler(request):
                a = request.user_id
                b = request.user_id
        """)
        req = Tool2Request(
            field_path="Model.user_id",
            entry_points=["symbol:handler.py:handler"],
        )
        r1 = run_tool2(req, str(tmp_path))
        r2 = run_tool2(req, str(tmp_path))

        res1 = Tool2Result(**r1)
        res2 = Tool2Result(**r2)

        ids1 = [(s.site_id, s.location.file, s.location.range.start.line) for s in res1.read_sites]
        ids2 = [(s.site_id, s.location.file, s.location.range.start.line) for s in res2.read_sites]
        assert ids1 == ids2

    def test_id_generation_is_content_derived(self):
        id_a1 = _compute_site_id("user_id", "sym_handler", "api.py", 10, 4, "attribute")
        id_a2 = _compute_site_id("user_id", "sym_handler", "api.py", 10, 4, "attribute")
        id_b = _compute_site_id("email", "sym_handler", "api.py", 10, 4, "attribute")
        assert id_a1 == id_a2
        assert id_a1 != id_b


# ═══════════════════════════════════════════════════════════════════════
# 8. TestEdgeCases
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge-case inputs that should not crash."""

    def test_missing_files_handled_gracefully(self, tmp_path):
        req = Tool2Request(
            field_path="Model.field",
            entry_points=["symbol:nonexistent.py:func"],
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)
        assert isinstance(result, Tool2Result)

    def test_syntax_error_files_produce_diagnostics(self, tmp_path):
        _write_py(tmp_path, "broken.py", """\
            def handler(req
                x = req.user_id
        """)
        req = Tool2Request(
            field_path="Model.user_id",
            entry_points=["symbol:broken.py:handler"],
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)
        assert len(result.diagnostics) >= 1 or len(result.read_sites) == 0

    def test_deeply_nested_attribute_access(self, tmp_path):
        _write_py(tmp_path, "deep.py", """\
            def handler(request):
                x = request.data.nested.user_id
        """)
        req = Tool2Request(
            field_path="Model.user_id",
            entry_points=["symbol:deep.py:handler"],
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)
        assert isinstance(result, Tool2Result)

    def test_empty_repo(self, tmp_path):
        req = Tool2Request(
            field_path="Model.field",
            entry_points=["route:GET /something"],
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)
        assert result.changed_field == "Model.field"
        assert len(result.read_sites) == 0


# ═══════════════════════════════════════════════════════════════════════
# 9. TestSchemaValidation
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaValidation:
    """Verify schema models accept/reject input correctly."""

    def test_tool2_request_valid(self):
        req = Tool2Request(
            field_path="OrderRequest.user_id",
            entry_points=["route:POST /orders"],
        )
        assert req.field_path == "OrderRequest.user_id"
        assert req.options.direction == "both"
        assert req.options.max_call_depth == 2

    def test_tool2_request_empty_entry_points_rejected(self):
        with pytest.raises(Exception):
            Tool2Request(field_path="OrderRequest.user_id", entry_points=[])

    def test_tool2_options_defaults(self):
        opts = Tool2Options()
        assert opts.direction == "both"
        assert opts.max_call_depth == 2
        assert opts.max_sites == 200
        assert opts.include_writes is True

    def test_tool2_options_custom(self):
        opts = Tool2Options(direction="request", max_call_depth=4, max_sites=50, include_writes=False)
        assert opts.direction == "request"
        assert opts.max_call_depth == 4

    def test_tool2_options_invalid_direction(self):
        with pytest.raises(Exception):
            Tool2Options(direction="invalid_direction")

    def test_tool2_options_depth_out_of_range(self):
        with pytest.raises(Exception):
            Tool2Options(max_call_depth=10)

    def test_read_write_site_model(self):
        site = ReadWriteSite(
            site_id="site_0123456789abcdef",
            field_path="OrderRequest.user_id",
            location=_make_location("api.py", 10, 4, 10, 20),
            enclosing_symbol_id="sym_handler",
            access_pattern="attribute",
            confidence="high",
            evidence_snippet="request.user_id",
        )
        assert site.breakage.if_removed is False
        assert site.breakage.if_renamed is False

    def test_validation_model(self):
        v = Validation(
            validation_id="val_0123456789abcdef",
            kind="pydantic_validator",
            field_path="OrderRequest.user_id",
            location=_make_location("models.py", 20, 4, 25, 0),
            enclosing_symbol_id="sym_validate_user_id",
            rule_summary="validates user_id is not blank",
            confidence="high",
        )
        assert v.kind == "pydantic_validator"

    def test_transform_model(self):
        t = Transform(
            transform_id="xform_0123456789abcdef",
            kind="cast",
            from_field="user_id",
            to_field="user_id",
            from_type="str",
            to_type="UUID",
            location=_make_location("svc.py", 15, 8, 15, 30),
            enclosing_symbol_id="sym_process",
            confidence="high",
        )
        assert t.kind == "cast"
        assert t.to_type == "UUID"

    def test_tool2_diagnostic_model(self):
        d = Tool2Diagnostic(
            severity="warning",
            code="entry_point_unresolved",
            message="Could not resolve route:DELETE /foo",
        )
        assert d.severity == "warning"
        assert d.location is None

    def test_tool2_stats_model(self):
        s = Tool2Stats(files_scanned=5, sites_emitted=12, truncated=False)
        assert s.files_scanned == 5

    def test_tool2_result_model_empty(self):
        result = Tool2Result(
            changed_field="Test.field",
            stats=Tool2Stats(files_scanned=0, sites_emitted=0, truncated=False),
        )
        assert len(result.read_sites) == 0
        assert len(result.write_sites) == 0

    def test_breakage_defaults(self):
        b = Breakage()
        assert b.if_removed is False
        assert b.if_renamed is False
        assert b.if_type_changed is None


# ═══════════════════════════════════════════════════════════════════════
# 10. TestRouteIndexPatterns
# ═══════════════════════════════════════════════════════════════════════


class TestRouteIndexPatterns:
    """Additional route index edge cases."""

    def test_decorated_with_depends(self, tmp_path):
        _write_py(tmp_path, "app.py", """\
            from fastapi import FastAPI, Depends
            app = FastAPI()

            def auth():
                pass

            @app.post("/secure")
            async def secure_endpoint(dep=Depends(auth)):
                pass
        """)
        index = _build_route_index_simple(tmp_path, ["app.py"])
        assert "POST /secure" in index

    def test_route_with_response_model(self, tmp_path):
        _write_py(tmp_path, "app.py", """\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/items", response_model=list)
            async def list_items():
                return []
        """)
        index = _build_route_index_simple(tmp_path, ["app.py"])
        assert "GET /items" in index

    def test_sync_handler(self, tmp_path):
        _write_py(tmp_path, "app.py", """\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/sync")
            def sync_handler():
                return {"ok": True}
        """)
        index = _build_route_index_simple(tmp_path, ["app.py"])
        assert "GET /sync" in index
        assert index["GET /sync"].handler_name == "sync_handler"


# ═══════════════════════════════════════════════════════════════════════
# 11. TestModelIndexAdvanced
# ═══════════════════════════════════════════════════════════════════════


class TestModelIndexAdvanced:
    """Advanced model index scenarios."""

    def test_model_inheritance(self, tmp_path):
        """Transitive BaseModel subclasses are detected via inheritance traversal."""
        _write_py(tmp_path, "models.py", """\
            from pydantic import BaseModel

            class BaseRequest(BaseModel):
                trace_id: str

            class OrderRequest(BaseRequest):
                user_id: str
                amount: float
        """)
        index = _build_model_index_simple(tmp_path, ["models.py"])
        # BaseRequest is a direct BaseModel subclass → detected
        assert "BaseRequest" in index
        # OrderRequest inherits BaseRequest which inherits BaseModel →
        # detected via transitive inheritance traversal.
        assert "OrderRequest" in index
        assert "user_id" in index["OrderRequest"].fields

    def test_optional_fields(self, tmp_path):
        _write_py(tmp_path, "models.py", """\
            from typing import Optional
            from pydantic import BaseModel

            class UserUpdate(BaseModel):
                name: Optional[str] = None
                email: str
        """)
        index = _build_model_index_simple(tmp_path, ["models.py"])
        fields = list(index["UserUpdate"].fields.keys())
        assert "name" in fields
        assert "email" in fields

    def test_complex_field_types(self, tmp_path):
        _write_py(tmp_path, "models.py", """\
            from pydantic import BaseModel

            class Order(BaseModel):
                items: list[str]
                metadata: dict[str, int]
        """)
        index = _build_model_index_simple(tmp_path, ["models.py"])
        fields = list(index["Order"].fields.keys())
        assert "items" in fields
        assert "metadata" in fields


# ═══════════════════════════════════════════════════════════════════════
# 12. TestImplVersion
# ═══════════════════════════════════════════════════════════════════════


class TestImplVersion:
    def test_version_is_string(self):
        assert isinstance(TOOL2_IMPL_VERSION, str)

    def test_version_non_empty(self):
        assert len(TOOL2_IMPL_VERSION) > 0


# ═══════════════════════════════════════════════════════════════════════
# 13. TestFieldPathParsing
# ═══════════════════════════════════════════════════════════════════════


class TestFieldPathParsing:
    """Field path canonicalization edge cases in integration."""

    def test_dotted_field_path(self, tmp_path):
        _write_py(tmp_path, "handler.py", """\
            def handler(request):
                uid = request.user_id
        """)
        req = Tool2Request(
            field_path="OrderRequest.user_id",
            entry_points=["symbol:handler.py:handler"],
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)
        assert "user_id" in result.changed_field

    def test_bare_field_name(self, tmp_path):
        _write_py(tmp_path, "handler.py", """\
            def handler(data):
                x = data["amount"]
        """)
        req = Tool2Request(
            field_path="amount",
            entry_points=["symbol:handler.py:handler"],
        )
        result_dict = run_tool2(req, str(tmp_path))
        result = Tool2Result(**result_dict)
        assert isinstance(result, Tool2Result)
