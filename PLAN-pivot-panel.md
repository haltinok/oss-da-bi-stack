# Plan 2: pivot table panels

Status: **Phase 1 done** (spec, validator, query plan, pure model; no rendering yet). Depends on the totals query from [`PLAN-table-totals.md`](PLAN-table-totals.md) (Phase 1 there). The user asked for a "pivot table visuals collection"; this plan delivers one new panel type, `pivot`, with a small set of variants, and a gallery section that shows them.

## Goal
A `pivot` panel: row dimension(s) down the side, one column dimension across the top, measures in the cells, with row totals, column totals and a grand total, plus optional heat shading. Read-only and spec-driven like every other panel; no drag-and-drop field picker.

## Fit with the existing design
- Every number still comes from Cube. Cube has no `ROLLUP`, so the pivot is **ordinary queries merged in the renderer**, in two waves (built in Phase 1, `pivotQueries` in `plan.js`, mirrored in `dashspec/queries.py`):
  - **Wave 1, the axes**, asked only of the first measure's cube: the top rows by that measure (or by name), the first columns by name, and for two row levels the groups. Limits are asked as `limit + 1`, so the panel knows more exist.
  - **Wave 2, the values**, asked of every measure's cube and narrowed to the rows and columns wave 1 chose: the cells; each row's total (all columns); each column's total and the grand total (**whole set**, not only the rows shown); for two row levels the group cells and group totals.
  Totals are asked, never summed in the browser, so ratios and distinct counts stay right. `pivotModel` turns the answers into numbers (pure, no DOM).
- **No "Other" row.** An exact "Other" would be the total minus the shown rows, which only works for additive measures; a ratio or a distinct count cannot be subtracted. So rows and columns past the limit are simply not shown, the panel says that more exist, and every total still covers the whole set.
- Row-level security and role rules apply to each query as to any other panel.
- Pre-aggregations: all queries are served by one rollup that has the measures and both dimensions (a rollup with more dimensions serves fewer). `dashspec lint` checks all of them (the shapes, without the key filters).
- Plain JS and HTML, no framework. A pivot is an HTML `<table>` (accessible, copyable, printable), not SVG.

## Spec (additive; `type` enum gets `pivot`)
```yaml
- id: mix
  type: pivot
  title: Revenue by category and year
  rows: [products.category]            # 1 or 2 dimensions; 2 gives a group header row with a subtotal
  columns: dates.fiscal_year           # exactly one dimension, or a time dimension with granularity
    measures:                            # 1 to 3; with more than one, the measures become a second header level
    - { member: internet_sales.revenue, label: Revenue, format: money }
  totals: both                         # both | rows | columns | none (default both)
  heat: { measure: internet_sales.revenue, scale: sequential }   # optional; none | sequential (diverging later)
  order: { by: total, dir: desc }      # row order: total | label | a column value; default total desc
  limit: { rows: 25, columns: 12 }     # beyond the limit the rest is not shown, and the panel says so; totals still cover everything
  on_click: { set_filter: [category, fy] }   # a cell sets the row filter and the column filter; a header sets one
```
Rules the validator enforces (messages name panel and field, like the others):
- `rows` are dimensions of cubes the measures can join to; `columns` is one dimension (or time dimension + granularity from the allowed list); the same dimension cannot be in `rows` and `columns`.
- Measures from several cubes are allowed when they share the dimensions (existing `_join_errors`), merged on `rows + columns`.
- `limit` bounds: rows ≤ 200, columns ≤ 24 (a wider pivot is a table). `heat` and a time `columns` with a granularity come in Phase 3, `show` in Phase 4: the schema does not accept them before then.
- `on_click` ids must be filters whose dimension is a row dimension or the column dimension (extends `_click_errors`).
- Role rules: a role-denied measure is rejected as for other panels.

## Variants in the collection
| Variant | Spec | Purpose |
|---|---|---|
| Plain crosstab | `rows` + `columns` + 1 measure | the base case |
| With subtotals | 2 `rows` | category → subcategory with category subtotal rows |
| Heatmap pivot | `heat` | spot the hot cells (month × region) |
| Multi-measure | 2-3 `measures` | revenue and margin % side by side per column |
| Time pivot | `columns` = time dimension | months across, years as a second header level when granularity is month |
| Share-of-total | `show: share` (`value` default | `share_of_row` | `share_of_column` | `share_of_total`) | computed from the queried totals, so always consistent with them |

`show` and the shares are a Phase 4 item; Phases 1-3 ship the first four rows.

## Phases (one PR each)

