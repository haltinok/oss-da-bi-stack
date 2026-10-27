# Plan: a way to the dashboard list, search and tags (`/d/`)

Status: **proposed, waiting for approval**. Phase 0 is tiny and can ship first. Written to be built one phase per PR, like [`PLAN-pivot-panel.md`](PLAN-pivot-panel.md). It comes before [`PLAN-dashboard-tabs.md`](PLAN-dashboard-tabs.md): tabs change the layout contract, this plan only adds metadata and a list view, so the two do not touch each other.

## Goal
Finding a dashboard on `/d/` should stay easy when there are dozens of them, and related dashboards should be groupable.
0. **A link to `/d/`** (done) from the other pages, so the list is one click away.
1. **Search**: one box that filters every list on the page as you type.
2. **Tags**: short labels on a dashboard (`sales`, `inventory`, `management`), shown as chips, usable as filters and as a way to group the list.

## What the page has today (read from the code)
- **There is no link to `/d/` anywhere.** A dashboard page (`/d/<id>`, `/d/draft`, `/d/s/<id>`, all served by `dashboard/static/d.html`) has a header with the title, the live status, Export all, Refresh and the theme toggle, but nothing that leads back to the list; the original sales page `/` (`index.html`) has none either. The only shortcut is that `/d` redirects to `/d/` (`nginx.conf.template`).
- `showList()` in `dashboard/static/render/main.js` draws three things: the **built dashboards** (cards from `dashboards/build/index.json`, filtered by the signed-in role), then, when the builder service is available, the **prompt box**, **your drafts** (this browser) and the **saved dashboards** (`mountSavedList` in `builder.js`: "Your saved dashboards" and "Shared with you").
- Nothing on the page searches, filters or groups. A saved row carries `title`, `description`, `owner`, `visibility`, `updated_at`; the spec is stored as YAML (`builder.saved_dashboards.yaml`) and the service already parses it for every row on every listing (`list_saved` → `_readable_for`, cached by `(id, version, role)`).
- `dashspec build` writes `index.json` with `id`, `title`, `description`, `roles` only.

## Decisions
- **Search runs in the browser.** The lists are small (a user may save at most 50 dashboards; the built set is a handful) and are already loaded, so there is no server call, no index and no new endpoint. It matches as you type and works on all lists at once.
- **Search is forgiving.** Case-insensitive and diacritic-insensitive with Turkish rules (`satis` finds "Satış", `I`/`İ`/`ı`/`i` behave), every word must match (AND), over title, description, tags and, for saved dashboards, the owner's name.
- **Tags are a field of the dashboard spec**, `tags: [sales, inventory]`, at the top level next to `title`. Reasons: one source of truth; checked-in dashboards can have tags too, reviewed in a pull request; a saved dashboard carries them in its YAML, so there is **no database migration**; the builder, the validator and the Excel/PDF-free renderer already pass the spec around. The cost: changing a saved dashboard's tags makes a new version (it is a change to the YAML). That is acceptable; a faster path is listed under "Open decisions".
- **Tags are read from the parsed spec at list time** for saved dashboards (cached by `(id, version)` like the readability check), and written into `index.json` by `dashspec build` for the built ones. A saved dashboard that the viewer's role cannot open still shows its tags (they are metadata, not data), so it can be found.
- **A tag is a short, plain word**: at most 5 per dashboard, 1-24 characters, lower-case letters, digits, spaces and hyphens (letters of any language: `satış` is fine), trimmed and unique. The validator normalises nothing silently: `Sales` is an error that says "use `sales`", so two spellings do not sneak in.
- **Grouping is by the first tag.** The author lists the most important tag first; the others serve search and filtering. A dashboard then appears once, under one heading ("Untagged" last). (Grouping by every tag would repeat dashboards and make counts confusing.)
- **The view is shareable**: `?q=...&tag=sales&tag=management` in the URL restores the search and the tag filters; whether the list is grouped is a per-viewer preference kept in `localStorage` (wrapped in try/catch, the page works without it).
- **Not building**: a tag manager screen, tag colours, tag permissions, synonyms, search on the server, full-text search inside panels.

## Phases (one PR each)

### Phase 0: a link to the list — done
Built as a slim **Dashboards** link (a small grid icon and the word) on a line of its own **above the header**, on every dashboard page (`/d/<id>`, `/d/draft`, `/d/s/<id>`, including the error pages, so a wrong role or a missing dashboard still leads back) and on the sales page `/`. It is a plain link to `/d/`, so it works with the keyboard, middle-click and "open in a new tab". It is hidden on the list itself, uses the page's own language (`Dashboards` / `Panolar`), goes to the plain list (the leaving page's filters are not carried over) and is a 44 px high target on a phone. No keyboard shortcut for now.
Why a line of its own: the first designs put it in the header (before the title, then as an icon in the tools row). `dashboard/cube/tests/header.py` rejected both: the sales page's header row has no spare width at 1280 px or with a wide fallback font (it wrapped to two rows, 94 px). A line above the header cannot disturb that row.
Tests: `renderer.py` (link and its target on a built dashboard, on an error page and on a dashboard that does not exist; opens the list and is hidden there; Turkish; 390 px: visible, 44 px target, no sideways scroll), `render.py` (the sales page), `header.py` unchanged and passing.

