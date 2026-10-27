# Plan 3: tab pages in dashboards

Status: **approved; reviewed against the code on 2026-10-27; all four phases done**. It was written before the pivot, search/tags and language-switch work; those did not touch the layout contract, so the design stands, and the review below records what the current code adds. It changes the layout contract that the validator, compiler, renderer, builder, saved dashboards and docs all read.

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

### Phase 1: spec and validator — done
Built as planned, with these notes:
- Schema: `layout` moved to `$defs/layout` (shared by the file and each tab), `tabs` (2 to 8 entries; `id`, `title` of 1-40 characters, `layout`), and a top-level `oneOf` of `required: [layout]` / `required: [tabs]`; the existing message for that reads `needs exactly one of: layout, tabs`. A tab count outside 2-8 gets its own message (`a dashboard has 2 to 8 tabs, this one has 9`).
- `validate.py`: `layouts_of(spec)` gives the file's layout or each tab's; `_layout_errors` checks the rows (12 wide, panels that exist) per layout with the tab named, that a panel is placed once across all of them (naming the tabs when it is twice), and that tab ids are unique. Messages for a plain `layout` are unchanged.
- `compile.py`: each tab's rows become explicit `{ panel, span }` cells and a tabbed file has `tabs` and no `layout`.
- `docs.py` and `docs/dashboard-spec-reference.md`: `tabs`, a "A tab" table and the rule.
- **Added to this phase (they were Phase 2 and 3):** the page lays a tabbed file's tabs out one below the other (`layoutRows`), so a tabbed file cannot break a page before the tab bar exists; and the stand-in's `refine` refuses a tabbed dashboard (it rebuilds `layout` from `panels` and would flatten the tabs). The builder's model guide does not mention tabs yet (Phase 3), but the field reference in its prompt, generated from the schema, does.
- Tests: 25 dashspec cases (valid at three split points, compile shape, the plain layout still compiles to `layout`, 17 broken setups naming the tab, panel and role checks still run, a filter error is reported once, queries do not care), a stand-in test, and a browser test (the tabbed dashboard draws every panel in order, loads, no console errors).

