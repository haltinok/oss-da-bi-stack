// Load timers for the dashboard pages: a spinner with the running seconds while a panel waits for its data, then "✓ 1.4s" once it has landed.
// The panels already mark themselves `pending` while they load, so the timer only watches that class and needs no hook in the load code.
import { el } from "./dom.js";

const TICK_MS = 100;
const seconds = (ms) => `${(ms / 1000).toFixed(1)}s`;

/** Puts a timer into `slot` that follows the `pending` class of `target`. Returns the timer's element. */
export function watchLoad(target, slot, { before = null, now = () => performance.now() } = {}) {
  const timer = el("span", { class: "timer" }, `<i class="spin" aria-hidden="true"></i><b></b>`);
  const text = timer.querySelector("b");
  let t0 = null, tick = 0;
  const show = () => { text.textContent = seconds(now() - t0); };
  const sync = () => {
    const busy = target.classList.contains("pending");
    if (busy && t0 === null) {
      t0 = now();
      timer.classList.add("run");
      timer.classList.remove("done");
      show();
      tick = setInterval(show, TICK_MS);
    } else if (!busy && t0 !== null) {
      clearInterval(tick);
      show();
      t0 = null;
      timer.classList.remove("run");
      timer.classList.add("done");
    }
  };
  slot.insertBefore(timer, before);
  new MutationObserver(sync).observe(target, { attributes: true, attributeFilter: ["class"] });
  sync();
  return timer;
}

/** Gives every card under a panel's root a timer: in the header of a normal card, in the corner of a key-figure tile. */
export function addTimers(root) {
  const cards = root.classList.contains("card") ? [root] : [...root.querySelectorAll(".card")];
  for (const card of cards) {
    const head = card.querySelector(".card-h");
    if (head) watchLoad(card, head, { before: head.querySelector(".tbl-toggle") });
    else if (card.classList.contains("kpi")) watchLoad(card, card);
  }
}
