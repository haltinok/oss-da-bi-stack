// The designer's structural edits, without the page: new panels with sensible contents, removing and duplicating a panel, the dashboard's filters and its own fields.
// Pure functions on the dashboard's source spec; each returns a copy (the argument is not touched) and what the person should be told. As with field edits, the builder
// service's validator has the last word: these functions only try to hand it a spec that is already as right as can be known here.
import { membersIn, cubeOf, reachableCubes } from "./designer-model.js";

export const PANEL_TYPES = ["kpi", "timeseries", "bar", "pie", "treemap", "table", "pivot", "text"];

export const clone = (x) => JSON.parse(JSON.stringify(x));
export const humanize = (name) => String(name).split(".").pop().replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const PREFERRED_MEASURES = ["revenue", "orders", "units", "stock"];
const PREFERRED_DIMENSIONS = ["category", "region", "country", "name", "status", "group_name"];

/** How a measure is shown when nothing says: money for amounts, whole numbers for counts, percent for rates. */
export const guessFormat = (member) => {
  const n = String(member).split(".").pop();
  if (/margin|pct|percent|rate|ratio|share/.test(n)) return "pct";
  if (/revenue|profit|cost|amount|price|value|sales|total/.test(n)) return "money";
  if (/orders|units|count|qty|quantity|stock|number/.test(n)) return "int";
  return "number";
};

/** Layouts of a source, as [{ tab (id or null), rows }] that point into it (so a clone's can be edited in place). */
export const layoutsOf = (source) => (source.tabs ? source.tabs.map((t) => ({ tab: t.id, rows: t.layout })) : [{ tab: null, rows: source.layout }]);

