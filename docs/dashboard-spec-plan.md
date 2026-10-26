# Plan: dashboards defined in YAML, rendered from Cube, authored by an agent

Status: **Phases 1 to 5 done** (spec, validator, compiler: `dashboards/`, `scripts/dashspec`; shared modules: `dashboard/static/lib/`, `dashboard/cube/cube-client.mjs`); later phases not started. Written to be implemented with Claude Code, one phase per PR, like
[`inventory-actions-plan.md`](inventory-actions-plan.md).

## Goal

Today's dashboard (`dashboard/static/app.js`, ~1,400 lines of plain JS and inline SVG) is a one-off: every panel, query and
interaction is hand-written. It looks good and it is fast, but a second dashboard, or the same one for another client, means
writing it again.

Build a small **dashboards-as-code** layer instead:

1. A **dashboard is a YAML file**: title, filters, panels, layout. No SQL, no code.
2. A **renderer** draws any valid YAML file as an interactive page, with the same look, speed and sign-in as today.
3. **Every number comes from Cube.** A panel names Cube measures and dimensions; the renderer never builds SQL. Metric
   definitions, row-level security and rollups stay in one place (`cube/model`).
4. A **validator** rejects a broken file before it is deployed: unknown members, wrong types, filters on things that are not
   dimensions, and (as a warning) panels no rollup serves.
5. An **agent skill** turns a request ("a monthly sales overview for the regional managers, in Turkish, in lira") into a YAML
   file, validates it, screenshots it and iterates. The agent writes YAML, never SQL and never renderer code.

The business case: after the first client, a new dashboard is a reviewed YAML file produced in minutes, not a new code base.
The numbers are consistent by construction, because they all come from the semantic layer.

## Non-goals

This must not grow into a BI tool. Out of scope until two paying clients ask for the same thing:

- a drag-and-drop editor (the editor is the YAML file, the agent and a pull request)
- scheduled e-mail reports, PDF export, alerting, a mobile app
- SQL or free-form expressions in a spec (a missing metric is added to the Cube model, in its own PR)
- more than the panel types listed below (a new type needs two real use cases)

## Design decisions

- **The existing dashboard stays as it is.** It is the showcase and the reference for look and behaviour. The new renderer
  lives next to it and is proven by re-expressing the sales part of it in YAML (parity, Phase 3/4). The inventory lists, the
  Approve actions and the proposals panel stay hand-written; they are an application, not a dashboard.
- **YAML is compiled, not parsed in the browser.** A small Python CLI (`dashspec`) validates a YAML file and compiles it to
  JSON. The browser loads the JSON. No YAML parser in the page, and nothing reaches the browser that has not been validated.
