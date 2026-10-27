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

/**
 * A pivot as HTML. `model` is plan.js `pivotModel`; `measures` [{ member, label, fmt }] in its order; `texts` { corner, total, notes: [string] }.
 * Elements a click can act on carry data-r (a row's index in model.rows), data-g (a group's index) and data-c (a column's index), whichever
 * they stand for: a cell has its row (or group) and its column, a total only the one it totals, the grand total none.
 * A missing cell is empty (Cube had no row: not a zero); a missing total shows a dash. Everything is escaped.
 * `heat` ({ member, level(v) -> 0..1 | null }) shades that measure's cells (not the totals); the number stays in every cell. `texts.colLabel(key)`
 * names a column (a time bucket); `texts.legend` ({ label, min, max }) explains the shading.
 */
export function pivotHtml({ model, measures, texts, heat = null }) {
  const M = measures.length, twoLevel = !!model.groups, labelCols = twoLevel ? 2 : 1;
  const rowTot = model.totals === "both" || model.totals === "rows", colTot = model.totals === "both" || model.totals === "columns";
  const at = (o) => Object.entries(o).filter(([, v]) => v !== undefined).map(([k, v]) => ` data-${k}="${v}"`).join("");
  const nums = (map, attrs, missing, cls = "", shade = false) => measures.map((m) => {
    const v = map?.get(m.member), level = shade && heat && m.member === heat.member && v != null ? heat.level(v) : null;
    const style = level == null ? "" : ` style="--heat:${level.toFixed(3)}"`;
    return `<td class="n${cls}${level == null ? "" : " heat"}"${at(attrs)}${style}>${v == null ? missing : esc(m.fmt(v))}</td>`;
  }).join("");
  const head1 = `<th class="corner" rowspan="${M > 1 ? 2 : 1}" colspan="${labelCols}">${esc(texts.corner)}</th>`
    + model.cols.map((c, j) => `<th class="n ck" colspan="${M}"${at({ c: j })}>${esc(texts.colLabel ? texts.colLabel(c) : c)}</th>`).join("")
    + (rowTot ? `<th class="n tc" colspan="${M}">${esc(texts.total)}</th>` : "");
  const head2 = M > 1 ? `<tr>${Array.from({ length: model.cols.length + (rowTot ? 1 : 0) }, () => measures.map((m) => `<th class="n mh">${esc(m.label)}</th>`).join("")).join("")}</tr>` : "";
  let ri = 0;
  const leaf = (r) => {
    const i = ri++;
    return `<tr>${twoLevel ? '<th class="rl"></th>' : ""}<th class="rl" scope="row"${at({ r: i })}>${esc(r.keys[r.keys.length - 1])}</th>`
      + r.cells.map((m, j) => nums(m, { r: i, c: j }, "", "", true)).join("") + (rowTot ? nums(r.total, { r: i }, "–", " tc") : "") + "</tr>";
  };
  const body = twoLevel
    ? model.groups.map((g, gi) => `<tr class="grp"><th class="rl" scope="row" colspan="2"${at({ g: gi })}>${esc(g.key)}</th>`
      + g.cells.map((m, j) => nums(m, { g: gi, c: j }, "")).join("") + (rowTot ? nums(g.total, { g: gi }, "–", " tc") : "") + "</tr>" + g.rows.map(leaf).join("")).join("")
    : model.rows.map(leaf).join("");
  const foot = colTot
    ? `<tfoot><tr class="tot"><th class="rl" colspan="${labelCols}">${esc(texts.total)}</th>${model.colTotals.map((m, j) => nums(m, { c: j }, "–")).join("")}${rowTot ? nums(model.grand.size ? model.grand : undefined, {}, "–", " tc") : ""}</tr></tfoot>` : "";
  const lg = texts.legend;
  const legend = lg ? `<div class="pivot-note pivot-legend">${esc(lg.label)} <span>${esc(lg.min)}</span><i class="heat-bar" aria-hidden="true"></i><span>${esc(lg.max)}</span></div>` : "";
  const notes = legend + (texts.notes || []).map((n) => `<div class="pivot-note">${esc(n)}</div>`).join("");
  return `<div class="tbl-wrap pivot-wrap"><table class="pivot"><thead><tr>${head1}</tr>${head2}</thead><tbody>${body}</tbody>${foot}</table></div>${notes}`;
}

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