### Phase 2: renderer — done
Built as planned, with these notes:
- **Pure parts** in `render/plan.js`: `normalizeTabs` (a plain `layout` is one untitled tab with id `main`, and no tab bar), `pickTab` (the address's tab, else the first), `tabPanelIds`, `tabKeyTarget` (arrows wrap, Home and End jump).
- **`showDashboard`:** all panels are created once; one `.rgrid` per tab (`role="tabpanel"`, hidden unless open); a `role="tablist"` bar of `role="tab"` buttons (roving `tabindex`, `aria-selected`, `aria-controls`), named by a new string `tabsLabel` (Tabs / Sekmeler). `loadAll` loads the **open tab's** panels (a newer load cancels an older one, so moving quickly costs nothing); `openTab` shows the tab, writes `?tab=` (the first tab leaves the address clean) and loads it. The period bar and the filters stay above the tabs.
- **Freshness:** a panel's own cache (`loadedKey`: filters and period) already reloads a stale panel, so a filter changed on another tab is applied when you come back; a tab whose data is older than `REFRESH_MS` is reloaded with `force` when it is opened (`tabLoadedAt`, exposed on `window.__render` for the test). Refresh and the automatic refresh reload the open tab.
- **Export all** loads every panel first (the never-opened tabs, and any left stale by a filter change), then exports all of them.
- **Hidden panels:** `modelPanel`'s `ResizeObserver` now skips a redraw while its panel has no width (its tab is hidden); it redraws by itself when the tab is shown. Panels of an unopened tab are never loaded, so they never measure 0.
- **Automatic activation:** an arrow key both moves the focus and opens the tab (loading is cached and a quicker move cancels the previous load, so it stays cheap).
- Tests: `lib_render.test.mjs` (84), `renderer.py` (330): a plain layout has no bar; the bar, its names and its semantics; opens on the first tab; only the open tab asks Cube for data; choosing a tab shows, loads and writes the address; the first tab keeps the address clean; back and forth sends nothing; an old tab reloads; a filter chosen before, and one changed while away, both apply; `?tab=` opens and loads only that tab and survives a reload; an unknown tab falls back quietly; the period is shared; arrows, wrap, Home, End and the focus; Export all takes every tab; the language switch keeps the tab; 390 px; contrast in both themes.

### Phase 3: builder, saved dashboards, authoring skill — done
Built as planned, with these notes:
- **Model guide** (`builder/core.py` `SPEC_GUIDE`): the top-level line says `layout (or tabs)`, and a `tabs:` paragraph says it replaces `layout`, 2-8 pages, each panel on exactly one tab, filters and the period shared, only the open tab loads, **use tabs only when the request asks for pages or separate topics or audiences, or the dashboard would pass about 8 panels**, KPIs and the main chart on the first tab, titles of 1-3 words in the dashboard's language. The field reference in the prompt is generated from the schema and already carried `tabs` and the "A tab" table (a test asserts it).
- **Example:** after the first full example the model is shown the same dashboard again as a `tabs:` block (`tabs_example`: the same rows split in two, titles in Turkish when the example is). It is valid by construction and a test merges it into the example for every role and validates it. The prompt grew by about 250 tokens (admin about 9,700, rep 8,300, purchasing 7,700, measured; `docs/builder.md` had said 6,000-8,000 and is corrected).
- **Mistakes come back naming the tab** (that was the validator's work in phase 1): tests with a scripted model send a panel placed on two tabs, a row of 11 on the second tab and both `layout` and `tabs`, each fixed in a second attempt, and a rep's tabbed file with profit on its first tab is refused after three tries.
- **The stand-in does not write tabs and refuses to change a tabbed dashboard** (done in phase 1; the browser test now shows its message in the draft bar and that the tabs are untouched).
- **Saved dashboards needed no change:** the stored value is the YAML and a dashboard is validated and compiled when it is opened. Tests: save, open (as a rep, shared with everyone), list (readable, tags), a dashboard saved before tabs still opens with its layout, changing a dashboard to tabs is a new version and the old version keeps its layout (restore brings it back), a tabbed file with a member a role cannot read is refused for that role and shown greyed to it, tags and tabs together, and over HTTP (`/validate`, `/saved`, the refusal's message).
- **Builder page:** the draft view is the same renderer, so a tabbed draft has the tab bar. Browser test (`builderui.py`, 102): a draft edited into tabs in the YAML tab is applied and drawn, every panel in the page and only the first tab open, the second tab loads, the stand-in's refusal, saving opens it with its bar, a saved tabbed dashboard opens on `?tab=details`, Edit opens it as a draft with its tabs, and the list shows it.
- **Authoring skill:** `skills/dashboard-author/SKILL.md` has the tabs rule, the YAML shape in its spec page, the messages to expect and the "put the KPIs and the main chart first" advice (only the open tab loads, which matters at 250M rows).
- Not done: the stand-in does not split a long request into tabs (it never writes them; the plan's "more than 8 panels" rule was dropped on purpose, a model decides).

### Phase 4: gallery, real dashboard, docs — done
- **The real dashboard is `pivot-gallery.yml`** (not `sales-drilldown`, as the plan suggested): it is the heaviest page (33 queries and five pivots on open) and the one tabs help most. Three tabs: Overview (the intro, the plain cross-tab, two measures side by side: 12 queries), Groups and shares (15), Heat (6). Opening it now asks Cube for 12 of the 33.
- **The old single-page version is not kept as a fixture:** four other checked-in dashboards (`sales-overview`, `sales-drilldown`, `regional-sales`, `envanter-sagligi`) keep a plain `layout`, and every test of the plain path still runs on them; a dashspec test requires that both kinds exist.
- **Tests moved with it** (`renderer.py`): the pivot-gallery test now checks the three tab titles, that only two pivots are drawn on open and the other tabs' panels are not, that opening the second and the third tab draws their panels, that **opening the gallery asked Cube for under 60% of what its three tabs need** (the plan's acceptance criterion, asserted against the mock stack), and that a click on a cell still filters the whole page.
- **Picture:** `gallery.py` writes `tabs.png` (the bar and the open tab) and opens the right tab before it shoots the groups, heat and share pictures; the docs show it. `dashboards/README.md` and `docs/dashboards.md` describe tabs; `dashspec`'s CI job validates and compiles the new file with the others.

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
