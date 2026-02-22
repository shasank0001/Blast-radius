# Blast Radius — LLM-Augmented Semantic Impact Analysis

> Given a codebase and a natural-language change intent (optionally plus a concrete diff/target), generate an engineer-readable **blast radius report** that lists downstream impacts **and** explains *why* — with evidence from multiple analysis engines.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)]()
[![Tests](https://img.shields.io/badge/tests-434%20passing-brightgreen.svg)]()
[![MCP](https://img.shields.io/badge/protocol-MCP-purple.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

---

## Table of Contents

- [Problem Statement](#problem-statement)
- [Solution Overview](#solution-overview)
  - [Key Innovations](#key-innovations)
  - [How It Works (Step by Step)](#how-it-works-step-by-step)
  - [Challenge Mapping](#how-it-maps-to-the-challenge)
  - [Agentic Workflow Skill](#agentic-workflow-skill)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Technical Approach &amp; Implementation](#technical-approach--implementation)
  - [Tool 1 — AST Structural Engine](#tool-1--ast-structural-engine)
  - [Tool 2 — Data Lineage Engine](#tool-2--data-lineage-engine)
  - [Tool 3 — Semantic Neighbor Search](#tool-3--semantic-neighbor-search)
  - [Tool 4 — Temporal Coupling Graph](#tool-4--temporal-coupling-graph)
  - [Tool 5 — Test Impact Analyzer](#tool-5--test-impact-analyzer)
  - [Orchestrator Pipeline](#orchestrator-pipeline)
- [Use Cases](#use-cases)
- [Report Format](#report-format)
- [Tech Stack &amp; Dependencies](#tech-stack--dependencies)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Configuration](#configuration)
  - [Running the MCP Server](#running-the-mcp-server)
  - [Connecting to VS Code](#connecting-to-vs-code)
  - [Connecting to OpenCode](#connecting-to-opencode)
- [Running Tests](#running-tests)
- [Demo Target Repository](#demo-target-repository)
- [Design Principles](#design-principles)
- [Success Metrics](#success-metrics)
- [Roadmap](#roadmap)
- [Repository](#repository)
- [License](#license)

---

## Problem Statement

> *From the [Blast Radius Challenge](docs/Blast%20Radius%20Challenge.md):*

In real-world software systems, even a small change can have wide-reaching consequences. Adding a field to an API, modifying a validation rule, or refactoring a shared function can silently impact downstream services, data flows, business logic, and existing tests.

**The challenge**: given (1) an existing codebase and (2) a clearly specified code change, automatically **define the blast radius of that change** in a clear, explainable, and structured way — answering:

> *"If I make this change, what parts of the system are impacted — and why?"*

Today, engineers rely on **tribal knowledge**, **manual inspection**, and **running too many tests**. Existing static analysis tools suffer from **semantic blindness** — they flag links that *exist* but are not *relevant* to the changed behavior or data:

- **Missed impacts**: Real breakages discovered only in production or late-stage testing.
- **Alert fatigue**: Engineers ignore noisy static analysis because it cries wolf too often.
- **Slow review cycles**: Team leads reviewing risky PRs lack tooling to understand *what* breaks and *why*.
- **No explanation**: Existing tools say "X depends on Y" but never "Y will break **because** it reads `user_id` which you just removed."
- **No multi-signal reasoning**: No tool combines structural analysis, data-flow tracing, semantic similarity, historical change patterns, and test coverage into a single, evidence-backed impact report.

---

## Solution Overview

**Blast Radius** is an **agentic MCP (Model Context Protocol) system** that produces deterministic, evidence-backed impact analysis reports for Python codebases.

Think of it as giving an LLM **five specialized senses** to examine a codebase, then asking it to write a doctor's report — except every diagnosis must cite the test that found it.

```
  YOU: "I'm removing user_id from the order payload."
                        │
                        ▼
              ┌─── Blast Radius ───┐
              │                    │
              │   5 analysis       │
              │   engines run      │
              │   automatically    │
              │                    │
              └────────┬───────────┘
                       │
                       ▼
  REPORT:  "12 read-sites will break.
            3 validators reference this field.
            Run these 4 tests first.
            Here's why, with evidence."
```

**Three components work together:**

1. **LLM Orchestrator** (OpenCode / VS Code Copilot) — the "brain." It plans which tools to call, merges their evidence, and renders the final report.
2. **Five MCP Tool Backends** — the "senses." Each one is deterministic, cacheable, and returns structured JSON. No guessing.
3. **Evidence Merge Pipeline** — the "judgment." Strict rules decide what counts as a real impact vs. a suggestion vs. noise.

### Key Innovations

What makes this approach different from a basic dependency graph:

---

#### 1. Two-Layer Graph — Separate Facts from Suggestions

Most tools build one big dependency graph and dump it on the engineer. We split into two layers:

- **Base Graph** = Tool 1 (AST) + Tool 2 (Data Lineage) → these are **structural facts** (imports, calls, field reads)
- **Evidence Overlays** = Tool 3 (Semantic) + Tool 4 (Git) + Tool 5 (Tests) → these are **suggestions** (similar code, co-change patterns, test coverage)

The key rule: **overlays can rank and enrich, but never assert impact on their own.** This directly solves the "semantic blindness" problem — you won't get flooded with false positives from vague similarity matches.

---

#### 2. Corroboration Gate — No Unproven Claims

Semantic neighbors (similar-looking code found by Tool 3) are always tagged `uncorroborated = True` and shown in an "Unknown Risk Zones" section. They only get promoted to real impacts if Tool 1 or Tool 2 **independently** confirms a structural link.

This is an **architectural rule**, not an LLM judgment call. The LLM literally cannot override it.

---

#### 3. Field-Path Tracing — Not "File A Depends on File B"

Instead of vague whole-file dependencies, Tool 2 traces the **exact field** (e.g., `request.user_id`) through the codebase:

```
POST /orders handler
  └─ reads request.user_id          ← breaks if removed ⚠️
  └─ passes to validate_order()
       └─ reads order.user_id       ← breaks if removed ⚠️
       └─ casts UUID(user_id)       ← transform detected
  └─ assigns to response.owner_id   ← rename detected
```

Each read-site gets a `breaks_if_removed` / `breaks_if_renamed` flag — so engineers know **exactly** what will fail, not just "these files are related."

---

#### 4. Noise-Suppressed Git Coupling

Tool 4 mines git history for co-change patterns, but weights each co-occurrence by $\frac{1}{\sqrt{n}}$ where $n$ = files in that commit. A 200-file formatting commit barely registers. A 3-file bugfix is strong signal.

This prevents bulk changes (dependency upgrades, linter runs, mass renames) from dominating the coupling scores — a common problem with naive co-change analysis.

---

#### 5. Smart Tool Planning — Don't Run What You Don't Need

The orchestrator derives a `ChangeSpec` from the intent and only runs tools that make sense:

| Change Type | Tools Used |
|-------------|-----------|
| API field removal | Tool 1 + **Tool 2** + Tool 3 + Tool 4 + Tool 5 |
| Structural refactor | Tool 1 + Tool 3 + Tool 4 + Tool 5 (skip Tool 2 — no field path) |
| Behavior change, no git | Tool 1 + Tool 3 + Tool 5 (skip Tool 4 — no history) |

No wasted computation, no noisy empty sections in the report.

---

#### 6. Content-Addressed Caching

Every tool result is cached in SQLite, keyed by:

```
SHA-256(tool_name + request + repo_fingerprint + impl_version)
```

The repo fingerprint hashes **every `.py` file's content** — change one line anywhere and stale cache auto-invalidates. Same inputs across runs → byte-identical outputs, guaranteed.

---

#### 7. Agentic Workflow Skill — Self-Documenting for AI Agents

We ship a reusable **[blast-radius-workflow skill](skills/blast-radius-workflow/SKILL.md)** — a structured instruction manual that any MCP-compatible agent can follow. It includes tool sequencing, evidence-weighting rules, escalation policies, and ready-to-use prompt templates. More on this [below](#agentic-workflow-skill).

---

### How It Works (Step by Step)

```
┌────────────────────────────────────────────────────────┐
│                    User Input                          │
│  "Remove user_id from POST /orders payload"            │
│  + optional: unified diff, file/symbol anchors         │
└──────────────────────┬─────────────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │   Step 1: Understand    │
          │   NL → ChangeSpec       │
          │   (api_change, field,   │
          │    remove, user_id)     │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │   Step 2: Plan          │
          │   Which tools to run?   │
          │   → All 5 (API change)  │
          └────────────┬────────────┘
                       │
    ┌──────┬───────┬───┴───┬───────┬──────┐
    ▼      ▼       ▼       ▼       ▼      │
 Tool 1  Tool 2  Tool 3  Tool 4  Tool 5   │
  AST    Field   Similar  Git    Test     │
 Graph   Trace   Code    History Impact   │
    │      │       │       │       │      │
    └──────┴───────┴───┬───┴───────┘      │
                       │                   │
          ┌────────────▼────────────┐      │
          │   Step 3: Merge         │      │
          │   Combine all evidence  │      │
          │   Apply corroboration   │      │
          │   gates + pruning       │      │
          └────────────┬────────────┘      │
                       │                   │
          ┌────────────▼────────────┐      │
          │   Step 4: Report        │      │
          │   Markdown with risk,   │      │
          │   confidence, evidence, │      │
          │   tests, unknowns       │      │
          └─────────────────────────┘
```

### How It Maps to the Challenge

| Challenge Asks For | What We Built |
|-------------------|---------------|
| **Model the codebase as a graph** | Tool 1 builds full AST graph (modules, classes, functions, methods + import/call/inherit edges). Tool 2 adds data-flow edges. Two-layer model keeps the graph minimal. |
| **Accept change intent** | Orchestrator normalizes NL intent → `ChangeSpec` with change class, entity kind, operation, and field path. Supports API changes, behavior changes, and structural mods. |
| **Identify direct + indirect impacts** | Direct = Tool 1/2 structural hits. Indirect = transitive imports, temporal coupling (Tool 4), semantic neighbors (Tool 3). All explicitly separated. |
| **Classify impacts** | Every item tagged with risk (`breaking` / `behavior` / `unknown`) and surface (`api` / `business` / `data` / `contract` / `tests` / `docs`). |
| **Explain why** | Each impact has a plain-English reason + tool evidence refs + access pattern details. Evidence appendix links every claim to a `query_id`. |
| **Bonus: Severity levels** | Three-tier risk × three-tier confidence on every item. |
| **Bonus: Insufficient info zones** | Dedicated "Unknown Risk Zones" section for uncorroborated signals + explicit assumptions & limitations. |
| **Bonus: Traceability** | Full chain: intent → `ChangeSpec` → tool calls → evidence → impacts → report, all linked by deterministic IDs. |
| **Bonus: Contract-breaking detection** | Tool 2 breakage flags (`if_removed`, `if_renamed`) directly detect contract-breaking field changes. |

### Agentic Workflow Skill

We built a reusable **[blast-radius-workflow](skills/blast-radius-workflow/SKILL.md)** skill — a structured playbook that any MCP-compatible LLM agent (VS Code Copilot, OpenCode) can follow autonomously to produce a blast radius report:

| Skill Component | What It Does |
|----------------|-------------|
| **Setup checks** | Verifies MCP server is running, `BLAST_RADIUS_REPO_ROOT` is set, paths are repo-relative |
| **Input normalization** | Captures intent + anchors + diff; auto-detects route vs. symbol anchor format |
| **Tool sequencing** | Prescribes order: AST → Data Lineage → Semantic → Git → Tests, with skip conditions |
| **Evidence weighting** | Strict rules: Tool 1/2 = primary evidence, Tool 3 = suggestive only, Tool 4 = ranking signal, Tool 5 = test priority |
| **Escalation policies** | When to request more anchors, widen scope, or label results low-confidence |
| **Prompt templates** | Ready-to-use prompts for rename, remove, and type-change scenarios ([see templates](skills/blast-radius-workflow/references/prompt-and-output-templates.md)) |

This means any MCP-compatible agent can produce consistent blast radius reports **without custom prompting** — the skill is the agent's instruction manual.

---

## Key Features

- **Evidence-First Analysis**: Every impact claim is backed by tool evidence — AST edges, data-shape traces, git history, semantic similarity, or test coverage. The LLM cannot assert impact without proof.
- **Multi-Signal Fusion**: Combines 5 independent analysis engines (structural, data-flow, semantic, temporal, test) for comprehensive coverage.
- **Deterministic & Cacheable**: All tools produce deterministic outputs. Results are cached in SQLite by content hash — repeated runs on unchanged repos are instant.
- **Natural Language Input**: Accepts change intent in plain English. Precision improves with optional unified diffs and anchors.
- **Confidence Scoring**: Every impacted item has explicit `High / Medium / Low` confidence and `Breaking / Behavior / Unknown` risk classification.
- **Aggressive Pruning**: Prefers missing a low-confidence edge over overwhelming the engineer. Semantic-only signals never count as confirmed impacts.
- **Python-First**: Optimized for Python repos with first-class support for FastAPI/Starlette + Pydantic patterns.
- **Incremental Indexing**: ASTs cached by file hash, semantic indices built incrementally — large repos stay fast after initial indexing.

---

## System Architecture

```
blast_radius/
├── blast_radius_mcp/          ← MCP Server (5 deterministic tools)
│   ├── server.py              ← FastMCP entrypoint, tool registration, execute_tool() pipeline
│   ├── settings.py            ← Environment-based config (pydantic-settings)
│   ├── ids.py                 ← Deterministic SHA-256 ID generation
│   ├── schemas/               ← Pydantic v2 request/response models (strict, extra="forbid")
│   ├── validation/            ← Request/response validation gates
│   ├── cache/                 ← SQLite cache (WAL mode, 3 tables: runs, tool_results, artifacts)
│   ├── repo/                  ← Repo fingerprinting (git HEAD + content hashes), safe file I/O
│   ├── tools/                 ← 5 tool implementations (AST, lineage, semantic, coupling, tests)
│   └── indices/               ← Semantic index layer (BM25 + OpenAI/Pinecone)
│
├── orchestrator/              ← Evidence merge pipeline
│   ├── __init__.py            ← Main pipeline: run_blast_radius()
│   ├── normalize.py           ← NL intent → ChangeSpec normalization
│   ├── diff_parser.py         ← Unified diff parsing
│   ├── merge_evidence.py      ← Cross-tool evidence merge, pruning, risk assignment
│   └── report_render.py       ← Markdown report renderer
│
├── scripts/                   ← CLI utilities
└── tests/                     ← 434 tests across 11 test files
```

### Graph Model (Minimal-First)

The codebase is represented as a graph with two layers:

| Layer                                  | Source                                          | Authority                                                 |
| -------------------------------------- | ----------------------------------------------- | --------------------------------------------------------- |
| **Base Graph** (required)        | Tool 1 (AST) + Tool 2 (Data Lineage)            | **Primary** — structural truth                     |
| **Evidence Overlays** (optional) | Tool 3 (Semantic), Tool 4 (Git), Tool 5 (Tests) | **Suggestive** — enrich & rank, never assert alone |

The orchestrator builds a candidate set from the base graph, then enriches and **prunes** using overlays, relevance checks, and confidence thresholds.

---

## Technical Approach & Implementation

### Tool 1 — AST Structural Engine

**Command**: `get_ast_dependencies(target_files)`

Provides hard structural truth about the codebase: imports, definitions, call edges, inheritance, and symbol references.

| Aspect                   | Detail                                                                                                            |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| **Parser**         | Python stdlib `ast` module (tree-sitter available as upgrade path)                                              |
| **Nodes**          | `module`, `class`, `function`, `method` — with qualified names, signatures, decorators, docstrings       |
| **Edges**          | `imports`, `calls`, `inherits`, `references` — with evidence spans, confidence scores, resolution status |
| **Resolution**     | Cross-file symbol resolution via global index; unresolved targets are explicit (never silently dropped)           |
| **Precision**      | Precision > recall — only creates concrete cross-file targets when uniquely resolved                             |
| **Determinism**    | Sorted by stable IDs; two identical runs produce byte-identical output                                            |
| **Implementation** | ~980 lines, 20 functions                                                                                          |

### Tool 2 — Data Lineage Engine

**Command**: `trace_data_shape(field_path, entry_points[])`

High-precision tracing for API payload and field changes — tracks where a field is introduced, read, validated, transformed, and passed downstream.

| Aspect                    | Detail                                                                                        |
| ------------------------- | --------------------------------------------------------------------------------------------- |
| **Route Discovery** | Detects FastAPI/Starlette route decorators (`@app.get`, `@router.post`, etc.)             |
| **Model Indexing**  | Parses Pydantic `BaseModel` subclasses — fields, aliases, validators, constraints          |
| **Read Detection**  | `obj.field`, `data["field"]`, `data.get("field")` — with access pattern classification |
| **Write Detection** | Attribute assignment, dict assignment                                                         |
| **Transforms**      | Casts (`UUID(field)`), renames, defaulting                                                  |
| **Breakage Flags**  | `if_removed=True`, `if_renamed=True` — per read-site                                     |
| **Trigger Policy**  | Only runs for API/field/schema changes with a usable entry point                              |
| **Implementation**  | ~1,580 lines, 20+ functions                                                                   |

### Tool 3 — Semantic Neighbor Search

**Command**: `find_semantic_neighbors(query_text)`

Finds "unknown impact zones" — conceptually similar code with no explicit structural link.

| Aspect                     | Detail                                                                                                  |
| -------------------------- | ------------------------------------------------------------------------------------------------------- |
| **Primary Path**     | OpenAI embeddings (`text-embedding-3-small`) + Pinecone vector search                                 |
| **Fallback**         | BM25 lexical similarity via `rank-bm25` (works fully offline)                                         |
| **Chunking**         | Function/method-level code chunks with deterministic IDs                                                |
| **Key Rule**         | All results marked `uncorroborated=True` — never promoted to "impact" without Tool 1/2 corroboration |
| **Auto-Degradation** | Falls back to BM25 automatically when API keys are missing                                              |
| **Implementation**   | ~457 lines (tool) + ~449 lines (index layer)                                                            |

### Tool 4 — Temporal Coupling Graph

**Command**: `get_historical_coupling(file_paths[])`

Mines git history to surface files that frequently co-change with the target — replacing tribal knowledge with data.

| Aspect                   | Detail                                                             |
| ------------------------ | ------------------------------------------------------------------ |
| **Source**         | `git log --name-status -M` via subprocess (no shell injection)   |
| **Scoring**        | Commit-size normalized co-change weight (penalizes bulk commits)   |
| **Renames**        | Full rename chain tracking (A→B→C treated as aliases)            |
| **Filters**        | Excludes merges (optional), large commits (cap), and self-coupling |
| **Evidence**       | Up to 3 example commits per coupling relationship                  |
| **Implementation** | ~706 lines                                                         |

### Tool 5 — Test Impact Analyzer

**Command**: `get_covering_tests(impacted_nodes_list)`

Returns a ranked minimal set of tests likely to cover the impacted paths.

| Aspect                   | Detail                                                                                                                                                               |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Discovery**      | Multi-strategy:`pytest.ini`, `pyproject.toml`, `setup.cfg`, conventional dirs, filename scanning                                                               |
| **Scoring**        | Weighted reasons:`direct_import` (1.0), `from_import_symbol` (1.0), `transitive_import` (0.5/depth), `symbol_reference` (0.4), `field_literal_match` (0.2) |
| **Ranking**        | Deterministic:`(score desc, file asc, nodeid asc)`                                                                                                                 |
| **Output**         | Ranked tests with confidence level + evidence reasons                                                                                                                |
| **Implementation** | ~845 lines, static analysis only (no test execution required)                                                                                                        |

### Orchestrator Pipeline

The orchestrator is a thin deterministic driver that:

1. **Normalizes** natural language intent → `ChangeSpec` (change class, entity kind, operation, field path, type changes)
2. **Parses** unified diff → changed files, added/removed lines, key identifiers
3. **Plans** tool calls conditionally (Tool 2 only for API changes, Tool 4 only with `.git`, etc.)
4. **Executes** each tool sequentially, collecting structured results
5. **Merges** all evidence into a unified candidate set with deduplication
6. **Prunes** false positives by intent relevance, field specificity, and confidence thresholds
7. **Assigns** risk (`breaking` / `behavior` / `unknown`) and surface (`api` / `business` / `data` / `contract` / `tests` / `docs`)
8. **Renders** a structured Markdown report with evidence citations

| Component             | Lines | Role                                     |
| --------------------- | ----- | ---------------------------------------- |
| `normalize.py`      | 495   | Intent normalization + tool planning     |
| `diff_parser.py`    | 186   | Unified diff parsing                     |
| `merge_evidence.py` | 775   | Evidence merge, pruning, risk assignment |
| `report_render.py`  | 413   | Markdown report rendering                |
| `__init__.py`       | 281   | Main async pipeline                      |

---

## Use Cases

### UC1 — API Field Removal

> **Intent**: "Remove `user_id` from the request payload of `POST /orders`."

**Output**: Downstream locations that read `user_id`, the functions/classes involved, breakage flags, and tests to run.

### UC2 — Type Change

> **Intent**: "Change user id from `int` to `uuid` across services."

**Output**: Read/parse/serialize sites, schema validators, DB access patterns, and semantically similar parsing utilities.

### UC3 — Behavioral Change in Validation

> **Intent**: "Relax email validation to allow plus-addressing."

**Output**: Callers relying on strict validation, duplicated validators elsewhere, and likely coupled config/docs.

### UC4 — Structural Modification (Refactor)

> **Intent**: "Change signature of `parse_user_id(value)` to accept `str` and return `UUID`."

**Output**: Call sites, downstream type expectations/serializers, related tests, and duplicated parsing utilities.

---

## Report Format

The system generates a structured Markdown report with the following sections:

| Section                             | Content                                                                       |
| ----------------------------------- | ----------------------------------------------------------------------------- |
| **Executive Summary**         | Intent, anchors, top 3 risks, overall confidence                              |
| **Priority Impact Digest**    | Ranked high-priority impacts                                                  |
| **Direct Structural Impacts** | AST-backed impacts table (risk, surface, location, why, evidence, confidence) |
| **Data-Shape Impacts**        | Field read-sites with breakage flags, transformations                         |
| **Unknown Risk Zones**        | Semantic neighbors (uncorroborated, for review)                               |
| **Implicit Dependencies**     | Temporally coupled files with co-change weights                               |
| **Tests to Run**              | Ranked test list with coverage reasons                                        |
| **Recommended Actions**       | Grouped engineer actions (update schema, run tests, review module)            |
| **Evidence Appendix**         | All tool query IDs, expandable full evidence details                          |
| **Assumptions & Limitations** | Explicitly stated constraints and gaps                                        |

Every impacted item includes: **Impact Risk**, **Impact Surface**, **Reason** (plain English), **Evidence** (tool outputs), **Confidence** (H/M/L), and **Suggested Action**.

---

## Tech Stack & Dependencies

### Core

| Package                      | Purpose                                            |
| ---------------------------- | -------------------------------------------------- |
| `mcp[cli]`                 | FastMCP server framework (MCP protocol over stdio) |
| `pydantic >= 2.0`          | Schema validation (`ConfigDict(extra="forbid")`) |
| `pydantic-settings >= 2.0` | Environment-variable based configuration           |
| `xxhash`                   | Fast stable hashing for cache keys                 |

### Analysis Engines

| Package                                  | Purpose                                              |
| ---------------------------------------- | ---------------------------------------------------- |
| `tree-sitter` + `tree-sitter-python` | AST parsing (upgrade path; v1 uses stdlib `ast`)   |
| `rank-bm25`                            | BM25 lexical similarity fallback for semantic search |
| `openai`                               | Embedding generation (`text-embedding-3-small`)    |
| `pinecone`                             | Vector database for semantic neighbor retrieval      |

### Development

| Package            | Purpose            |
| ------------------ | ------------------ |
| `pytest`         | Test runner        |
| `pytest-asyncio` | Async test support |

### Runtime Requirements

| Requirement      | Note                                                     |
| ---------------- | -------------------------------------------------------- |
| Python 3.11+     | Required (uses `tomllib`, modern typing)               |
| `git`          | Required for temporal coupling + repo fingerprinting     |
| OpenAI API key   | Optional (semantic search falls back to BM25 without it) |
| Pinecone API key | Optional (semantic search falls back to BM25 without it) |

---

## Project Structure

```
ai_for_vizag/
├── README.md                              ← You are here
├── opencode.json                          ← OpenCode MCP configuration
│
├── blast_radius/                          ← Main package
│   ├── pyproject.toml                     ← Package config (hatchling build)
│   ├── README.md                          ← Server-specific README
│   ├── blast_radius_mcp/
│   │   ├── server.py                      ← FastMCP server (5 tools + execute_tool pipeline)
│   │   ├── settings.py                    ← Config via pydantic-settings (env_prefix=BLAST_RADIUS_)
│   │   ├── logging_config.py              ← Structured JSON logging
│   │   ├── ids.py                         ← Deterministic SHA-256 ID generation
│   │   ├── schemas/
│   │   │   ├── common.py                  ← Shared models: Position, Range, Location, Envelopes
│   │   │   ├── tool1_ast.py               ← AST engine schemas
│   │   │   ├── tool2_lineage.py           ← Data lineage schemas
│   │   │   ├── tool3_semantic.py          ← Semantic neighbor schemas
│   │   │   ├── tool4_coupling.py          ← Temporal coupling schemas
│   │   │   └── tool5_tests.py             ← Test impact schemas
│   │   ├── validation/
│   │   │   └── validate.py                ← Request/response validation dispatch
│   │   ├── cache/
│   │   │   ├── sqlite.py                  ← SQLite cache (WAL mode, 3 tables)
│   │   │   └── keys.py                    ← Cache key canonicalization
│   │   ├── repo/
│   │   │   ├── io.py                      ← Safe file I/O, globbing, hashing
│   │   │   └── fingerprint.py             ← Repo fingerprinting (git HEAD + content hashes)
│   │   ├── tools/
│   │   │   ├── tool1_ast_engine.py        ← AST Structural Engine (~980 lines)
│   │   │   ├── tool2_data_lineage.py      ← Data Lineage Engine (~1,580 lines)
│   │   │   ├── tool3_semantic_neighbors.py← Semantic Neighbor Search (~457 lines)
│   │   │   ├── tool4_temporal_coupling.py ← Temporal Coupling Graph (~706 lines)
│   │   │   └── tool5_test_impact.py       ← Test Impact Analyzer (~845 lines)
│   │   └── indices/
│   │       └── semantic_index.py          ← BM25 + OpenAI/Pinecone index (~449 lines)
│   ├── orchestrator/
│   │   ├── __init__.py                    ← Main pipeline: run_blast_radius() (~281 lines)
│   │   ├── normalize.py                   ← ChangeSpec normalization (~495 lines)
│   │   ├── diff_parser.py                 ← Unified diff parser (~186 lines)
│   │   ├── merge_evidence.py              ← Evidence merge & pruning (~775 lines)
│   │   └── report_render.py               ← Markdown report renderer (~413 lines)
│   ├── scripts/
│   │   ├── run_mcp_server.py              ← Convenience dev entry point
│   │   └── init_tool3_semantic_index.py   ← Warm semantic index for new repos
│   └── tests/                             ← 434 tests (0 failures)
│       ├── test_schemas.py                ← 58 tests — schemas, fixtures, validation
│       ├── test_ids.py                    ← 24 tests — deterministic ID generation
│       ├── test_fingerprint.py            ← 16 tests — repo I/O, fingerprinting
│       ├── test_cache.py                  ← 21 tests — SQLite cache + keys
│       ├── test_tool1_ast.py              ← 77 tests — AST engine
│       ├── test_tool2.py                  ← 94 tests — Data lineage
│       ├── test_tool3.py                  ← 38 tests — Semantic neighbors
│       ├── test_tool4.py                  ← 34 tests — Temporal coupling
│       ├── test_tool5.py                  ← 50 tests — Test impact
│       ├── test_server.py                 ← 2 tests — execute_tool pipeline
│       ├── test_orchestrator_units.py     ← 23 tests — Orchestrator units
│       └── fixtures/                      ← Golden JSON fixtures (10 files)
│
├── demo_target_repo/                      ← Demo Python project for testing
│   ├── app/
│   │   ├── api/                           ← FastAPI route handlers
│   │   ├── models.py                      ← Pydantic models
│   │   ├── services/                      ← Business logic
│   │   └── utils.py                       ← Utility functions
│   └── tests/                             ← Demo test suite
│
├── docs/                                  ← Design documents
│   ├── PRD.md                             ← Product Requirements Document
│   ├── MCP_SERVER_ARCHITECTURE.md         ← Server architecture spec
│   ├── IMPLEMENTATION_PLAN.md             ← Build plan
│   ├── STATE.md                           ← Project state & milestone tracker
│   ├── REPORT_TEMPLATE.md                 ← Report output template
│   ├── TOOL1-5_SCHEMA.md                  ← Per-tool JSON schemas
│   └── ...                                ← Additional design docs
│
├── blast_docs/                            ← Generated blast radius reports
│
└── skills/
    └── blast-radius-workflow/             ← Agentic workflow skill definition
        └── SKILL.md
```

---

## Getting Started

### Prerequisites

- **Python 3.11+**
- **git** (required for temporal coupling and repo fingerprinting)
- Optional: OpenAI API key + Pinecone API key (for embedding-backed semantic search; BM25 fallback works without them)

### Installation

```bash
# Clone the repository
git clone https://github.com/shasank0001/Blast-radius.git
cd Blast-radius

# Create and activate virtual environment
cd blast_radius
python3 -m venv .venv
source .venv/bin/activate

# Install the package with dev dependencies
pip install --upgrade pip
pip install -e ".[dev]"

# Verify installation
which blast-radius-mcp
```

### Configuration

The server reads environment variables with the `BLAST_RADIUS_` prefix (and loads `.env` when present):

| Variable                                | Default                      | Description                               |
| --------------------------------------- | ---------------------------- | ----------------------------------------- |
| `BLAST_RADIUS_REPO_ROOT`              | `.`                        | Path to the target repository             |
| `BLAST_RADIUS_CACHE_DB_PATH`          | `~/.blast_radius/cache.db` | SQLite cache location                     |
| `BLAST_RADIUS_SCHEMA_VERSION`         | `v1`                       | Schema version (locked)                   |
| `BLAST_RADIUS_LOG_LEVEL`              | `INFO`                     | Logging verbosity                         |
| `BLAST_RADIUS_OPENAI_API_KEY`         | —                           | OpenAI key for embeddings (optional)      |
| `BLAST_RADIUS_OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small`   | Embedding model                           |
| `BLAST_RADIUS_PINECONE_API_KEY`       | —                           | Pinecone key for vector search (optional) |
| `BLAST_RADIUS_PINECONE_INDEX`         | `blast-radius`             | Pinecone index name                       |
| `BLAST_RADIUS_PINECONE_HOST`          | —                           | Pinecone host URL (optional)              |

Example `.env` file:

```bash
BLAST_RADIUS_REPO_ROOT=.
BLAST_RADIUS_CACHE_DB_PATH=.cache/blast-radius/cache.db
BLAST_RADIUS_LOG_LEVEL=INFO

# Optional — semantic search falls back to BM25 without these
BLAST_RADIUS_OPENAI_API_KEY=sk-...
BLAST_RADIUS_PINECONE_API_KEY=...
BLAST_RADIUS_PINECONE_INDEX=blast-radius
BLAST_RADIUS_PINECONE_HOST=...
```

### Running the MCP Server

```bash
blast-radius-mcp
```

This runs the MCP server over stdio, which is what MCP clients (VS Code, OpenCode) expect.

### Connecting to VS Code

1. Open Command Palette → **MCP: Open Workspace Folder Configuration**
2. Add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "blastRadius": {
      "type": "stdio",
      "command": "${workspaceFolder}/blast_radius/.venv/bin/blast-radius-mcp",
      "envFile": "${workspaceFolder}/blast_radius/.env",
      "env": {
        "BLAST_RADIUS_REPO_ROOT": "${workspaceFolder}",
        "BLAST_RADIUS_CACHE_DB_PATH": "${workspaceFolder}/.cache/blast-radius/cache.db",
        "BLAST_RADIUS_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

3. Run **MCP: List Servers** and start `blastRadius`
4. In Chat, enable tools from the `blastRadius` server in the tool picker

### Connecting to OpenCode

Add to `opencode.json` at your project root:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "blast_radius": {
      "type": "local",
      "command": ["./blast_radius/.venv/bin/blast-radius-mcp"],
      "enabled": true,
      "timeout": 15000,
      "environment": {
        "BLAST_RADIUS_REPO_ROOT": ".",
        "BLAST_RADIUS_CACHE_DB_PATH": ".cache/blast-radius/cache.db",
        "BLAST_RADIUS_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Verify with:

```bash
opencode mcp list
opencode mcp debug blast_radius
```

### Initializing the Semantic Index (Optional)

For embedding-backed semantic search, warm the vector index once per target repo:

```bash
python scripts/init_tool3_semantic_index.py \
  --repo-root /path/to/target_repo
```

Requires `BLAST_RADIUS_OPENAI_API_KEY`, `BLAST_RADIUS_PINECONE_API_KEY`, `BLAST_RADIUS_PINECONE_INDEX`, and `BLAST_RADIUS_PINECONE_HOST`.

---

## Running Tests

```bash
cd blast_radius
pytest -q tests/
```

### Test Suite Summary

| Test File                      | Tests         | Coverage                                                        |
| ------------------------------ | ------------- | --------------------------------------------------------------- |
| `test_schemas.py`            | 58            | Schemas, golden fixtures, validation, settings, JSON export     |
| `test_ids.py`                | 24            | Deterministic IDs (canonical_json, run_id, query_id, cache_key) |
| `test_fingerprint.py`        | 16            | Safe file I/O, glob, file hashing, repo fingerprinting          |
| `test_cache.py`              | 21            | SQLite CRUD, stats, cleanup (age + size cap), cache keys        |
| `test_tool1_ast.py`          | 77            | AST engine: nodes, edges, cross-file resolution, determinism    |
| `test_tool2.py`              | 94            | Data lineage: routes, models, field tracing, breakage           |
| `test_tool3.py`              | 38            | Semantic neighbors: BM25, chunking, diagnostics                 |
| `test_tool4.py`              | 34            | Temporal coupling: git parsing, rename maps, scoring            |
| `test_tool5.py`              | 50            | Test impact: discovery, import graph, scoring, ranking          |
| `test_server.py`             | 2             | Server pipeline: deterministic run/cache behavior               |
| `test_orchestrator_units.py` | 23            | Normalize, diff parse, merge, prune                             |
| **Total**                | **434** | **All passing, 0 failures**                               |

---

## Demo Target Repository

The `demo_target_repo/` directory contains a compact Python project (FastAPI + Pydantic) intentionally structured across multiple commits to exercise all 5 tools:

- **FastAPI route handlers** (for Tool 1 AST + Tool 2 data lineage)
- **Pydantic models** with fields, validators, and constraints (for Tool 2)
- **Service layer** with business logic (for Tool 1 call edges)
- **Test suite** (for Tool 5 test impact)
- **Multi-commit git history** (for Tool 4 temporal coupling)

---

## Design Principles

| Principle                          | Description                                                                                                                         |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| **Evidence-First**           | The LLM cannot claim impact without tool-backed evidence                                                                            |
| **Prune Aggressively**       | Prefer missing a low-confidence edge over overwhelming the engineer                                                                 |
| **Deterministic Tooling**    | Tools are deterministic, cacheable, and testable — same input → same output                                                       |
| **Pluggable LLM**            | The orchestrator model is "whatever OpenCode/VS Code uses"; tools don't assume a specific vendor                                    |
| **No Semantic-Only Impacts** | Semantic similarity suggests*where to look*, but doesn't count as impact unless corroborated by structural or data-shape evidence |
| **Strict Schema Validation** | All Pydantic models use `extra="forbid"` — unknown fields are rejected                                                           |
| **Incremental Caching**      | ASTs cached by file hash in SQLite; semantic indices built incrementally                                                            |

---

## Success Metrics

| Metric                      | Target                                                    |
| --------------------------- | --------------------------------------------------------- |
| **Precision**         | ≥ 70% of listed impacts judged "relevant" by an engineer |
| **Time-to-Report**    | < 2 minutes after indexing                                |
| **Actionability**     | Report recommends ≤ 10 tests for a typical change        |
| **Evidence Coverage** | ≥ 90% of impacts have at least 2 evidence types          |

---


## Repository

**GitHub**: [https://github.com/shasank0001/Blast-radius.git](https://github.com/shasank0001/Blast-radius.git)

---

## License

MIT
