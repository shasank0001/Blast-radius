"""Tests for orchestrator report renderer mapping behavior."""

from __future__ import annotations

from orchestrator.report_render import _render_temporal_coupling, _render_tests


def test_temporal_coupling_reads_couplings_payload():
    tool_results = {
        "get_historical_coupling": {
            "couplings": [
                {
                    "target_file": "app/api/orders.py",
                    "coupled_file": "app/models.py",
                    "weight": 0.78,
                }
            ]
        }
    }

    rendered = _render_temporal_coupling(tool_results)

    assert "`app/models.py`" in rendered
    assert "weight: 78%" in rendered


def test_temporal_coupling_falls_back_to_legacy_coupled_files():
    tool_results = {
        "get_historical_coupling": {
            "coupled_files": [
                {
                    "file": "legacy/path.py",
                    "weight": 45,
                }
            ]
        }
    }

    rendered = _render_temporal_coupling(tool_results)

    assert "`legacy/path.py`" in rendered
    assert "weight: 45%" in rendered


def test_render_tests_reads_nodeid_and_reason_from_reasons_evidence():
    tool_results = {
        "get_covering_tests": {
            "tests": [
                {
                    "nodeid": "tests/test_orders.py::test_create_order",
                    "reasons": [
                        {
                            "type": "direct_import",
                            "evidence": "imports app.api.orders",
                        },
                        {
                            "type": "symbol_reference",
                            "evidence": "references create_order",
                        },
                    ],
                }
            ]
        }
    }

    rendered = _render_tests(tool_results)

    assert "`tests/test_orders.py::test_create_order`" in rendered
    assert "imports app.api.orders" in rendered


def test_render_tests_keeps_fallbacks_for_legacy_reason_and_node_key():
    tool_results = {
        "get_covering_tests": {
            "tests": [
                {
                    "node_id": "tests/test_legacy.py::test_old_style",
                    "reason": "legacy fallback reason",
                    "reasons": [],
                }
            ]
        }
    }

    rendered = _render_tests(tool_results)

    assert "`tests/test_legacy.py::test_old_style`" in rendered
    assert "legacy fallback reason" in rendered
