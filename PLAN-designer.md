# Plan: a visual designer for dashboards

Status: **approved; phases 1 to 6 done; phases 7 to 9 (filter types, filter scopes with hidden filters, the slicer) added 2026-10-28 and not started**. One PR per phase, like [`PLAN-pivot-panel.md`](PLAN-pivot-panel.md) and [`PLAN-dashboard-tabs.md`](PLAN-dashboard-tabs.md).

## Why
Today a dashboard is made by describing it to a model, or by writing YAML. Neither works for an analyst who knows what the panel should look like and
just wants to change the measure, the grouping or the chart style, or to move a panel. The competition (Power BI) is a designer; the answer is not to copy it
but to give the same people a third way to write **the same spec**: describe it, write it, or click it. The spec stays the single source of truth, so
everything built around it (the validator, role rules, version history, tests, review in a pull request) keeps working with no change.

## Decisions
- **The designer edits the spec, nothing else.** It has no model of its own: each change is a change to the dashboard's source spec (the YAML as a JSON object), and the same
  validator that checks a model's answer or a hand-edited file checks it. So a designer cannot produce a page that shows data the role may not read, and a mistake comes back
  as the validator's usual message, shown next to the field.
- **Plain JS, no library**, like the rest of the page (`dashboard/static`): no framework, no drag-and-drop package. The layout phase will use the browser's pointer events.
- **The page applies a change by loading the draft again** (phase 1). The draft already lives in this browser (`/d/draft`), a change is validated and stored, and the page
  redraws it; the selected panel and the scroll position survive in `sessionStorage`. A live redraw without a reload is a later optimisation, not a requirement.
- **Fields are declared, not coded.** Each panel type has a table of fields (key, kind, options, when it applies) that the drawer draws; adding a type or a field is
  adding a row. Kinds: text, number, choice, measure, dimension, and a list of them.
- **Only what a role may read is offered.** The member lists come from `GET /catalog`, which is already filtered by role.
- **The model keeps working beside it.** The "Change" box on the draft page edits the same draft; a designer edit and a model edit are both a new draft version.
- **Not here, on purpose:** conditional formatting and logo upload (the user's call: they come with the designer, after phase 3, since both need new spec fields and
  new validator rules), sum/ratio formula building (phase 6), server-side storage of designs other than the existing save flow.

## What the code gives us (reviewed 2026-10-27)
- The page renders the **compiled** spec (explicit layout rows, normalised table columns, a `members` map); the **source** spec is what a person edits. The builder
  service's `POST /validate` takes YAML text and returns the compiled spec but not the source, so phase 1 adds `source` to its answer (and to `check_submission`).
  JSON is valid YAML, so the designer sends `JSON.stringify(source)` and needs no YAML library in the browser.
- A draft is `{ yaml, spec, ... }` in `localStorage` (`drafts` in `render/builder.js`); a saved dashboard opens for its owner as a draft with `savedId`, so designing a saved dashboard is designing its draft and pressing Save.
- Panels keep every field of the source, so what the drawer shows for a panel is the panel's own source fields.
- A click rule (`on_click: { set_filter }`) must point at a filter on the panel's grouping dimension; changing that dimension in the designer drops the rule and says so, rather than leaving a spec the validator refuses.

## Phases
### Phase 1: the inspector (selected panel's fields) — done
Built as below. Notes: the grouping lists are filtered to the cubes **every** measure of the panel can reach (the overlap, not the sum), which on the real model is exactly the set the validator accepts for the sales-overview bar (14 of 54 dimensions); a list shows the full member name (`internet_sales.revenue`), since the short name is the same for both channels; a panel's own `readonly` items are formulas (`sum`, `ratio`), shown in words.
- Server: `check_submission` and `POST /validate` also return `source`.
- A **Design** button in the draft bar turns design mode on (kept in `sessionStorage`): panels get an outline and a name; a click selects one (and does not also filter the page).
- A **drawer** (right side; a bottom sheet on a phone) shows the selected panel's fields from the table of fields: title, and per type the measure(s), the grouping dimension(s),
  the style, the granularity, the sort and limit, the format, the totals, the text of a text panel.
- Each change is validated by the server; on success the draft is updated and the page redraws with the panel still selected; on failure the problems are shown in the drawer and the draft is left as it was.
- Tests: node unit tests for the field table and the edit functions; the server test that a spec round-trips (source → JSON → validator → same compiled spec); a browser test that selects a panel, changes a measure and a style, sees the redrawn panel, and sees a refusal.

