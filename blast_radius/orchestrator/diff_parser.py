from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict


class DiffResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed_files: list[str] = []
    added_lines: dict[str, list[int]] = {}
    removed_lines: dict[str, list[int]] = {}
    key_identifiers: list[str] = []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_HUNK_RE = re.compile(
    r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@"
)

_FUNC_RE = re.compile(r"\bdef\s+([A-Za-z_]\w*)\s*\(")
_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_]\w*)")
_ASSIGN_RE = re.compile(r"^[ \t]*([A-Za-z_]\w*)\s*[=:]")
_SELF_ATTR_RE = re.compile(r"\bself\.([A-Za-z_]\w*)")
_UNDERSCORE_ID_RE = re.compile(r"\b([A-Za-z_]\w*_\w+)\b")


def _strip_prefix(path: str) -> str | None:
    """Strip the leading ``a/`` or ``b/`` prefix from a diff path.

    Returns *None* for ``/dev/null`` so the caller can skip it.
    """
    if path == "/dev/null":
        return None
    for prefix in ("a/", "b/"):
        if path.startswith(prefix):
            return path[len(prefix):]
    return path


def _extract_identifiers(line: str) -> list[str]:
    """Return deduplicated identifiers found in a single changed line."""
    ids: list[str] = []
    for regex in (_FUNC_RE, _CLASS_RE, _ASSIGN_RE, _SELF_ATTR_RE, _UNDERSCORE_ID_RE):
        ids.extend(regex.findall(line))
    return ids


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_unified_diff(diff: str) -> DiffResult:
    """Parse a git-style unified diff and return a :class:`DiffResult`."""

    if not diff or not diff.strip():
        return DiffResult()

    changed_files_set: set[str] = set()
    added_lines: dict[str, list[int]] = {}
    removed_lines: dict[str, list[int]] = {}
    identifiers_set: set[str] = set()

    lines = diff.splitlines()
    idx = 0
    n_lines = len(lines)

    while idx < n_lines:
        line = lines[idx]

        # ----- detect file header pair -----
        if line.startswith("diff --git"):
            idx += 1
            continue

        # Skip binary file markers
        if line.startswith("Binary files") or line.startswith("GIT binary patch"):
            idx += 1
            continue

        # Skip index / mode / similarity lines
        if line.startswith(("index ", "old mode", "new mode", "similarity", "rename", "copy", "new file", "deleted file")):
            idx += 1
            continue

        if line.startswith("--- "):
            minus_path_raw = line[4:].strip()
            minus_path = _strip_prefix(minus_path_raw)

            plus_path: str | None = None
            if idx + 1 < n_lines and lines[idx + 1].startswith("+++ "):
                plus_path_raw = lines[idx + 1][4:].strip()
                plus_path = _strip_prefix(plus_path_raw)
                idx += 2
            else:
                idx += 1

            # Determine the effective file path for this section
            file_path: str | None = plus_path or minus_path
            if file_path is None:
                # Both sides are /dev/null — nothing useful
                continue

            changed_files_set.add(file_path)
            added_lines.setdefault(file_path, [])
            removed_lines.setdefault(file_path, [])

            # ----- process hunks for this file -----
            while idx < n_lines:
                hunk_line = lines[idx]

                # If we hit another file header, break out
                if hunk_line.startswith(("diff --git", "--- ")):
                    break

                m = _HUNK_RE.match(hunk_line)
                if not m:
                    idx += 1
                    continue

                old_start = int(m.group(1))
                new_start = int(m.group(3))
                idx += 1

                old_cur = old_start
                new_cur = new_start

                while idx < n_lines:
                    cl = lines[idx]

                    # End of hunk: next hunk header, file header, or diff header
                    if cl.startswith(("@@ ", "diff --git", "--- ")):
                        break

                    if cl.startswith("+"):
                        content = cl[1:]
                        added_lines[file_path].append(new_cur)
                        identifiers_set.update(_extract_identifiers(content))
                        new_cur += 1
                    elif cl.startswith("-"):
                        content = cl[1:]
                        removed_lines[file_path].append(old_cur)
                        identifiers_set.update(_extract_identifiers(content))
                        old_cur += 1
                    elif cl.startswith(" "):
                        old_cur += 1
                        new_cur += 1
                    elif cl.startswith("\\"):
                        # "\ No newline at end of file" — skip
                        pass
                    else:
                        # Unknown line outside of hunk context — stop hunk parsing
                        break

                    idx += 1

            continue

        # Handle bare +++ without a preceding --- (shouldn't happen often)
        if line.startswith("+++ "):
            plus_path_raw = line[4:].strip()
            p = _strip_prefix(plus_path_raw)
            if p is not None:
                changed_files_set.add(p)
                added_lines.setdefault(p, [])
                removed_lines.setdefault(p, [])
            idx += 1
            continue

        idx += 1

    # Clean up empty entries
    added_lines = {k: v for k, v in added_lines.items() if v}
    removed_lines = {k: v for k, v in removed_lines.items() if v}

    return DiffResult(
        changed_files=sorted(changed_files_set),
        added_lines=added_lines,
        removed_lines=removed_lines,
        key_identifiers=sorted(identifiers_set),
    )
