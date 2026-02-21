# PRD — Blast Radius (LLM-Augmented Semantic Graph)

## 0) One-liner

Given a codebase and a natural-language change intent (optionally plus a concrete diff/target), generate an engineer-readable “blast radius” report that lists downstream impacts **and** explains *why* with evidence from multiple analysis engines.

## 1) Problem

Small code changes can silently break systems. Developers currently rely on tribal knowledge, manual inspection, and running too many tests.

Static dependency graphs are noisy (“semantic blindness”): they flag links that *exist* but are not *relevant* to the changed behavior/data.

## 2) Goals (Hackathon v1)

1. **End-to-end demo**: A user provides a change intent + target context and receives a structured Markdown report in < 2 minutes on a laptop.
2. **High precision for API payload changes**: Track additions/removals/renames/type changes of request/response fields and identify exact downstream read sites.
3. **Large-repo readiness**: Indexing must be incremental and cached so repeated runs are fast.
4. **Evidence-backed explanations**: Every impacted item must cite the tool evidence used (AST edge, data-shape trace, historical coupling, semantic neighbor, test coverage).

Additional alignment goals (challenge fit):

5. **Support the three change classes**: API change, behavior change, and structural modification. In v1, API/validation changes should be high-precision; structural refactors must at least be covered by AST-level impacts.
6. **Minimal, appropriate graph**: Use a small “base graph” as the source of truth and treat other signals as optional overlays (to avoid an overbuilt graph design).

## 3) Non-goals (v1)

- Not auto-fixing code.
- Not a UI-heavy product (OpenCode CLI + Markdown output is enough).
- Not multi-language support in a single run (we intentionally pick one language for hackathon v1).

## 4) Target users

- Backend engineers changing API contracts, validators, schemas, routing.
- Team leads reviewing risky PRs.
- Hackathon judges evaluating agentic tool orchestration.

## 5) Primary use cases

### UC1 — API field removal

Intent: “Remove `user_id` from the request payload of `POST /orders`.”
Output: Downstream locations that read `user_id`, the functions/classes involved, and tests to run.

### UC2 — Type change

Intent: “Change user id from `int` to `uuid` across services.”
Output: Read/parse/serialize sites, schema validators, DB access patterns likely impacted, and semantically similar parsing utilities.

### UC3 — Behavioral change in validation

Intent: “Relax email validation to allow plus-addressing.”
Output: Callers relying on strict validation, any duplicated validators elsewhere, and likely coupled config/docs.

### UC4 — Structural modification (refactor)

Intent: “Change signature of `parse_user_id(value)` to accept `str` and return `UUID`.”
Output: Call sites, downstream type expectations/serializers, related tests, and any duplicated parsing utilities.

## 6) Inputs

The system accepts **natural language** change intent and optional context.

### 6.1 User-provided inputs (v1)

- **Change intent** (required): natural language, but must be explicit and unambiguous (per challenge prompt).
- **Target anchors** (optional but strongly encouraged): file paths, symbols, endpoints, or entry points.
- **Diff snippet / patch** (optional but expected in demos): **unified diff (git-style)**.

Practical note (demo + robustness):

- The system should produce a report from **intent-only** input, but precision and confidence increase substantially when a diff and/or anchors are provided.
- In intent-only mode, the orchestrator should widen its search scope and label more items as **Unknown** risk with **Low** confidence rather than over-asserting.

Anchor formats (v1):

- **Route anchor**: `POST /orders` (or other HTTP methods).
- **Symbol anchor**: `path/to/file.py:symbol_name`.
- CLI should accept one or more anchors and auto-detect route vs symbol. If ambiguous, allow prefixes like `route:POST /orders` and `symbol:path/to/file.py:symbol_name`.

### 6.2 Internal normalized representation (derived)

Even though the user inputs are natural language, the orchestrator must normalize them into a structured internal hypothesis to keep the system deterministic and explainable.

- **`ChangeSpec` (derived)**: a structured change descriptor extracted from intent (+ anchors/diff when available). Example fields:
  - `change_class`: `api_change | behavior_change | structural_change`
  - `entity_kind`: `field | function | validator | schema | route | module`
  - `entity_id`: e.g., `POST /orders`, `OrderRequest.user_id`, `parse_user_id`
  - `operation`: `add | remove | rename | type_change | relax | tighten | refactor`
  - `field_path` (when relevant): e.g., `request.user_id`
  - `from_type` / `to_type` (when relevant)
  - `notes`: free-text constraints extracted from intent

## 7) Outputs

### 7.1 Report format (v1)

- A single **Markdown** report (rendered in OpenCode) with sections:
  - Executive summary
  - Impacted areas (grouped by evidence type)
  - “Why” explanations (evidence-backed)
  - Suggested tests
  - Unknown risk zones
  - Confidence and assumptions

