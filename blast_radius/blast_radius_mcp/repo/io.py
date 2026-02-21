"""Repository I/O utilities with path safety."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def safe_read_file(repo_root: str, rel_path: str) -> bytes:
    """Read file ensuring path stays inside repo_root (no path traversal).

    Args:
        repo_root: Absolute or relative path to the repository root.
        rel_path: Repo-relative path of the file to read.

    Returns:
        Raw file bytes.

    Raises:
        ValueError: If the resolved path escapes repo_root.
        FileNotFoundError: If the file doesn't exist.
    """
    root = Path(repo_root).resolve()
    target = (root / rel_path).resolve()

    # Security: ensure target is within repo_root
    if not str(target).startswith(str(root) + os.sep) and target != root:
        raise ValueError(
            f"Path traversal detected: {rel_path!r} resolves outside repo root"
        )

    if not target.is_file():
        raise FileNotFoundError(f"File not found: {target}")

    return target.read_bytes()


def glob_python_files(repo_root: str) -> list[str]:
    """Return sorted list of repo-relative *.py file paths.

    Excludes common non-source directories like __pycache__, .git, .venv, etc.

    Args:
        repo_root: Path to the repository root.

    Returns:
        Sorted list of repo-relative Python file paths using forward slashes.
    """
    root = Path(repo_root).resolve()
    exclude_dirs = {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "env",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "node_modules",
        ".eggs",
        "*.egg-info",
        "dist",
        "build",
    }

    py_files: list[str] = []
    for path in root.rglob("*.py"):
        # Check if any parent directory should be excluded
        parts = path.relative_to(root).parts
        if any(part in exclude_dirs or part.endswith(".egg-info") for part in parts):
            continue
        rel = str(path.relative_to(root))
        # Normalize to forward slashes
        py_files.append(rel.replace(os.sep, "/"))

    py_files.sort()
    return py_files


def compute_file_hash(content: bytes) -> str:
    """Compute sha256 hex digest of file content.

    Args:
        content: Raw file bytes.

    Returns:
        SHA-256 hex digest string.
    """
    return hashlib.sha256(content).hexdigest()