- **Plain JS and SVG, no framework, no build step**, like `app.js`. The chart code in `app.js` (bars, stacked bars,
  sparklines, the treemap's `squarify`, tooltips, number formatting, the Excel writer `xlsx.js`) is extracted into shared ES
  modules and reused, not rewritten.
- **Sign-in and the Cube client are shared.** `dashboard/cube/cube-source.mjs` is split so the Keycloak (PKCE) sign-in, the
  Cube token from the auth service and the query runner are a module both pages import. Row-level security keeps living in
  `cube/cube.js`; the renderer adds nothing to it and cannot bypass it.
- **Multi-fact panels are a renderer feature.** Cube cannot join two fact cubes in one query (see `spike/results.md`), so a
  panel may list measures from several cubes that share the dimensions it groups by. The renderer sends one query per cube
  and merges the results on those dimensions, as `cube-source.mjs` already does for internet and reseller sales.
- **Datasets keep working.** A spec names cubes, not schemas. The dataset switch (`window.STACK.datasets`: live / 250M) only
  changes which Cube endpoint answers, so every YAML dashboard works on both.

## The spec (v1)

Illustrative; Phase 1 fixes the exact shape in a JSON Schema (`dashboards/schema/dashboard.schema.json`).

```yaml
spec: 1
id: sales-overview
title: Sales overview
description: Revenue, margin and orders by channel, product and territory.
locale: en-US            # tr-TR gives 1.234,56 and Turkish month names
currency: USD            # TRY gives ₺
roles: [admin, manager]  # who sees it in the list; data access is still Cube's row-level security
time:
  dimension: dates.full_date
  fiscal_year_start: 7    # July, as AdventureWorks
filters:
  - id: fy
    dimension: dates.fiscal_year
    label: Fiscal year
  - id: region
    dimension: territories.region
    parent: territories.group_name     # cascading: picking a region narrows nothing above it, picking a group narrows regions
  - id: category
    dimension: products.category
  - id: subcategory
    dimension: products.subcategory
    parent: products.category
panels:
  - id: kpis
    type: kpi
    measures:
      - { sum: [internet_sales.revenue, reseller_sales.revenue], label: Revenue, format: money }   # across facts (see below)
      - { member: internet_sales.margin_pct, label: Gross margin, format: pct }
      - { member: internet_sales.orders, label: Orders, format: int }
    sparkline: { granularity: month }
  - id: trend
    type: timeseries
    title: Monthly revenue by channel
    series:
      - { member: internet_sales.revenue, label: Internet, color: internet }
      - { member: reseller_sales.revenue, label: Reseller, color: reseller }
    granularity: month
    style: stacked-bar
    on_click: { set_filter: fy }       # clicking a month focuses its fiscal year
  - id: mix
    type: treemap
    title: Product mix
    measure: internet_sales.revenue
    group: [products.category, products.subcategory]
    on_click: { set_filter: [category, subcategory] }
  - id: top
    type: bar
    title: Top 10 products
    measure: internet_sales.revenue
    by: products.name
    sort: desc
    limit: 10
  - id: lines
    type: table
    title: Latest orders
    columns: [internet_sales.order_number, internet_sales.order_date, territories.country, internet_sales.revenue]
    order: { internet_sales.order_date: desc }
    limit: 50
layout:                   # 12-column grid; rows top to bottom
  - [kpis: 12]
  - [trend: 8, lines: 4]
  - [mix: 7, top: 5]
```

Notes for Phase 1 to settle:
- **Cross-fact arithmetic (settled in Phase 3: `sum` plus `ratio` of two sums, nothing more).** "Revenue across both channels" is a sum of two measures from two cubes. Either allow a small,
  closed set of combinations in the spec (`sum` of measures with the same unit) or require such a measure to exist in Cube
  (a view or a combined cube). Prefer the second if Cube can serve it from rollups; fall back to `sum` only.
- **Labels and translations.** Labels in the spec, with an optional `labels_tr:` block, or a per-locale label file. Keep it
  simple: one language per dashboard file is acceptable for v1.

### Panel types (v1, and only these)

| Type | Draws | Interactions |
|---|---|---|
| `kpi` | one tile per measure, optional sparkline and comparison to the previous period | none |
| `timeseries` | line, bar or stacked bar over a time granularity, several series (several cubes allowed) | click sets a filter; granularity switch (Phase 4) |
| `bar` | ranked horizontal bars, optional split by a dimension (stacked) | click sets a filter |
| `treemap` | nested rectangles over one or two dimensions | click sets one or two filters |
| `table` | rows of dimensions and measures, sort, limit, Excel export | click on a row sets a filter (Phase 4) |
| `text` | a short Markdown note | none |

Every panel: a title, the Table/Excel toggle the current dashboard has, a loading state, and an error state that shows a
readable message (never raw HTML from a proxy, as the 404 page did on the demo).

## The validator and compiler: `dashspec`

A Python CLI in `dashboards/dashspec/` (uv-runnable like the other scripts):

```
dashspec validate dashboards/*.yml [--cube-url URL]   # schema + member checks; non-zero exit on error
dashspec compile  dashboards/sales-overview.yml -o dashboards/build/sales-overview.json
dashspec meta     --cube-url URL                       # compact catalog of cubes, measures, dimensions (for the agent)
dashspec lint     dashboards/sales-overview.yml --cube-url URL   # warnings: panels no rollup serves
```

- **Schema:** the JSON Schema, with error messages that name the panel and the field.
- **Members:** every member exists in Cube's `/v1/meta`, measures are measures and dimensions are dimensions, granularities
  are valid, filter `parent`s are dimensions, layout ids exist and every panel is placed once.
- **Rollup lint:** for each panel's queries, ask Cube's `/v1/dry-run` whether a pre-aggregation serves it, and warn when not
  (at 250M rows an unserved panel costs seconds, see `spike/results.md`). A warning, not an error: on the live mart it is fine.
- Runs in CI on every file in `dashboards/`, against the mock stack (`dashboard/cube/tests/mock_stack.py`) or a Cube started
  in the CI job.

## Serving

- `dashboards/build/*.json` is served by the `dashboard-cube` nginx; the renderer page is `/d/<id>` and `/d/` lists the
  dashboards the signed-in user's role may see.
- The existing dashboard stays at `/`.
- Deploy is `git pull` + `dashspec compile` + reload, documented in `docs/deploy-demo.md`. (Compiling in the container on
  start is acceptable too; pick one.)

## The agent skill

`skills/dashboard-author/SKILL.md`, for Claude Code:

1. Read the request. Ask at most a few questions when the audience, the metrics or the language are unclear.
2. Run `dashspec meta` and choose members from the catalog only.
3. If a needed metric does not exist, stop and propose a Cube model change as a separate step. Never approximate it in the spec.
4. Write `dashboards/<id>.yml`, run `dashspec validate` and `dashspec lint`, fix until clean.
5. Render it against the mock stack or a dev stack with Playwright, look at the screenshot, adjust layout and labels.
6. Open a PR with the YAML, the screenshot and the lint output.

Evaluation (Phase 5 acceptance): three written requests (a sales overview for managers in English; an inventory health page
in Turkish with lira; a regional page that must respect row-level security) each produce a dashboard that validates, renders
and shows the same totals as `spike/cube/check.py` for the same filters.

## Phases (one PR each)

### Phase 1 — the spec and the validator
- JSON Schema for spec v1, `dashspec validate | compile | meta`, unit tests with good and broken examples.
- `dashboards/sales-overview.yml` describing the sales part of today's dashboard.
- CI job: validate every file in `dashboards/`.
- Acceptance: the example validates; each broken example fails with a message that names the panel and field.

### Phase 2 — shared modules (refactor, no visible change)
- Extract from `app.js` and `cube-source.mjs`: sign-in + Cube token + query runner; formatting (locale-aware); chart
  primitives (bars, stacked bars, lines, sparkline, treemap, tooltips); table + Excel export.
- The existing dashboard imports them and behaves exactly as before: the existing browser tests
  (`dashboard/cube/tests/e2e.py`, `progressive.py`, `header.py`, `dataset.py`) pass unchanged.

### Phase 3 — renderer v1
- `/d/<id>` page: loads the compiled JSON, builds the grid, renders `kpi`, `timeseries`, `bar`, `table`, `text`, global
  filters (with cascading parents), per-panel loading and error states, Excel export, the dataset switch.
- Multi-cube panels: one query per cube, merged on shared dimensions.
- Panels load independently and in parallel, like today; filter changes cancel in-flight queries.
- Acceptance: `sales-overview.yml` renders the KPIs, the monthly trend, top products and a table with the same numbers as the
  current dashboard for the same filters (a check script compares them), on both datasets.

### Phase 4 — interactions and the treemap
- `on_click: set_filter` (cross-filtering), clicking again to undo (as `toggleChild` does today), `treemap`, a granularity
  switch on `timeseries`, row click on `table`.
- Acceptance: the sales section of the current dashboard is fully reproduced from YAML (screenshot comparison per role:
  admin, `na_manager`, `de_rep`), and row-level security is unchanged (the `cube/tests` suite still passes).

### Phase 5 — localization, theming, the agent
- `locale` and `currency` (tr-TR, TRY), Turkish month names and number formats; `theme:` (colors, logo, name) per dashboard.
- A Turkish example dashboard on `inventory_health` (read-only lists and KPIs, no Approve).
- `skills/dashboard-author/SKILL.md`, `dashspec lint` (rollup coverage via dry-run), and the three-request evaluation above.

### Phase 6 — documentation
- `docs/dashboards.md`: authoring guide, spec reference (generated from the schema where possible), panel gallery with
  screenshots, how to add a metric to Cube first, how to deploy.

## Risks

- **Scope creep** into a general BI tool. Hold the non-goals and the panel list.
- **Parity takes longer than expected**, because `app.js` has many small touches (axis breaks for gaps, fiscal-year logic,
  progressive rendering). Accept small visual differences; numbers must match exactly.
- **Rollup coverage**: a YAML author can easily ask for a grain no rollup serves. The lint warning and the agent's loop
  exist for this; at 250M rows treat a lint warning as a blocker.
- **Cross-fact measures** need a clear rule (see the spec notes) or the spec gains arithmetic, which is a slippery slope.

## Open questions

- ~~Compile at deploy time on the server, or in CI with the JSON committed?~~ Settled in Phase 3: committed (`dashboards/build/`), a test fails if it is stale, a deploy is `git pull`.
- One language per dashboard file, or labels per locale in one file?
- Should `/d/` replace `/` once parity is reached, with the inventory and actions as their own page?