### 7.2 Report quality bars

- Every impacted item has:
  - **Impact risk** (breaking risk, behavior change risk, unknown)
  - **Impact surface** (API-level, business logic, data handling, contract compatibility, tests, docs, unknown)
  - **Reason** (plain English)
  - **Evidence** (tool outputs; file/symbol references)
  - **Confidence** (High/Med/Low)
  - **Suggested action** (run tests, review module, update schema, etc.)

## 8) Product principles

- **Evidence-first**: The LLM cannot claim impact without tool-backed evidence.
- **Prune aggressively**: Prefer missing a low-confidence edge over overwhelming the engineer.
- **Deterministic tooling**: Tools should be deterministic, cacheable, and testable.
- **Pluggable LLM**: The orchestrator model is “whatever OpenCode uses”; tools must not assume a specific vendor.
- **No “semantic-only” impacts**: Semantic similarity can suggest *where to look*, but does not count as an impact unless corroborated by structural or data-shape evidence.

## 9) System overview

The system is an **agentic gateway**:

- OpenCode LLM = orchestrator (“brain”)
- Five tool backends = specialized “senses”
- Orchestrator merges evidence into an **LLM-Augmented Semantic Graph** and emits a blast radius report.

### 9.1 Graph model (challenge-aligned, minimal-first)

We represent the codebase as a **graph-based model**, but keep it minimal and appropriate:

- **Base graph (required)**
  - **Structural graph**: AST dependencies, call edges, inheritance, symbol references.
  - **Data-shape edges (when applicable)**: field-path reads/writes/validation/transform edges for API and schema changes.

- **Evidence overlays (optional, non-authoritative)**
  - **Semantic neighbors**: similar code for “unknown risk zones”.
  - **Temporal coupling**: files that historically co-change.
  - **Test coverage**: tests likely to exercise impacted paths.

The orchestrator builds a candidate set of impacted nodes from the base graph, then enriches and **prunes** using:

- Relevance to the intent/diff
- Field-path specificity (only edges that touch the changed field/path)
- Confidence thresholds
- Corroboration rules (semantic-only signals do not create “impacts”)

## 10) Tooling (MCP) — v1 APIs

All tools are exposed via MCP. Each tool must return **structured JSON** with stable schemas.

### 10.0 Language scope (v1)

Hackathon v1 targets **one language** for determinism and demo quality.

- Supported language (v1): **Python** repositories.
- Framework focus (for payload tracing): **FastAPI/Starlette + Pydantic** when present.
- Other languages/frameworks are out of scope for v1.

### Tool 1 — AST Structural Engine

**Command:** `get_ast_dependencies(target_files)`

**Purpose:** Hard structural truth: imports, definitions, call edges, inheritance, symbol references.

**Mechanism:** Tree-sitter incremental parsing + symbol table.

**Minimum schema:**

- `nodes`: list of symbols (`module`, `class`, `function`, `method`)
- `edges`: typed edges (`imports`, `calls`, `inherits`, `references`)
- `locations`: file, start/end offsets (line/col if available)
- `hashes`: file content hash for caching

See: `docs/TOOL1_SCHEMA.md` for a concrete, stable JSON contract (v1).

**MVP precision focus:**

- Python: imports, function defs, call sites, class inheritance.

### Tool 2 — Data Lineage Engine (API payload shapes)

**Command:** `trace_data_shape(field_path, entry_points[])`

**Purpose:** High-precision impacts for API contract changes: trace where a field is **introduced**, **renamed**, **validated**, **passed**, and **read**.

**Mechanism (Python-first):**

- Parse FastAPI/Starlette handlers and Pydantic models when present.
- Identify field-path reads via:
  - attribute access (`obj.user_id`)
  - dict subscripts with string literals (`payload["user_id"]`, `payload.get("user_id")`)
  - Pydantic access (`model.user_id`), `.model_dump()`, `.dict()`
- Build a field-path graph: `request -> validate -> transform -> outbound`.

**Output expectations:**

- Exact read-sites with location and enclosing symbol.
- Transform steps: rename, type cast, defaulting.
- A “breaks if removed/renamed” flag at each read.

### Tool 3 — Semantic Vector Search

**Command:** `find_semantic_neighbors(query_text)`

**Purpose:** Find “unknown impact zones” with conceptual similarity but no explicit structural link.

**Rules:** Results from this tool populate “unknown risk zones” unless corroborated by Tool 1 or Tool 2 evidence.

**Mechanism:**

- Embed functions/modules into vectors.
- Query by diff snippet/intent.

**Pragmatic v1 plan:**

- Use OpenAI embeddings + Pinecone as primary retrieval.
- Fall back to BM25 when embedding/vector services are unavailable.
- Return top neighbors with similarity score and rationale snippet.

