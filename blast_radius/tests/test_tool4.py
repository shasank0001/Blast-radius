"""Comprehensive tests for Tool 4 — Temporal Coupling Engine."""

from __future__ import annotations

import os
import re
import subprocess
import textwrap

import pytest

from blast_radius_mcp.schemas.tool4_coupling import (
    Coupling,
    CouplingTarget,
    ExampleCommit,
    HistoryStats,
    Tool4Diagnostic,
    Tool4Result,
)
from blast_radius_mcp.tools.tool4_temporal_coupling import (
    TOOL4_IMPL_VERSION,
    Commit,
    FileChange,
    _normalize_path,
    _sha256_prefix,
    build_rename_map,
    compute_coupling,
    parse_git_log,
    run_tool4,
)

# ── Helpers ──────────────────────────────────────────────────────────

SHA_PREFIX_RE = re.compile(r"^[0-9a-f]{16}$")


def _init_git_repo(path):
    """Initialise a git repo at *path* with deterministic config."""
    subprocess.run(
        ["git", "init", str(path)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )


def _git_add_commit(path, message="commit"):
    """Stage all files and commit."""
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", message, "--allow-empty"],
        cwd=str(path),
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": "2025-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2025-01-01T00:00:00+00:00",
        },
    )


def _write_file(tmp_path, relpath: str, content: str = "") -> str:
    """Write a file under *tmp_path* and return the relative path."""
    full = tmp_path / relpath
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return relpath


# ═══════════════════════════════════════════════════════════════════════
# 1. TestHelpers
# ═══════════════════════════════════════════════════════════════════════


class TestHelpers:
    """Tests for _normalize_path and _sha256_prefix."""

    def test_normalize_path_forward_slashes(self):
        """Backslashes are converted to forward slashes."""
        assert _normalize_path("a\\b\\c.py") == "a/b/c.py"

    def test_normalize_path_dot_prefix(self):
        """Leading ./ is removed."""
        assert _normalize_path("./src/main.py") == "src/main.py"

    def test_normalize_path_double_slash(self):
        """Redundant separators are collapsed."""
        result = _normalize_path("a//b///c.py")
        assert result == "a/b/c.py"

    def test_normalize_path_dotdot(self):
        """Parent directory references are collapsed."""
        result = _normalize_path("a/b/../c.py")
        assert result == "a/c.py"

    def test_sha256_prefix_format(self):
        """Result starts with prefix and has 16 hex chars after."""
        result = _sha256_prefix("cp_", "fileA", "fileB")
        assert result.startswith("cp_")
        suffix = result[len("cp_"):]
        assert len(suffix) == 16
        assert SHA_PREFIX_RE.match(suffix)

    def test_sha256_prefix_deterministic(self):
        """Same arguments produce the same output."""
        id1 = _sha256_prefix("cp_", "x.py", "y.py")
        id2 = _sha256_prefix("cp_", "x.py", "y.py")
        assert id1 == id2

    def test_sha256_prefix_different_inputs(self):
        """Different arguments produce different output."""
        id1 = _sha256_prefix("cp_", "a.py")
        id2 = _sha256_prefix("cp_", "b.py")
        assert id1 != id2

    def test_sha256_prefix_custom_length(self):
        """Custom hex length is respected."""
        result = _sha256_prefix("cp_", "x.py", length=8)
        suffix = result[len("cp_"):]
        assert len(suffix) == 8


# ═══════════════════════════════════════════════════════════════════════
# 2. TestParseGitLog
# ═══════════════════════════════════════════════════════════════════════


