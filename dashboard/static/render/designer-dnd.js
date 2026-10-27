// Moving and resizing panels with the pointer in design mode: a grip in each panel's corner to drag it (onto the top, bottom, left or right edge of another panel, onto a tab,
// or onto the empty end of the page), and a bar between two neighbours in a row to change their widths. The logic is in lib/designer-layout.js; this file only turns pointer
// positions into those calls. The same moves are available as buttons in the drawer, so nothing here is the only way to do anything (and a keyboard needs none of it).
import { el, esc } from "../lib/dom.js";
import { dropPanel, rowOf, setWidths } from "../lib/designer-layout.js";

const GAP = 16;                                                  // the grid's gap in px (render.css .rgrid)
const EDGE = 70, SPEED = 18;                                     // near the top or bottom of the window a drag scrolls the page, up to SPEED px a frame
const NARROW = 900;                                              // below this width every panel is a full row (render.css), so only top / bottom make sense

/** Which edge of a rectangle a point is nearest, in the sense of a drop: the outer quarters left and right, else top or bottom by half. */
export function sideOf(rect, x, y, narrow = false) {
  const rx = (x - rect.left) / rect.width, ry = (y - rect.top) / rect.height;
  if (!narrow && rx < 0.25) return "left";
  if (!narrow && rx > 0.75) return "right";
  return ry < 0.5 ? "top" : "bottom";
}

/** The columns a drag of `dx` pixels moves, given the grid's width: a column and its gap are (width + gap) / 12. */
export const columnsMoved = (dx, gridWidth) => Math.round(dx / ((gridWidth + GAP) / 12));

