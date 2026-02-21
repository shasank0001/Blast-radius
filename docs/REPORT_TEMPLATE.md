# Blast Radius Report — Template (v1)

## Executive summary
- **Intent:** <natural-language intent>
- **Anchor(s):** <file/symbol/endpoint>
- **Top risks:** <3 bullets>
- **Overall confidence:** High / Medium / Low

## Direct structural impacts (AST)
| Impact | Impact risk | Impact surface | Location | Why | Evidence | Confidence |
|---|---|---|---|---|---|---|
| <symbol/file> | <breaking/behavior/unknown> | <api/business/data/contract/tests/docs/unknown> | <file:line or symbol> | <reason> | AST edge(s) | H/M/L |

## Data-shape impacts (payload lineage)
**Changed field/path:** `<field_name>`

### Read sites that will break if removed/renamed
- <file:symbol> — reads `<field>` via `<attr/dict access>`

### Transformations
- <file:symbol> — renames `<a>` → `<b>`
- <file:symbol> — casts `<field>` to `<type>`

## Unknown risk zones (semantic neighbors)
- <file:symbol> (similarity: 0.xx) — why it’s similar

## Implicit dependencies (temporal coupling)
- <file> (weight: xx%) — often changes with the target

## Tests to run (impact prover)
Ranked list:
1. <test node> — why it covers the impacted path
2. <test node>

## Recommended engineer actions
- Update schema/docs: <items>
- Update downstream consumers: <items>
- Run tests: <items>

## Evidence appendix (machine evidence references)
- AST query id: <id>
- Data lineage trace id: <id>
- Semantic query id: <id>
- Git coupling query id: <id>
- Test impact query id: <id>

## Assumptions & limitations
- <assumption>
- <limitation>
