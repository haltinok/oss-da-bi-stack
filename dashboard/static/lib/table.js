// Tables and file downloads shared by the dashboard pages. A column is { label, type, get(row), fmt(value) }; `type` is an xlsx.js
// column type (text, int, money, pct, date), and the numeric ones are right-aligned.
import { el, esc } from "./dom.js";
import { buildXlsx } from "./xlsx.js";

export const tableHtml = ({ columns, rows }) => {
  const num = (c) => (c.type !== "text" && c.type !== "date" ? "n" : "");
  const head = columns.map((c) => `<th class="${num(c)}">${esc(c.label)}</th>`).join("");
  const body = rows.map((r) => `<tr>${columns.map((c) => `<td class="${num(c)}">${esc(c.fmt(c.get(r)))}</td>`).join("")}</tr>`).join("");
  return `<div class="tbl-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
};

/** Sheets [{ name, title, subtitle, columns: [{label, type}], rows }] -> an .xlsx download named `<prefix>-<slug>-<yyyymmdd-hhmm>.xlsx`. */
export function downloadXlsx(sheets, { prefix, slug, symbol }) {
  const blob = buildXlsx(sheets, { symbol });
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:]/g, "").replace("T", "-");
  const a = el("a", { href: URL.createObjectURL(blob), download: `${prefix}-${slug}-${stamp}.xlsx` });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
}

export const slugify = (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
