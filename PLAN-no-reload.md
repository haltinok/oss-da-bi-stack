# Plan: no whole-page reloads while working on a dashboard

Status: **built** (2026-11-07): phases 1, 2 and 3. Decisions as proposed: phase 2 with phase 1, and Save replaces the draft's history entry. Small phases, one PR each.

## The problem
Three everyday actions load the whole page again in the browser (white flash, every panel blank and queried again, the scroll and the drawer's place restored from sessionStorage afterwards):

| Action | What it does today | Where |
|---|---|---|
| **Design** (or Edit) on a saved dashboard | `location.assign("/d/draft")` | `render/builder.js` `mountSavedBar` → `asDraft` |
| **Save** (or Save as new) a draft | `location.assign("/d/s/<id>")` | `render/builder.js` save pane `go()` |
| **A designer change** that `patch()` cannot apply (filters, tabs, a panel added, removed or turned into a slicer, the page's own fields) and **every undo / redo** | `location.reload()` | `render/designer.js` `commit()`, `step()` |
| The Change box, **Apply YAML**, restoring a version, sharing and tags on a saved dashboard | `location.reload()` / `location.assign` | `render/builder.js` |

The cause is one thing: `showDashboard()` (`render/main.js`) draws a dashboard **once**. It adds listeners to the document and to fixed elements (`#export-all`, `#refresh`, the timers, the designer's and the draft bar's `document` listeners, the slicer pop-ups), so it cannot be run a second time in the same page. The page's only way to show a different spec is to be loaded again. `patch()` handles the panel-only changes; everything else falls back to the browser.

## The design: one in-page "show this dashboard" that can run again
- **`mount(view)` / `unmount()`** in `render/main.js`: `showDashboard` becomes `mount({ id, spec, draft, savedDash })`, which returns a teardown. Every listener it (and what it mounts: designer, draft bar, saved bar, dnd, filter controls) adds is registered with **one `AbortController`'s signal** (`addEventListener(..., { signal })`); intervals and timeouts are cleared by the same teardown. `unmount()` aborts it, cancels the running queries, and empties `#main`, `#filters` and `#builder-host`.
- **`go(path, { spec?, replace? })`**: the page's own navigation. It `history.pushState`s the new address (or `replaceState`), unmounts, and mounts the new view, from a spec it already has (the validator's answer, the draft) without fetching it again. `popstate` (Back / Forward) runs the same path. `location.assign` / `reload` remain only for leaving the dashboard page (the list, signing out, the language switch).
- **Keeping what has not changed (no blank cards):** the panels whose compiled definition is identical before and after (and whose filters' definitions are identical) keep their **DOM and their loaded data**: the new mount takes them over instead of making them again. A panel reads the page through `ctx`; `ctx` becomes a stable object the new mount refills (spec, values, filters), so a kept panel never holds the old spec. Only new or changed panels are made and loaded. A changed filter loads the panels it applies to, as a filter change does today.
- **The reader's place:** the scroll position, the open tab, the filter values in the address and the designer's drawer (picked panel, scroll, focus) are kept in memory across `go`, not round-tripped through sessionStorage. sessionStorage stays only for a real reload (F5).
- `patch()` stays as the fast path for a panel's own fields; the new path replaces only the `location.reload()` fallback.

## Phases
**1. Re-mountable page.** `showDashboard` → `mount` / `unmount` with one AbortController for every listener and timer (main.js, designer.js, designer-dnd.js, builder.js bars, filter-controls.js). `window.__render.remount(spec)` redraws in place (all panels made again, the place kept). The designer's `commit()` and `step()` call it instead of `location.reload()`; so do the Change box and Apply YAML. `__render.mountCount` for the tests; `designer.py`'s `changes()` waits for a patch, a remount or a load. Browser check: after a filter is added, a tab made and an undo, `performance.timeOrigin` has not changed and the document has one listener set (no doubled clicks: one export, one refresh).

**2. Keep unchanged panels.** The stable `ctx`; a remount takes over the panels whose definition (and filters) did not change, with their data. Browser check: after adding a filter, the untouched cards keep their element (same node) and send no query.

**3. In-page navigation.** `go()` + `popstate`: Design / Edit on a saved dashboard, Save / Save as new, restore a version, sharing and tags use it. Address and history stay right (Back from the draft returns to the saved dashboard). Browser check: Design then Save without a page load; Back and Forward.

## Decisions to make
1. Phase 2 (keeping unchanged panels) is what removes the "every card blanks and reloads" feeling; phase 1 alone removes the browser reload (no white flash, no lost scroll) but still redraws every card. **Proposed: do both, in that order.**
2. Saving moves the address from `/d/draft` to `/d/s/<id>` with `pushState` (Back goes to the draft). **Proposed:** `replaceState`, since the draft is gone once saved and Back to it would show an empty draft.
