// The life of the dashboard drawn in the page. What it adds outside its own elements (listeners on the document and the window, timers, queries) is tied to the
// signal of its life, so the page can draw the dashboard again, or another one, without loading itself again (render/main.js `remount`): renew() ends the old
// life, and with it everything registered on its signal.
let current = new AbortController();

/** The signal of the dashboard drawn now: pass it as `{ signal }` to addEventListener, or listen for its "abort" to stop a timer or a query. */
export const life = () => current.signal;

/** Ends the current life (every listener registered with its signal is removed) and starts a new one. */
export function renew() {
  current.abort();
  current = new AbortController();
  return current.signal;
}

// Drawing the page again: render/main.js registers its remount; until it has (or on a page without one), it is a reload.
let redrawer = () => location.reload();
/** Sets how the page draws itself again (render/main.js). */
export const onRedraw = (fn) => { redrawer = fn; };
/** Draws the dashboard again from what this browser holds (the draft, the saved dashboard), in the page: the designer's changes, undo, the Change box. */
export const redraw = () => redrawer();

// Moving to another dashboard (a draft, a saved one) without loading the page: render/main.js registers how; until it has, it is a page load.
let goer = (path) => location.assign(path);
/** Sets how the page moves to another dashboard (render/main.js). */
export const onGo = (fn) => { goer = fn; };
/**
 * Shows the dashboard at `path` (/d/draft, /d/s/<id>) in this page: the address changes (`replace`: without a new history entry) and the dashboard is drawn
 * there, keeping the cards that are the same. `keepQuery`: the filters, period and tab in the address stay (the same dashboard, in another mode).
 */
export const go = (path, { replace = false, keepQuery = true } = {}) => goer(path, { replace, keepQuery });
