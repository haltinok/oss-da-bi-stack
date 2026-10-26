# Dashboards as code

A dashboard is one YAML file here. Plan: [`../docs/dashboard-spec-plan.md`](../docs/dashboard-spec-plan.md). This is Phase 1: the spec,
the validator and the compiler. The renderer comes in Phase 3.

```bash
scripts/dashspec validate dashboards/*.yml                          # schema + member checks against cube/model; exit 1 on any problem
scripts/dashspec compile dashboards/sales-overview.yml -o dashboards/build/sales-overview.json
scripts/dashspec meta                                               # the cubes, measures and dimensions a spec may use
scripts/dashspec meta --json                                        # the same for a program (the authoring agent)
```
`--model DIR` reads another Cube model; `--cube-url URL` reads a running Cube's `/v1/meta` instead (a Cube JWT in `$CUBE_TOKEN`; that
catalog has no joins, so the join check is skipped). Needs `uv`; nothing else is installed.

## What is checked
- The shape: `schema/dashboard.schema.json` (JSON Schema 2020-12). Unknown fields, missing fields, bad enums and ranges.
- Every member exists in the Cube model, measures are used as measures and dimensions as dimensions, the time dimension is a time one.
- Filters and `on_click` point at filters that exist; `ignore_filters` too; filter parents are dimensions.
- A measure is only combined with dimensions its cube can join to (a filter on `territories.region` on an `inventory_health` panel is an
  error: add the filter id to that panel's `ignore_filters`).
- The layout: every row is 12 columns wide, every panel is placed exactly once.

Every message names the panel (or filter) and the field, for example
`panel 'top' (bar): by: 'products.nme' is not in the Cube model (products has: ...)`.

## Tests
```bash
PYTHONPATH=dashboards uv run --with pytest --with pyyaml --with 'jsonschema>=4.18' python -m pytest dashboards/tests -q
```
CI runs them in the `dashspec` job, and validates and compiles every `dashboards/*.yml`.
