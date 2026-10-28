# Plan: a visual designer for dashboards

Status: **approved; phases 1 to 4 done** (the rest is not started). One PR per phase, like [`PLAN-pivot-panel.md`](PLAN-pivot-panel.md) and [`PLAN-dashboard-tabs.md`](PLAN-dashboard-tabs.md).

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
Pivot's measures and heat, `sum` and `ratio` builders with a plain-words preview, **conditional formatting**, **logo upload** (both need spec fields and validator rules first).

## Open decisions
- Whether phase 2's gallery should offer "start from a template" (a finished panel) as well as an empty type. Leaning yes, but it is a content job.
- Whether design mode should be allowed on the built (checked-in) dashboards. They are reviewed in pull requests, so the likely answer is: it opens a draft copy, like a shared saved dashboard.
