# Dashboards as code

A dashboard here is **one YAML file** that names things in the Cube semantic layer (measures and dimensions) and says how to lay them out.
No SQL, no JavaScript. A validator checks the file, a renderer draws it at `/d/<id>`, and every number comes from Cube, so metric
definitions, row-level security and rollups stay in one place. A new dashboard is a reviewed file, not a new code base, and a Claude Code
skill can write it from a request.

![A dashboard drawn from YAML](images/dashboards/page.png)
*[`dashboards/sales-overview.yml`](../dashboards/sales-overview.yml) rendered from generated data (the numbers mean nothing; the layout, formats and interactions are real).*

- Reference of every field: [dashboard-spec-reference.md](dashboard-spec-reference.md) (generated from the schema).
- What you can ask for: the semantic layer, with every cube, measure and dimension, what it means and who may read it: [semantic-layer.md](semantic-layer.md) (generated from the Cube model). `scripts/dashspec meta` prints the same in the terminal.
- Describe a dashboard instead of writing it: [the builder](../builder/README.md); running it, its limits and what it sends out: [builder.md](builder.md).
- Why and how it was built, phase by phase: [dashboard-spec-plan.md](dashboard-spec-plan.md).
- The hand-written sales dashboard at `/` stays as it is: it is the showcase and the reference for look and behaviour. The inventory
  actions (Approve, campaigns, proposals) are an application, not a dashboard, and live only there.

## Five minutes to a new dashboard

