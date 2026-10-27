# Plan: a way to the dashboard list, search and tags (`/d/`)

Status: **approved; all phases (0-4) done**. Phase 0 is tiny and can ship first. Written to be built one phase per PR, like [`PLAN-pivot-panel.md`](PLAN-pivot-panel.md). It comes before [`PLAN-dashboard-tabs.md`](PLAN-dashboard-tabs.md): tabs change the layout contract, this plan only adds metadata and a list view, so the two do not touch each other.

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
- **Not building** (at first; synonyms came later, see `docs/dashboards.md`): a tag manager screen, tag colours, tag permissions, search on the server, full-text search inside panels.

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
- No stemming in phase 1 (`sağlık` and `sağlığı` differ by a letter, as in Turkish itself). Later, the search got a TR/EN dictionary (`lib/synonyms.js`), a short list of Turkish and English endings and one-slip tolerance for words of five letters or more; `sağlık`/`sağlığı` are still different words. See `docs/dashboards.md`.
- Tests: `lib.test.mjs` (fold with Turkish rules, words, matches, literal pattern characters, `filterItems`), and `renderer.py` against seeded saved dashboards (`mock_stack.seed_saved`): Turkish folding, owner search, several words in any order, a bracket, no match and Clear, HTML in a title shown as text, Escape, `/` (and a slash typed in the field), delete from a filtered list, no request while typing, 390 px with a 44 px field and no sideways scroll, no console errors.

### Phase 2: tags in the spec — done
Built as described, with these notes:
- Schema `tags` (array of 1-24 character strings, at most 5, unique); the character, case and spacing rules are in the validator (`dashspec/validate.py` `tag_problem`) because JSON Schema's regular expressions cannot say "a letter of any language". Messages name the field and say what to write; nothing is fixed silently. For a capital the message suggests the lower-case form (only for ASCII text, since Turkish `I`/`ı` and `İ`/`i` cannot be guessed).
- `dashspec build` writes `tags` into `index.json` (the key is left out when a dashboard has none). The five checked-in dashboards have tags (`sales`; `sales, regional`; `envanter, stok` in Turkish; `sales, reference` for the gallery); a test requires every checked-in dashboard to have them.
- `builder/saved.py` `tags_of(row)`: read from the row's YAML, cached by `(id, version)`, sanitised (anything odd gives fewer tags or none), returned as a copy so a caller cannot change the cache; `meta()` carries `tags`, so the list, a save and an update all return them, including for a dashboard the viewer's role cannot open.
- The model guide and the `dashboard-author` skill say: write tags only when the request names a topic or group, 1-3 words, in the dashboard's language, most important first, nothing sensitive. The stand-in writes none.
- Nothing is drawn yet; the list page ignores `tags` until Phase 3.
- Tests: dashspec (7 good shapes including Turkish letters and a 24-character tag; 16 bad ones with the message checked; compile and index carry tags; no key when there are none; every checked-in dashboard has tags), builder (own and shared rows carry tags, a private dashboard stays private, an unreadable one still shows tags, a new version shows its new tags, odd YAML gives fewer tags and never an error, the cache cannot be changed by a caller, tags survive the builder checks, the guide explains them, the stand-in writes none).

