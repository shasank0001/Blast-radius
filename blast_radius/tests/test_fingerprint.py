"""Tests for repository fingerprinting."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from blast_radius_mcp.repo.fingerprint import compute_repo_fingerprint
from blast_radius_mcp.repo.io import (
    compute_file_hash,
    glob_python_files,
    safe_read_file,
)


class TestSafeReadFile:
    def test_reads_file_in_repo(self, tmp_path):
        (tmp_path / "hello.py").write_text("print('hello')")
        content = safe_read_file(str(tmp_path), "hello.py")
        assert content == b"print('hello')"

    def test_reads_nested_file(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "mod.py").write_text("x = 1")
        content = safe_read_file(str(tmp_path), "sub/mod.py")
        assert content == b"x = 1"

    def test_rejects_path_traversal(self, tmp_path):
        with pytest.raises(ValueError, match="Path traversal"):
            safe_read_file(str(tmp_path), "../../../etc/passwd")

    def test_rejects_absolute_escape(self, tmp_path):
        with pytest.raises((ValueError, FileNotFoundError)):
            safe_read_file(str(tmp_path), "/etc/passwd")

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            safe_read_file(str(tmp_path), "nonexistent.py")


class TestGlobPythonFiles:
    def test_finds_py_files(self, tmp_path):
        (tmp_path / "a.py").write_text("# a")
        (tmp_path / "b.py").write_text("# b")
        (tmp_path / "c.txt").write_text("# not python")
        result = glob_python_files(str(tmp_path))
        assert result == ["a.py", "b.py"]

    def test_finds_nested_py_files(self, tmp_path):
        sub = tmp_path / "pkg"
        sub.mkdir()
        (sub / "mod.py").write_text("# mod")
        (tmp_path / "top.py").write_text("# top")
        result = glob_python_files(str(tmp_path))
        assert "pkg/mod.py" in result
        assert "top.py" in result

    def test_excludes_pycache(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-311.pyc").write_bytes(b"")
        (cache / "something.py").write_text("# cached")
        (tmp_path / "real.py").write_text("# real")
        result = glob_python_files(str(tmp_path))
        assert result == ["real.py"]

    def test_excludes_venv(self, tmp_path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "lib.py").write_text("# venv")
        (tmp_path / "app.py").write_text("# app")
        result = glob_python_files(str(tmp_path))
        assert result == ["app.py"]

    def test_sorted_output(self, tmp_path):
        for name in ["z.py", "a.py", "m.py"]:
            (tmp_path / name).write_text(f"# {name}")
        result = glob_python_files(str(tmp_path))
        assert result == sorted(result)

    def test_empty_dir(self, tmp_path):
        assert glob_python_files(str(tmp_path)) == []


class TestComputeFileHash:
    def test_deterministic(self):
        h1 = compute_file_hash(b"hello world")
        h2 = compute_file_hash(b"hello world")
        assert h1 == h2

    def test_different_content(self):
        h1 = compute_file_hash(b"hello")
        h2 = compute_file_hash(b"world")
        assert h1 != h2

    def test_hex_format(self):
        result = compute_file_hash(b"test")
        assert len(result) == 64
        int(result, 16)


class TestComputeRepoFingerprint:
    def test_deterministic_for_same_content(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1")
        fp1 = compute_repo_fingerprint(str(tmp_path))
        fp2 = compute_repo_fingerprint(str(tmp_path))
        assert fp1.fingerprint_hash == fp2.fingerprint_hash

    def test_changes_when_file_changes(self, tmp_path):
        f = tmp_path / "app.py"
        f.write_text("x = 1")
        fp1 = compute_repo_fingerprint(str(tmp_path))

        f.write_text("x = 2")
        fp2 = compute_repo_fingerprint(str(tmp_path))

        assert fp1.fingerprint_hash != fp2.fingerprint_hash

    def test_no_git_returns_none_head(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1")
        fp = compute_repo_fingerprint(str(tmp_path))
        assert fp.git_head is None
        assert fp.dirty is True

    def test_invalid_repo_root_raises(self):
        with pytest.raises(ValueError, match="not a directory"):
            compute_repo_fingerprint("/nonexistent/path/xyz")

    def test_empty_repo(self, tmp_path):
        fp = compute_repo_fingerprint(str(tmp_path))
        assert fp.fingerprint_hash
        assert len(fp.fingerprint_hash) == 64
