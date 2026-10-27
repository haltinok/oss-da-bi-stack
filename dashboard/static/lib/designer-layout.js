// The designer's layout edits, without the page: moving a panel (by command, or dropped on another), widening and narrowing, and the order and names of tabs.
// Pure functions on the dashboard's source spec; each returns a copy, or { problem } (a short key) when the move cannot be made. A layout is rows of cells { panelId: span },
// every row adding up to 12 columns; every function here keeps that true, so the validator only has to agree.
import { clone, layoutsOf } from "./designer-structure.js";

export const MAX_PER_ROW = 12;
const span = (cell) => Object.values(cell)[0];
const idOf = (cell) => Object.keys(cell)[0];
const widen = (row, by) => { const last = row[row.length - 1]; last[idOf(last)] += by; };

/** Where a panel is: { tab (id or null), rows (the layout, live in `source`), r (row index), c (cell index) }, or null. */
export function locate(source, id) {
  for (const { tab, rows } of layoutsOf(source)) {
    for (let r = 0; r < rows.length; r++) {
      const c = rows[r].findIndex((cell) => id in cell);
      if (c >= 0) return { tab, rows, r, c };
    }
  }
  return null;
}

/** The row a panel is in, in order: [{ id, span }]. */
export const rowOf = (source, id) => { const at = locate(source, id); return at ? at.rows[at.r].map((cell) => ({ id: idOf(cell), span: span(cell) })) : []; };

/**
 * Takes a panel out of its row (in the copy `next`); the others in the row take its width, and an empty row goes. Returns where it was:
 * { tab, rows, r, removedRow }.
 */
function extract(next, id) {
  const at = locate(next, id);
  const { rows, r, c } = at;
  const [cell] = rows[r].splice(c, 1);
  const removedRow = !rows[r].length;
  if (removedRow) rows.splice(r, 1); else widen(rows[r], span(cell));
  return { tab: at.tab, rows, r, removedRow };
}

/** Puts `id` into a row right after cell `after`, halving the cell at `prefer` (else the widest) for room. False when the row is full or every cell is 1 wide. */
function insertInto(row, id, after, prefer = -1) {
  if (row.length >= MAX_PER_ROW) return false;
  let at = prefer >= 0 && span(row[prefer]) >= 2 ? prefer : -1;
  if (at < 0) row.forEach((cell, i) => { if (span(cell) >= 2 && (at < 0 || span(cell) > span(row[at]))) at = i; });
  if (at < 0) return false;
  const w = span(row[at]);
  row[at][idOf(row[at])] = Math.ceil(w / 2);
  row.splice(after + 1, 0, { [id]: Math.floor(w / 2) });
  return true;
}

/**
 * A move by command: up | down (a row up or down: alone in its row it swaps with the next row; in a shared row it leaves into a row of its own above or below), left | right (swap
 * places with the neighbour, each keeping its width), join-up | join-down (into the row above or below, sharing it), own-row (out of a shared row), narrower | wider (a column
 * to or from the neighbour: the right one, else the left). Returns { source } or { problem: missing | edge | alone | full }.
 */
