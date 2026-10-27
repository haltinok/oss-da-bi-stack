# Plan 3: tab pages in dashboards

Status: **approved; reviewed against the code on 2026-10-27; phase 1 in progress**. It was written before the pivot, search/tags and language-switch work; those did not touch the layout contract, so the design stands, and the review below records what the current code adds. It changes the layout contract that the validator, compiler, renderer, builder, saved dashboards and docs all read.

## Review against the current code (2026-10-27)
Read `render/main.js` (`showDashboard`), `dashspec/validate.py`, `compile.py`, `docs.py`, `builder/composer.py` and `core.py`. What changes in the plan:
- **Who reads `layout` today:** `render/main.js` (the `span` map and the grid), `validate.py` `_layout_errors`, `compile.py`, `docs.py` (two descriptions), `builder/composer.py` (`layout()` builds it, and `refine` rebuilds it at three places), `builder/core.py` (the guide), tests. `dashboard/static/app.js` (the sales page at `/`) has its own unrelated layout. Nothing else: lint, queries, saved dashboards and the list page only look at `panels`.
- **The compiler writes explicit cells** (`{ panel, span }`), so a tab is compiled the same way inside `tabs[].layout`, and `layout` is left out of a tabbed file.
- **`refine` in the stand-in would flatten tabs** (it rebuilds `layout` from `panels`). Phase 3 must make the stand-in say it cannot change a tabbed dashboard (edit the YAML, or use a model) instead of silently losing the tabs.
- **Loading is already per panel.** `modelPanel.load` caches by filter values and period (`loadedKey`), so activating a tab can just call `load` on its panels: stale ones reload, loaded ones redraw. `loadAll` takes the list of panels to load.
- **Hidden panels redraw by themselves:** each panel's `ResizeObserver` fires when its tab is shown (width 0 to real), so no manual redraw is needed; a tab's panels are only loaded after it is shown, so they never measure 0.
- **Auto-refresh and Refresh** (`REFRESH_MS`) reload the active tab only. A tab's data older than `REFRESH_MS` is reloaded with `force` when it is opened, so a hidden tab never shows stale numbers.
- **Export all** (`#export-all`) loads the tabs that were never opened first (it is an explicit action), then exports every panel.
- **URL state** is written by one `writeUrl` that edits only the keys it knows, so `?tab=` joins it and `?lang=` / `?dataset=` pass through; the language switch reloads the page and the tab survives.
- **Tests live in `renderer.py`** (the `/d` pages), not `render.py` (the sales page). Tab specs can be patched into a compiled dashboard with `page.route`, as the pivot tests do; Phase 4 adds a real tabbed YAML.
- **Strings:** the tab bar needs one new word, its accessible name ("Tabs" / "Sekmeler"); titles are the author's.
- **Top-level `oneOf`:** the schema's existing message for "none of these `required` matched" already reads `needs exactly one of: layout, tabs`.

## Goal
One dashboard file can have several **tabs** (pages), for example "Overview", "Products", "Regions". The filter bar and the header stay; the tab bar switches the panels below. A tab is part of the URL so it can be linked and survives reload.

