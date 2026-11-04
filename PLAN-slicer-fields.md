# Plan: a slicer on any field of the model

Status: **phases 1a to 2c built** (#179, #183, #181, #182, #184 and this one, 2026-11-04); **phase 3 (builder) later**, as decided. Small phases, one PR each, like [`PLAN-designer.md`](PLAN-designer.md) phases 9 and 10. Note from 1c: the sample slicer is *Sales group* (`territories.group_name`), not colour, because the group is in the rollups of both models.

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
  - no scope setting: a field slicer narrows **only the panels of its own tab** (the whole dashboard when there are no tabs). That is what a slicer means in Power BI and what `cross_filter` already does; a reader who wants every tab narrowed uses a header filter.
  - `display` stays as it is.
- **Compile** (`dashspec/slicers.py`, run **before** the cross-filter expansion):
  - A `dimension` slicer adds a filter `{ id: "sl_<panel id>", dimension, label, type, default, source: <panel id> }`, with `scope: page, tab: <its tab>` on a dashboard with tabs, and points the panel's `filter` at it.
  - A panel that cannot join to the field ignores that filter (added to `ignore_filters`, as the cross-filter expansion does).
  - Because the made filter is a visible `select`, a cross-filtering click on a bar by the same field reuses it, so clicking a region bar ticks the region slicer.
  - The source file keeps only `dimension`: the designer, versions and review see what the author wrote.
- **The page and the query mirrors do not change:** they read the compiled file, in which every slicer has a `filter`. The address carries the value as `?sl_colour=Red`.
- **Members used:** the slicer's dimension counts as a field the dashboard reads. Who may open a dashboard (datasets and grants) and the builder's catalog checks already go by those, so a slicer on a governed field hides the dashboard from people who may not read that field, exactly like a filter on it.

## Validation (`dashspec/validate.py`)
- Exactly one of `filter` and `dimension`. A file's own filter ids may not start with `sl_` (as with `xf_`).
- `dimension` exists in the model and is a dimension; `type` fits it (`date` needs a time field, `number` a number field); `default` is a value of the type, checked by the filter rules already there (the made filter is validated, so the messages are the same).
- **It must narrow something:** at least one data panel in its scope can join to the field. Otherwise the slicer has no options to show (the options query needs a measure from a panel it narrows), and the error says which panels were checked.
- **One control per field:** a `dimension` slicer is refused when a visible filter on the same field applies to the same panels (decided). The two would AND, and a reader would see two controls for one thing. The message says to use `filter: <id>` to draw the existing one.
- `display` only with `select` / `multiselect`, as today.

## Designer (phase 2)
- **The slicer's drawer** gets **Field**: only the dimensions the role may read that at least one panel on the slicer's tab can join to (decided), grouped by cube, from the existing `dimensionOptions`.
  - Choosing a field writes `dimension` (and drops `filter`).
  - The drawer also has **Type**, **Default** and **Shown as**, the filter card's controls reused.
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

## Phases (one small PR each)
Each phase ships something that works on its own and has its tests in the same PR.

**1a. The field slicer, written by hand.**
- Schema: `dimension` and `label` on a slicer, exactly one of `filter` and `dimension`.
- Validator: the field exists and is a dimension, it narrows at least one panel on its tab, no visible filter on the same field applies to the same panels, and file filter ids may not start with `sl_`.
- Compile (`dashspec/slicers.py`, before the cross-filter expansion): the made `select` filter, its tab scope, `ignore_filters` on panels that cannot join.
- The members-used count includes the field. Reference text in `docs.py`.
- Tests: one validator case per rule; the compile output, including a cross-filter click reusing the slicer's filter.

**1b. Its filter settings:** `type` (fits the field), `default` (checked by the filter rules) and `display` with them. Tests for each.

**1c. Seen working:** a colour slicer on `sales-drilldown.yml` (so the query mirror test covers its options), a browser check in `renderer.py` (chips show the colours, a click narrows the panels, `sl_colour` in the address, Reset clears it), and a section in `docs/dashboards.md`.

**2a. Designer, Field in the slicer's drawer:** the field list (only what the tab can filter by), writing `dimension`, the Type / Default / Shown as controls for a field slicer, and **Draw an existing filter** as the other mode. Unit tests and a `designer.py` check.

**2b. Designer, adding and moving:**
- The gallery's *Slicer* adds a field slicer on the first unused field the tab can filter by.
- **Move to the filter bar** writes a header filter and removes the slicer.

Unit tests and a browser check.

**2c. Designer, the rollup note:** the catalog carries each cube's pre-aggregation dimensions, and **Field** says when a field is in none (options read the raw data, slow on large data). A unit test.

**3. Builder (later):** the spec guide's `dimension` form; the stand-in's "a slicer for colour" / "dilimleyici" and "make region a slicer".

## Decisions (2026-11-04)
1. A field slicer narrows **only its own tab**, with no setting to widen it (a header filter does that).
2. A second control for a field that already has a header filter on the same panels is **refused**.
3. The designer's **Field** list shows **only the fields the tab can be filtered by**.
4. The builder comes **later**, after the designer phases.
