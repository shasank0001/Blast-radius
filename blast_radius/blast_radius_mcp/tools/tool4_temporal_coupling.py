"""Tool 4 — Temporal Coupling Engine (``get_historical_coupling``).

Analyses git commit history to discover files that frequently change together
with the target files.  The implementation:

1. Parses ``git log --name-status`` output to extract commits with file
   changes (additions, modifications, deletions, renames).
2. Builds rename chains so that files can be tracked across renames.
3. Computes conditional co-change probabilities for each target file,
   normalized by commit size to reduce noise from large bulk commits.
4. Assembles a deterministic ``Tool4Result`` with ranked couplings,
   history statistics, and diagnostics.

All outputs are deterministic — identical inputs always produce identical
output.  No network access is required; only the local ``.git`` directory
is inspected.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from blast_radius_mcp.schemas.tool4_coupling import (
    Coupling,
    CouplingTarget,
    ExampleCommit,
    HistoryStats,
    Tool4Diagnostic,
    Tool4Result,
)

logger = logging.getLogger(__name__)

# ── Module-level constants ───────────────────────────────────────────

TOOL4_IMPL_VERSION = "1.0.0"

# Maximum number of example commits to include per coupling relationship.
_MAX_EXAMPLE_COMMITS = 3

# Minimum number of commits below which we emit a ``low_history_support``
# diagnostic.
_LOW_HISTORY_THRESHOLD = 10


# ── Deterministic ID helper ─────────────────────────────────────────


def _sha256_prefix(prefix: str, *parts: str, length: int = 16) -> str:
    """Return *prefix* followed by the first *length* hex chars of a SHA-256
    digest computed from the joined *parts*."""
    h = hashlib.sha256("|".join(parts).encode("utf-8"))
    return f"{prefix}{h.hexdigest()[:length]}"


# ── Path normalisation ───────────────────────────────────────────────


def _normalize_path(raw: str) -> str:
    """Normalize a file path for consistent comparison.

    - Converts backslashes to forward slashes.
    - Strips leading ``./``.
    - Applies ``os.path.normpath`` to collapse ``..`` and redundant separators.
    """
    p = raw.replace("\\", "/")
    p = os.path.normpath(p)
    # os.path.normpath may introduce OS-specific separators on Windows.
    p = p.replace("\\", "/")
    # Strip leading "./" that normpath may leave behind.
    if p.startswith("./"):
        p = p[2:]
    return p


# ── Data classes for internal git log representation ────────────────


@dataclass
class FileChange:
    """A single file status line from ``git log --name-status``."""

    status: str  # A, M, D, R (possibly with score, e.g. R100)
    path: str  # Normalized file path
    old_path: str | None = None  # Only set for renames (status starts with R)


@dataclass
class Commit:
    """Parsed representation of one git commit."""

    sha: str
    date: str
    message: str
    files: list[FileChange] = field(default_factory=list)


@dataclass
class _CouplingEvidence:
    """Accumulator for co-change evidence between a target and a coupled file."""

    co_change_count: float = 0.0  # Size-normalized count
    raw_support: int = 0  # Raw number of commits where both appear
    example_commits: list[Commit] = field(default_factory=list)


# ── Git log parsing ─────────────────────────────────────────────────


def _build_git_log_command(
    repo_root: str,
    window_commits: int,
    exclude_merges: bool,
) -> list[str]:
    """Construct the ``git log`` command argument list.

    Uses fixed argument lists (no shell interpolation) for security.
    """
    cmd = [
        "git",
        "-C", repo_root,
        "log",
        "--name-status",
        "-M",  # Detect renames
        "--format=%H|%aI|%s",
        f"-n{window_commits}",
    ]
    if exclude_merges:
        cmd.append("--no-merges")
    return cmd


def _parse_rename_path(status_field: str, fields: list[str]) -> FileChange:
    """Parse a rename status line.

    Rename lines have the format::

        R100\told_path\tnew_path

    Returns a :class:`FileChange` with both ``old_path`` and ``path`` set.
    """
    if len(fields) >= 3:
        old = _normalize_path(fields[1])
        new = _normalize_path(fields[2])
    elif len(fields) == 2:
        # Fallback: treat as move with same name
        old = _normalize_path(fields[1])
        new = old
    else:
        old = ""
        new = ""
    return FileChange(status=status_field, path=new, old_path=old)


def _parse_file_status_line(line: str) -> FileChange | None:
    """Parse a single file status line from ``git log --name-status``.

    Returns ``None`` if the line is not a valid status line.
    """
    line = line.rstrip()
    if not line:
        return None

    parts = line.split("\t")
    if len(parts) < 2:
        return None

    status = parts[0].strip()
    if not status:
        return None

    first_char = status[0].upper()

    if first_char == "R":
        return _parse_rename_path(status, parts)
    elif first_char in ("A", "M", "D", "C", "T"):
        return FileChange(status=status, path=_normalize_path(parts[1]))
    else:
        # Unknown status — skip gracefully.
        logger.debug("Skipping unknown git status line: %r", line)
        return None


def parse_git_log(
    repo_root: str,
    window_commits: int = 500,
    exclude_merges: bool = True,
    max_commit_size: int = 200,
) -> tuple[list[Commit], int]:
    """Run ``git log`` and parse the output into a list of :class:`Commit`.

    Args:
        repo_root: Absolute path to the repository root.
        window_commits: Number of recent commits to scan.
        exclude_merges: Whether to exclude merge commits.
        max_commit_size: Drop commits that touch more files than this.

    Returns:
        A tuple ``(commits, scanned_count)`` where *commits* is the list
        of usable commits (after filtering) and *scanned_count* is the
        total number of commits parsed from git output.

    Raises:
        subprocess.CalledProcessError: If ``git log`` fails.
        FileNotFoundError: If the ``git`` binary is not found.
    """
    cmd = _build_git_log_command(repo_root, window_commits, exclude_merges)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )

    lines = result.stdout.splitlines()
    raw_commits: list[Commit] = []
    current_commit: Commit | None = None

    for line in lines:
        # Commit header line: "sha|date|message"
        if "|" in line and not line[0].isspace() and "\t" not in line:
            # Potentially a header line — validate it has the expected format.
            header_parts = line.split("|", 2)
            if len(header_parts) >= 3 and len(header_parts[0]) == 40:
                # Looks like a valid commit header.
                if current_commit is not None:
                    raw_commits.append(current_commit)
                sha = header_parts[0]
                date = header_parts[1]
                message = header_parts[2] if len(header_parts) > 2 else ""
                current_commit = Commit(
                    sha=sha, date=date, message=message
                )
                continue

        # File status line
        if current_commit is not None:
            fc = _parse_file_status_line(line)
            if fc is not None:
                current_commit.files.append(fc)

    # Don't forget the last commit.
    if current_commit is not None:
        raw_commits.append(current_commit)

    scanned_count = len(raw_commits)

    # Filter out oversized commits.
    commits = [c for c in raw_commits if len(c.files) <= max_commit_size]

    logger.info(
        "Parsed %d commits from git log, %d after filtering (max_commit_size=%d)",
        scanned_count,
        len(commits),
        max_commit_size,
    )

    return commits, scanned_count


# ── Rename tracking ─────────────────────────────────────────────────


def build_rename_map(
    commits: list[Commit],
    follow_renames: bool = True,
) -> tuple[dict[str, set[str]], int]:
    """Build a bidirectional alias map from rename operations in commits.

    For every rename ``old → new``, both ``old`` and ``new`` are grouped
    into the same alias set.  If ``follow_renames`` is ``False``, returns
    an empty map.

    Args:
        commits: Parsed commit list.
        follow_renames: Whether to actually follow renames.

    Returns:
        A tuple ``(alias_map, renames_followed)`` where *alias_map* maps
        every known path to its full set of aliases (including itself),
        and *renames_followed* is the total number of rename operations
        found.
    """
    if not follow_renames:
        return {}, 0

    # Union-Find style grouping: map each path to a canonical representative.
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])  # Path compression
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    renames_followed = 0

    for commit in commits:
        for fc in commit.files:
            if fc.old_path is not None:
                # This is a rename.
                union(fc.old_path, fc.path)
                renames_followed += 1

    # Build the alias sets.
    groups: dict[str, set[str]] = defaultdict(set)
    all_paths: set[str] = set()
    for commit in commits:
        for fc in commit.files:
            all_paths.add(fc.path)
            if fc.old_path is not None:
                all_paths.add(fc.old_path)

    for p in all_paths:
        root = find(p)
        groups[root].add(p)

    alias_map: dict[str, set[str]] = {}
    for root, members in groups.items():
        for m in members:
            alias_map[m] = members

    return alias_map, renames_followed


# ── Co-change scoring ───────────────────────────────────────────────


def _get_all_aliases(path: str, alias_map: dict[str, set[str]]) -> set[str]:
    """Return all known aliases for *path*, including itself."""
    aliases = alias_map.get(path, set())
    if not aliases:
        return {path}
    return aliases


def _files_in_commit(commit: Commit) -> set[str]:
    """Return the set of all file paths touched in *commit*.

    For renames, both old and new paths are included.
    """
    result: set[str] = set()
    for fc in commit.files:
        result.add(fc.path)
        if fc.old_path is not None:
            result.add(fc.old_path)
    return result


def compute_coupling(
    target_file: str,
    commits: list[Commit],
    alias_map: dict[str, set[str]],
    max_files: int = 20,
) -> tuple[list[Coupling], int, list[str]]:
    """Compute temporal coupling scores for a single target file.

    For each commit that touches *target_file* (or any of its aliases),
    we record all other files that co-changed.  The coupling weight is
    the conditional probability ``P(coupled | target_changed)``,
    normalized by the commit size to reduce the influence of large
    refactoring commits.

    Args:
        target_file: The file to compute couplings for.
        commits: Filtered commit list.
        alias_map: Alias map from :func:`build_rename_map`.
        max_files: Maximum number of coupled files to return.

    Returns:
        A tuple ``(couplings, support_commits, aliases)`` where:
        - *couplings* is a ranked list of :class:`Coupling` objects.
        - *support_commits* is total commits touching the target.
        - *aliases* is the list of known aliases for the target file.
    """
    target_aliases = _get_all_aliases(target_file, alias_map)
    aliases_list = sorted(a for a in target_aliases if a != target_file)

    # Find all commits that include the target (or any alias).
    target_commits: list[Commit] = []
    for commit in commits:
        commit_files = _files_in_commit(commit)
        if target_aliases & commit_files:
            target_commits.append(commit)

    support_commits = len(target_commits)

    if support_commits == 0:
        return [], 0, aliases_list

    # Accumulate co-change evidence.
    evidence: dict[str, _CouplingEvidence] = defaultdict(_CouplingEvidence)

    for commit in target_commits:
        commit_files = _files_in_commit(commit)
        commit_size = len(commit_files)
        # Size normalization factor: divide contribution by sqrt(commit_size)
        # to reduce noise from large bulk commits.
        size_factor = 1.0 / math.sqrt(max(commit_size, 1))

        for f in commit_files:
            # Skip the target file itself and its aliases.
            if f in target_aliases:
                continue

            # Resolve the coupled file to its canonical (latest) name.
            canonical = f
            coupled_aliases = _get_all_aliases(f, alias_map)
            if coupled_aliases:
                # Use the lexicographically last alias as canonical (often
                # the newest name after renames).
                canonical = sorted(coupled_aliases)[-1]

            ev = evidence[canonical]
            ev.co_change_count += size_factor
            ev.raw_support += 1
            if len(ev.example_commits) < _MAX_EXAMPLE_COMMITS:
                # Avoid duplicate commits in examples.
                if not any(ec.sha == commit.sha for ec in ev.example_commits):
                    ev.example_commits.append(commit)

    # Compute weights: conditional probability, normalized by commit size.
    # weight = normalized_co_change_count / normalized_target_count
    # We use the same size normalization for the denominator.
    target_norm = sum(
        1.0 / math.sqrt(max(len(_files_in_commit(c)), 1))
        for c in target_commits
    )
    if target_norm == 0:
        target_norm = 1.0

    couplings_raw: list[tuple[str, float, int, list[Commit]]] = []
    for coupled_file, ev in evidence.items():
        weight = ev.co_change_count / target_norm
        # Clamp to [0, 1] and round for determinism.
        weight = round(min(max(weight, 0.0), 1.0), 4)
        couplings_raw.append(
            (coupled_file, weight, ev.raw_support, ev.example_commits)
        )

    # Deterministic sort: weight desc, support desc, file asc.
    couplings_raw.sort(key=lambda x: (-x[1], -x[2], x[0]))

    # Truncate to max_files.
    couplings_raw = couplings_raw[:max_files]

    # Build Coupling objects.
    couplings: list[Coupling] = []
    for coupled_file, weight, support, example_commits in couplings_raw:
        examples = [
            ExampleCommit(
                sha=c.sha[:12],
                date=c.date,
                message=c.message[:120],
            )
            for c in example_commits[:_MAX_EXAMPLE_COMMITS]
        ]
        couplings.append(
            Coupling(
                target_file=target_file,
                coupled_file=coupled_file,
                weight=weight,
                support=support,
                example_commits=examples,
            )
        )

    return couplings, support_commits, aliases_list


# ── Main entry point ────────────────────────────────────────────────


def run_tool4(validated_inputs: dict, repo_root: str) -> dict:
    """Execute Tool 4 — Temporal Coupling Analysis.

    Orchestrates the full pipeline:

    1. Validate that target file paths exist (relative to *repo_root*).
    2. Check for a ``.git`` directory.
    3. Parse ``git log`` output.
    4. Build rename mappings.
    5. Compute coupling scores for each target file.
    6. Assemble ``CouplingTarget`` and ``Coupling`` objects.
    7. Attach diagnostics for edge cases.

    Args:
        validated_inputs: A dict with keys ``file_paths`` (list[str]) and
            optionally ``options`` (dict) matching :class:`Tool4Options`.
        repo_root: Absolute or relative path to the repository root.

    Returns:
        A ``dict`` matching ``Tool4Result.model_dump(by_alias=True)``.
    """
    diagnostics: list[Tool4Diagnostic] = []

    # ── Extract inputs ───────────────────────────────────────────────
    file_paths_raw: list[str] = validated_inputs.get("file_paths", [])
    options: dict = validated_inputs.get("options", {})

    max_files: int = options.get("max_files", 20)
    window_commits: int = options.get("window_commits", 500)
    follow_renames: bool = options.get("follow_renames", True)
    exclude_merges: bool = options.get("exclude_merges", True)
    max_commit_size: int = options.get("max_commit_size", 200)

    # Normalize target file paths.
    file_paths = [_normalize_path(fp) for fp in file_paths_raw]

    # ── 1. Validate file paths exist ─────────────────────────────────
    valid_paths: list[str] = []
    for fp in file_paths:
        abs_path = os.path.join(repo_root, fp)
        if os.path.isfile(abs_path):
            valid_paths.append(fp)
        else:
            diagnostics.append(
                Tool4Diagnostic(
                    severity="warning",
                    code="target_not_in_history",
                    message=f"Target file does not exist: {fp}",
                )
            )

    valid_path_set = set(valid_paths)

    # ── 2. Check for .git directory ──────────────────────────────────
    git_dir = os.path.join(repo_root, ".git")
    if not os.path.isdir(git_dir):
        logger.warning("No .git directory found at %s", git_dir)
        diagnostics.append(
            Tool4Diagnostic(
                severity="error",
                code="git_history_unavailable",
                message=f"No .git directory found in {repo_root}",
            )
        )
        result = Tool4Result(
            targets=[
                CouplingTarget(file=fp, aliases=[], support_commits=0)
                for fp in file_paths
            ],
            couplings=[],
            history_stats=HistoryStats(
                commits_scanned=0,
                commits_used=0,
                renames_followed=0,
            ),
            diagnostics=diagnostics,
        )
        return result.model_dump(by_alias=True)

    # ── 3. Parse git log ─────────────────────────────────────────────
    try:
        commits, scanned_count = parse_git_log(
            repo_root=repo_root,
            window_commits=window_commits,
            exclude_merges=exclude_merges,
            max_commit_size=max_commit_size,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.error("Failed to parse git log: %s", exc)
        diagnostics.append(
            Tool4Diagnostic(
                severity="error",
                code="git_history_unavailable",
                message=f"Failed to run git log: {exc}",
            )
        )
        result = Tool4Result(
            targets=[
                CouplingTarget(file=fp, aliases=[], support_commits=0)
                for fp in file_paths
            ],
            couplings=[],
            history_stats=HistoryStats(
                commits_scanned=0,
                commits_used=0,
                renames_followed=0,
            ),
            diagnostics=diagnostics,
        )
        return result.model_dump(by_alias=True)
    except subprocess.TimeoutExpired as exc:
        logger.error("Git log timed out: %s", exc)
        diagnostics.append(
            Tool4Diagnostic(
                severity="error",
                code="git_history_unavailable",
                message="git log timed out after 60 seconds",
            )
        )
        result = Tool4Result(
            targets=[
                CouplingTarget(file=fp, aliases=[], support_commits=0)
                for fp in file_paths
            ],
            couplings=[],
            history_stats=HistoryStats(
                commits_scanned=0,
                commits_used=0,
                renames_followed=0,
            ),
            diagnostics=diagnostics,
        )
        return result.model_dump(by_alias=True)

    commits_used = len(commits)

    # ── 4. Build rename mappings ─────────────────────────────────────
    alias_map, renames_followed = build_rename_map(commits, follow_renames)

    # ── 5. Compute coupling scores for each target file ──────────────
    all_targets: list[CouplingTarget] = []
    all_couplings: list[Coupling] = []

    for fp in file_paths:
        if fp in valid_path_set:
            couplings, support, aliases = compute_coupling(
                target_file=fp,
                commits=commits,
                alias_map=alias_map,
                max_files=max_files,
            )
        else:
            couplings, support, aliases = [], 0, []

        # ── 6. Build CouplingTarget ─────────────────────────────────
        all_targets.append(
            CouplingTarget(
                file=fp,
                aliases=aliases,
                support_commits=support,
            )
        )
        all_couplings.extend(couplings)

        # ── 9. target_not_in_history diagnostic ─────────────────────
        if support == 0:
            diagnostics.append(
                Tool4Diagnostic(
                    severity="warning",
                    code="target_not_in_history",
                    message=(
                        f"Target file '{fp}' was not found in the "
                        f"analysed git history ({commits_used} commits)."
                    ),
                )
            )

    # ── 8. Low history support diagnostic ────────────────────────────
    if commits_used < _LOW_HISTORY_THRESHOLD:
        diagnostics.append(
            Tool4Diagnostic(
                severity="warning",
                code="low_history_support",
                message=(
                    f"Only {commits_used} commits were usable out of "
                    f"{scanned_count} scanned.  Coupling weights may be "
                    f"unreliable."
                ),
            )
        )

    # ── 7. History window truncation diagnostic ──────────────────────
    if scanned_count >= window_commits:
        diagnostics.append(
            Tool4Diagnostic(
                severity="info",
                code="history_window_truncated",
                message=(
                    f"Scanned the maximum {window_commits} commits.  "
                    f"Older history was not analysed."
                ),
            )
        )

    # ── 10. Assemble and return Tool4Result ──────────────────────────
    # Compute date_range from commit dates.
    if commits:
        dates = sorted(c.date for c in commits)
        earliest = dates[0][:10]
        latest = dates[-1][:10]
        date_range = f"{earliest} to {latest}"
    else:
        date_range = ""

    # Compute files_in_history: unique file paths across all commits.
    all_files_seen: set[str] = set()
    for c in commits:
        for fc in c.files:
            all_files_seen.add(fc.path)
            if fc.old_path is not None:
                all_files_seen.add(fc.old_path)
    files_in_history = len(all_files_seen)

    history_stats = HistoryStats(
        commits_scanned=scanned_count,
        commits_used=commits_used,
        renames_followed=renames_followed,
        date_range=date_range,
        files_in_history=files_in_history,
    )

    result = Tool4Result(
        targets=all_targets,
        couplings=all_couplings,
        history_stats=history_stats,
        diagnostics=diagnostics,
    )

    return result.model_dump(by_alias=True)