### Phase 3: tags in the list — done
Built as described, with these notes:
- The whole list page moved from `main.js` into `render/list.js` (the prompt box, search, tag bar, built list, saved lists, semantic layer); the pure parts are in `lib/tags.js` (`tagsOf`, `withTags`, `tagCounts`, `groupByFirstTag`, `parseListUrl`, `listSearch`, `chipsHtml`).
- **Cards changed shape:** the title is the link and stretches over the whole card (`.dcard .stretch::after`), so the tag chips are real buttons on top of it instead of nested in a link. The saved cards show chips too; `mountSavedList` takes the query, the selected tags, the grouping and an `onTag` callback.
- **Tag bar:** every tag with its count, most used first then Turkish order; the counts follow the search words, not the tag choice ("if I also pick this, how many?"); selected tags stay listed with a count of 0 so they can be undone. The bar is hidden when nothing is tagged.
- **Filters are AND.** Clear (✕) and Escape drop the search *and* the tags. The state is in the URL (`?q=` and repeatable `?tag=`, written with `replaceState`); odd values are cleaned (trimmed, lower case with Turkish rules, no repeats, at most 5, none over 24 characters).
- **Group by tag** by the first tag, the tags in Turkish order, "Untagged" last, each dashboard once; applies to built and saved lists only while the switch is on; the preference is in `localStorage` and the switch still works for the visit when storage is blocked.
- A chip is redrawn when used, so the focus is put back on its new self (keyboard users do not lose their place).
- Tests: `lib.test.mjs` (23): tags of odd items, AND filtering, counts and Turkish collation, grouping (once, untagged last, the first tag decides), URL round trip and cleaning, escaped chips. `renderer.py` (278): the bar and its counts, chips on built and saved cards, AND, counts following the search, the URL both ways (restored; an unknown tag), Clear and Escape, no request while filtering, grouping for built and saved lists, the switch's memory and with storage blocked, keyboard (Enter and Space, focus kept), 390 px, and chip and switch contrast (4.5:1) in both themes. A picture for the docs comes from `gallery.py`.

## Risks
- **Tag sprawl** (`satis`, `satış`, `sales`). Mitigation: strict normalisation errors, the tag bar showing what exists, the guide telling the model to prefer short common words. No synonym table until it is a real problem.
- **Retagging needs a new version** of a saved dashboard. Mitigation: it is a YAML edit the owner already knows (the builder's YAML tab); see the open decision below.
- **Tags are visible to everyone who can see the dashboard**, including the model when a dashboard is changed through the builder in LLM mode (the YAML is sent). Tags must not carry anything sensitive; the guide says so.
- **Turkish letter rules** are the classic source of search bugs; covered by the unit tests above, not by hope.

## Decisions taken (were open)
1. **Group by the first tag only.** A dashboard appears once, under its first tag; "Untagged" last.
2. **A Tags field in the Save dialog: yes, as phase 4.** Done on the server: the save and update requests take `tags`, the service writes them into the spec and runs the same validator, so the page never edits YAML text and a bad tag is refused with the usual message before anything is stored. A change of tags is a new version (it is a change to the YAML).
3. **Built (checked-in) dashboards are grouped only while the "Group by tag" switch is on.** Off by default.

### Phase 4: a Tags field in the Save dialog — done
Built as planned, with these notes:
- **Server:** `builder/saved.py` `retag(yaml, tags)` puts the tags after the description (or the title) and re-dumps; `save_new` and `update_saved` take `tags` (None leaves the YAML's own, a list sets them, `[]` removes them) and run the usual validator on the result, so there is one set of rules. A refusal that is only about tags says "Those tags are not valid." with the validator's problems; any other problem keeps the general message. The same tags again leave the text untouched (not a new version); a change is a new version, the old one keeping its tags. `POST /saved` and `PUT /saved/{id}` accept `tags` (bounded: at most 10 of at most 100 characters; the validator decides the rest).
- **Only the owner changes tags,** not an admin and not someone it is shared with (a change of tags is a change of YAML). A rename or a change of sharing leaves the tags alone.
- **Page:** a `tagEditor` (chips with a remove button, Enter or a comma adds one, "x,y" adds x and keeps y in the box, Backspace in an empty box removes the last, a half-typed tag is kept when you press Save, the box is disabled at five). It does not judge a tag; the server does. `read()` gives null until something changed, so an untouched field never overrides the YAML's tags. It is in the Save dialog (new or new version) and in a **Tags** button on a saved dashboard (owner only). English and Turkish words.
- **CI:** `builderui.py` (the Save dialog's only browser test) was not part of CI; it now runs in the `dashboard-ui` job.
- Tests: `test_saved.py` (written after the description, kept or removed, refused before anything is stored, the general message for other problems, new version or not, the old version keeps its tags, owner only, tags win over a YAML edit in the same request, `retag` on text it cannot read), `test_service.py` (over HTTP, including the request bound and the 403s), `builderui.py` (the field, Enter and comma, the refusal and its message, chips kept, remove, the saved list, the owner's tab, comma and Enter, a half-typed tag, the five-tag limit, Backspace, a refusal that changes nothing, nothing-changed does nothing, the other user sees tags but no button, 390 px).