### Phase 1: spec, validator, query plan (no rendering)
- Schema block for `pivot`, `$defs` for `pivot_columns`; validator rules above; `docs.py` regenerates the reference.
- `plan.js`: `pivotQueries(spec, def, values, keys?)` returns the two waves (axes, values); `pivotQueryList` is the flat list `panelQueries` and lint use; `pivot` added to `panelMeasures`; `byDims` merge helper reused. The Python mirror is `dashspec/queries.py` `pivot_queries`.
- `plan.js`: pure `pivotModel(def, axes, values)` → `{ measures, cols, rows, groups, colTotals, grand, totals, hidden, truncated }`, with ordering and limits. Pure functions only, so they are testable without a browser.
- Tests:
  - validator: good example; two dims the same; `heat.measure` not in `measures`; 3 `rows`; unknown member; `on_click` to a filter on an unrelated dimension; role-denied measure; layout still needs each panel placed once.
  - `lib_render.test.mjs`: `pivotModel` on a fixed result set: totals come from the totals queries (a ratio measure's row total is not the sum of its cells); missing cells are empty, not 0; ordering by total / label; a limit shows the first rows and columns, says more exist, and leaves the totals the whole set's; two-level rows give groups with their own figures; several cubes merge on `rows + columns`.
  - `dump_queries.mjs` fixture and `dashspec lint` see every query (a Python-equals-JS test per variant).

### Phase 2: renderer v1 (crosstab, totals, sorting)
- `render/panels.js`: `pivotPanel` through `modelPanel` (same loading/error states, Excel button; Table toggle off since it already is a table).
- `lib/table.js`: `pivotHtml(model, opts)`: sticky first column and header, right-aligned numbers, total row/column with `tot` class, group rows for subtotals, `scope="col|row"` on headers for screen readers, long headers wrapped not truncated. Everything escaped.
- Excel export: one sheet with a merged group header if a second level exists; numbers stay numbers, formatted by column type.
- Clicks per `on_click`; selected cells highlighted like a selected table row; keyboard activation as `clickable()` already provides.
- `strings.js`: Total / Toplam, a "more rows/columns not shown" note, empty-pivot message.
- Tests: `lib_render.test.mjs` for `pivotHtml` (header structure, escaping, totals placement, `colspan` for multi-measure); browser test in `dashboard/cube/tests/render.py` against the mock stack: cells equal the mock, totals equal the totals queries, a click sets filters and the other panels reload, Excel download opens and has the same numbers.

### Phase 3: heat shading, multi-measure, time pivot
- Heat: a sequential scale from the theme tokens (works in light and dark), computed over the non-total cells of the chosen measure; the cell text colour switches for contrast; a legend line with min and max. Never red/green alone: also a number in every cell.
- Multi-measure header level; time pivot with `columns` granularity and the existing `bucketLabel`.
- Tests: contrast rule unit-tested for both themes; scale bounds ignore totals; null cells are unshaded; screenshot in `gallery.py` for each variant (light and dark).

### Phase 4: shares, gallery, docs, builder
- `show: share_of_*` derived from the queried totals.
- **The collection:** a pivot section in the panel gallery (`dashboard/cube/tests/gallery.py`, `docs/dashboards.md` panel gallery) with one example per variant, and `dashboards/pivot-gallery.yml` as a validated, compiled example dashboard.
- `skills/dashboard-author/SKILL.md`: when a pivot beats a bar chart or a table; `builder/composer.py` cheat sheet and one valid-for-role example in the prompt; `builder/standin.py` can emit a simple crosstab for "X by Y and Z".
- Builder tests: output with a pivot validates for admin and rep; the reference table in the prompt includes the `pivot` rows; token budget of the prompt stays inside the figure in `docs/builder.md`.

## Acceptance
- Every cell, row total, column total and grand total equals the same number from `spike/cube/check.py` / direct SQL on the mart, on both datasets, with and without a filter, for a sum measure, a ratio measure (`margin_pct`) and a `count_distinct` measure.
- A pivot whose `limit` hides rows still reconciles at the edges: the column totals and grand total equal the whole set's figures, and the panel says rows are hidden.
- A rep never sees a profit measure or other territories' rows in a pivot (`cube/tests/test_rls.py` gets a pivot-shaped query case; the builder's role check rejects the spec for a role without access).
- Pivot on the 250M dataset: every query answered from a rollup (lint is clean) and the panel loads under the dashboard's p95 target.

## Risks and decisions
- **Five queries per pivot.** They are small and parallel; the cost is rollup coverage. Mitigation: lint, plus a documented recipe for the rollup (measure × row dim × column dim × territory, territory always included for RLS).
- **Wide pivots.** Hard limits in the schema; beyond them it is a table or a filter.
- **Cube cannot do subtotals/rollups.** We do not simulate them in the browser by summing; ratios would be wrong.
- **Not building:** drag-and-drop field lists, user-chosen aggregations, calculated fields (a missing metric goes into the Cube model, as the spec plan says).