### Tool 4 — Temporal Coupling Graph (Git archaeology)

**Command:** `get_historical_coupling(file_paths[])`

**Purpose:** Replace tribal knowledge by learning co-change patterns.

**Mechanism:**

- Mine `git log` and compute co-change weights between files.

**Output expectations:**

- Top coupled files with weight (% of commits/PRs) and examples.

See: `docs/TOOL2_SCHEMA.md`, `docs/TOOL3_SCHEMA.md`, and `docs/TOOL4_SCHEMA.md` for concrete, stable JSON contracts (v1).

### Tool 5 — Test Impact Analyzer

**Command:** `get_covering_tests(impacted_nodes_list)`

**Purpose:** Provide a minimal test set that best validates the blast-radius hypothesis.

**Mechanism (v1 options):**

- Static mapping: tests importing impacted modules/symbols.
- Optional dynamic enhancement: coverage.py for a focused subset if runnable.

**Output expectations:**

- Ranked tests with reason (import path, call edge, historical failure proximity).

See: `docs/TOOL5_SCHEMA.md` for a concrete, stable JSON contract and the recommended v1 implementation plan.

## 11) Orchestrator responsibilities (OpenCode LLM)

1. Parse the intent into a **change hypothesis**: what entity changes (field/type/behavior), and what evidence is needed.
  - Emit a derived `ChangeSpec` that drives subsequent tool calls.
2. Select which tools to call (not all every time).
  - If a unified diff is provided, use it to seed changed files/symbols.
  - If only NL is provided, attempt anchor discovery (route/symbol lookup). If no reliable entry point is found, prefer conservative “unknown risk zone” output over speculative impacts.
3. Merge tool outputs into a candidate impact set.
4. Prune false positives by intent relevance and field specificity.
  - Run Tool 2 (data lineage) when the `ChangeSpec` indicates an API/schema/field/validation change and there is a usable entry point; avoid global payload tracing in NL-only mode without anchors.
5. Generate the Markdown report with evidence-backed “why.”

## 12) Large repo performance requirements

- Indexing must be incremental:
  - Cache parsed ASTs by file hash.
  - Store symbol index + edges in SQLite.
  - Recompute only changed files.
- Semantic index must be incrementally updateable.
- Typical operations:
  - First-time index: acceptable to take longer.
  - Subsequent runs: must be fast.

Note: v1 performance targets apply to the chosen single-language implementation (Python).

## 13) Success metrics (v1)

- **Precision proxy**: In curated demos, ≥ 70% of listed impacts are judged “relevant” by an engineer.
- **Time-to-report**: < 2 minutes after indexing.
- **Actionability**: Report recommends ≤ 10 tests for typical change.
- **Evidence coverage**: ≥ 90% of impacts have at least 2 evidence types (e.g., AST + data lineage).

## 14) Acceptance criteria

- Given a repo (Python) + a clearly specified natural-language change intent (and optional anchors/diff), the system outputs a Markdown report that includes:
  - impacted APIs and/or symbols (direct and indirect)
  - impacted modules/functions/classes grouped by evidence type
  - an impact classification that includes both **impact risk** and **impact surface**
  - at least one data-shape trace when the intent is an API/schema/field change
  - at least one semantic neighbor recommendation labeled as “unknown risk zone”
  - historical coupling suggestions (if `.git` exists)
  - ranked tests
  - confidence + assumptions, with evidence references

## 15) Milestones (hackathon-friendly)

1. **Day 1 — Core indexing + Tool 1**
   - Tree-sitter parser, symbol index, AST edges.
2. **Day 2 — Tool 2 (payload field tracing)**
   - FastAPI/Pydantic heuristics; field-path tracing.
3. **Day 3 — Tool 4 + Tool 5 (static)**
   - Git co-change analysis; test selection via static import graph.
4. **Day 4 — Tool 3 + report quality**
   - Embeddings/BM25 fallback; tighten pruning + confidence scoring.

## 16) Key risks & mitigations

- **Dynamic Python ambiguity** → label low-confidence edges; rely on evidence + conservative claims.
- **Huge repos** → incremental cache, limit analysis to impacted subgraph.
- **Tool noise** → strict pruning rules; cap per-section items.
- **LLM overreach** → enforce “evidence-first” report generation.

## 17) Open questions (to resolve early)

- Which Python web frameworks to prioritize for payload tracing after FastAPI/Pydantic (Flask, Django, something else)?
- Demo robustness: What is the minimum input we promise to support?
  - Supported: NL-only (best-effort, lower confidence)
  - Preferred: NL + unified diff and/or anchors (higher precision)
- Do we require running tests/coverage locally, or keep v1 purely static?
- Are we optimizing for a single framework (FastAPI) in the demo, or should we include at least one fallback heuristic for non-FastAPI Python web apps?