### Phase 2: adding, removing, duplicating panels; the page's own fields — done
Built as below, with these notes: a new panel is a full-width row at the end of the open tab (moving it is phase 3), with a measure chosen by preference (revenue, orders, units, stock) among those the role may read, for a time chart one whose cube joins to the time dimension; a filter on a dimension some panels cannot join to is added to those panels' `ignore_filters`; removing a filter removes its `ignore_filters` mentions and drops the click rules that named it; the page view also has language and currency. All eight starting panels were accepted by the validator on the first try for admin, manager, rep and purchasing. No "start from a template" yet (an open decision).
A panel gallery (the types, with a picture), a first sensible default per type from the first measure the role may read, delete and duplicate, and the dashboard's title, description, filters and time dimension.

### Phase 3: layout by drag and drop — done
Built as below, with these notes: the moves are pure functions in `lib/designer-layout.js` (a randomised test applies 400 moves and checks after each that every row adds up to 12 and every panel is placed once); the pointer layer (`render/designer-dnd.js`) only turns positions into those calls, and every move is also a button in the drawer, which is the keyboard path; a drop has four edges (top/bottom: a row of its own; left/right: beside, sharing the width) plus tabs and the end of the page; the window autoscrolls near its edges (a far tab bar could not be reached otherwise); resize is a bar between neighbours and moves whole columns; tabs can be renamed and reordered, but **adding and deleting tabs, and turning a layout into tabs, are not built** (they need a decision about what happens to the panels).
Move panels between rows, resize by span (12 columns, the validator's limits shown as the snap points), reorder tabs and move a panel between tabs. Pointer and keyboard (the keyboard is not optional: the page must stay usable without a mouse).

### Phase 4: saved dashboards and history — done
Built as below, with these notes: a **Design** button on a saved dashboard opens the same draft as Edit (with `savedId`) and turns the designer on; a non-owner gets **Design a copy**; undo and redo live in `drafts` (`edit` records a step, `setCurrent` starts a draft with none), so they cover the Change box and the YAML tab as well as the designer, 20 steps, and the history stays in this browser; the version list shows what changed, computed on the server by `builder/changes.py` as facts (`panel_added`, `layout`...) that the page words in either language (so a new kind of change needs a line in both `strings.js` objects); a version whose predecessor has fallen out of the kept window says "Changed". Phase 5 can reuse the history as it is: a model edit already goes through `drafts.edit`.
Design mode for a saved dashboard you own (it is the draft flow with `savedId`), undo and redo for the session, the version list showing what changed.

### Phase 5: designer and model together — done
Built as below, with these notes: `POST /build` takes an optional `focus` (a panel id; it is checked against the current file and an id that is not there is ignored); the model is told "Focus: panel id …, titled …, type …: change it and leave the rest" and the stand-in (`composer.refine_panel`) edits only that panel without rebuilding the layout, so tabs survive (pie or donut, bars or columns, a chart style, top N, remove). The designer announces its pick with a `designer:pick` event on `document`; the Change box (`builder.js`) shows "The change applies to “…” only" and sends the id. Undo is unchanged: both paths go through `drafts.edit`. **Not run against a real model**: the tests use the stand-in, so how DeepSeek or Claude respects the focus is for the user to check.

The Change box sends the selected panel as the focus ("make this one a donut"); a model edit and a designer edit can be undone the same way.

### Phase 6: the rest of the types, formulas, and the two things left out
Split into three PRs: **6a** pivot's own fields and the sum/ratio builder (done), **6b** tabs (add, delete, layout into tabs; done), **6c** conditional formatting (**6c-1**, done) and logo upload (**6c-2**: `theme.logo` already takes a path or an `https://` URL; the upload would add a small data URI, decided with the user: inside the spec, PNG/JPEG/WebP up to about 20 KB, shrunk in the browser, no SVG).

**6c-2, built:** `theme.logo` also takes `data:image/(png|jpeg|webp);base64,...` (at most 20,000 characters; the validator decodes it and checks the file signature, so a script or an SVG cannot pass as an image); `lib/designer-logo.js` (sizes to try, encodings, what fits) and the Look section of the drawer (organisation name, upload, preview, remove; the browser draws the picture smaller until PNG, WebP or JPEG fits). The builder's check no longer strips an inline logo, only a path or an address. No content-security policy exists in this repository; a bank gateway's would need `img-src data:`.

**6c-1, built:** `rules` in the schema (`$defs/rules`, on a KPI measure and on a table column object; 1 to 4 of `{ when, value, tone }`), validator errors for a rule on a dimension column or a pivot measure, `lib/rules.js` (`toneOf`, first match wins), the tone drawn on a KPI tile and on table cells with a symbol and a hidden word, and in the designer three fields per rule with Add and Remove (`addRule` in `designer-items.js`). The scope the user chose: key figures and table cells only; no bars, no rules that compare with another measure. The model learns the field from the generated spec reference.

**6b, built:** in `lib/designer-layout.js`: `layoutToTabs` (a plain layout becomes two tabs, the first half of the rows and the rest; needs two rows), `tabsToLayout`, `addTab` (a tab cannot be empty, so it starts with a text `note` panel; eight at most) and `removeTab` (its panels join the neighbouring tab; at one tab left the dashboard goes back to a plain layout). The page view of the drawer has the buttons.

**6a, built:** `lib/designer-items.js` (pure: add/remove a KPI measure, a series or a pivot measure within the list's limits; turn a KPI measure or a series into a sum or a ratio and back, edit, add and remove its members, minimums two for a sum and one per side of a ratio; the formula told in words) and the pivot's `columns` step, `heat.measure`, `order` and `limit` in `designer-model.js`. An optional field emptied leaves no empty object behind (`heat: {}` would not validate). A pie's `sum` and a bar's `stack` are not in this: they stay as they were. Pivot measures cannot be formulas in the spec, so they are not offered as such.
Pivot's measures and heat, `sum` and `ratio` builders with a plain-words preview, **conditional formatting**, **logo upload** (both need spec fields and validator rules first).

### Phase 7: filter types (added 2026-10-28, not started)
Today a filter is `{ id, dimension, label?, parent? }`: one value picked from a select, sent to Cube as `equals` with one value (`plan.js` and, mirrored for the tests, `dashspec/queries.py`), kept in the URL as `?id=value`. The request is more than a single select, and the designer should be able to make all of them.

**Types** (a new `type` on a filter; the existing one stays the default, `select`):
- **`select`**: one value (today).
- **`multiselect`**: several values, `equals` with a list. A switch makes it the inverse (**not** multiselect: `notEquals`). A search box inside the list (the options are read from the data; past a limit, the search asks Cube with `contains`). Select all, clear, and invert the selection.
- **`text`**: contains, does not contain, starts with, ends with (`contains`, `notContains`, `startsWith`, `endsWith`), for names and codes.
- **`number`** (numeric dimensions): equals, not equals, **between**, **greater than**, **greater than or equal**, **less than**, **less than or equal** (`gt`, `gte`, `lt`, `lte`; between is a `gte` and a `lte`). Boxes for the numbers, with the unit of the dimension's format.
- **`date`** (time dimensions): the same comparisons (**between**, **after**, **on or after**, **before**, **on or before**: `inDateRange`, `afterDate`, `afterOrOnDate`, `beforeDate`, `beforeOrOnDate`) with date pickers, **and dynamic dates**: today, yesterday, tomorrow; this / last / next week, month, quarter, year; **last N** days, weeks, months, quarters, years (and next N); week, month, quarter, year **to date**; **fiscal** year, quarter and year to date and previous fiscal year (the spec already has `time.fiscal_year_start`); same period last year; all time. A dynamic choice is saved as a name (`last_30_days`), not as dates, so a saved dashboard stays current.
- Improvised extras worth having: **is empty / is not empty** (`notSet`, `set`) on any dimension; a **default value** for every type (the dashboard opens already filtered, and Reset goes back to it); a **"keep this filter out of the URL"** flag for filters a link should not carry; **boolean** dimensions as a three-way toggle (yes, no, both).

**What has to change underneath**
- Spec: `type`, `operator` where the type has several, `default`, and for `date` a `range` of named presets or a pair of dates; schema, validator rules (the type must fit the dimension's type: no `between` on a text dimension, no `date` on a number; a default must be one the type allows), `docs.py` and the generated reference.
- Renderer: the filter bar draws a control per type; `plan.js` turns a filter value into Cube filters (one function, tested), dynamic dates are resolved to concrete dates **in the browser at query time** (Cube's relative ranges only exist for `timeDimensions`, not for filters) using the dashboard's locale, week start and fiscal year; the URL carries `?id=a,b`, `?id=between:10..20`, `?id=last_30_days`; a click rule (`on_click.set_filter`) still sets a filter, as a one-value selection on a multiselect.
- Python mirror in `queries.py` (the tests keep the two equal), the Excel sheet's header lines that say which filters were on, and the saved views if there are any.
- Cascading: `parent` keeps working for `select` and `multiselect`; the other types ignore it.
- Designer: the filter card in the page view gets a type choice, the dimension (only those that fit the type), the default and, for a date, the preset list; a filter can change type without being deleted when the new type fits. The Change box and the model learn the new fields from the generated reference.
- Tests: node tests for the value-to-Cube-filter function and the date presets (including month ends, leap years, the fiscal year, a week that starts on Monday), the Python mirror, schema and validator cases, Playwright for each control and the URL.

### Phase 8: where a filter applies (added 2026-10-28, not started)
Three kinds, by scope (a `scope` on a filter, `dashboard` by default):
- **Dashboard filter**: in the header, applies to every panel on every tab (today's only kind).
- **Page filter**: belongs to one tab (`tab: <id>`; a plain one-page dashboard has just the one page): shown in that tab's own bar, applies to the panels on that tab only, and is not in the URL of the other tabs.
- **Pane filter**: belongs to one panel (`panel: <id>`): a small control on the panel's own card, applies to that panel only, so a chart can be narrowed without changing the page. **Open question for the user:** "pane" is read here as a single panel's card. If a different meaning was intended (for example a group of panels inside a tab), say so and this changes.

Rules to decide in the build: a panel's filters are the dashboard's, then its page's, then its own, ANDed; two filters on the same dimension in different scopes are allowed and both apply (the designer warns about it); a page or pane filter's id is unique across the file (it is a URL key) while its `ignore_filters` entry works as it does now; **Reset** resets what is in view (dashboard and the open tab's), and a pane has its own; a click rule may set a dashboard or page filter, and a pane filter only from its own panel; the designer moves a filter between scopes with a choice on the card and offers a pane filter from the picked panel's drawer; removing a tab or a panel removes the filters scoped to it (and says so). The validator refuses a scope that points at something that is not there. The built-in list order, the tab bar, and the print/export layout need a look.

**Order:** 7, then 8 (with 8b), then 9: 7 before 8: the types are useful on their own, and the scopes then apply to all of them. Each is several PRs (spec and validator, renderer and queries, designer), the same one-at-a-time rhythm as before.

### Phase 8b: hidden filters (added 2026-10-28, not started; goes with phase 8)
A filter is **visible** (the reader sees it and changes it; today's behaviour) or **hidden** (`visible: false`, chosen at design time): the reader never sees it, it always applies, with the value the designer gave it. It works at every scope (a hidden dashboard filter "region = Ontario", a hidden page filter, a hidden pane filter). A hidden filter must have a value (`default`), is never in the URL, is not cleared by Reset, and shows in the designer with an eye icon so it cannot be forgotten. The spec already lists "fixed (non-selectable) filters" under *Not in v1* in `docs/dashboards.md`: this removes that line.
**It is not a security boundary.** The value is in the page's own queries, so a reader with the browser's developer tools can see it. Who may read what stays Cube's job (the role rules); a hidden filter is for scoping a view, not for hiding data from someone. The docs say so in those words.

### Phase 9: the slicer, a filter that is a panel (added 2026-10-28, not started)
A **slicer** is a filter drawn as a panel (a `slicer` panel type): a list, buttons, a dropdown or a range slider placed in the layout like any chart, instead of in the header bar. It is the "physical" filter: the reader changes it while interacting, and it takes part in the same things the header filters do. Chosen design:
- It **is** a filter (the types of phase 7, an `id` that is a URL key, a dimension, a default); the panel only decides where and how it is drawn. A header filter and a slicer are the same thing in two places, so one spec shape (`filters[]` with `display: bar | slicer`, or a panel that points at a filter id; settle in the build) avoids two engines.
- **Affected by** the dashboard and page filters (they narrow the options it offers, and its figures if it shows counts), by **cross-filtering** (a click on a bar sets the slicer's value, and the slicer shows it) and by **drill-down** (the drill period narrows its options and the slicer does not fight it). It may have **its own pane filters**, narrowing the options only.
- **Options are never narrowed by the slicer itself**, and two slicers narrow each other's options only in one direction at a time (the one changed last does not narrow itself), so there are no cycles. This is the rule that needs a test with three slicers.
- Hidden slicers do not exist (a hidden filter has no panel); a slicer on a page belongs to that tab, like a page filter.
- The designer: it joins the gallery, and the drawer for it is the filter card plus the display choice; "make this filter a slicer" and back from the filter card.
- Order: after 7 and 8 (it needs the types and the scopes). The panel type must meet the project's own rule that "a new panel type needs two real use cases"; the two here are a region slicer on a sales page and a status slicer beside the reorder list.

## Open decisions
- Whether phase 2's gallery should offer "start from a template" (a finished panel) as well as an empty type. Leaning yes, but it is a content job.
- Whether design mode should be allowed on the built (checked-in) dashboards. They are reviewed in pull requests, so the likely answer is: it opens a draft copy, like a shared saved dashboard.
