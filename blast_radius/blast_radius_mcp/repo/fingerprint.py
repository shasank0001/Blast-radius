"""Repository fingerprinting for cache invalidation."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from blast_radius_mcp.repo.io import compute_file_hash, glob_python_files, safe_read_file
from blast_radius_mcp.schemas.common import RepoFingerprint


def _get_git_head(repo_root: str) -> str | None:
    """Read HEAD commit hash from .git directory.

    Args:
        repo_root: Path to the repository root.

    Returns:
        HEAD commit SHA hex string, or None if not a git repo.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _is_dirty(repo_root: str) -> bool:
    """Check if the repo has uncommitted changes.

    Args:
        repo_root: Path to the repository root.

    Returns:
        True if the repo is dirty or if git is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    # Default to dirty if we can't determine status
    return True


def _compute_content_fingerprint(repo_root: str) -> str:
    """Hash all *.py files to create a content-based fingerprint.

    1. Get sorted list of repo-relative Python file paths.
    2. For each file, compute sha256 of its content.
    3. Combine all (path, hash) pairs into a final sha256.

    Args:
        repo_root: Path to the repository root.

    Returns:
        SHA-256 hex digest of the combined file hashes.
    """
    py_files = glob_python_files(repo_root)

    h = hashlib.sha256()
    for rel_path in py_files:
        try:
            content = safe_read_file(repo_root, rel_path)
            file_hash = compute_file_hash(content)
            # Include both path and hash for fingerprint
            h.update(f"{rel_path}:{file_hash}\n".encode("utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            # Skip files that can't be read (permissions, etc.)
            continue

    return h.hexdigest()


def compute_repo_fingerprint(repo_root: str) -> RepoFingerprint:
    """Compute a deterministic fingerprint of the repository state.

    Combines git HEAD (if available), dirty flag, and a content hash
    of all Python files.

    Args:
        repo_root: Path to the repository root.

    Returns:
        RepoFingerprint with git_head, dirty flag, and fingerprint_hash.
    """
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise ValueError(f"repo_root is not a directory: {repo_root!r}")

    git_head = _get_git_head(str(root))
    dirty = _is_dirty(str(root))
    content_fp = _compute_content_fingerprint(str(root))

    # Combine git_head + dirty + content hash for the final fingerprint
    fp_input = f"{git_head or 'none'}:{dirty}:{content_fp}"
    fingerprint_hash = hashlib.sha256(fp_input.encode("utf-8")).hexdigest()

    return RepoFingerprint(
        git_head=git_head,
        dirty=dirty,
        fingerprint_hash=fingerprint_hash,
    )
