# Plan: a slicer on any field of the model

Status: **proposed** (written 2026-11-04), waiting for answers to the questions at the end. Three phases, one PR each, like [`PLAN-designer.md`](PLAN-designer.md) phases 9 and 10.

## Goal
A slicer can show the values of **any dimension in the Cube model** that the dashboard's data can be filtered by: colour, subcategory, country, a ship date. It no longer has to be a filter declared first in `filters:`.

```yaml
panels:
  - id: colour
    type: slicer
    dimension: products.color      # new: any dimension; the slicer is its own filter
    display: chips
  - id: region_slicer
    type: slicer
    filter: region                 # as today: draws a filter that already exists
```

## How it works today (phase 9, #114, #115)
- A slicer **points at a filter**: `filter: <id>` (required), plus `display: list | chips | dropdown`. The filter keeps its type, scope and default, and is drawn in the slicer instead of the header bar.
- So the slicer's values can already come from any dimension, but only in two steps: declare a filter on it, then a slicer that draws it. The designer works the same way. "Filter" in the slicer's drawer lists only the dashboard's filters, and the gallery's *Slicer* first looks for a filter without a slicer.
- The options query (`slicerQueries` / `slicer_queries`) is the filter's dimension, narrowed by every other filter that applies to the slicer and by the drill period, never by its own value. It uses one measure per cube from the panels the filter narrows (`option_measures`).

## The design: a slicer with a `dimension` becomes a filter when the file is compiled
This is the same move as `cross_filter` (phase 10, `dashspec/crossfilter.py`): the file says what the author means, and the compiler writes what the page already knows how to run.

- **Spec:** a slicer has **either** `filter: <id>` (unchanged) **or** `dimension: <cube.field>`, with the filter's own settings next to it, all optional:
  - `label` (default: the field's name);
  - `type` (`select`, the default; `multiselect`, `text`, `number`, `date`; the type must fit the field, as for a filter);
  - `default`;
  - `applies` (`page`: the panels of the slicer's tab, the default on a dashboard with tabs; `dashboard`: every tab).
  - `display` stays as it is.
- **Compile** (`dashspec/slicers.py`, run **before** the cross-filter expansion):
  - A `dimension` slicer adds a filter `{ id: "sl_<panel id>", dimension, label, type, default, scope, tab, source: <panel id> }` and points the panel's `filter` at it.
  - A panel that cannot join to the field ignores that filter (added to `ignore_filters`, as the cross-filter expansion does).
  - Because the made filter is a visible `select`, a cross-filtering click on a bar by the same field reuses it, so clicking a region bar ticks the region slicer.
  - The source file keeps only `dimension`: the designer, versions and review see what the author wrote.
- **The page and the query mirrors do not change:** they read the compiled file, in which every slicer has a `filter`. The address carries the value as `?sl_colour=Red`.
- **Members used:** the slicer's dimension counts as a field the dashboard reads. Who may open a dashboard (datasets and grants) and the builder's catalog checks already go by those, so a slicer on a governed field hides the dashboard from people who may not read that field, exactly like a filter on it.

## Validation (`dashspec/validate.py`)
- Exactly one of `filter` and `dimension`. A file's own filter ids may not start with `sl_` (as with `xf_`).
- `dimension` exists in the model and is a dimension; `type` fits it (`date` needs a time field, `number` a number field); `default` is a value of the type, checked by the filter rules already there (the made filter is validated, so the messages are the same).
- **It must narrow something:** at least one data panel in its scope can join to the field. Otherwise the slicer has no options to show (the options query needs a measure from a panel it narrows), and the error says which panels were checked.
- **One control per field:** a `dimension` slicer is refused when a visible filter on the same field applies to the same panels. The two would AND, and a reader would see two controls for one thing. The message says to use `filter: <id>` to draw the existing one.
- `display` only with `select` / `multiselect`, as today.

## Designer (phase 2)
- **The slicer's drawer** gets **Field**: every dimension the role may read that at least one panel on the slicer's tab can join to, grouped by cube, from the existing `dimensionOptions`.
  - Choosing a field writes `dimension` (and drops `filter`).
  - The drawer also has **Type**, **Default**, **Applies to** and **Shown as**, the filter card's controls reused.
  - **Draw an existing filter** stays as a second choice (writes `filter`, drops the rest).
- **The gallery's Slicer** adds a `dimension` slicer on the first field the tab's panels can join to that no filter or slicer uses yet. It no longer creates a header filter first.
- **A filter card's "Show it as a slicer in the layout"** stays as it is (filter mode).
- **Turning a `dimension` slicer into a header filter:** "Move to the filter bar" on the slicer's drawer writes a filter with the same settings and removes the slicer. The reverse is the filter card's existing switch.

## Builder (phase 3)
- The model's spec guide (`builder/core.py`) gets the `dimension` form.
- The rule-based stand-in understands "a slicer for colour / by country" (`dilimleyici`), adding a `dimension` slicer on that field. It also understands "make region a slicer" for an existing filter.

## Performance: a field outside the rollups
A slicer on any field can ask Cube for a field no pre-aggregation has (colour, say), and its options query then reads the raw facts. That is fine on the live mart and slow on the 250M tier.
- `dashspec lint` already reports every query no rollup serves, and the slicer's options query is among the queries it checks (`slicer_queries`). Nothing new is needed there.
- The designer shows a one-line note under **Field** when the field is in no rollup of the panels' cubes, using the model's pre-aggregation dimensions, which the catalog can carry.
- The docs say: add the field to the rollup, or expect a slow first load on large data.

## Tests
- **Phase 1:**
  - Validator cases, one per rule above.
  - The compile output: the made filter, its scope on tabs, `ignore_filters` on a panel that cannot join, and the cross-filter click reusing the slicer's filter.
  - The sample `sales-drilldown.yml` gets a colour slicer, so `test_python_queries_match_the_renderers` covers its options query.
  - A browser check in `renderer.py`: the chips show the colours, a click narrows the panels, the address has `sl_colour`, and Reset clears it.
- **Phase 2:** `designer-structure` / `designer-model` unit tests (Field options, add, switch modes, move to the bar); a browser check in `designer.py`.
- **Phase 3:** composer prompts in English and Turkish, and refusals for a field the role cannot read.

## Phases (one PR each)
1. Spec, validator, compile (`slicers.py`), reference and guide docs, the sample slicer, tests.
2. Designer: Field in the slicer's drawer, the gallery's slicer, the mode switch, the rollup note.
3. Builder: spec guide and stand-in.

## Questions for you
1. **Which panels a field slicer narrows by default on a dashboard with tabs:** its tab (`page`, my recommendation: what a slicer means in Power BI, and what `cross_filter` already does) or every tab?
2. **A field that already has a header filter:** refuse the second control (recommended), or allow both (they would AND)?
3. **Which fields the designer offers:** only those the slicer's tab can filter (recommended; a slicer that narrows nothing is refused anyway), or every dimension in the model with the ones that cannot apply greyed out?
4. Should **phase 3 (builder)** be part of this work now, or later?