## Design decisions
- **Filters are global.** One filter bar, one set of values, shared by all tabs (a filter chosen on tab 1 still applies on tab 3). A per-tab filter set is a different feature; not now.
- **Panels belong to one tab; ids stay unique across the file.** `on_click` can set any filter regardless of tab, so a click never needs a panel on another tab.
- **Lazy loading.** Only the active tab's panels query Cube. Switching loads the new tab's panels (cached for the current filter values, re-fetched when a filter changed while the tab was hidden). That is the main performance win: a 3-tab dashboard costs one tab's queries on open.
- **The drill-down period** (set by a time chart's drill) is global like filters; it is shown in the period bar on every tab.
- **Backward compatible.** `layout` stays valid and means a single, untitled tab with no tab bar. `tabs` is an alternative to `layout`; exactly one of them is present. Every existing file compiles unchanged.

## Spec (additive)
```yaml
tabs:
  - id: overview                 # used in the URL: ?tab=overview
    title: Overview
    layout:
      - [kpis: 12]
      - [trend: 8, mix: 4]
  - id: products
    title: Products
    layout:
      - [top: 6, categories: 6]
      - [lines: 12]
```
- `panels` stays one flat list (the panel definitions); the tabs only place them. This keeps the panel schema, `panelQueries`, `lint` and the builder's per-panel checks untouched.
- `tabs`: 2 to 8 entries, unique `id` (same pattern as other ids), non-empty `title`.
- `text` panels work as tab intros as before.

Compiler: `dashspec compile` turns each tab's rows into explicit `{ panel, span }` cells, like `layout` today, and emits only what was written (no `layout` in a tabbed file); the renderer normalizes (`layout` → `tabs: [{ id: "main", layout }]`) in one function, so there is a single code path and old compiled JSON in `dashboards/build/` and in saved dashboards still loads.

## Phases (one PR each)

### Phase 1: spec and validator
- Schema: `tabs` array; `layout` no longer required, `oneOf` required `layout` / `tabs` at top level.
- `validate.py` `_layout_errors` generalized to a list of `(where, layout)`: each tab's rows add up to 12; a panel is placed exactly once **across all tabs**; unknown panel ids named with the tab id (`tab 'products': row 2: no panel with id 'top'`); duplicate tab ids; a tab with no panels. A panel not placed in any tab is an error, as today.
- `docs.py` regenerates `docs/dashboard-spec-reference.md`; `docs/dashboards.md` gets a Tabs section.
- Tests (`dashboards/tests/test_dashspec.py`): valid two-tab file; both `layout` and `tabs` fail; neither fails; panel placed in two tabs fails; panel placed nowhere fails; row not 12 wide in tab 2 names the tab; duplicate tab id; one tab only (schema min 2) fails; every existing `dashboards/*.yml` still validates; role checks still run per panel.

### Phase 2: renderer
- `render/main.js`: `normalizeTabs(spec)` → always a list; the grid builds one `.rgrid` per tab (`hidden` for the inactive), panels created once up front like now (`createPanel` is cheap; the **load** is deferred). `span` map is built from all tabs.
- Tab bar: `role="tablist"`, buttons `role="tab"` with `aria-selected`, `aria-controls`; arrow keys move, Home/End jump; hidden when only the implicit tab exists. Styled in `render.css` with theme tokens, horizontally scrollable on a phone, with a visible focus ring.
- State: `?tab=<id>` in the URL (`writeUrl`), unknown or role-hidden value falls back to the first tab. Switching uses `history.replaceState`, like filters.
- Loading: `loadAll()` loads the active tab's panels; `activateTab` loads the panels whose `loadedKey` (filter values + period) is stale. Hidden panels do not redraw on resize; on show they redraw once (charts need a laid-out width: SVG panels read `clientWidth`, so redraw after un-hiding).
- Export all loads the tabs never opened, then exports every panel; per-panel download unchanged. Auto-refresh and Refresh reload the active tab; a tab older than `REFRESH_MS` reloads with `force` when it is opened.
- `strings.js`: no new words needed unless a tab-level error message is added.
- Tests:
  - JS unit (`lib_render.test.mjs`): `normalizeTabs` for `layout` and `tabs`; tab fallback for an unknown id.
  - Browser (`dashboard/cube/tests/renderer.py`, mock stack, tabs patched into a compiled dashboard with `page.route`): a two-tab spec opens on tab 1 and sends **no** queries for tab 2's panels (count them in the mock); switching sends them; `?tab=products` opens directly there; a filter set on tab 1 is applied on first load of tab 2 and in its queries; reload keeps the tab; keyboard navigation works; a single-layout dashboard shows no tab bar and is pixel-identical to before (existing `shot.py` baselines).
  - Existing e2e tests (`e2e.py`, `progressive.py`, `header.py`, `dataset.py`) pass unchanged.

### Phase 3: builder, saved dashboards, authoring skill
- `builder/composer.py` cheat sheet and `builder/core.py` prompt: how and when to use tabs (more than ~8 panels, distinct audiences/questions per page; otherwise one page); one valid example with two tabs for the role; the reference table comes from the schema so it updates itself (test asserts `tabs` is in it).
- Builder loop: validation errors now name the tab, so retries stay precise. The stand-in (`builder/composer.py`) does not write tabs, and its `refine` (which rebuilds `layout` from `panels`) refuses a tabbed dashboard with a clear note instead of flattening it; a model edits the whole file and is not affected.
- Builder UI (`render/builder.js`): the draft view shows the tab bar (it is the same renderer); the "change this draft" box is unchanged.
- Saved dashboards (`builder/saved.py`, Postgres): the stored value is the spec JSON, so tabs need no migration; test that a saved single-layout dashboard from before still loads and that a saved tabbed one round-trips (private/shared/role visibility unchanged).
- `skills/dashboard-author/SKILL.md`: guidance and an example.
- Tests: `builder/tests/test_composer.py` (a tabbed example validates for admin and rep, a rep's example contains no denied members on any tab), `test_core.py` (a model answer with an invalid tab placement is sent back with the tab-naming message, and fixed within 3 tries), `test_saved.py` (round trip).

### Phase 4: gallery, real dashboard, docs
- Convert one real dashboard to tabs where it helps (e.g. `sales-drilldown.yml` → Overview / Breakdown), keeping the old single-page version as a test fixture so both paths stay covered.
- Gallery/doc screenshots; `dashboards/README.md` and `docs/builder.md` updated; CI `dashspec` job validates and compiles the new file.

## Acceptance
- All existing dashboards, compiled JSON and saved dashboards open exactly as before.
- A tabbed dashboard issues no queries for hidden tabs until they are opened; total queries on open fall roughly in proportion to the share of panels on tab 1 (assert in the mock stack).
- Tab, filters and period are all restored from the URL.
- Keyboard and screen-reader operable (tablist semantics); works at phone width.
- Builder produces a valid tabbed dashboard for a request with several topics, for admin and for rep.

## Risks
- **Charts hidden at load measure width 0.** Mitigation: deferred load and redraw after un-hiding; covered by the browser test.
- **Stale hidden tabs.** A filter change while on tab 1 marks tab 2 stale; it loads on activation (the `loadedKey` check), never shows old numbers.
- **Prompt size for the builder.** Tabs add a section to the reference; check the token figure in `docs/builder.md` and trim the examples if needed.
- **Layout contract changed in many places.** That is why it ships last, with the normalizer as the single reader of `layout`/`tabs` in the browser and `_layout_errors` as the single one in Python.

## Out of scope
Per-tab filters, nested tabs, tab-level role visibility, user-reorderable tabs, drag-and-drop layout.
