// Small DOM helpers shared by the dashboard pages.
export const $ = (sel) => document.querySelector(sel);
export const el = (tag, attrs = {}, html = "") => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) n.setAttribute(k, v);   // an undefined attribute is left off, not set to "undefined"
  if (html) n.innerHTML = html;
  return n;
};
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
export function svgEl(tag, attrs = {}) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) n.setAttribute(k, v);
  return n;
}
