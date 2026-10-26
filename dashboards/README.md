# Dashboards as code

A dashboard is one YAML file here. Plan: [`../docs/dashboard-spec-plan.md`](../docs/dashboard-spec-plan.md). The validator and compiler
(`dashspec`) check a file; the renderer (`dashboard/static/render/`) draws it at `/d/<id>`.

```bash
scripts/dashspec validate dashboards/*.yml                          # schema + member checks against cube/model; exit 1 on any problem
scripts/dashspec compile dashboards/sales-overview.yml -o /tmp/x.json                  # one file, to look at
scripts/dashspec build                                              # every dashboards/*.yml -> dashboards/build/<id>.json + index.json
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

## Serving
`dashboards/build/` is **committed**: nginx (the `dashboard-cube` service) serves it at `/dashboards/`, and `/d/` lists what the signed-in
role may open, `/d/<id>` draws one. After editing a YAML file run `scripts/dashspec build` and commit the JSON with it; a test fails if
they differ. A deploy is then just `git pull` (nginx reads the files on each request; no restart).

## What the renderer draws
`kpi` (tiles, optional sparkline), `timeseries` (line, bar, stacked bar; optional `granularities` switch), `bar` (ranked; one `measure`,
or a `stack` of measures from several cubes, or a `split` by a dimension), `treemap` (one or two dimensions), `table`, `text`. Filters are selects (a
filter's `parent` groups its options, or narrows them when the dashboard has a filter on that dimension); they go in the URL
(`?fy=2021&region=Canada`). Every panel loads on its own: one that fails shows its message in its card and the rest draw; changing a
filter cancels what is still running.

**Click to filter** (`on_click: { set_filter: <id> | [<id>, <id>] }`): a click on a bar, a treemap tile, a table row or a month sets those
filters from what was clicked, and a second click undoes it (restoring what the filters held before the first click). A bar carries its
`by` value, a treemap tile its group values in order (a category heading only the first), a table row its dimension columns, a month its
fiscal or calendar year. The validator checks that each named filter is on a dimension the click carries. The panel that was clicked
does not narrow itself with the filters it sets (it keeps showing every choice and marks the selected one).

A KPI measure (and a time-chart series) is a `member`, a `sum` of measures (across cubes), or a `ratio` of two sums
(`{ num: [...], den: [...] }`, for a margin over both channels). A `format` is `money`, `int`, `pct` (a fraction, 0.153 -> 15.3%),
`decimal` or `number`. Table columns are a member or `{ member, label, format }`. For a measure over more than one cube the renderer
sends one query per cube and merges the rows (a ranked bar over two cubes ranks after merging).
Not yet: comparison with the previous period on KPI tiles, a different time dimension per panel.