```bash
scripts/dashspec meta                              # the cubes, measures and dimensions you may use (and which cubes join)
cp dashboards/sales-overview.yml dashboards/my-page.yml    # start from the closest example; the file name is the id
$EDITOR dashboards/my-page.yml                     # change id, title, panels, layout
scripts/dashspec validate dashboards/my-page.yml   # every message names the panel and the field
scripts/dashspec build                             # compiles dashboards/*.yml into the committed dashboards/build/
uv run --with playwright python -I dashboard/cube/tests/shot.py my-page --role admin    # a screenshot, no stack needed
```
Then open `http://localhost:<DASHBOARD_CUBE_PORT>/d/my-page` on a running stack (`/d/` lists what your role may open), commit the YAML **and**
the rebuilt `dashboards/build/*.json`, and open a PR. `scripts/dashspec` needs only [`uv`](https://docs.astral.sh/uv/).

Or ask Claude Code: the [`dashboard-author`](../skills/dashboard-author/SKILL.md) skill does these steps (and refuses to invent a metric).

## Describe a dashboard instead of writing it
On `/d/` there is a box: say what you want ("monthly revenue by channel and the top 5 products, with a table of the latest orders") and the
[builder](../builder/README.md) drafts the YAML for **your role**, checks it with the same validator, and draws it at `/d/draft`. Change it in words, edit the
YAML, browse the [semantic layer](semantic-layer.md) next to it, save it (private, or shared with roles or everyone; [details](builder.md#saved-dashboards)), download the file, and send it through a pull request when it should become part of the product.
Until an API key is configured, a rule-based stand-in answers (a fixed set of phrases, not free text); with a key, Claude does.

![A draft built from a request](images/dashboards/builder.png)

## Anatomy of a file

```yaml
spec: 1
id: sales-overview                 # = the file name = /d/sales-overview
title: Sales overview
locale: en-US                      # number and date formats, and the page's own words (en, tr)
currency: USD
roles: [admin, manager]            # who sees it listed; what they may read is Cube's decision
time: { dimension: dates.full_date, fiscal_year_start: 7 }
filters:                           # selects above the panels
  - { id: fy, dimension: dates.fiscal_year, label: Fiscal year }
panels:                            # see the gallery
  - { id: kpis, type: kpi, measures: [ ... ] }
layout:                            # rows of 12 columns; every panel once
  - [kpis: 12]
  - [trend: 8, lines: 4]
```

**Measures** come in three forms, for a KPI tile or a time-chart series: `member: cube.measure`; `sum: [a.m, b.m]` (the same measure of two
fact cubes added: Cube cannot join two fact cubes in one query, so the page asks each and adds the answers); and
`ratio: { num: [...], den: [...] }` (a margin over both channels). Nothing more: there is no arithmetic in a spec. If you need another
combination, it is a measure in the Cube model (see [adding a metric](#adding-a-metric-to-cube-first)).

**Formats:** `money` (compact on tiles and bars, whole units in tables), `int`, `pct` (a *fraction*: 0.153 shows 15.3%, so use a `ratio`, not a
measure that already holds percentage points), `decimal`, `number`.

**Filters** are selects; a value goes in the URL (`?fy=2021&region=Canada`) so a view can be shared. A filter applies to every panel whose
measures can join to its dimension; for a panel that cannot, list the filter in that panel's `ignore_filters` (the validator tells you).
`parent` groups a filter's options under another dimension, and narrows them when the dashboard has a filter on that dimension too.

**Drill down:** `drill: [year, month, day]` on a time chart. A click on a point opens the next, finer level for that period and, at the same time, filters every other panel
to that date range (the "period", shown as a chip and kept in the URL); a trail above the chart (`All › 2020 › Mar 2020`) goes back up, the chip's x clears it, and
a panel that should not follow lists `period` in its `ignore_filters`. On the last level a click picks one day. Years are calendar years. Chart styles: `line`,
`area`, `stacked-area`, `bar`, `stacked-bar`.

**Click to filter:** `on_click: { set_filter: <id> | [<id>, <id>] }` makes marks clickable. A click sets those filters from what was clicked;
clicking again undoes it and brings back what they held before. The clicked panel does not narrow itself with the filters it sets, so it keeps
showing every choice and marks the selected one. What a click carries: a bar its `by` value, a treemap tile its `group` values in order
(a heading only the first), a table row its dimension columns, a month its fiscal or calendar year.

## Panel gallery

| | |
|---|---|
| **`kpi`**: one tile per measure, optional sparkline. Each tile loads on its own. | ![kpi](images/dashboards/kpi.png) |
| **`timeseries`**: line, bar or stacked bar over a granularity (`granularities` adds a switch); a click sets a year filter. | ![timeseries](images/dashboards/timeseries.png) |
| **`timeseries`, `style: line`** with a `ratio` series: a margin over both channels. | ![line](images/dashboards/line.png) |
| **`timeseries` with `drill: [year, month, day]`**: a click opens the next level for that period, a trail goes back up, and every other panel follows the period. | ![drill](images/dashboards/drill.png) |
| **`bar`**: ranked; one `measure`, a `stack` of measures from several cubes, or a `split` by a dimension; `orientation: vertical` draws columns. | ![bar](images/dashboards/bar.png) |
| **`pie`** (`style: pie` or `donut`): slices by a dimension, the tail grouped as "Other"; a click filters. | ![pie](images/dashboards/pie.png) |
| **`treemap`**: one or two dimensions; with two, tiles sit under headings. | ![treemap](images/dashboards/treemap.png) |
| **`table`**: members or `{ member, label, format }`, `order`, `limit`; a row can set filters. | ![table](images/dashboards/table.png) |
| **`text`**: a short Markdown note. | ![text](images/dashboards/text.png) |
| **Filters** above the panels, with Reset when one is set. | ![filters](images/dashboards/filters.png) |

Every panel has a loading state (dimmed), an error state (the message, in its card, while the rest of the page draws), a Table view of the same
rows and an Excel button; the header has Export all, a refresh, the theme toggle and, when two datasets are served, the dataset switch.

### Language, currency, theme
`locale: tr-TR` and `currency: TRY` give Turkish separators, month names, the lira sign and the page's own words in Turkish (titles and labels
are yours to write in Turkish). Currency is display only: amounts are not converted, so say so on the page when the data is in another
currency ([`envanter-sagligi.yml`](../dashboards/envanter-sagligi.yml) has a note panel for it). `theme` sets a name, a logo and colours.

![A Turkish inventory page](images/dashboards/turkish.png)

On a phone every panel takes a full row:

![A phone](images/dashboards/phone.png)

## Roles and security
- Data access is **Cube's**: the page sends the user's own token, `cube/cube.js` filters rows by territory and refuses what a role may not
  read. The spec cannot widen it, and the renderer adds nothing to it.
- `roles:` decides who sees the dashboard listed (and gets "not available for your role" if they open it anyway; no query is sent).
  The validator checks each listed role against the same rules as Cube (a rep has no profit members, purchasing and marketing only
  inventory data, marketing no supplier data, managers and reps no inventory), so a page that would show an error to a role it lists does
  not validate. A test keeps that list equal to `cube/cube.js`.
- A tile or panel whose query Cube refuses shows Cube's message ("Profit and margin are not available for your role") instead of a
  number; the rest of the page still draws.
- Demo data only until InfoSec has approved real data ([`SECURITY.md`](../SECURITY.md)).

## Adding a metric to Cube first
If the page needs a number the model does not have, **do not approximate it in the spec**; add it to the model in its own PR, then use it.

1. **The measure.** Add it to the cube in `cube/model/cubes/<cube>.yml` (for the two sales facts, to both `internet_sales.yml` and
   `reseller_sales.yml`, with the same name, so a `sum` across them works). A new column needs a dbt change first
   (`dbt/adventureworks_starrocks/models/marts/` and its tests).
2. **The 250M dataset.** It runs the model in `spike/cube/model` (plus the two inventory cubes of `cube/model`), so a sales measure must be
   added there too, or the dashboard fails on the benchmark dataset.
3. **A rollup.** An unserved query scans the fact table: fine on the live mart, seconds at 250M rows. Add the measure to the
   pre-aggregations that serve your panels (or add one), then `scripts/dashspec lint dashboards/<id>.yml --cube-url ...` shows what is
   still unserved. A changed rollup is rebuilt; set a new `CUBE_PREAGG_SCHEMA` in `.env` to force a full rebuild of old partitions
   (see `.env.example`).
4. **Who may see it.** If it is sensitive, add it to `PROFIT_MEMBERS` or `SUPPLIER_MEMBERS` in `cube/cube.js` and to
   `dashboards/dashspec/validate.py`; the test that compares the two fails until both agree.
5. **Check it.** `cube/tests` (row-level security) and `spike/cube/check.py` (Cube equals direct SQL) need the stack; then
   `docker compose --profile starrocks up -d cube` to load the model.

## Deploying
The compiled JSON in `dashboards/build/` is committed (a test fails if it is stale) and nginx in the `dashboard-cube` service reads it on
each request, so a deploy is `git pull`. The **first** deploy of this feature needs `docker compose up -d dashboard-cube` (new mount and routes).
Nothing else changes: Keycloak's redirect URIs already cover `/d/*`, the public Caddy front door sends everything that is not `/kc`,
`/auth-api`, `/actions-api` or `/cubejs-*` to the dashboard, and `?dataset=250m` or the header switch picks the dataset exactly as on `/`:
a spec names cubes, never schemas, so every dashboard works on both. See [deploy-demo.md](deploy-demo.md).

## Testing and CI
| What | Command |
|---|---|
| Spec: validator, compiler, roles, lint (stub Cube), the Python query mirror vs the page's own builders, the committed build is current | `PYTHONPATH=dashboards uv run --with pytest --with pyyaml --with 'jsonschema>=4.18' python -m pytest dashboards/tests -q` |
| Page logic: formatting, chart geometry, queries, clicks, translations (node) | `node --test dashboard/cube/tests/*.test.mjs` |
| The renderer in a real Chrome against a mock stack (every panel, filters, clicks, errors, roles, language, theme, widths) | `uv run --with playwright python -I dashboard/cube/tests/renderer.py` |
| Look at any dashboard | `... dashboard/cube/tests/shot.py <id> --role rep --width 390` |
| Regenerate this page's images / the field reference | `... dashboard/cube/tests/gallery.py` / `scripts/dashspec docs` |

CI runs them in the `dashspec` and `dashboard-ui` jobs. Neither runs against the real Cube and Keycloak: after a deploy, open the page next to
`/` as `admin`, `na_manager` and `de_rep` and compare the figures.

## When something looks wrong
| You see | It means |
|---|---|
| The validator: `'x.y' is not in the Cube model (... has: ...)` | A member name is wrong, or the model lacks it: `scripts/dashspec meta`. |
| The validator: `cube 'a' has no join to 'b' ... Add the filter id to this panel's ignore_filters` | A filter's dimension is not reachable from that panel's measures. |
| The validator: `role 'rep' cannot read '...'` | The page lists a role Cube would refuse for that member. Remove the role or the member. |
| A tile shows `—` and a message | Cube refused or failed that query (the message is Cube's; a role limit is a 403). |
| A panel shows `⚠` and a message | The same, for a whole panel. The rest of the page is unaffected. |
| A filter select is empty | No panel applies that filter (all ignore it), so there is nothing to read its values from. |
| Orders / Avg order value arrive last | They use the exact distinct count, which a rollup cannot serve; each tile loads on its own. On the 250M dataset use a measure a rollup serves, or accept the wait. |
| Sign-in loops | The page's address is not among the Keycloak client's redirect URIs (`PUBLIC_URL/*`). |
| `/d/x` says there is no dashboard | `dashboards/build/x.json` is missing: run `scripts/dashspec build` and commit it. |

## Not in v1
Comparison with the previous period on KPI tiles; per-panel time dimensions; fixed (non-selectable) filters in a spec; folding small treemap
tiles into "Other"; languages other than English and Turkish for the page's own words; currency conversion; scheduled e-mail reports, PDF
export, alerts (out of scope on purpose: [the plan](dashboard-spec-plan.md#non-goals)). A new panel type needs two real use cases.
