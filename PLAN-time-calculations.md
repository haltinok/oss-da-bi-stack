# Plan: time intelligence in calculations, `prior()` and `rolling()`

Status: **planned** (2026-11-15), not started.

## Goal
A calculation (`calculations[]`, used as `calc.<id>`) is arithmetic over the measures of **one result row**. It is parsed in `dashboards/dashspec/calculations.py` and evaluated in the browser by `dashboard/static/lib/calc.js` through `queriesPerCube` → `runAll` → `combine` in `dashboard/static/render/plan.js`. Time intelligence needs values from **other rows**: the same group one period earlier (YoY, MoM), or the last N time buckets (rolling sums and averages).

Today only key-figure tiles do this, with `compare: previous_year | previous_period` (`lib/compare.js` and its mirror `dashspec/compare.py`). The goal is two functions any calculation can use, on any panel where they make sense. They stay model-agnostic (no member names in `dashboard/` or `dashboards/dashspec/`), every query they add stays rollup-served and checked by `dashspec lint`, and Cube preview features (`time_shift`) are not used.

```yaml
calculations:
  - { id: revenue_yoy, label: Revenue vs last year, format: pct,
      formula: (a.revenue - prior(a.revenue, year)) / prior(a.revenue, year) }
  - { id: revenue_mom, label: Revenue vs last month, format: pct, formula: a.revenue / prior(a.revenue, month) - 1 }
  - { id: revenue_r12, label: Revenue, last 12 months, formula: rolling(a.revenue, 12) }
  - { id: price_r3,    label: Average price, 3-month rolling, formula: rolling(a.revenue, 3) / rolling(a.units, 3) }
```

## The language (additive, v1)
- `prior(<measure>, <unit>)`, unit one of `year | quarter | month | week | day`. The measure's value one unit earlier, for the same group.
- `rolling(<measure>, <N>)`, N an integer from 2 to 36. The sum of the measure over this time bucket and the N−1 before it. A rolling average is `rolling(x, N) / N`, or a ratio of two rollings (a ratio of sums, matching the totals rule).
- The argument is a single model measure, not an expression and not a calculation. Nesting is refused.
- AST nodes: `{"prior": "<member>", "by": "<unit>"}` and `{"rolling": "<member>", "n": N}`. `members_of` and `realMembers` include their measures, so cube reach, the join check and lint work unchanged.

