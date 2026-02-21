# Tool 1 Detailed Plan — AST Structural Engine

## Tool identity

- Name: `get_ast_dependencies`
- Goal: produce the base structural graph (nodes + edges) with exact evidence spans.
- Priority: foundational and mandatory for all impact reasoning.

---

## 1) Input contract (inside envelope `inputs`)

```json
{
  "target_files": ["path/to/file.py"],
  "options": {
    "include_references": false,
    "include_import_edges": true,
    "include_call_edges": true,
    "include_inheritance_edges": true,
    "resolve_imports": true,
    "resolve_calls": true,
    "max_edges_per_file": 5000,
    "max_snippet_chars": 240,
    "parse_mode": "tree_sitter"
  }
}
```

---

## 2) Output contract (inside envelope `result`)

- `files[]`: parse status + hash per file
- `nodes[]`: module/class/function/method symbols
- `edges[]`: `imports|calls|inherits|references`
- `diagnostics[]`: syntax/resolution warnings/errors
- `stats`: parse/edge counts + cache stats

### key invariants

- lines are 1-based
- columns are 0-based
- confidence in `[0.0, 1.0]`
- every edge has source evidence range

---

## 3) Internal implementation plan

### core functions

1. `load_and_hash_files(target_files)`
2. `parse_python_file(file_content, parse_mode)`
3. `build_symbol_table(ast_or_tree)`
4. `emit_nodes(symbol_table)`
5. `emit_edges(symbol_table, options)`
6. `resolve_targets(edge_candidates, symbol_index)`
7. `finalize_and_sort(nodes, edges, diagnostics)`

### algorithm

1. Normalize and validate `target_files`.
2. Hash file content and fetch per-file parse cache.
3. Parse file and collect definitions/imports/calls/inheritance references.
4. Build per-file and cross-file symbol index.
5. Emit nodes.
6. Emit edges with resolution state:
   - `resolved`
   - `ambiguous`
   - `unresolved`
7. Assign confidence by resolution strategy.
8. Sort deterministically and return structured result.

---

## 4) Caching and determinism

### caching

- per-file cache key: `sha256(file_hash + parse_mode + tool_impl_version)`
- query cache key: envelope-level canonical key

### determinism

- stable node IDs from qualified symbol + file + span hash
- stable edge IDs from `(source, type, target_ref, span)` hash
- sorted outputs:
  - nodes by `id`
  - edges by `(source, type, target, id)`

---

## 5) Failure handling

- Syntax error: keep partial graph for file + diagnostic entry.
- Missing file: structured error + continue with other files.
- Timeout or cap exceeded: set diagnostic and truncate deterministically.

---

## 6) Acceptance checklist (MVP)

1. Route handlers appear as function nodes.
2. Import/call/inheritance edges are emitted with evidence ranges.
3. Repeated runs on unchanged repo yield identical ordering and IDs.
4. Unresolved targets are explicit (not silently ignored).

---

## 7) Stretch improvements

- deeper call resolution for attribute chains
- name binding across dynamic imports
- reference edge sub-kinds with richer metadata
