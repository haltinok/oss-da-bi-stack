---
name: dashboard-author
description: Turn a request for a dashboard ("a monthly sales overview for the regional managers, in Turkish, in lira") into a validated YAML spec in dashboards/, check it, screenshot it and open a PR. Use when asked to create or change a dashboard page served at /d/<id>. Writes YAML only, never SQL or renderer code.
---

# Authoring a dashboard

A dashboard is one YAML file in `dashboards/`. Every number comes from Cube: you name Cube **members** (measures and dimensions) and
the renderer builds the queries. Full reference: `dashboards/README.md`. Plan: `docs/dashboard-spec-plan.md`.

## Rules (they are not negotiable)
1. **YAML only.** Never write SQL, JavaScript or CSS for a dashboard. If the page needs something the spec cannot say, stop and say so.
2. **Members come from the catalog.** Run `scripts/dashspec meta` and use only what it lists. Never guess a member name.
3. **A metric that does not exist is not approximated.** If the request needs one (a measure Cube does not have), stop, say which one, and
   propose a change to `cube/model/cubes/*.yml` as a separate PR. Do not fake it with a different measure or a `sum` of unrelated ones.
4. **Roles are real.** `roles:` lists who may open the page, and Cube enforces what each role may read (row-level security, profit hidden
   from `rep`, inventory only for `purchasing`/`marketing`/`admin`, supplier data not for `marketing`). The validator checks the page against
   those rules; never widen a role to make it pass. A regional page must not use profit members if reps may open it.
5. **Demo data only** until InfoSec has approved real data (see `SECURITY.md`).
6. **Do not change `cube/`, `dashboard/` or `auth/` in the same PR** as a dashboard. A dashboard PR touches `dashboards/` only.

## Workflow
1. **Read the request.** Ask at most three questions, only when the audience (roles), the metrics or the language/currency are unclear.
2. `scripts/dashspec meta` : the cubes, measures and dimensions (with types, what each means) and which cubes join; the same as a page with who may read what is `docs/semantic-layer.md`. Pick members from it.
3. **Write `dashboards/<id>.yml`.** The file name is the id (lowercase, digits, `-` and `_`). Start from the closest example:
   `sales-overview.yml` (KPIs, charts, click-to-filter, treemap), `regional-sales.yml` (no profit: safe for reps),
   `envanter-sagligi.yml` (Turkish, lira, inventory tables).
4. `scripts/dashspec validate dashboards/<id>.yml` : fix every message (each names the panel and the field) until it says `ok`.
5. `scripts/dashspec build` : compiles every dashboard into the committed `dashboards/build/` (a test fails if it is stale).
6. **Look at it.** `uv run --with playwright python -I dashboard/cube/tests/shot.py <id> --role <role> [--width 1440 --width 390] [--theme dark]`
   renders it from generated data (the numbers mean nothing; layout, labels, formats, clicks and errors are real) and prints console
   errors. Open the PNG it names (Read tool) and check: titles and labels in the right language, no clipped text, every panel drawn,
   nothing wider than the screen at 390 px. Do it once per role the page lists (an error that only a role sees shows up here as a message
   in the panel). Adjust layout and labels and repeat from step 4.
7. **Rollups.** With a Cube running: `CUBE_TOKEN=<admin jwt> scripts/dashspec lint dashboards/<id>.yml --cube-url http://localhost:4000`
   says which queries no pre-aggregation serves. On the live mart a warning is acceptable; on the 250M dataset treat it as a blocker
   (`--strict`): change the panel (fewer dimensions, a coarser granularity) or ask for a rollup in the Cube model as a separate PR.
8. **Open a PR** with the YAML, the rebuilt JSON, the screenshot(s) and the lint output. Say which request it answers and what you did
   not do.

## The spec in one page
```yaml
spec: 1
id: sales-overview            # = file name
title: Sales overview
description: One line.
locale: en-US                 # en-US | tr-TR ... (numbers, dates, month names; the page's own words exist in en and tr)
currency: USD                 # TRY gives the lira sign
roles: [admin, manager]       # admin | manager | rep | purchasing | marketing
theme: { name: Fairstone, logo: /assets/logo.svg, colors: { internet: "#2a78d6" } }   # optional
time: { dimension: dates.full_date, fiscal_year_start: 7 }
filters:                      # selects above the panels; a click can set them
  - { id: fy, dimension: dates.fiscal_year, label: Fiscal year }
  - { id: subcategory, dimension: products.subcategory, label: Subcategory, parent: products.category }
panels:
  - { id: kpis, type: kpi, measures: [ { member: x.m, label: L, format: money }, { sum: [a.m, b.m], label: L }, { ratio: { num: [..], den: [..] }, label: L, format: pct } ], sparkline: { granularity: month } }
  - { id: trend, type: timeseries, series: [ { member: a.m, label: A, color: internet, format: money } ], granularity: month, granularities: [month, quarter, year], style: stacked-bar, on_click: { set_filter: fy } }
  - { id: top, type: bar, measure: a.m, by: products.name, sort: desc, limit: 10, format: money }     # or stack: [ {member, label, color}, ... ] / split: <dimension>
  - { id: mix, type: treemap, measure: a.m, group: [products.category, products.subcategory], on_click: { set_filter: [category, subcategory] } }
  - { id: lines, type: table, columns: [ { member: a.order_number, label: Order }, { member: a.m, label: Revenue, format: money } ], order: { a.order_date: desc }, limit: 50 }
  - { id: note, type: text, markdown: "Plain **Markdown**." }
layout:                       # rows of 12 columns; every panel exactly once
  - [kpis: 12]
  - [trend: 8, lines: 4]
```
- **Formats:** `money` (compact on tiles and bars, whole units in tables), `int`, `pct` (a *fraction*: 0.153 shows 15.3%; use a `ratio`, not a
  `*_pct` measure), `decimal`, `number`. Default `number`.
- **Across cubes:** Cube cannot join two fact cubes, so combine them with `sum` or `ratio` (of two sums), or `stack` for bars. Nothing
  else: no other arithmetic.
- **A filter applies to every panel** whose measures can join to its dimension; a panel that cannot (an inventory panel under a territory
  filter) lists it in `ignore_filters`. The panel a click comes from does not narrow itself with the filters it sets.
- **Click rules** (validated): a bar sets a filter on its `by`; a treemap's filters follow its `group` in order; a table row sets filters
  on the dimension columns it shows; a time chart sets a filter on a `fiscal_year` or `calendar_year` dimension.
- **Labels:** one language per file. For `tr-TR` write every `title`, `label` and `description` in Turkish; the page's own words (buttons,
  "All", status) follow `locale`. Currency formatting is a display choice only: the data is not converted. If the demo data is in another
  currency than `currency`, say so in a `text` panel (see `envanter-sagligi.yml`).

## When the validator says no
The messages name the panel and field, e.g. `panel 'top' (bar): by: 'products.nme' is not in the Cube model (products has: ...)`. Typical:
unknown or wrongly-kinded member; a filter with no join to the panel's cube (add it to `ignore_filters`); a row not adding up to 12;
a role the page lists that Cube would refuse (remove the role or the member).

## Checking that it is right (the evaluation)
`skills/dashboard-author/evals.md` has three written requests and what each result must satisfy. A dashboard is done when it validates,
renders for every listed role without a panel error, and (with the stack up) shows the same totals as `spike/cube/check.py` for the
same filters.