### Phase 1: search — done
Built as described, with these notes from the code and the tests:
- There is **no "your drafts" list on `/d/`** (the one draft lives at `/d/draft` and has no card), so the search covers the **built dashboards**, **your saved dashboards** and **those shared with you**.
- `dashboard/static/lib/search.js` (`fold`, `words`, `matches`, `filterItems`, pure); `main.js` `showList` (the field, the filtering, the count, `/`, Escape, Clear); `builder.js` `mountSavedList` now takes the query and returns a handle that redraws the lists from what it already has, and keeps the search after a delete. English and Turkish words in `strings.js`.
- The count ("3 of 7") is one line for all lists; each saved list also shows its own ("Your saved dashboards (0 of 4)").
- Matches title and description for built dashboards, plus the owner for saved ones. A description counts: "satis" finds *Envanter sağlığı* because its description says "satış panosundaki".
- No stemming (`sağlık` and `sağlığı` differ by a letter, as in Turkish itself); documented in `docs/dashboards.md`.
- Tests: `lib.test.mjs` (fold with Turkish rules, words, matches, literal pattern characters, `filterItems`), and `renderer.py` against seeded saved dashboards (`mock_stack.seed_saved`): Turkish folding, owner search, several words in any order, a bracket, no match and Clear, HTML in a title shown as text, Escape, `/` (and a slash typed in the field), delete from a filtered list, no request while typing, 390 px with a 44 px field and no sideways scroll, no console errors.

### Phase 2: tags in the spec
- Schema: `tags` (array, max 5, strings 1-24 characters, unique); `dashspec/validate.py`: the character and lower-case rules with messages that name the field and say what to write (`tags[1]: 'Sales' has capitals; use 'sales'`); `docs.py` description; `docs/dashboard-spec-reference.md` regenerated.
- `dashspec build`: `index.json` entries get `tags` (omitted when empty).
- `builder/saved.py`: `meta()` gets `tags`, taken from the parsed spec of the row, cached by `(id, version)`, sanitised (a bad or missing `tags` gives `[]`, never an error in a list). `list_saved` stays one pass.
- Builder guide (`builder/core.py`) and the `dashboard-author` skill: "write `tags` only when the request names a topic or group; 1-3 words, lower case, in the dashboard's language"; the stand-in writes none.
- Existing dashboards: give the five checked-in ones tags (`sales`, `inventory`, `reference` for the gallery) so the feature has something to show.
- Tests:
  - dashspec: a good list; more than 5; empty string; 25 characters; duplicate; capitals; punctuation, `<`, `"`, a newline; a non-string; Turkish letters accepted; compile and index carry tags; the committed build is current.
  - builder: `list_saved` returns tags for own and shared rows, for a row the role cannot open, and `[]` for a row whose YAML has no or a broken `tags`; the cache is keyed by version (an updated dashboard shows its new tags); the prompt guide mentions `tags`; the stand-in output is unchanged.
  - Nothing is rendered yet in this phase except what the API returns.

### Phase 3: tags in the list
- Cards (built, drafts, saved) show tag chips. Clicking a chip adds that tag to the filter; the active tags appear as removable chips next to the search field (AND with the search words and with each other). A **tag bar** under the field lists the tags that exist on the visible lists with counts, so people reuse them instead of inventing synonyms.
- A **Group by tag** switch (off by default, remembered in `localStorage`): headings by first tag with counts, "Untagged" last; the saved lists group the same way.
- URL: `?q=`, `?tag=` (repeatable) restored on load and updated with `history.replaceState`; an unknown tag in the URL is shown as an empty result, not an error.
- Tests:
  - node: tag counting, AND filtering, grouping by first tag, "Untagged" last, a dashboard appears once.
  - Browser: chips render and are escaped, a chip click filters and the tag bar counts follow the search, removing a chip, the grouped view and its headings, the switch survives a reload and works when `localStorage` throws, the URL round trip, keyboard operation of chips and the switch, phone width (390 px: the tag bar wraps, no horizontal scroll), dark theme contrast of the chips (the same measured check as the pivot heat).
- Docs: `docs/dashboards.md` (a short "Finding dashboards" section with a picture), `docs/builder.md`, gallery picture via `gallery.py`.
- Acceptance: with 30 saved dashboards across 6 tags, a person reaches the one they want in at most two interactions (a chip, then a word).

## Risks
- **Tag sprawl** (`satis`, `satış`, `sales`). Mitigation: strict normalisation errors, the tag bar showing what exists, the guide telling the model to prefer short common words. No synonym table until it is a real problem.
- **Retagging needs a new version** of a saved dashboard. Mitigation: it is a YAML edit the owner already knows (the builder's YAML tab); see the open decision below.
- **Tags are visible to everyone who can see the dashboard**, including the model when a dashboard is changed through the builder in LLM mode (the YAML is sent). Tags must not carry anything sensitive; the guide says so.
- **Turkish letter rules** are the classic source of search bugs; covered by the unit tests above, not by hope.

## Open decisions (need your answer before Phase 2 or 3)
1. **Group by the first tag only (recommended) or by every tag?** Every tag repeats a dashboard under several headings.
2. **A Tags field in the Save dialog?** It would write `tags` into the YAML for the owner without opening the YAML tab. Not in the phases above because it edits the YAML text from the page; it is a small Phase 4 if you want it.
3. **Should the built (checked-in) dashboards be grouped by default** when they have tags, or only when the switch is on? Recommended: only when the switch is on.
