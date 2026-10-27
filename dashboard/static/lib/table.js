// Tables and file downloads shared by the dashboard pages. A column is { label, type, get(row), fmt(value) }; `type` is an xlsx.js
// column type (text, int, money, pct, date), and the numeric ones are right-aligned.
import { el, esc } from "./dom.js";
import { buildXlsx } from "./xlsx.js";

/**
 * `totals` (optional) is { position: "header" | "footer", cells: [value per column] }: a bold row pinned inside the scroll area. A column whose
 * cell is `undefined` (a dimension) is left empty; a measure with no value shows "–".
 */
export const tableHtml = ({ columns, rows, totals = null, sort = null }) => {
  const num = (c) => (c.type !== "text" && c.type !== "date" ? "n" : "");
  // A column with a `sortKey` has a clickable title; `sort` ({ member, dir }) marks the one the rows are ordered by.
  const th = (c) => {
    if (!c.sortKey) return `<th class="${num(c)}">${esc(c.label)}</th>`;
    const dir = sort?.member === c.sortKey ? sort.dir : "";
    return `<th class="${num(c)} sortable" data-sort="${esc(c.sortKey)}" tabindex="0" aria-sort="${dir ? (dir === "asc" ? "ascending" : "descending") : "none"}">${esc(c.label)}<i class="arr" aria-hidden="true">${dir === "asc" ? "↑" : dir === "desc" ? "↓" : ""}</i></th>`;
  };
  const head = columns.map(th).join("");
  const body = rows.map((r) => `<tr>${columns.map((c) => `<td class="${num(c)}">${esc(c.fmt(c.get(r)))}</td>`).join("")}</tr>`).join("");
  const totalRow = totals && `<tr class="tot">${columns.map((c, i) => `<td class="${num(c)}">${totals.cells[i] === undefined ? "" : totals.cells[i] === null ? "–" : esc(c.fmt(totals.cells[i]))}</td>`).join("")}</tr>`;
  const header = totals?.position === "header" ? totalRow : "";
  const footer = totals?.position === "footer" ? `<tfoot>${totalRow}</tfoot>` : "";
  return `<div class="tbl-wrap"><table><thead><tr>${head}</tr>${header}</thead><tbody>${body}</tbody>${footer}</table></div>`;
};

/** A header total row sticks under the title row, whose height depends on the font: measure it and hand it to the CSS. */
export function pinTotals(host) {
  const wrap = host.querySelector(".tbl-wrap");
  const title = wrap?.querySelector("thead tr");
  if (title) wrap.style.setProperty("--head-h", `${title.getBoundingClientRect().height}px`);
}

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
