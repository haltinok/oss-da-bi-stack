# Plan: key figures compared with the previous period

Status: **done** (written and built 2026-11-04; phases 1 and 2 in one PR, as they are small). `dashboards/README.md` listed this under "Not yet". The other item there, a different time dimension per panel, already shipped as `time_dimension` (#129).

## Goal
A key-figures panel can show, under each value, how it changed from the previous period:

```
Revenue           Gross margin
$12.4M            41.2%
▲ 8.3% vs FY2020  ▼ 1.1 pts vs FY2020
```

The old hard-coded page (`dashboard/static/app.js`, `renderKpis`) did this for one case: the fiscal-year select, compared with the year before. The spec-driven renderer has the `.delta` line and its `up`/`down` styles, but nothing fills them.

## Spec change (v1, additive)
```yaml
- id: kpis
  type: kpi
  compare: previous_year          # previous_year | previous_period; absent = no comparison, so every existing file is unchanged
  measures:
    - { sum: [internet_sales.revenue, reseller_sales.revenue], label: Revenue, format: money }
    - { member: internet_sales.discount_amount, label: Discounts, format: money, better: lower }
```
- `compare` is on the panel: every tile in the row compares the same way.
- `better: higher | lower` on a measure picks the colour: by default a rise is good (green) and a fall bad (red); `lower` reverses this, for costs, returns or discounts.

## What "the previous period" is
The tile's value comes from its Cube query: the filters that apply to the panel, plus the drill-down period. The comparison sends **the same query with its time constraints moved back**. Nothing else changes: other filters, row rules and the period's date field stay as they are.

Time constraints are:
1. **Date ranges**: the drill-down period (a `dateRange` on a time dimension) and a `date` filter's `inDateRange` (`between`, `on`, dynamic dates like `last_month`).
2. **Year values**: an `equals` filter on a dimension named `fiscal_year` or `calendar_year` (of any date role: `dates.fiscal_year`, `ship_dates.fiscal_year`). This is the same rule the validator uses for a time chart's click rule.

How they move:

| | `previous_year` | `previous_period` |
|---|---|---|
| a date range | both ends 12 months back (the last day of a month stays the last day: Feb 29 → Feb 28) | whole months (starting on the 1st, ending on a month's last day): back by that many months; otherwise back by the number of days, ending the day before it starts |
| year values | each value minus 1 | a single year minus 1; several consecutive years (`in:2021,2022`) back by how many there are |

**No comparison** (the tile shows a quiet "no period chosen to compare" line, and no second query is sent) when:
- the query has no time constraint at all (all periods: there is nothing earlier to compare with);
- a time constraint cannot be moved: an open range (`before`, `after`), `notEquals` on a year, a year value that is not a number, years that are not consecutive (`previous_period`).

Other date parts (a month-name or quarter select) are left as they are. With `previous_year` that is right (March 2021 against March 2020). With `previous_period` and a month select, the result compares the same month of the previous year. The reference says so.

## The number shown
- `pct` measures (fractions such as a margin): the **difference in points**, `▲ 1.2 pts`.
- Others: the **relative change** `(now − before) / |before|`, `▲ 8.3%`.
- No value before, or before is 0: "no data to compare" (quiet), no arrow.
- No change (to the shown precision): no colour.
- After the number, `vs <what>`: `vs FY2020` / `vs 2020` when the only thing moved is a single year value; otherwise `vs previous year` / `vs previous period`. The tile's tooltip gives the dates or years compared.
- The arrow has an `aria-label` (up/down), as the old page did. The Excel sheet of the panel gets a "vs previous" column.

## Queries
- `kpiQueries` (`dashboard/static/render/plan.js`) returns a third list, `previous`: the `now` queries with their time constraints moved, or `null`. It is built from the `now` queries themselves (after `activeFilters` and `followPeriod`), so it cannot drift from them.
- The moving lives in `dashboard/static/lib/compare.js` (pure, no DOM) with a Python mirror, `dashboards/dashspec/compare.py`. A table of cases (`dashboards/tests/test_compare.py` plus `dump_compare.mjs`) runs both and compares them, like the filter mirror.
- `panel_queries` in `queries.py` includes the comparison queries, so `dashspec lint` checks that a rollup serves them, and `test_python_queries_match_the_renderers` covers them. They have the same shape as the `now` queries with different values, so the rollup that serves one serves the other.
- The tile runs `now` and `previous` at the same time. A failed comparison leaves the value standing and shows its message on the delta line.

## Validation
- `compare` only on a `kpi` panel, `better` only on a key figure's measure. The schema does both: its `measure` definition is used by key figures only (time-chart series have their own), so no validator rule is needed.
- A designer that sets `better` without `compare` is harmless (nothing to colour) and is not refused.

## Phases
1. **Spec, queries, tiles.** Schema + `docs.py` text, validator, `compare.js` + `compare.py` + mirror test, `kpiQueries` / `panel_queries`, tile rendering and strings (en, tr), the Excel column. `sales-overview.yml` and `regional-sales.yml` use `compare: previous_year`. Docs: `docs/dashboards.md`, `dashboards/README.md` (the "Not yet" line goes).
2. **Designer.** A "Compare with" choice on the key-figures card (none, previous year, previous period), and "Which way is good" on each tile once the row compares.

## Not in this plan
- A fixed comparison with no period chosen (for example "last 30 days against the 30 before" when nothing is selected). A dashboard that wants this gives its date filter a default (`rel:last_30_days`), and the comparison follows it.
- A comparison line on time charts.