export function moveCommand(source, id, cmd) {
  const next = clone(source);
  const at = locate(next, id);
  if (!at) return { problem: "missing" };
  const { rows, r, c } = at, row = rows[r];
  const alone = row.length === 1;
  if (cmd === "up" || cmd === "down") {
    const d = cmd === "up" ? -1 : 1;
    if (alone) {
      if (!rows[r + d]) return { problem: "edge" };
      [rows[r], rows[r + d]] = [rows[r + d], rows[r]];
    } else {
      extract(next, id);
      rows.splice(d < 0 ? r : r + 1, 0, [{ [id]: 12 }]);
    }
    return { source: next };
  }
  if (cmd === "left" || cmd === "right") {
    const d = cmd === "left" ? -1 : 1;
    if (!row[c + d]) return { problem: "edge" };
    [row[c], row[c + d]] = [row[c + d], row[c]];
    return { source: next };
  }
  if (cmd === "own-row") {
    if (alone) return { problem: "alone" };
    extract(next, id);
    rows.splice(r + 1, 0, [{ [id]: 12 }]);
    return { source: next };
  }
  if (cmd === "join-up" || cmd === "join-down") {
    const d = cmd === "join-up" ? -1 : 1;
    if (!rows[r + d]) return { problem: "edge" };
    const target = rows[r + d];                                                       // the row object itself: it keeps its identity when the rows shift
    extract(next, id);
    return insertInto(target, id, target.length - 1) ? { source: next } : { problem: "full" };
  }
  if (cmd === "narrower" || cmd === "wider") {
    if (alone) return { problem: "alone" };
    const n = c < row.length - 1 ? c + 1 : c - 1;
    const d = cmd === "wider" ? 1 : -1;
    const [own, other] = [span(row[c]) + d, span(row[n]) - d];
    if (own < 1 || other < 1) return { problem: "edge" };
    row[c][id] = own;
    row[n][idOf(row[n])] = other;
    return { source: next };
  }
  return { problem: "missing" };
}

/**
 * A panel dropped: on the top / bottom edge of another panel (a row of its own above or below that panel's row), on its left / right edge (beside it, sharing the row, taking
 * half of its width), or on the end of a tab (`{ tab, end: true }`: a new row at the end of that tab). Returns { source } or { problem: same | missing | full | tab }.
 */
export function dropPanel(source, id, target) {
  if (target.ref === id) return { problem: "same" };
  const next = clone(source);
  if (!locate(next, id) || (target.ref && !locate(next, target.ref))) return { problem: "missing" };
  if (target.end) {
    const lay = layoutsOf(next).find((l) => l.tab === (target.tab ?? null));
    if (!lay) return { problem: "tab" };
    extract(next, id);
    lay.rows.push([{ [id]: 12 }]);
    return { source: next };
  }
  extract(next, id);
  const { rows, r, c } = locate(next, target.ref);
  if (target.side === "top") rows.splice(r, 0, [{ [id]: 12 }]);
  else if (target.side === "bottom") rows.splice(r + 1, 0, [{ [id]: 12 }]);
  else if (!insertInto(rows[r], id, target.side === "left" ? c - 1 : c, c)) return { problem: "full" };
  return { source: next };
}

/** Sets the widths of the row a panel is in, in order; they must be as many as the cells, each at least 1, and add up to 12. Returns { source } or { problem: count | sum }. */
export function setWidths(source, id, widths) {
  const next = clone(source);
  const at = locate(next, id);
  if (!at) return { problem: "missing" };
  const row = at.rows[at.r];
  if (widths.length !== row.length) return { problem: "count" };
  if (widths.some((w) => !Number.isInteger(w) || w < 1) || widths.reduce((a, b) => a + b, 0) !== 12) return { problem: "sum" };
  row.forEach((cell, i) => { cell[idOf(cell)] = widths[i]; });
  return { source: next };
}

// ------------------------------------------------------------------------------------------------------------------ tabs
/** The tabs as [{ id, title, panels }], or [] for a dashboard without tabs. */
export const tabsOf = (source) => (source.tabs || []).map((t) => ({ id: t.id, title: t.title, panels: t.layout.flat().map(idOf) }));

/** Moves a tab one place earlier (-1) or later (1). */
export function moveTab(source, tabId, dir) {
  const next = clone(source);
  const i = (next.tabs || []).findIndex((t) => t.id === tabId);
  if (i < 0) return { problem: "missing" };
  if (!next.tabs[i + dir]) return { problem: "edge" };
  [next.tabs[i], next.tabs[i + dir]] = [next.tabs[i + dir], next.tabs[i]];
  return { source: next };
}

/** Renames a tab (the title is what the reader sees; the id stays). */
export function renameTab(source, tabId, title) {
  const next = clone(source);
  const tab = (next.tabs || []).find((t) => t.id === tabId);
  if (!tab) return { problem: "missing" };
  tab.title = title;
  return { source: next };
}

/** Moves a panel to the end of another tab. */
export const moveToTab = (source, id, tabId) => dropPanel(source, id, { tab: tabId, end: true });
