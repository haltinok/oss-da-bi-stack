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
