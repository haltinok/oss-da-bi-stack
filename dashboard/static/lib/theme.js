// The viewer's theme: the list of themes, the choice kept in this browser, and the menu in the header that changes it.
// "light" and "dark" are the original two (dark is shown as Black); the other five are in themes.css. With no choice kept the page follows the system.
import { el, esc } from "./dom.js";

export const THEMES = [
  { id: "light", name: { en: "Light", tr: "Açık" }, swatch: ["#f9f9f7", "#2a78d6"] },
  { id: "dark", name: { en: "Black", tr: "Siyah" }, swatch: ["#0d0d0d", "#3987e5"] },
  { id: "slate", name: { en: "Slate", tr: "Arduvaz" }, swatch: ["#1b1f27", "#6aaefc"] },
  { id: "navy", name: { en: "Navy", tr: "Lacivert" }, swatch: ["#0a1a33", "#7bb8ff"] },
  { id: "sand", name: { en: "Sand", tr: "Kum" }, swatch: ["#f5efe3", "#1f6fb5"] },
  { id: "mint", name: { en: "Mint", tr: "Nane" }, swatch: ["#eef5f2", "#0f766e"] },
  { id: "contrast", name: { en: "High contrast", tr: "Yüksek karşıtlık" }, swatch: ["#000000", "#ffe600"] },
];
const SYSTEM = { en: "System", tr: "Sistem" };
const LABEL = { en: "Theme", tr: "Tema" };
const KEY = "theme";
const known = (id) => THEMES.some((t) => t.id === id);

/** The kept choice, or null (follow the system). A value this version does not know is ignored. */
export function storedTheme() {
  try { const id = localStorage.getItem(KEY); return known(id) ? id : null; } catch { return null; }
}

/** Applies a theme (null = follow the system) and keeps the choice. */
export function setTheme(id) {
  const root = document.documentElement;
  if (id && known(id)) root.dataset.theme = id; else delete root.dataset.theme;
  try { if (id && known(id)) localStorage.setItem(KEY, id); else localStorage.removeItem(KEY); } catch { /* storage unavailable: the choice lasts for this visit */ }
}

/** Applies the kept choice; call it before the page draws. */
export const initTheme = () => { const id = storedTheme(); if (id) document.documentElement.dataset.theme = id; };

/** The theme in use now: the chosen one, else what the system asks for. */
export const activeTheme = () => document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

/**
 * Turns the header's theme button into a menu of the themes. `locale()` gives "en" or "tr" when the menu opens; `onChange(id)` runs after a choice
 * (the sales page redraws its canvas charts). Returns { label(lang) } so the page can name the button in its language.
 */
export function mountThemeMenu(button, { locale = () => "en", onChange = () => {} } = {}) {
  const wrap = el("span", { class: "theme-wrap" });
  button.replaceWith(wrap);
  wrap.append(button);
  const menu = el("div", { class: "theme-menu", role: "menu", hidden: "" });
  wrap.append(menu);
  button.setAttribute("aria-haspopup", "menu");
  button.setAttribute("aria-expanded", "false");
  const items = () => [...menu.querySelectorAll("[role=menuitemradio]")];
  const close = (focus = false) => { menu.hidden = true; button.setAttribute("aria-expanded", "false"); if (focus) button.focus(); };
  const choose = (id) => { setTheme(id); onChange(id); close(true); };
  function open() {
    const lang = locale(), chosen = storedTheme();
    const rows = [{ id: null, name: SYSTEM, swatch: null }, ...THEMES];
    menu.setAttribute("aria-label", LABEL[lang] || LABEL.en);
    menu.innerHTML = rows.map((t) => `<button type="button" role="menuitemradio" aria-checked="${(t.id ?? null) === chosen}" data-id="${esc(t.id ?? "")}" tabindex="-1">
      <i class="swatch" ${t.swatch ? `style="--a:${t.swatch[0]};--b:${t.swatch[1]}"` : 'data-system="1"'}></i><span>${esc(t.name[lang] || t.name.en)}</span></button>`).join("");
    menu.hidden = false;
    button.setAttribute("aria-expanded", "true");
    (items().find((b) => b.getAttribute("aria-checked") === "true") || items()[0]).focus();
  }
  button.addEventListener("click", () => (menu.hidden ? open() : close()));
  button.addEventListener("keydown", (e) => { if (e.key === "ArrowDown" && menu.hidden) { e.preventDefault(); open(); } });
  menu.addEventListener("click", (e) => { const b = e.target.closest("[role=menuitemradio]"); if (b) choose(b.dataset.id || null); });
  menu.addEventListener("keydown", (e) => {
    const list = items(), at = list.indexOf(document.activeElement);
    const go = { ArrowDown: (at + 1) % list.length, ArrowUp: (at - 1 + list.length) % list.length, Home: 0, End: list.length - 1 }[e.key];
    if (go !== undefined) { e.preventDefault(); list[go].focus(); }
    else if (e.key === "Escape") { e.preventDefault(); close(true); }
    else if (e.key === "Tab") close();
  });
  document.addEventListener("click", (e) => { if (!menu.hidden && !wrap.contains(e.target)) close(); });
  return { label: (lang) => LABEL[lang] || LABEL.en };
}
