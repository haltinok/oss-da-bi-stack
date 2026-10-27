# Plan 1: totals row on the table panel

Status: **proposed**. One PR per phase, same style as [`docs/dashboard-spec-plan.md`](docs/dashboard-spec-plan.md). Order of the three plans: 1 (this) → 2 (pivot, [`PLAN-pivot-panel.md`](PLAN-pivot-panel.md)) → 3 (tabs, [`PLAN-dashboard-tabs.md`](PLAN-dashboard-tabs.md)). The pivot reuses the totals query built here.

## Goal
A `table` panel can show a **total row** (footer or header) for its measure columns. The total is the true total of everything the filters select, not the sum of the rows on screen.

## Why it is not "sum the rows"
- A table is cut at `limit` (default 100, max 1000), so the visible rows are a subset.
- Ratios (`margin_pct`, AOV) and `count_distinct` measures do not add up.
- Several measure cubes are merged client-side (`tablePanel` in `dashboard/static/render/panels.js`), so one query cannot give the grand total.

So the total is its own Cube query per measure cube: the same measures and filters (and the same period, via `followPeriod`), **no dimensions, no limit**. Cube computes it, row-level security applies, and a rollup that has the measure serves it (a query with fewer dimensions is served by a rollup that has more).

## Spec change (v1, additive)
```yaml
- id: lines
  type: table
  columns: [products.name, internet_sales.revenue, internet_sales.margin_pct]
  totals: footer          # footer | header; absent = no total row, so every existing file is unchanged
```
Decisions (from review):
- **Frozen.** The total row is pinned inside the table's scroll area: a footer stays at the bottom edge, a header total sits directly under the column titles; both stay put while the rows scroll.
- **Bold**, with a stronger rule (2px) between it and the rows, so it reads as a total and not as one more row.
- **Dimension cells are empty.** No "Total" label, no `totals_label` field.
- **Measure cells follow the measure's own aggregation.** The value is what Cube returns for the measure with no grouping: a `sum` measure is summed, a `count_distinct` is the true distinct count over the set, a `count`/`min`/`max` likewise.
- **Calculated measures are calculated for the set.** A ratio such as `margin_pct` or AOV is the ratio of the set's totals (profit total / revenue total), never the sum or average of the rows' ratios. This is automatic because Cube evaluates the measure's own definition over the whole set; the renderer does no arithmetic on rows.
- **Show/hide.** A `Totals` button in the panel header (next to Table/Excel; shown only when the spec has `totals`) toggles the row per viewer. It is on by default, needs no new query to flip (the totals are already loaded), and the Excel export follows what is shown. The spec's `totals` only says where the row goes.
- Not allowed when the table has no measure column (validator error naming the panel and field).
- The total covers all matching rows, not only the ones shown when `limit` cuts the table.

## Column sorting (added to this work)
Clicking a column title sorts the table. No spec field: every table gets it.
- **Cycle.** Measures: descending, ascending, none. Dimensions: ascending, descending, none. Another column starts over at its first step.
- **None** (and a table nobody has touched that has no `order`) means every dimension column ascending, left to right. A table with an `order` in the spec opens in that order; clearing a sort goes to the dimension order, not back to the spec's.
- **Cube sorts, not the browser.** `limit` cuts the rows, so a header click re-queries with the new `order` (the clicked column first, then the other dimensions ascending for a steady order). Tables merging several measure cubes sort after the merge, as they already do. A newer click aborts an older one still running.
- **Totals do not move** with the sort (the total query has no order) and stay frozen.
- Title cells are keyboard operable (`tabindex`, Enter/Space), carry `aria-sort`, and show an arrow on the sorted column. The Excel export is in the order on screen.
- `dashspec lint` mirrors the default order (`queries.py`), so a rollup check sees the same `order`.
- Tests: `tableOrder`/`nextSort`/`tableHtml` unit tests; the Python mirror for a table without `order`; browser test clicks each cycle and checks the query Cube receives, `aria-sort`, and the keyboard.

## Phases

