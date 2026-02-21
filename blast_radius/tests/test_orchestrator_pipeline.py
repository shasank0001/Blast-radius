"""Regression tests for orchestrator pipeline behavior."""

from __future__ import annotations

import pytest

import orchestrator


@pytest.mark.asyncio
async def test_run_blast_radius_returns_markdown_with_mocked_tool_calls(
    tmp_path,
    monkeypatch,
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        orchestrator,
        "build_tool_plan",
        lambda *args, **kwargs: [{"tool_name": "get_ast_dependencies", "inputs": {}}],
    )

    async def _fake_call_tool(**kwargs):
        return {}, "qid_mock"

    monkeypatch.setattr(orchestrator, "_call_tool", _fake_call_tool)
    monkeypatch.setattr(orchestrator, "render_report", lambda **kwargs: "# Blast Radius\n")

    report = await orchestrator.run_blast_radius(
        intent="rename user_id to account_id",
        repo_root=str(repo_root),
        anchors=[],
        diff="",
    )

    assert report.startswith("# ")
