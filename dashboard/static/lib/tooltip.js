// One floating tooltip for a page: elements carry data-tip="<id>" and the tooltip shows the html registered under that id.
import { esc } from "./dom.js";

/** @param tip the #tip element (position: fixed in style.css). Returns tipAttr(html) -> id, tipLines(title, [[label, value, color?]]) -> html, and clear() (forget every registered tip before a redraw). */
export function createTooltip(tip) {
  const tips = new Map();
  let seq = 0;
  const tipAttr = (html) => { const id = String(++seq); tips.set(id, html); return id; };
  const tipLines = (title, lines) =>
    `<div class="t">${esc(title)}</div>` + lines.map(([label, value, color]) =>
      `<div class="l"><span>${color ? `<i class="swatch" style="background:${color}"></i>` : ""}${esc(label)}</span><b>${esc(value)}</b></div>`).join("");
  function place(x, y) {
    const r = tip.getBoundingClientRect();
    let left = x + 14, top = y + 14;
    if (left + r.width > innerWidth - 8) left = x - r.width - 14;
    if (top + r.height > innerHeight - 8) top = y - r.height - 14;
    tip.style.left = `${Math.max(8, left)}px`;
    tip.style.top = `${Math.max(8, top)}px`;
  }
  function show(target, x, y) {
    const html = tips.get(target.dataset.tip);
    if (!html) return;
    tip.innerHTML = html;
    tip.classList.add("on");
    if (x == null) { const b = target.getBoundingClientRect(); x = b.left + b.width / 2; y = b.top; }
    place(x, y);
  }
  const hide = () => tip.classList.remove("on");
  document.addEventListener("pointermove", (e) => {
    const t = e.target.closest?.("[data-tip]");
    if (t) show(t, e.clientX, e.clientY); else hide();
  });
  document.addEventListener("focusin", (e) => { const t = e.target.closest?.("[data-tip]"); if (t) show(t); });
  document.addEventListener("focusout", hide);
  document.addEventListener("scroll", hide, { passive: true });
  return { tipAttr, tipLines, clear: () => tips.clear() };
}
