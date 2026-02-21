# Prompt and Output Templates

Use these templates when drafting user prompts or producing consistent agent output.

## Prompt templates

### Rename field

Rename `<old_field>` to `<new_field>` in `<route_or_module>`. Use blast_radius tools. Report impacted files/symbols, risk/confidence, and tests to run first.

### Remove field

Remove `<field>` from `<API route or payload>`. Use blast_radius. Focus on breakage hotspots and prioritized tests.

### Type change

Change `<field>` type from `<old_type>` to `<new_type>` in `<scope>`. Use blast_radius and identify validators, transforms, callers, and tests.

## Output skeleton

- Summary: one-line change risk statement.
- Impacts: top files/symbols with risk + confidence.
- Evidence: per-impact supporting tools (Tool1/2/3/4/5).
- Tests: prioritized list with reason.
- Assumptions: missing context or inferred scope.
- Limitations: static-analysis and history constraints.

## Anchor examples

- route anchor: `route:POST /orders`
- symbol anchor: `symbol:app/api/orders.py:create_order`
- file anchor: `app/api/orders.py`
