// The SQL lab's result grid, without the DOM: sorting a column, text for copying, how a value is shown. Pure functions.

/** A copy of `rows` ordered by column `index` ("asc" or "desc"). Numbers by value, everything else by text (Turkish rules); empty values last either way. */
export function sortRows(rows, index, dir = "asc", type = "string") {
  const sign = dir === "desc" ? -1 : 1;
  const empty = (v) => v === null || v === undefined || v === "";
  const num = type === "number";
  return rows.map((r, i) => [r, i]).sort(([a, i], [b, j]) => {
    const x = a[index], y = b[index];
    if (empty(x) || empty(y)) return empty(x) && empty(y) ? i - j : empty(x) ? 1 : -1;
    const c = num ? Number(x) - Number(y) : String(x).localeCompare(String(y), "tr", { numeric: true, sensitivity: "base" });
    return c * sign || i - j;                                         // equal values keep the order the query gave
  }).map(([r]) => r);
}

/** How a value appears in a cell: empty is blank, a time is shortened of its zero time-of-day, a number is as it came. */
export function formatCell(v, type) {
  if (v === null || v === undefined) return "";
  if (type === "time") return String(v).replace(/T00:00:00(\.0+)?$/, "").replace("T", " ").replace(/\.0+$/, "");
  if (type === "boolean") return v ? "true" : "false";
  return String(v);
}

/** Tab-separated text of a result (header first), ready for a spreadsheet: tabs and line breaks inside a value become spaces. */
export function toTsv(columns, rows) {
  const clean = (s) => String(s).replace(/[\t\r\n]+/g, " ");
  return [columns.map((c) => clean(c.name)).join("\t"), ...rows.map((r) => r.map((v, i) => clean(formatCell(v, columns[i]?.type))).join("\t"))].join("\n");
}

/** The tabs the lab keeps in the browser, made safe: at least one, each with a string `sql` and a numeric `id`. */
export function cleanTabs(raw) {
  const tabs = (Array.isArray(raw) ? raw : []).filter((t) => t && typeof t.sql === "string" && Number.isFinite(t.id)).slice(0, 12).map((t) => ({ id: t.id, sql: t.sql.slice(0, 20000) }));
  return tabs.length ? tabs : [{ id: 1, sql: "" }];
}

/** `history` with `sql` first (a repeat moves up), at most `max` entries. */
export function pushHistory(history, sql, at = Date.now(), max = 30) {
  const text = sql.trim();
  return text ? [{ sql: text, at }, ...history.filter((h) => h.sql !== text)].slice(0, max) : history;
}

/** The query text with `insert` put where the cursor is (replacing a selection), and the cursor position after it. */
export function insertAt(text, start, end, insert) {
  return { text: text.slice(0, start) + insert + text.slice(end), cursor: start + insert.length };
}
