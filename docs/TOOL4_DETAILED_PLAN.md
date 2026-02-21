# Tool 4 Detailed Plan — Temporal Coupling

## Tool identity

- Name: `get_historical_coupling`
- Goal: surface files that frequently co-change with target files.
- Role: implicit dependency signal for review prioritization.

---

## 1) Input contract (inside envelope `inputs`)

```json
{
  "file_paths": ["app/api/orders.py"],
  "options": {
    "max_files": 20,
    "window_commits": 500,
    "follow_renames": true,
    "exclude_merges": true,
    "max_commit_size": 200
  }
}
```

---

## 2) Output contract (inside envelope `result`)

- `targets[]`
- `couplings[]`
- `history_stats`

### coupling item fields

- `file`
- `weight` (0..1)
- `support` (# commits)
- `example_commits[]` (sha/date/message)

---

## 3) Internal implementation plan

1. Validate `file_paths[]` and resolve repo-relative paths.
2. Collect history via `git log --name-status -M` (bounded by window).
3. Build commit-to-files sets after filters:
   - optionally drop merge commits
   - drop very large commits above threshold
   - normalize rename paths
4. For each target file, compute co-change scores.
5. Rank and emit top coupled files with evidence commits.

### recommended score

- weighted conditional co-change with commit-size normalization.
- preserve deterministic rounding and ordering.

---

## 4) Caching and determinism

### caching

- parsed log snapshot cache keyed by `(HEAD, options_hash)`
- query cache keyed by `(sorted(file_paths), options, repo_fingerprint)`

### determinism

- stable path normalization
- fixed filter order
- tie-break sort `(weight desc, support desc, file asc)`

---

## 5) Failure handling

- no `.git`: return structured limitation `git_history_unavailable`.
- shallow history: warning `low_history_support`.
- missing target file in history: return empty couplings for that file, no hard failure.

---

## 6) Acceptance checklist (MVP)

1. Returns ranked coupled files for a known changed file.
2. Includes evidence commit examples.
3. Handles rename scenarios in bounded way.
4. Degrades cleanly when git metadata is unavailable.

---

## 7) Stretch improvements

- PR-level coupling
- time-decay score weighting
- package/folder-level aggregation views