## What the functions mean, per panel
| Panel rows | `prior(x, unit)` | `rolling(x, N)` |
|---|---|---|
| Grouped by a time bucket (time chart, a pivot's `{member, granularity}` column, a KPI sparkline) | The row whose bucket is `unit` earlier: Mar 2021 → Mar 2020 (`year`) or Feb 2021 (`month`). Day buckets move by calendar months, so Feb 29 has no match (no value). | This bucket and the N−1 before it, per group (the other dimensions). Missing buckets count as 0. |
| Grouped by a year field (`yearFields` from model.config.yml) | The row with year − 1 (`year` only) | refused |
| No time grouping (KPI value, bar, pie, table, pivot without a time column) | The panel's time constraints moved back by `unit`, as `compare` does: a range by 12, 3 or 1 months, 7 days or 1 day; a year value −1 for `year` only. With nothing to move, or a constraint that cannot be moved (open range, `notEquals` year, a year value with a non-year unit), the result is no value. | refused (no time axis) |

Allowed units per bucket granularity (otherwise the validator refuses it): year → `year`; quarter → `year`, `quarter`; month → `year`, `quarter`, `month`; week → `week` and `year` (= 52 weeks, so Monday matches Monday); day → any; hour → refused. A panel with `granularities` or `drill` must allow the unit at every level.

`rolling()` is allowed only on **additive** measures: Cube type `sum` or `count`. `count_distinct`, `count_distinct_approx`, `avg`, `number`, `min` and `max` are refused with a message saying why (twelve monthly distinct counts are not a 12-month distinct count) and pointing to a Cube `rolling_window` measure in the model. `prior()` accepts any measure, since nothing is added together.

## Queries
**`prior`.** For each distinct unit used on a panel, one extra query per cube, holding only the measures read through `prior(·, unit)`. It is the panel's query with its time constraints moved back by the unit.
- Time-grouped panels move the date range the same way (so the earlier buckets come back). With no range (all time), the shifted query equals the now query and is reused.
- Identical queries (a shifted query equal to the now one, or a KPI `compare` query equal to a `prior(·, year)` one) are sent once: `runAll` dedupes on the JSON of the query.

**`rolling`.** No extra query. The now query's date range starts N−1 buckets earlier, and the extra rows are dropped after the calculation.
- With no range, the first N−1 buckets of the data have no value (incomplete windows).
- With a year-value constraint and time grouping (fy=2021, monthly), the year filter is widened to the years the window reaches (`equals [2020, 2021]`, the same shape).

**Moving and widening** is shared code: `compare.js` generalises from the two `kind`s to a shift `{months: n} | {days: n}` plus year steps, with `previous_year` / `previous_period` expressed through it, so KPI `compare` behaves exactly as before. Python mirror in `compare.py`, both covered by the existing `dashboards/tests/test_compare.py` + `dump_compare.mjs` table (new cases added).

**Lint.** `per_cube` / `panel_queries` in `dashboards/dashspec/queries.py` emit the shifted and widened queries, like `compare` today. `dashspec lint` then checks that a rollup serves them, and `test_python_queries_match_the_renderers` (via `dump_queries.mjs`) keeps Python and JS equal.

## Putting rows together (`combine` in `render/plan.js`, browser only)
- The `post` of a calculation gains `shifts` (unit → which part results are shifted) and `window` (time key, granularity, the requested start, per-rolling N).
- Shifted rows are re-keyed **forward** before merging: the time bucket moves by +unit, a year field +1, and the measure is renamed `prior:<unit>:<member>`. They only fill keys that exist among the now rows (a shifted row with no now row is dropped).
- Rolling: rows are grouped by their non-time dimensions and walked in bucket order over the full bucket sequence (gaps = 0), filling `rolling:<n>:<member>`. Rows before the requested start are then dropped.
- `evaluateCalc` / `calculations.evaluate` look up `prior` / `rolling` nodes by those synthetic keys. Missing value rules are unchanged.
- Totals rows: `prior` = the formula over the shifted totals, as `compare` does. `rolling` on a total row = no value.
- Order and limit run after this, as now (a bar sorted by a YoY calculation works).
- Pure helpers (bucket arithmetic, re-keying, windowing) go into a new `dashboard/static/lib/timecalc.js` so they are unit-testable without the DOM.

## Validation (`dashboards/dashspec/validate.py`, `_calculation_errors` and the per-panel check)
- Parse errors for the new syntax: unknown unit, N out of range, argument not a single measure.
- Per use: `rolling` needs time grouping; the unit must suit every granularity the panel can show; `rolling` measures must be additive.
- Additivity comes from the catalog. Model files already give `sum` / `count_distinct` / `number`; for `/v1/meta` the catalog (`dashboards/dashspec/catalog.py` around line 194) must also read Cube's `aggType`, since `type` there is just `number`.

## Files
- `dashboards/dashspec/calculations.py`: grammar, AST, `members_of`, `evaluate`, `entry` (record units and windows used)
- `dashboard/static/lib/calc.js`: evaluator nodes; `realMembers` unchanged in shape
- `dashboard/static/lib/compare.js`, `dashboards/dashspec/compare.py`: generalised shift + widening
- `dashboard/static/lib/timecalc.js` (new): bucket math, re-key, window
- `dashboard/static/render/plan.js`: `queriesPerCube` (extra queries, widened ranges, `post.shifts` / `post.window`), `runAll` dedupe, `combine`
- `dashboards/dashspec/queries.py`: the same queries for lint
- `dashboards/dashspec/validate.py`, `catalog.py` (aggType)
- `dashboards/dashspec/docs.py` → `docs/dashboard-spec-reference.md`; `docs/dashboards.md` (a "time intelligence" section: YoY, MoM, rolling 12, rolling average, the distinct-count caveat); `dashboard/static/render/strings.js` (en, tr) for the formula help and the validation messages the designer shows
- Example use: one example dashboard per model (e.g. `dashboards/sales-overview.yml` and a distributor dashboard) gains a YoY series and a rolling-12 line. Example dashboards may name members.

## Phases
1. **Grammar, validation, query shifting** (Python + JS mirror, compare refactor with no behaviour change, new compare cases, lint).
2. **Rows and rendering** (`timecalc.js`, `combine`, dedupe, totals), JS unit tests in `dashboard/cube/tests/` (`timecalc.test.mjs`), the example dashboards, docs.
3. **Measure:** benchmark a dashboard using both functions through the spike concurrency harness at 10 and 25 users. Record p95, query count and served-by-rollup share (target ≈ the current 96–97%) in `spike/results.md`.

## Verification
- `python -m pytest dashboards/tests builder/tests`: grammar, validator, query mirror, compare cases, both models via `test_models.py`.
- `node --test dashboard/cube/tests/*.test.mjs`: `timecalc` (bucket shift across year ends, Feb 29, week 52, gaps, incomplete windows, re-key drop), `compare` (unchanged results), `combine` with prior and rolling.
- `python -m dashboards.dashspec lint` against a running Cube: the new example panels are rollup-served.
- `python3 scripts/no_model_names.py`: no new hits.
- The UI on the mock stack (port 19350) in Chrome: YoY and rolling series on a time chart, a drill-down to month and day, a fiscal-year filter, a bar sorted by YoY, the empty values with all time and an open range.

## Not in this plan
- Rolling distinct counts: a Cube `rolling_window` measure in the model with its own `count_distinct_approx` rollup, if someone asks for one.
- `prior(·, period)` (the previous bucket of whatever granularity is shown); `month` / `quarter` cover it for now.
- Expressions as arguments (`prior(a.revenue / a.units, year)`): write `prior(a.revenue, year) / prior(a.units, year)`.
- Designer UI for building these formulas beyond the help text.