class TestParseGitLog:
    """Tests for parse_git_log with real git repos."""

    def test_parse_basic_commits(self, tmp_path):
        """Parse a repo with a few commits and verify structure."""
        _init_git_repo(tmp_path)

        _write_file(tmp_path, "a.py", "# a")
        _git_add_commit(tmp_path, "add a")

        _write_file(tmp_path, "b.py", "# b")
        _git_add_commit(tmp_path, "add b")

        commits, scanned = parse_git_log(str(tmp_path))

        assert scanned >= 2
        assert len(commits) >= 2
        # Each commit should have a sha, date, and at least one file
        for c in commits:
            assert len(c.sha) == 40
            assert c.date  # non-empty ISO date
            assert c.message

    def test_parse_excludes_large_commits(self, tmp_path):
        """Commits touching more files than max_commit_size are excluded."""
        _init_git_repo(tmp_path)

        # Create a commit with 5 files
        for i in range(5):
            _write_file(tmp_path, f"file_{i}.py", f"# {i}")
        _git_add_commit(tmp_path, "bulk commit")

        commits, scanned = parse_git_log(str(tmp_path), max_commit_size=3)

        assert scanned >= 1
        # The commit with 5 files should be filtered out
        for c in commits:
            assert len(c.files) <= 3

    def test_parse_handles_renames(self, tmp_path):
        """Renamed files produce FileChange with old_path set."""
        _init_git_repo(tmp_path)

        _write_file(tmp_path, "old_name.py", "print('hello')")
        _git_add_commit(tmp_path, "add old_name")

        subprocess.run(
            ["git", "mv", "old_name.py", "new_name.py"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )
        _git_add_commit(tmp_path, "rename file")

        commits, scanned = parse_git_log(str(tmp_path))

        # Find the rename commit
        rename_changes = []
        for c in commits:
            for fc in c.files:
                if fc.old_path is not None:
                    rename_changes.append(fc)

        assert len(rename_changes) >= 1
        rename = rename_changes[0]
        assert rename.path == "new_name.py"
        assert rename.old_path == "old_name.py"
        assert rename.status.startswith("R")

    def test_parse_no_git(self, tmp_path):
        """A directory without .git raises an appropriate error."""
        with pytest.raises((subprocess.CalledProcessError, FileNotFoundError)):
            parse_git_log(str(tmp_path))

    def test_parse_empty_repo(self, tmp_path):
        """A repo with no commits raises CalledProcessError (git log fails)."""
        _init_git_repo(tmp_path)

        with pytest.raises(subprocess.CalledProcessError):
            parse_git_log(str(tmp_path))

    def test_parse_window_commits_limit(self, tmp_path):
        """window_commits limits how many commits are scanned."""
        _init_git_repo(tmp_path)

        for i in range(5):
            _write_file(tmp_path, f"f{i}.py", f"# {i}")
            _git_add_commit(tmp_path, f"commit {i}")

        commits, scanned = parse_git_log(str(tmp_path), window_commits=3)

        assert scanned <= 3


# ═══════════════════════════════════════════════════════════════════════
# 3. TestBuildRenameMap
# ═══════════════════════════════════════════════════════════════════════


class TestBuildRenameMap:
    """Tests for build_rename_map."""

    def test_rename_simple(self):
        """A single rename A→B creates bidirectional alias."""
        commits = [
            Commit(
                sha="a" * 40,
                date="2025-01-01T00:00:00",
                message="rename",
                files=[
                    FileChange(status="R100", path="b.py", old_path="a.py"),
                ],
            ),
        ]
        alias_map, count = build_rename_map(commits)

        assert count == 1
        assert "a.py" in alias_map
        assert "b.py" in alias_map
        assert alias_map["a.py"] == alias_map["b.py"]
        assert "a.py" in alias_map["b.py"]
        assert "b.py" in alias_map["a.py"]

    def test_rename_chain(self):
        """A→B→C creates a single alias group containing all three."""
        commits = [
            Commit(
                sha="a" * 40,
                date="2025-01-01",
                message="rename a→b",
                files=[
                    FileChange(status="R100", path="b.py", old_path="a.py"),
                ],
            ),
            Commit(
                sha="b" * 40,
                date="2025-01-02",
                message="rename b→c",
                files=[
                    FileChange(status="R100", path="c.py", old_path="b.py"),
                ],
            ),
        ]
        alias_map, count = build_rename_map(commits)

        assert count == 2
        # All three should be in the same alias set
        assert alias_map["a.py"] == alias_map["b.py"] == alias_map["c.py"]
        assert {"a.py", "b.py", "c.py"} == alias_map["a.py"]

    def test_rename_disabled(self):
        """follow_renames=False returns empty map."""
        commits = [
            Commit(
                sha="a" * 40,
                date="2025-01-01",
                message="rename",
                files=[
                    FileChange(status="R100", path="b.py", old_path="a.py"),
                ],
            ),
        ]
        alias_map, count = build_rename_map(commits, follow_renames=False)

        assert alias_map == {}
        assert count == 0

    def test_no_renames(self):
        """Commits without renames produce alias entries for touched files."""
        commits = [
            Commit(
                sha="a" * 40,
                date="2025-01-01",
                message="normal",
                files=[
                    FileChange(status="M", path="x.py"),
                    FileChange(status="A", path="y.py"),
                ],
            ),
        ]
        alias_map, count = build_rename_map(commits)

        assert count == 0


# ═══════════════════════════════════════════════════════════════════════
# 4. TestComputeCoupling
# ═══════════════════════════════════════════════════════════════════════


class TestComputeCoupling:
    """Tests for compute_coupling."""

    def _make_commits(self) -> list[Commit]:
        """Create a set of commits where a.py and b.py often co-change."""
        commits = []
        # 3 commits where a.py and b.py change together
        for i in range(3):
            commits.append(
                Commit(
                    sha=f"{i:040d}",
                    date=f"2025-01-0{i + 1}",
                    message=f"commit {i}",
                    files=[
                        FileChange(status="M", path="a.py"),
                        FileChange(status="M", path="b.py"),
                    ],
                )
            )
        # 1 commit where a.py and c.py change together
        commits.append(
            Commit(
                sha=f"{3:040d}",
                date="2025-01-04",
                message="commit 3",
                files=[
                    FileChange(status="M", path="a.py"),
                    FileChange(status="M", path="c.py"),
                ],
            )
        )
        return commits

    def test_coupling_basic(self):
        """Files changed together get positive weight."""
        commits = self._make_commits()
        alias_map = {}

        couplings, support, aliases = compute_coupling(
            "a.py", commits, alias_map
        )

        assert support == 4  # a.py appears in all 4 commits
        assert len(couplings) >= 2
        # b.py should be coupled
        coupled_files = {c.coupled_file for c in couplings}
        assert "b.py" in coupled_files
        assert "c.py" in coupled_files

    def test_coupling_ranking(self):
        """Files ranked by weight desc, then support desc, then file asc."""
        commits = self._make_commits()
        alias_map = {}

        couplings, support, _ = compute_coupling("a.py", commits, alias_map)

        # b.py co-changed 3 times, c.py 1 time → b.py should rank first
        assert len(couplings) >= 2
        assert couplings[0].coupled_file == "b.py"
        assert couplings[0].weight >= couplings[1].weight

    def test_coupling_max_files(self):
        """max_files limits the number of coupled files returned."""
        commits = self._make_commits()
        alias_map = {}

        couplings, support, _ = compute_coupling(
            "a.py", commits, alias_map, max_files=1
        )

        assert len(couplings) <= 1

    def test_coupling_deterministic(self):
        """Same inputs produce identical output."""
        commits = self._make_commits()
        alias_map = {}

        result1 = compute_coupling("a.py", commits, alias_map)
        result2 = compute_coupling("a.py", commits, alias_map)

        # Couplings should be identical
        c1 = [(c.coupled_file, c.weight, c.support) for c in result1[0]]
        c2 = [(c.coupled_file, c.weight, c.support) for c in result2[0]]
        assert c1 == c2
        assert result1[1] == result2[1]  # support_commits

    def test_coupling_no_target_commits(self):
        """Target file not in any commit returns empty couplings."""
        commits = self._make_commits()
        alias_map = {}

        couplings, support, aliases = compute_coupling(
            "nonexistent.py", commits, alias_map
        )

        assert couplings == []
        assert support == 0

    def test_coupling_with_aliases(self):
        """Aliases of the target are excluded from coupled files."""
        commits = [
            Commit(
                sha="a" * 40,
                date="2025-01-01",
                message="co-change",
                files=[
                    FileChange(status="M", path="a.py"),
                    FileChange(status="M", path="old_a.py"),
                    FileChange(status="M", path="b.py"),
                ],
            ),
        ]
        alias_map = {
            "a.py": {"a.py", "old_a.py"},
            "old_a.py": {"a.py", "old_a.py"},
        }

        couplings, support, aliases = compute_coupling(
            "a.py", commits, alias_map
        )

        # old_a.py is an alias and should NOT appear as a coupled file
        coupled_files = {c.coupled_file for c in couplings}
        assert "old_a.py" not in coupled_files
        assert "b.py" in coupled_files

    def test_coupling_example_commits(self):
        """Example commits are included up to the maximum."""
        commits = self._make_commits()
        alias_map = {}

        couplings, _, _ = compute_coupling("a.py", commits, alias_map)

        for c in couplings:
            assert len(c.example_commits) <= 3  # _MAX_EXAMPLE_COMMITS
            for ex in c.example_commits:
                assert ex.sha  # non-empty
                assert ex.date


# ═══════════════════════════════════════════════════════════════════════
# 5. TestRunTool4Integration
# ═══════════════════════════════════════════════════════════════════════


class TestRunTool4Integration:
    """End-to-end tests for run_tool4."""

    def test_run_tool4_basic(self, tmp_path):
        """Basic end-to-end: create commits, run tool4, verify structure."""
        _init_git_repo(tmp_path)

        _write_file(tmp_path, "src/handler.py", "# handler")
        _write_file(tmp_path, "src/utils.py", "# utils")
        _git_add_commit(tmp_path, "add files")

        # Modify both together
        _write_file(tmp_path, "src/handler.py", "# handler v2")
        _write_file(tmp_path, "src/utils.py", "# utils v2")
        _git_add_commit(tmp_path, "update both")

        result = run_tool4(
            {"file_paths": ["src/handler.py"]},
            str(tmp_path),
        )

        assert "targets" in result
        assert "couplings" in result
        assert "history_stats" in result
        assert "diagnostics" in result

        # Validate with pydantic model
        parsed = Tool4Result(**result)
        assert len(parsed.targets) == 1
        assert parsed.targets[0].file == "src/handler.py"
        assert parsed.history_stats.commits_scanned >= 2
        assert parsed.history_stats.commits_used >= 2

    def test_run_tool4_no_git(self, tmp_path):
        """Without .git, returns git_history_unavailable diagnostic."""
        _write_file(tmp_path, "a.py", "# no git")

        result = run_tool4(
            {"file_paths": ["a.py"]},
            str(tmp_path),
        )

        parsed = Tool4Result(**result)
        codes = [d.code for d in parsed.diagnostics]
        assert "git_history_unavailable" in codes
        assert parsed.history_stats.commits_scanned == 0
        assert parsed.couplings == []

    def test_run_tool4_deterministic(self, tmp_path):
        """Two runs on the same repo produce identical output."""
        _init_git_repo(tmp_path)

        _write_file(tmp_path, "x.py", "# x")
        _write_file(tmp_path, "y.py", "# y")
        _git_add_commit(tmp_path, "init")

        _write_file(tmp_path, "x.py", "# x v2")
        _write_file(tmp_path, "y.py", "# y v2")
        _git_add_commit(tmp_path, "update")

        inputs = {"file_paths": ["x.py"]}
        result1 = run_tool4(inputs, str(tmp_path))
        result2 = run_tool4(inputs, str(tmp_path))

        assert result1 == result2

    def test_run_tool4_low_history(self, tmp_path):
        """Few commits produce low_history_support diagnostic."""
        _init_git_repo(tmp_path)

        _write_file(tmp_path, "a.py", "# a")
        _git_add_commit(tmp_path, "only commit")

        result = run_tool4(
            {"file_paths": ["a.py"]},
            str(tmp_path),
        )

        parsed = Tool4Result(**result)
        # Only 1 commit used, threshold is 10
        codes = [d.code for d in parsed.diagnostics]
        assert "low_history_support" in codes

    def test_run_tool4_target_not_in_history(self, tmp_path):
        """Target file not in any commit gets target_not_in_history diagnostic."""
        _init_git_repo(tmp_path)

        # Create some history that does NOT include target.py
        _write_file(tmp_path, "other.py", "# other")
        _git_add_commit(tmp_path, "add other")

        # Create target.py but don't commit it
        _write_file(tmp_path, "target.py", "# target")

        result = run_tool4(
            {"file_paths": ["target.py"]},
            str(tmp_path),
        )

        parsed = Tool4Result(**result)
        codes = [d.code for d in parsed.diagnostics]
        assert "target_not_in_history" in codes

    def test_run_tool4_multiple_targets(self, tmp_path):
        """Multiple target files produce multiple CouplingTarget entries."""
        _init_git_repo(tmp_path)

        _write_file(tmp_path, "a.py", "# a")
        _write_file(tmp_path, "b.py", "# b")
        _write_file(tmp_path, "c.py", "# c")
        _git_add_commit(tmp_path, "init")

        result = run_tool4(
            {"file_paths": ["a.py", "b.py"]},
            str(tmp_path),
        )

        parsed = Tool4Result(**result)
        assert len(parsed.targets) == 2
        target_files = {t.file for t in parsed.targets}
        assert target_files == {"a.py", "b.py"}

    def test_run_tool4_with_options(self, tmp_path):
        """Options like max_files and window_commits are respected."""
        _init_git_repo(tmp_path)

        _write_file(tmp_path, "main.py", "# main")
        _write_file(tmp_path, "dep1.py", "# dep1")
        _write_file(tmp_path, "dep2.py", "# dep2")
        _git_add_commit(tmp_path, "init")

        _write_file(tmp_path, "main.py", "# v2")
        _write_file(tmp_path, "dep1.py", "# v2")
        _write_file(tmp_path, "dep2.py", "# v2")
        _git_add_commit(tmp_path, "update all")

        result = run_tool4(
            {
                "file_paths": ["main.py"],
                "options": {"max_files": 1, "window_commits": 100},
            },
            str(tmp_path),
        )

        parsed = Tool4Result(**result)
        assert len(parsed.couplings) <= 1

    def test_run_tool4_nonexistent_file(self, tmp_path):
        """Non-existent target file produces a diagnostic."""
        _init_git_repo(tmp_path)

        _write_file(tmp_path, "other.py", "# other")
        _git_add_commit(tmp_path, "init")

        result = run_tool4(
            {"file_paths": ["does_not_exist.py"]},
            str(tmp_path),
        )

        parsed = Tool4Result(**result)
        codes = [d.code for d in parsed.diagnostics]
        assert "target_not_in_history" in codes

    def test_run_tool4_renames_followed(self, tmp_path):
        """Renames are tracked in history_stats."""
        _init_git_repo(tmp_path)

        _write_file(tmp_path, "old.py", "print('hello')")
        _git_add_commit(tmp_path, "add old")

        subprocess.run(
            ["git", "mv", "old.py", "new.py"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )
        _git_add_commit(tmp_path, "rename old→new")

        result = run_tool4(
            {"file_paths": ["new.py"]},
            str(tmp_path),
        )

        parsed = Tool4Result(**result)
        assert parsed.history_stats.renames_followed >= 1
