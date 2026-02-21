# Detailed Planning Docs Index (v1)

This index links all detailed planning artifacts generated for the Blast Radius hackathon scope.

## Core

- [Main MCP Detailed Plan](MAIN_MCP_DETAILED_PLAN.md)
- [Coding Agent Flow Implementation Plan](CODING_AGENT_FLOW_IMPLEMENTATION_PLAN.md)
- [Alignment Crosscheck Report](ALIGNMENT_CROSSCHECK_REPORT.md)

## Tool Plans

- [Tool 1 Detailed Plan — AST Structural Engine](TOOL1_DETAILED_PLAN.md)
- [Tool 2 Detailed Plan — Data Lineage Engine](TOOL2_DETAILED_PLAN.md)
- [Tool 3 Detailed Plan — Semantic Neighbor Search](TOOL3_DETAILED_PLAN.md)
- [Tool 4 Detailed Plan — Temporal Coupling](TOOL4_DETAILED_PLAN.md)
- [Tool 5 Detailed Plan — Test Impact Analyzer](TOOL5_DETAILED_PLAN.md)

## Tool Schemas

- [Tool 1 Schema](TOOL1_SCHEMA.md)
- [Tool 2 Schema](TOOL2_SCHEMA.md)
- [Tool 3 Schema](TOOL3_SCHEMA.md)
- [Tool 4 Schema](TOOL4_SCHEMA.md)
- [Tool 5 Schema](TOOL5_SCHEMA.md)

## Locked decisions included in all docs

1. Tool 3 default: OpenAI + Pinecone primary, BM25 fallback.
2. Tool 2 canonical API: `field_path + entry_points[]`.
3. Canonical contract: `schema_version = "v1"` with deterministic hash-based `run_id` and `query_id`.
4. Minimal orchestrator merge/prune pipeline is mandatory in v1.