/** An id for a new panel: `base`, then `base_2`, `base_3`... that no panel has. */
export function newPanelId(source, base) {
  const taken = new Set(source.panels.map((p) => p.id));
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base}_${n}`)) n++;
  return `${base}_${n}`;
}

/**
 * The measure a new panel starts with: the first the role may read, preferring revenue, orders and the like; for a panel on a time axis, one whose cube joins to the time
 * dimension's cube. null when there is none.
 */
export function pickMeasure(catalog, source, { time = false } = {}) {
  const timeCube = cubeOf(source.time?.dimension || "");
  const all = catalog.flatMap((c) => c.measures.map((m) => m.member));
  const ok = (m) => !time || reachableCubes(catalog, [cubeOf(m)])?.has(timeCube) !== false;
  const usable = all.filter(ok);
  return PREFERRED_MEASURES.map((n) => usable.find((m) => m.endsWith(`.${n}`))).find(Boolean) || usable[0] || null;
}

/** A dimension to group `measure` by that its cube can join to (not a key, not a time dimension), skipping `not`; null when there is none. */
export function pickDimension(catalog, measure, not = []) {
  const reach = reachableCubes(catalog, [cubeOf(measure)]);
  const dims = catalog.flatMap((c) => c.dimensions.map((d) => ({ ...d, cube: c.cube })))
    .filter((d) => (!reach || reach.has(d.cube)) && d.type !== "time" && !/^(key|id)$|_id$|_key$/.test(d.name) && !not.includes(d.member));
  return PREFERRED_DIMENSIONS.map((n) => dims.find((d) => d.name === n)).find(Boolean)?.member || dims[0]?.member || null;
}

/**
 * A new panel of `type` with contents that should validate: { panel } or { problem } (a short key: "measure" when the role may read no measure that fits, "dimension"
 * when nothing can be grouped). `title(type, measure, dimension)` words the title in the page's language.
 */
export function defaultPanel(type, catalog, source, id, title = (ty, m, d) => (d ? `${humanize(m)} by ${humanize(d)}` : ty === "timeseries" ? `${humanize(m)} over time` : humanize(m))) {
  if (type === "text") return { panel: { id, type, markdown: "Write your note here." } };
  const measure = pickMeasure(catalog, source, { time: type === "timeseries" });
  if (!measure) return { problem: "measure" };
  const money = guessFormat(measure);
  const base = { id, type };
  if (type === "kpi") return { panel: { ...base, measures: [{ member: measure, label: humanize(measure), format: money }] } };
  if (type === "timeseries") return { panel: { ...base, title: title(type, measure, null), series: [{ member: measure, label: humanize(measure), format: money }], granularity: "month", style: "line" } };
  const dim = pickDimension(catalog, measure);
  if (!dim) return { problem: "dimension" };
  const name = title(type, measure, dim);
  if (type === "bar") return { panel: { ...base, title: name, measure, label: humanize(measure), by: dim, sort: "desc", limit: 10, format: money } };
  if (type === "pie") return { panel: { ...base, title: name, measure, label: humanize(measure), by: dim, limit: 8, style: "donut", format: money } };
  if (type === "treemap") return { panel: { ...base, title: name, measure, group: [dim], format: money } };
  if (type === "table") return { panel: { ...base, title: name, columns: [dim, measure], limit: 20 } };
  if (type === "pivot") {
    const cols = pickDimension(catalog, measure, [dim]);
    if (!cols) return { problem: "dimension" };
    return { panel: { ...base, title: name, rows: [dim], columns: cols, measures: [{ member: measure, label: humanize(measure), format: money }] } };
  }
  return { problem: "type" };
}

/** Adds a panel of `type` as a new full-width row at the end of the layout (of tab `tab`, else of the last tab). Returns { source, id } or { problem }. */
export function addPanel(source, type, catalog, { tab = null, title } = {}) {
  const next = clone(source);
  const id = newPanelId(next, type);
  const made = defaultPanel(type, catalog, next, id, title);
  if (made.problem) return { problem: made.problem };
  next.panels.push(made.panel);
  const lay = layoutsOf(next);
  (lay.find((l) => l.tab === tab) || lay[lay.length - 1]).rows.push([{ [id]: 12 }]);
  return { source: next, id };
}

/** Takes a panel out of every layout; a row it leaves empty goes, and the others in its row widen so the row still adds up to 12. */
export function unplace(next, id) {
  for (const { rows } of layoutsOf(next)) {
    for (let r = rows.length - 1; r >= 0; r--) {
      const cells = rows[r].filter((c) => !(id in c));
      if (cells.length === rows[r].length) continue;
      if (!cells.length) { rows.splice(r, 1); continue; }
      const total = cells.reduce((s, c) => s + Object.values(c)[0], 0);
      const last = cells[cells.length - 1], key = Object.keys(last)[0];
      last[key] += 12 - total;
      rows[r] = cells;
    }
  }
}

/** Removes a panel and its place in the layout. The dashboard must keep one panel (the validator says so; here the caller is told with `problem`). */
export function removePanel(source, id) {
  if (source.panels.length < 2) return { problem: "last" };
  const next = clone(source);
  next.panels = next.panels.filter((p) => p.id !== id);
  unplace(next, id);
  return { source: next };
}

/** A copy of a panel with a new id, placed as a new full-width row right under the original's row. */
export function duplicatePanel(source, id, { suffix = " (copy)" } = {}) {
  const next = clone(source);
  const original = next.panels.find((p) => p.id === id);
  if (!original) return { problem: "missing" };
  const copy = { ...clone(original), id: newPanelId(next, id.replace(/_\d+$/, "")) };
  if (copy.title) copy.title += suffix;
  next.panels.splice(next.panels.indexOf(original) + 1, 0, copy);
  for (const { rows } of layoutsOf(next)) {
    const at = rows.findIndex((row) => row.some((c) => id in c));
    if (at >= 0) { rows.splice(at + 1, 0, [{ [copy.id]: 12 }]); break; }
  }
  return { source: next, id: copy.id };
}

// ------------------------------------------------------------------------------------------------------------------ filters
/** Does a panel's data join to this dimension? True when it has no measure (nothing to join) or its measures' cubes all reach the dimension's cube. */
function reaches(catalog, panel, dimension) {
  const measures = [...membersIn(panel)].filter((m) => catalog.some((c) => c.measures.some((x) => x.member === m)));
  if (!measures.length) return true;
  const reach = reachableCubes(catalog, [...new Set(measures.map(cubeOf))]);
  return !reach || reach.has(cubeOf(dimension));
}

/** Panels that cannot join to the filter's dimension list it in `ignore_filters`, as the validator requires (and the page then shows them unfiltered). */
function ignoreWhereUnreachable(next, catalog, filter) {
  const ignored = [];
  for (const p of next.panels) {
    if (p.type === "text" || reaches(catalog, p, filter.dimension)) { p.ignore_filters = (p.ignore_filters || []).filter((x) => x !== filter.id); if (!p.ignore_filters.length) delete p.ignore_filters; continue; }
    if (!(p.ignore_filters || []).includes(filter.id)) { p.ignore_filters = [...(p.ignore_filters || []), filter.id]; ignored.push(p.id); }
  }
  return ignored;
}

const newFilterId = (source, dimension) => {
  const base = dimension.split(".").pop().replace(/[^a-z0-9_]/g, "_");
  const taken = new Set((source.filters || []).map((f) => f.id));
  let id = base, n = 2;
  while (taken.has(id)) id = `${base}_${n++}`;
  return id;
};

/** Adds a filter on a dimension; panels that cannot join to it ignore it. Returns { source, id, notes } ("ignored" when some panels were set to ignore it). */
export function addFilter(source, catalog, dimension) {
  const next = clone(source);
  const id = newFilterId(next, dimension);
  const filter = { id, dimension, label: humanize(dimension) };
  next.filters = [...(next.filters || []), filter];
  const ignored = ignoreWhereUnreachable(next, catalog, filter);
  return { source: next, id, notes: ignored.length ? ["ignored"] : [] };
}

export const FILTER_TYPES = ["select", "multiselect", "text", "number", "date"];
const NEEDS = { text: "string", number: "number", date: "time" };              // the dimension type a filter type needs; select and multiselect take any

/** The filter types a dimension of this type (string, number, time) can have. */
export const typesFor = (dimType) => FILTER_TYPES.filter((t) => !NEEDS[t] || NEEDS[t] === dimType);
/** The type Cube gives a dimension, from the catalog (undefined when it is not there). */
export const dimensionTypeOf = (catalog, member) => catalog.flatMap((c) => c.dimensions).find((d) => d.member === member)?.type;

/**
 * Changes a filter's type. The default is dropped (it was a value of the old type); a `parent` stays only on a select or multiselect; and what cannot work with the new type is
 * dropped with a note: click rules that set this filter (only a select can be set by a click) and the `parent` of another filter that points at this one.
 * Returns { source, notes } or { problem: "type" } when the type does not fit the filter's dimension.
 */
export function setFilterType(source, catalog, id, type) {
  const next = clone(source);
  const filter = (next.filters || []).find((f) => f.id === id);
  if (!filter) return { problem: "missing" };
  if (!typesFor(dimensionTypeOf(catalog, filter.dimension)).includes(type)) return { problem: "type" };
  const notes = [];
  if (type === "select") delete filter.type; else filter.type = type;
  if ("default" in filter) { delete filter.default; notes.push("defaultDropped"); }
  if (type !== "select" && type !== "multiselect" && filter.parent) { delete filter.parent; notes.push("parentDropped"); }
  if (type !== "select") {
    for (const p of next.panels) if (p.on_click && [].concat(p.on_click.set_filter || []).includes(id)) { delete p.on_click; notes.push("click"); }
    for (const g of next.filters) if (g.parent === filter.dimension) { delete g.parent; notes.push("parentDropped"); }
  }
  return { source: next, notes: [...new Set(notes)] };
}

/** Changes a filter's label, dimension, default or parent (an empty one removes it). A new dimension re-decides which panels ignore the filter. */
export function setFilter(source, catalog, id, field, value) {
  const next = clone(source);
  const filter = next.filters.find((f) => f.id === id);
  if (!filter) throw new Error(`no filter '${id}'`);
  if ((field === "parent" || field === "label" || field === "default") && !value) delete filter[field]; else filter[field] = value;
  let notes = [];
  if (field === "dimension") {
    notes = ignoreWhereUnreachable(next, catalog, filter).length ? ["ignored"] : [];
    if (!typesFor(dimensionTypeOf(catalog, value)).includes(filter.type || "select")) { delete filter.type; delete filter.default; notes.push("typeReset"); }        // the type no longer fits the new field
    if (filter.parent === value) delete filter.parent;
    for (const p of next.panels) if (p.on_click) { const ids = [].concat(p.on_click.set_filter || []); if (ids.includes(id)) { delete p.on_click; notes.push("click"); } }       // a click rule names this filter for the old dimension
  }
  return { source: next, notes };
}

/** Removes a filter, and every mention of it: panels' `ignore_filters` and the click rules that name it (those are dropped, with a note). */
export function removeFilter(source, id) {
  const next = clone(source);
  next.filters = (next.filters || []).filter((f) => f.id !== id);
  if (!next.filters.length) delete next.filters;
  const notes = [];
  for (const p of next.panels) {
    if (p.ignore_filters) { p.ignore_filters = p.ignore_filters.filter((x) => x !== id); if (!p.ignore_filters.length) delete p.ignore_filters; }
    if (p.on_click && [].concat(p.on_click.set_filter || []).includes(id)) { delete p.on_click; notes.push("click"); }
  }
  return { source: next, notes };
}

// ------------------------------------------------------------------------------------------------------------------ the page's own fields
/** Sets a field of the dashboard: "title", "description", "locale", "currency", "time.dimension", "time.fiscal_year_start". An empty description is removed. */
export function setPageField(source, path, value) {
  const next = clone(source);
  const steps = path.split(".");
  const last = steps.pop();
  let cur = next;
  for (const k of steps) cur = cur[k] ??= {};
  if ((value === "" || value == null) && ["description", "fiscal_year_start", "locale", "currency", "name", "logo"].includes(last)) {
    delete cur[last];
    if (next.theme && !Object.keys(next.theme).length) delete next.theme;                  // `theme: {}` says nothing
  } else cur[last] = value;
  return { source: next, notes: [] };
}

/** The time dimensions of the catalog (what `time.dimension` may be). */
export const timeDimensions = (catalog) => catalog.flatMap((c) => c.dimensions.filter((d) => d.type === "time").map((d) => ({ value: d.member, label: d.member, cube: c.cube, description: d.description })));