### Phase 1: spec, validator, query plan
- `dashboards/schema/dashboard.schema.json`: `totals` enum (`header`, `footer`) on `table`.
- `dashboards/dashspec/validate.py`: error when `totals` is set and `tableParts(...).measures` is empty; `docs.py` regenerates `docs/dashboard-spec-reference.md` (a test already keeps it in sync).
- `dashboard/static/render/plan.js`: `tableTotalQueries(spec, def, values)` = `queriesPerCube(measures, { filters })` wrapped in `followPeriod`, no dimensions, no limit. Add it to `panelQueries` (after the row queries) and mirror it in `dashspec/queries.py`, so `dashspec lint` and `test_python_queries_match_the_renderers` cover it.
- Tests (`dashboards/tests/test_dashspec.py`, `dashboard/cube/tests/lib_render.test.mjs`):
  - `totals: footer` validates; a table with only dimension columns and `totals` fails with a message naming panel and field; a bad enum value fails.
  - `tableTotalQueries` has the table's measures, the active filters, no `dimensions`, no `limit`; one query per measure cube; honours `ignore_filters` and the drill-down period.

### Phase 2: renderer
- `tablePanel` runs the totals queries in the same `runAll` as the rows (parallel, same abort signal). Merge the per-cube results with `totals()` from `plan.js`.
- `lib/table.js` `tableHtml` takes an optional `totals` ({ position, cells }); the row is a `<tfoot>` row / a second `<thead>` row with class `tot`, `position: sticky` inside `.tbl-wrap` (footer `bottom: 0`; header `top` = height of the title row, set by a small `pinTotals(host)` after render), bold, 2px rule, opaque background so rows scroll under it. Keep numeric alignment. Dimension cells are empty.
- `strings.js`: `totals` (button label) in English and Turkish.
- Excel export: the `sheet() of the panel appends the total row (header position: right under the column titles), formatted with the same column types. Update `xlsx.js` only if it cannot style a row; otherwise reuse.
- Failure of only the totals query: rows still render, the total cells show "–" and the panel's error tooltip names the cause (never raw proxy HTML, `readable()` already does this).
- Tests: `lib_render.test.mjs` for `tableHtml` with totals (footer, header, none, text-escaping of the label); browser test in `dashboard/cube/tests/render.py` against the mock stack: the row is present, bold and still visible after the body is scrolled (header and footer variants), dimension cells are empty, it equals the mock's all-rows figure (not the sum of the visible rows when `limit` cuts), changes after a filter click, and is in the downloaded sheet.

### Phase 3: mock stack, docs, builder, one real dashboard
- `mock_stack.py`: a dimensionless query already returns one row; add a case where `limit` < row count so the "not the sum of visible rows" test is meaningful.
- Use it on one real table: "Latest orders" in `dashboards/sales-overview.yml` stays without (a list of orders has no meaningful total); add it to a product or territory table in `sales-drilldown.yml` or a new gallery panel.
- `docs/dashboards.md` (table section), `skills/dashboard-author/SKILL.md` (when to use it: ranked or grouped lists, not lists of individual orders), `builder/composer.py` cheat sheet line, one example in the builder prompt.
- Builder tests (`builder/tests/test_composer.py`): the stand-in/composer output still validates; the reference table in the prompt includes `totals`.
- Check in a real stack, StarRocks 500M: the totals query p95 with and without a rollup (`spike/bench`). A table whose measures are not in any rollup gets a `dashspec lint` warning, as other panels do.

## Acceptance
- Footer total equals `spike/cube/check.py` for the same filters, on both datasets.
- With a table cut at 10 rows, the total is the all-rows figure.
- A ratio column's total is the ratio of the totals, not the sum of ratios; a distinct-count column's total is the distinct count of the set.
- All existing dashboards compile unchanged; CI jobs `dashspec`, JS tests, `builder` and the browser tests pass.

## Risks
- **Extra query per table.** One small query per measure cube, parallel. Lint warns when no rollup serves it.
- **Multi-cube `ratio`/`sum` terms in a column**: not available in tables today (columns are single members), so out of scope.
- **Role-limited members** (e.g. a rep may not read profit): the totals query uses the same members, so Cube's rules apply; the validator already rejects them per role.

## Out of scope
Subtotals by group (that is the pivot, plan 2), a total column, sorting by several columns at once.