export function mountDnd({ panels, getSource, getActiveTab, commit, dz }) {
  let enabled = false, observer = null, frame = 0, busy = false, dragging = false;     // `dragging`: the bars are left alone while one is held (rebuilding it would drop the pointer)
  const grips = new Map(), overlays = new Map();

  const live = () => [...panels].filter(([, p]) => p.root.offsetParent !== null);            // the panels of the open tab (a hidden tab has no layout)
  const narrow = () => window.innerWidth <= NARROW;

  // ---------------------------------------------------------------------------------------------------------------- grips
  function addGrips() {
    for (const [id, p] of panels) {
      if (grips.has(id)) continue;
      const grip = el("button", { type: "button", class: "dz-grip", tabindex: "-1", "aria-hidden": "true", title: dz.drag }, "⠿");
      grip.addEventListener("pointerdown", (e) => startMove(e, id, grip));
      p.root.append(grip);
      grips.set(id, grip);
    }
  }

  function startMove(e, id, grip) {
    if (e.button !== 0 || busy) return;
    e.preventDefault();
    e.stopPropagation();
    grip.setPointerCapture(e.pointerId);
    const source = getSource();
    const title = source.panels.find((p) => p.id === id)?.title || id;
    const ghost = el("div", { class: "dz-ghost" }, esc(title));
    const marker = el("div", { class: "dz-drop" });
    document.body.append(ghost, marker);
    document.body.classList.add("dz-dragging");
    dragging = true;
    let target = null;

    const at = (x, y) => {
      const under = document.elementFromPoint(x, y);
      const tab = under?.closest?.('[role="tab"]');
      if (tab) return { target: { tab: tab.dataset.tab, end: true }, rect: tab.getBoundingClientRect(), box: "tab" };
      const node = under?.closest?.("[data-panel]");
      if (node && node.dataset.panel !== id && panels.has(node.dataset.panel)) {
        const rect = node.getBoundingClientRect(), side = sideOf(rect, x, y, narrow());
        return { target: { ref: node.dataset.panel, side }, rect, box: side };
      }
      const grid = under?.closest?.(".rgrid");
      if (grid && !node) return { target: { tab: getActiveTab(), end: true }, rect: grid.getBoundingClientRect(), box: "end" };
      return null;
    };
    const draw = (hit) => {
      marker.hidden = !hit;
      if (!hit) return;
      const r = hit.rect, t = 4, off = 6;
      const box = { top: [r.left, r.top - off, r.width, t], bottom: [r.left, r.bottom + off - t, r.width, t], left: [r.left - off, r.top, t, r.height], right: [r.right + off - t, r.top, t, r.height],
        tab: [r.left, r.top, r.width, r.height], end: [r.left, r.bottom - t, r.width, t] }[hit.box];
      Object.assign(marker.style, { left: `${box[0]}px`, top: `${box[1]}px`, width: `${box[2]}px`, height: `${box[3]}px` });
      marker.classList.toggle("tab", hit.box === "tab");
    };
    let pointer = { x: e.clientX, y: e.clientY }, raf = 0;
    const retarget = () => {
      ghost.style.transform = `translate(${pointer.x + 14}px, ${pointer.y + 14}px)`;
      const hit = at(pointer.x, pointer.y);
      target = hit?.target ?? null;
      draw(hit);
    };
    const move = (ev) => { pointer = { x: ev.clientX, y: ev.clientY }; retarget(); };
    const autoscroll = () => {                                                         // so a far tab bar or panel can be reached while a panel is held
      raf = 0;
      if (!dragging) return;
      const y = pointer.y, h = window.innerHeight;
      const dy = y < EDGE ? -Math.ceil((SPEED * (EDGE - y)) / EDGE) : y > h - EDGE ? Math.ceil((SPEED * (y - (h - EDGE))) / EDGE) : 0;
      if (dy) { window.scrollBy(0, dy); retarget(); }
      raf = requestAnimationFrame(autoscroll);
    };
    const finish = async (apply) => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", up);
      grip.removeEventListener("pointercancel", cancel);
      document.removeEventListener("keydown", esc_, true);
      cancelAnimationFrame(raf);
      ghost.remove();
      marker.remove();
      document.body.classList.remove("dz-dragging");
      dragging = false;
      if (apply && target) { busy = true; try { await commit(dropPanel(getSource(), id, target), { panel: id, message: dz.moved }); } finally { busy = false; } }
    };
    const up = () => finish(true), cancel = () => finish(false), esc_ = (ev) => { if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); finish(false); } };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", up);
    grip.addEventListener("pointercancel", cancel);
    document.addEventListener("keydown", esc_, true);
    move(e);
    raf = requestAnimationFrame(autoscroll);
  }

  // ---------------------------------------------------------------------------------------------------------------- resize bars
  function layoutBars() {
    frame = 0;
    if (dragging) return;
    for (const o of overlays.values()) o.replaceChildren();
    if (!enabled || narrow()) return;
    const source = getSource();
    const shown = new Map(live());
    for (const [id, p] of shown) {
      const row = rowOf(source, id);
      const i = row.findIndex((c) => c.id === id);
      const next = row[i + 1] && shown.get(row[i + 1].id);
      if (!next) continue;
      const grid = p.root.parentElement;
      const gr = grid.getBoundingClientRect(), a = p.root.getBoundingClientRect(), b = next.root.getBoundingClientRect();
      let overlay = overlays.get(grid);
      if (!overlay) { overlay = el("div", { class: "dz-overlay" }); grid.append(overlay); overlays.set(grid, overlay); }
      const bar = el("button", { type: "button", class: "dz-resize", tabindex: "-1", "aria-hidden": "true", title: dz.resize });
      Object.assign(bar.style, { left: `${(a.right + b.left) / 2 - gr.left - GAP / 2}px`, top: `${a.top - gr.top}px`, height: `${Math.max(a.height, b.height)}px`, width: `${GAP}px` });
      bar.addEventListener("pointerdown", (e) => startResize(e, id, bar, grid));
      overlay.append(bar);
    }
  }
  const schedule = () => { if (!frame) frame = requestAnimationFrame(layoutBars); };

  function startResize(e, id, bar, grid) {
    if (e.button !== 0 || busy) return;
    e.preventDefault();
    e.stopPropagation();
    bar.setPointerCapture(e.pointerId);
    const source = getSource(), row = rowOf(source, id), i = row.findIndex((c) => c.id === id);
    const [left, right] = [panels.get(row[i].id).root, panels.get(row[i + 1].id).root];
    const widths = row.map((c) => c.span), gridWidth = grid.getBoundingClientRect().width, x0 = e.clientX;
    const tip = el("div", { class: "dz-tip" });
    document.body.append(tip);
    bar.classList.add("active");
    dragging = true;
    let d = 0;
    const show = (ev) => {
      d = Math.max(1 - widths[i], Math.min(widths[i + 1] - 1, columnsMoved(ev.clientX - x0, gridWidth)));
      left.style.gridColumn = `span ${widths[i] + d}`;
      right.style.gridColumn = `span ${widths[i + 1] - d}`;
      tip.textContent = `${widths[i] + d} | ${widths[i + 1] - d}`;
      Object.assign(tip.style, { left: `${ev.clientX + 12}px`, top: `${ev.clientY + 12}px` });
    };
    const finish = async (apply) => {
      bar.removeEventListener("pointermove", show);
      bar.removeEventListener("pointerup", up);
      bar.removeEventListener("pointercancel", cancel);
      document.removeEventListener("keydown", esc_, true);
      tip.remove();
      dragging = false;
      bar.classList.remove("active");
      left.style.gridColumn = `span ${widths[i]}`;
      right.style.gridColumn = `span ${widths[i + 1]}`;
      if (apply && d !== 0) {
        const next = widths.slice();
        next[i] += d;
        next[i + 1] -= d;
        busy = true;
        try { await commit(setWidths(getSource(), id, next), { panel: id, message: dz.resized }); } finally { busy = false; }
      }
    };
    const up = () => finish(true), cancel = () => finish(false), esc_ = (ev) => { if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); finish(false); } };
    bar.addEventListener("pointermove", show);
    bar.addEventListener("pointerup", up);
    bar.addEventListener("pointercancel", cancel);
    document.addEventListener("keydown", esc_, true);
    show(e);
  }

  // ---------------------------------------------------------------------------------------------------------------- on and off
  return {
    enable() {
      enabled = true;
      addGrips();
      observer ||= new ResizeObserver(schedule);
      for (const [, p] of panels) observer.observe(p.root);
      window.addEventListener("resize", schedule);
      document.addEventListener("transitionend", schedule);
      schedule();
    },
    disable() {
      enabled = false;
      for (const g of grips.values()) g.remove();
      grips.clear();
      for (const o of overlays.values()) o.remove();
      overlays.clear();
      observer?.disconnect();
      window.removeEventListener("resize", schedule);
      document.removeEventListener("transitionend", schedule);
    },
    refresh: schedule,
    active: () => dragging,
  };
}
