// The renderer's data logic, with no DOM: which Cube queries a panel needs, and how their rows become numbers. A panel names Cube
// members only; this module never writes SQL. Cube cannot join two fact cubes in one query, so a panel that lists measures of several
// cubes gets one query per cube and the rows are merged here, on the dimensions the panel groups by.

import { defaultEnv, toCube } from "../lib/filters.js";
import { AGGREGATE_LIMIT } from "../lib/aggregate.js";

export const cubeOf = (member) => member.split(".")[0];
export const num = (v) => (v == null || v === "" ? null : Number(v));

/** "internet_sales.order_number" -> "Order number" (the label of a column that has none). */
export const humanize = (member) => {
  const name = member.split(".")[1].replace(/_/g, " ");
  return name.charAt(0).toUpperCase() + name.slice(1);
};

/** The filter ids a click on this panel sets (its `on_click.set_filter`, one id or a list). */
export const ownFilterIds = (def) => {
  const f = def.on_click?.set_filter;
  return f == null ? [] : Array.isArray(f) ? f : [f];
};

/**
 * The Cube filters for the page's filter values. A panel leaves out the filters in its ignore_filters and the ones its own clicks set:
 * a cross-filtering panel keeps showing every choice (and marks the selected one) instead of narrowing itself to it.
 */
export function activeFilters(spec, values, panel = {}, env = defaultEnv(spec)) {
  const ignored = new Set([...(panel.ignore_filters || []), ...ownFilterIds(panel)]);
  return (spec.filters || [])
    .filter((f) => filterApplies(spec, f, panel) && !ignored.has(f.id))
    .flatMap((f) => { const v = filterValue(f, values); return v === undefined || v === "" ? [] : toCube(f, v, env); });          // a filter of a kind other than `select` can mean several Cube filters, or none
}

/** The id of the tab that places a panel (null on a dashboard without tabs). `spec` is the compiled one: tab layouts are rows of { panel, span }. */
export const tabOf = (spec, panelId) => spec.tabs?.find((t) => t.layout.flat().some((c) => c.panel === panelId))?.id ?? null;

/** Does a filter narrow this panel? A dashboard filter every panel; a page filter the panels of its tab; a pane filter its own panel (`panel` may be `{}`: only dashboard filters then). */
export function filterApplies(spec, f, panel = {}) {
  const scope = f.scope || "dashboard";
  if (scope === "panel") return f.panel === panel.id;
  if (scope === "page") return panel.id !== undefined && f.tab === tabOf(spec, panel.id);
  return true;
}

/** What a filter holds: a hidden filter always holds its default; a visible one what the reader chose. */
export const filterValue = (f, values) => (f.visible === false ? f.default || "" : values[f.id]);

/** A KPI measure as a term: what to fetch (members) and how to turn the fetched numbers into the tile's value. */
export function term(def) {
  if (def.member) return { kind: "member", members: [def.member], parts: [def.member], label: def.label, format: def.format };
  if (def.sum) return { kind: "sum", members: [...def.sum], parts: def.sum, label: def.label, format: def.format };
  return {
    kind: "ratio", members: [...new Set([...def.ratio.num, ...def.ratio.den])], num: def.ratio.num, den: def.ratio.den,
    label: def.label, format: def.format,
  };
}

/** The tile's value from valueOf(member) -> number | null. A sum of nothing is null (not 0); a ratio with a zero denominator is null. */
export function evaluate(t, valueOf) {
  const total = (ms) => {
    const vs = ms.map(valueOf).filter((v) => v != null && isFinite(v));
    return vs.length ? vs.reduce((a, b) => a + b, 0) : null;
  };
  if (t.kind === "member") return valueOf(t.members[0]) ?? null;
  if (t.kind === "sum") return total(t.members);
  const n = total(t.num), d = total(t.den);
  return n == null || !d ? null : n / d;
}

/** Group members by cube: Map(cube -> [members]), in first-seen order. */
export function byCube(members) {
  const out = new Map();
  for (const m of members) {
    const c = cubeOf(m);
    if (!out.has(c)) out.set(c, []);
    if (!out.get(c).includes(m)) out.get(c).push(m);
  }
  return out;
}

/** One Cube query per cube that owns some of `measures`; `base` (dimensions, timeDimensions, filters, ...) is added to each. */
export function queriesPerCube(measures, base = {}) {
  return [...byCube(measures)].map(([cube, ms]) => ({ cube, query: { ...base, measures: ms } }));
}

/** Run those queries in parallel -> [{ cube, rows }]. */
export function runAll(run, queries, signal) {
  return Promise.all(queries.map(async ({ cube, query }) => ({ cube, rows: await run(query, signal) })));
}

/** Measures of a no-dimension query: member -> number (a query with no rows has no value). */
export function totals(results) {
  const out = new Map();
  for (const { rows } of results) for (const [k, v] of Object.entries(rows[0] || {})) out.set(k, num(v));
  return out;
}

/**
 * Rows of per-cube queries grouped by one time dimension -> [{ bucket, values: Map(member -> number) }] in time order. A bucket that one
 * cube has and another lacks simply has no value for the other's members.
 */
export function byBucket(results, timeKey) {
  const buckets = new Map();
  for (const { rows } of results) {
    for (const r of rows) {
      const b = r[timeKey];
      if (b == null) continue;
      if (!buckets.has(b)) buckets.set(b, new Map());
      for (const [k, v] of Object.entries(r)) if (k !== timeKey) buckets.get(b).set(k, num(v));
    }
  }
  return [...buckets].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([bucket, values]) => ({ bucket, values }));
}

/**
 * Rows of per-cube queries that all group by the same `dims` -> one row per distinct combination, with every cube's measures on it.
 * Returns [{ key, dims: {dim: value}, values: Map(member -> number) }] (in first-seen order).
 */
export function byDims(results, dims) {
  const out = new Map();
  for (const { rows } of results) {
    for (const r of rows) {
      const key = dims.map((d) => r[d]).join("\u0000");
      if (!out.has(key)) out.set(key, { key, dims: Object.fromEntries(dims.map((d) => [d, r[d]])), values: new Map() });
      const cur = out.get(key);
      for (const [k, v] of Object.entries(r)) if (!dims.includes(k)) cur.values.set(k, num(v));
    }
  }
  return [...out.values()];
}

/** The Cube row key of a time dimension at a granularity. */
export const timeKey = (dimension, granularity) => `${dimension}.${granularity}`;

/** "2020-07-01T00:00:00.000" -> "2020-07-01" */
export const day = (bucket) => String(bucket).slice(0, 10);

/**
 * Filter options for the page's filter bar: rows [{ value, parent }] from per-cube queries of [parent?, dimension], de-duplicated and
 * sorted (numbers numerically). `parentValue` (the chosen value of the parent filter, if the dashboard has one) narrows them.
 */
export function optionsOf(results, filter, parentValue = "") {
  const seen = new Map();
  for (const { rows } of results) {
    for (const r of rows) {
      const value = r[filter.dimension];
      const parent = filter.parent ? r[filter.parent] : undefined;
      if (value == null || value === "") continue;
      if (parentValue !== "" && String(parent) !== String(parentValue)) continue;
      seen.set(`${parent}\u0000${value}`, { value: String(value), parent: parent == null ? undefined : String(parent) });
    }
  }
  const all = [...seen.values()];
  const numeric = all.every((o) => o.value !== "" && !isNaN(Number(o.value)));
  const cmp = (a, b) => (numeric ? Number(a) - Number(b) : String(a).localeCompare(String(b)));
  return all.sort((a, b) => (a.parent !== undefined && b.parent !== undefined && a.parent !== b.parent ? cmp(a.parent, b.parent) : cmp(a.value, b.value)));
}

/** The measures a filter's option query can use: one measure per cube of the panels that apply that filter. */
export function optionMeasures(spec, filter, nested = false) {
  const per = new Map();
  for (const p of spec.panels) {
    if ((p.ignore_filters || []).includes(filter.id) || !filterApplies(spec, filter, p)) continue;
    let members;
    if (p.type === "slicer") {                                // no data of its own: a pane filter on a slicer narrows that slicer's options, so it uses its slicer's filter's measures
      const inner = (spec.filters || []).find((f) => f.id === p.filter);
      members = nested || !inner || inner.id === filter.id ? [] : optionMeasures(spec, inner, true);
    } else members = panelMeasures(p, spec.members);
    for (const m of members) if (!per.has(cubeOf(m))) per.set(cubeOf(m), m);
  }
  return [...per.values()];
}

/** Every measure a panel reads (`members` is the compiled spec's member map, needed to tell a table's measures from its dimensions). */
export function panelMeasures(p, members = {}) {
  switch (p.type) {
    case "kpi": return p.measures.flatMap((m) => term(m).members);
    case "timeseries": return p.series.flatMap((s) => term(s).members);
    case "bar": return p.stack ? p.stack.map((s) => s.member) : [p.measure];
    case "pie": return p.sum || [p.measure];
    case "treemap": return [p.measure];
    case "table": return tableParts(p, members).measures;
    case "pivot": return p.measures.map((m) => m.member);
    case "slicer": return p.optionMeasures || [];                       // set by slicerQueries (the measures of the panels its filter applies to)
    default: return [];
  }
}

/** The members a table shows, split by kind with the compiled `members` map: { measures, dimensions }. */
export function tableParts(p, members) {
  const isMeasure = (c) => members[c.member]?.kind === "measure";
  return {
    measures: p.columns.filter(isMeasure).map((c) => c.member),
    dimensions: p.columns.filter((c) => !isMeasure(c) && !c.aggregate).map((c) => c.member),          // the groups
    values: p.columns.filter((c) => !isMeasure(c) && c.aggregate).map((c) => ({ member: c.member, aggregate: c.aggregate })),          // summarised over each group's rows
  };
}

/** The CSS colour for a series: a theme name (internet, reseller) is a CSS variable, a hex colour is used as is, none cycles a palette. */
const CYCLE = ["var(--internet)", "var(--reseller)", "#1baf7a", "#eda100", "#6250d6", "#e87ba4"];
export const colorOf = (color, i) => (!color ? CYCLE[i % CYCLE.length] : /^[a-z][a-z-]*$/.test(color) ? `var(--${color})` : color);

/** A subset of Markdown for text panels: paragraphs, **bold**, `code`, [links](https://...), and "- " lists. Everything is escaped first. */
export function markdown(src, esc) {
  const inline = (t) => esc(t)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" rel="noopener noreferrer" target="_blank">$1</a>');
  const out = [];
  for (const block of String(src).trim().split(/\n{2,}/)) {
    const lines = block.split("\n");
    if (lines.every((l) => /^\s*[-*] /.test(l))) out.push(`<ul>${lines.map((l) => `<li>${inline(l.replace(/^\s*[-*] /, ""))}</li>`).join("")}</ul>`);
    else out.push(`<p>${lines.map(inline).join("<br>")}</p>`);
  }
  return out.join("");
}

/** The year a time bucket belongs to: kind is "fiscal_year" (the year starts in `startMonth`, named after the year it ends in) or "calendar_year". */
export function yearOf(bucket, startMonth, kind) {
  const [y, m] = String(bucket).split("-").map(Number);
  return kind === "fiscal_year" && startMonth > 1 && m >= startMonth ? y + 1 : y;
}

/**
 * A click that sets filters `ids` to `values`, as the filter patch to apply. Clicking what is already selected undoes it: the filters go back
 * to what they were before the first click (`saved`, remembered per set of ids), so picking a subcategory and clicking it again restores
 * the category that was chosen before. Mutates `saved`.
 */
export function pick(current, ids, values, saved) {
  const key = ids.join("|");
  const same = ids.every((id, i) => String(current[id] ?? "") === String(values[i]));
  if (same) {
    const back = saved[key] || {};
    delete saved[key];
    return Object.fromEntries(ids.map((id) => [id, back[id] ?? ""]));
  }
  if (!saved[key]) saved[key] = Object.fromEntries(ids.map((id) => [id, current[id] ?? ""]));
  return Object.fromEntries(ids.map((id, i) => [id, String(values[i])]));
}

/** Is exactly this selection active? (every named filter holds its value; with `only`, the filters after the first are empty.) */
export const isSelected = (current, ids, values, only = false) =>
  ids.every((id, i) => (only && i >= values.length ? !current[id] : String(current[id] ?? "") === String(values[i])));

// ------------------------------------------------------------------ the period (a drill-down's date range, applied to the other panels)
export const PERIOD = "_period";                 // the key in the page's filter values; not a filter id (those start with a letter)
const iso = (d) => d.toISOString().slice(0, 10);
const utc = (y, m, d) => new Date(Date.UTC(y, m, d));

export function parsePeriod(v) {
  const m = /^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$/.exec(v || "");
  return m ? [m[1], m[2]] : null;
}
export const formatPeriod = (from, to) => `${from}..${to}`;

/** The first and last day (ISO dates) of the period a time bucket stands for: "2021-03-01T00:00:00.000" at month -> ["2021-03-01", "2021-03-31"]. */
export function rangeOf(bucket, granularity) {
  const [y, m, d] = day(bucket).split("-").map(Number);
  switch (granularity) {
    case "year": return [iso(utc(y, 0, 1)), iso(utc(y, 11, 31))];
    case "quarter": { const q = Math.floor((m - 1) / 3) * 3; return [iso(utc(y, q, 1)), iso(utc(y, q + 3, 0))]; }
    case "month": return [iso(utc(y, m - 1, 1)), iso(utc(y, m, 0))];
    case "week": return [iso(utc(y, m - 1, d)), iso(utc(y, m - 1, d + 6))];
    default: return [iso(utc(y, m - 1, d)), iso(utc(y, m - 1, d))];      // day, hour: the date
  }
}

/** Can a query of cube `src` use the time dimension of cube `dst`? Follows the joins the compiled spec carries (no `cubes` means: assume so). */
function reaches(spec, src, dst) {
  if (src === dst || !spec.cubes) return true;
  const seen = new Set([src]);
  const todo = [src];
  while (todo.length) {
    for (const next of spec.cubes[todo.pop()]?.joins || []) {
      if (next === dst) return true;
      if (!seen.has(next)) { seen.add(next); todo.push(next); }
    }
  }
  return false;
}

/** Does the page's period narrow this panel? Not text, not the drill panel itself (it keeps its own range), not one that opted out with ignore_filters: [period], and only if its measures can join the time dimension. */
export function appliesPeriod(spec, def) {
  if (def.type === "text" || def.drill || (def.ignore_filters || []).includes("period")) return false;
  const measures = panelMeasures(def, spec.members);
  const timeCube = cubeOf(spec.time.dimension);
  return measures.length > 0 && measures.every((m) => reaches(spec, cubeOf(m), timeCube));
}

/** The query with a date range on the dashboard's time dimension (merged into the entry the query already has for it, if any). */
export function withRange(spec, query, range) {
  const dim = spec.time.dimension;
  const td = query.timeDimensions || [];
  const has = td.some((t) => t.dimension === dim);
  return { ...query, timeDimensions: has ? td.map((t) => (t.dimension === dim ? { ...t, dateRange: range } : t)) : [...td, { dimension: dim, dateRange: range }] };
}

/** `queries` ([{ cube, query }]) narrowed by the page's period when this panel follows it. */
export function followPeriod(spec, def, values, queries) {
  const range = parsePeriod(values[PERIOD]);
  return range && appliesPeriod(spec, def) ? queries.map((q) => ({ ...q, query: withRange(spec, q.query, range) })) : queries;
}

// ------------------------------------------------------------------ the queries of each panel type
// One place builds them: the panels run them, and `dashspec lint` (which asks Cube whether a rollup serves each) mirrors them in Python;
// dashboards/tests checks the two agree on every dashboard.

/** KPI tile `t` (a term): { now, series } queries per cube; series is null without a sparkline. */
export function kpiQueries(spec, def, t, values) {
  const filters = activeFilters(spec, values, def);
  return {
    now: followPeriod(spec, def, values, queriesPerCube(t.members, { filters })),
    series: def.sparkline
      ? followPeriod(spec, def, values, queriesPerCube(t.members, { filters, timeDimensions: [{ dimension: spec.time.dimension, granularity: def.sparkline.granularity }] })) : null,
  };
}

/** `range` is the drill-down's own date range (the period of the bucket drilled into); a chart that does not drill follows the page's period instead. */
export function timeseriesQueries(spec, def, values, granularity, range = null) {
  const members = [...new Set(def.series.flatMap((s) => term(s).members))];
  const queries = queriesPerCube(members, { timeDimensions: [{ dimension: spec.time.dimension, granularity, ...(range ? { dateRange: range } : {}) }], filters: activeFilters(spec, values, def) });
  return range ? queries : followPeriod(spec, def, values, queries);
}

export function barQueries(spec, def, values) {
  const measures = def.stack ? def.stack.map((s) => s.member) : [def.measure];
  const single = !def.stack && !def.split;       // then the database ranks and limits; otherwise totals per row are needed first
  return followPeriod(spec, def, values, queriesPerCube(measures, {
    dimensions: [def.by, ...(def.split ? [def.split] : [])], filters: activeFilters(spec, values, def),
    ...(single ? { order: { [def.measure]: def.sort || "desc" }, limit: def.limit || 10 } : {}),
  }));
}

/** A pie reads every slice (up to 100) so that the tail past `limit` can be grouped as "Other" with an exact total. */
export const pieQueries = (spec, def, values) => followPeriod(spec, def, values,
  queriesPerCube(def.sum || [def.measure], { dimensions: [def.by], filters: activeFilters(spec, values, def), limit: 100 })
    .map((q) => ({ ...q, query: { ...q.query, order: { [q.query.measures[0]]: "desc" } } })));

export const treemapQueries = (spec, def, values) => followPeriod(spec, def, values, queriesPerCube([def.measure], { dimensions: def.group, filters: activeFilters(spec, values, def) }));

/**
 * The order a table is read in. `sort` is the viewer's header click: undefined = untouched (the author's `order`, else every dimension
 * ascending, left to right), null = cleared (every dimension ascending), { member, dir } = that column first, then the dimensions ascending
 * so that equal values keep a steady order.
 */
export function tableOrder(def, dimensions, sort) {
  const dimsAsc = (skip = "") => Object.fromEntries(dimensions.filter((d) => d !== skip).map((d) => [d, "asc"]));
  if (sort === undefined) return Object.keys(def.order || {}).length ? { ...def.order } : dimsAsc();
  return sort === null ? dimsAsc() : { [sort.member]: sort.dir, ...dimsAsc(sort.member) };
}

/** What a header click on `member` does: measures cycle desc, asc, none; dimensions asc, desc, none. null is "none". */
export function nextSort(sort, member, isMeasure) {
  const [first, second] = isMeasure ? ["desc", "asc"] : ["asc", "desc"];
  if (!sort || sort.member !== member) return { member, dir: first };
  return sort.dir === first ? { member, dir: second } : null;
}

export function tableQueries(spec, def, values, sort) {
  const { measures, dimensions, values: agg } = tableParts(def, spec.members);
  const order = tableOrder(def, dimensions, sort);
  const filters = activeFilters(spec, values, def);
  const single = new Set(measures.map((m) => m.split(".")[0])).size <= 1 && !agg.length;           // with aggregated fields the rows are merged and ordered in the page, not in Cube
  const base = { dimensions, filters, ...(single ? { order, limit: def.limit || 100 } : {}) };
  const out = [];
  if (measures.length) out.push(...followPeriod(spec, def, values, queriesPerCube(measures, base)));
  else if (!agg.length) return [{ cube: "", query: { ...base, order, limit: def.limit || 100 } }];
  if (agg.length) {                                                                              // the rows the value fields are aggregated over: one per row of their cube, tagged `agg:<cube>`
    const cube = cubeOf(agg[0].member), key = spec.rowKeys[cube];
    out.push({ cube: `agg:${cube}`, query: { dimensions: [...dimensions, key, ...new Set(agg.map((a) => a.member))], filters, order: { [key]: "asc" }, limit: AGGREGATE_LIMIT } });
  }
  return out;
}

/** A table's total row (`def.totals`): its measures with no grouping and no limit, one query per cube, so Cube aggregates over the whole set. */
export function tableTotalQueries(spec, def, values) {
  if (!def.totals) return [];
  const { measures } = tableParts(def, spec.members);
  return measures.length ? followPeriod(spec, def, values, queriesPerCube(measures, { filters: activeFilters(spec, values, def) })) : [];
}

// ------------------------------------------------------------------ tabs
/** The pages of a dashboard: its `tabs`, or its one `layout` as a single untitled tab (and then there is no tab bar). */
export const normalizeTabs = (spec) => (spec.tabs?.length ? spec.tabs : [{ id: "main", title: "", layout: spec.layout }]);

/** The tab to open: the one the address names, else the first (an unknown name is not an error). */
export const pickTab = (tabs, wanted) => (tabs.some((t) => t.id === wanted) ? wanted : tabs[0].id);

/** The ids of the panels a tab places, in layout order. */
export const tabPanelIds = (tab) => tab.layout.flat().map((c) => c.panel);

/** Where a key moves the focus in a tab bar: the index to go to, or null when the key is not one of ours (arrows wrap, Home and End jump). */
export function tabKeyTarget(key, index, count) {
  if (key === "ArrowRight" || key === "ArrowDown") return (index + 1) % count;
  if (key === "ArrowLeft" || key === "ArrowUp") return (index - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}

// ------------------------------------------------------------------ pivot
// Cube has no ROLLUP, so a pivot is several ordinary queries merged here, in two waves. Wave 1 (the axes) asks the first measure's cube which
// rows and columns to show: the top rows by that measure (or by name) and the first columns by name. Wave 2 (the values) asks every
// measure's cube for the cells and the totals, filtered to those rows and columns. Totals are asked, never summed in the browser, so a
// ratio is the ratio of the totals; the column and grand totals cover the whole filtered set, not only the rows shown.

export const PIVOT_LIMIT = { rows: 25, columns: 12 };
const PIVOT_MAX_ROWS = 200;                      // the schema's ceiling on `limit.rows`: every group is asked for
const PIVOT_CELLS = 50000;                       // Cube's own ceiling on a result; a pivot that reaches it says so (`truncated`)

const pivotOrder = (def) => { const by = def.order?.by || "total"; return { by, dir: def.order?.dir || (by === "label" ? "asc" : "desc") }; };
const keyFilter = (member, values) => ({ member, operator: "equals", values });
/** A pivot's columns are a dimension (`"dates.fiscal_year"`) or a time dimension at a granularity (`{ member, granularity }`) -> { member, granularity? }. */
export const pivotColumn = (def) => (typeof def.columns === "string" ? { member: def.columns } : def.columns);

/**
 * { axes: { rows, groups, cols }, values: { cells, groupCells, rowTotals, groupTotals, colTotals, grand } }, each a list of { cube, query }.
 * `keys` ({ rows: [[r0, r1?], ...], cols: [...] }, the axes' answer) narrows wave 2 to those rows and columns; without it (a lint) the shapes only.
 */
export function pivotQueries(spec, def, values, keys = null) {
  const measures = def.measures.map((m) => m.member), lead = measures[0];
  const [r0, r1] = def.rows, { member: col, granularity: gran } = pivotColumn(def), totalsMode = def.totals || "both";
  const lim = { ...PIVOT_LIMIT, ...def.limit }, { by, dir } = pivotOrder(def);
  // The grouping of a query by these rows and, with `withCol`, the column: a time column is a timeDimension at its granularity, narrowed
  // (once the axes are known) to the span of the chosen buckets; any other column is one more dimension.
  const colRange = keys && gran && keys.cols.length ? [rangeOf(keys.cols[0], gran)[0], rangeOf(keys.cols[keys.cols.length - 1], gran)[1]] : null;
  const shape = (rowDims, withCol) => {
    const dimensions = withCol && !gran ? [...rowDims, col] : rowDims;
    return { ...(dimensions.length ? { dimensions } : {}), ...(withCol && gran ? { timeDimensions: [{ dimension: col, granularity: gran, ...(colRange ? { dateRange: colRange } : {}) }] } : {}) };
  };
  const base = activeFilters(spec, values, def);
  const follow = (qs) => followPeriod(spec, def, values, qs);
  const leadQuery = (query) => follow([{ cube: cubeOf(lead), query: { measures: [lead], filters: base, ...query } }]);
  const dimsAsc = Object.fromEntries(def.rows.map((d) => [d, "asc"]));
  const axes = {
    rows: leadQuery({ ...shape(def.rows, false), order: by === "total" ? { [lead]: dir, ...dimsAsc } : Object.fromEntries(def.rows.map((d) => [d, dir])), limit: lim.rows + 1 }),
    groups: r1 ? leadQuery({ ...shape([r0], false), order: by === "total" ? { [lead]: dir, [r0]: "asc" } : { [r0]: dir }, limit: PIVOT_MAX_ROWS }) : [],
    cols: leadQuery({ ...shape([], true), order: { [col]: "asc" }, limit: lim.columns + 1 }),
  };
  const rowF = !keys ? [] : [keyFilter(r0, [...new Set(keys.rows.map((k) => k[0]))]), ...(r1 ? [keyFilter(r1, [...new Set(keys.rows.map((k) => k[1]))])] : [])];
  const groupF = !keys ? [] : [rowF[0]];
  const colF = !keys || gran ? [] : [keyFilter(col, keys.cols)];
  const per = (rowDims, withCol, filters) => {
    const grouping = shape(rowDims, withCol);
    return follow(queriesPerCube(measures, { filters: [...base, ...filters], ...grouping, ...(Object.keys(grouping).length ? { limit: PIVOT_CELLS } : {}) }));
  };
  const rowTot = totalsMode === "both" || totalsMode === "rows", colTot = totalsMode === "both" || totalsMode === "columns", any = totalsMode !== "none";
  return {
    axes,
    values: {
      cells: per(def.rows, true, [...rowF, ...colF]),
      groupCells: r1 && any ? per([r0], true, [...groupF, ...colF]) : [],
      rowTotals: rowTot ? per(def.rows, false, rowF) : [],
      groupTotals: r1 && rowTot ? per([r0], false, groupF) : [],
      colTotals: colTot ? per([], true, colF) : [],
      grand: any ? per([], false, []) : [],
    },
  };
}

/** Every pivot query in a fixed order, for `panelQueries` (lint and the tests that keep the Python mirror equal). */
export function pivotQueryList(spec, def, values) {
  const { axes, values: v } = pivotQueries(spec, def, values);
  return [axes.rows, axes.groups, axes.cols, v.cells, v.groupCells, v.rowTotals, v.groupTotals, v.colTotals, v.grand].flat();
}

/**
 * The numbers of a pivot, from the answers of its two waves ({ rows, groups, cols } and { cells, groupCells, rowTotals, groupTotals,
 * colTotals, grand }, each what `runAll` returns). Pure, no DOM.
 *   { measures, cols: [key], rows: [{ keys, cells: [Map|undefined per col], total: Map|undefined }],
 *     groups: null | [{ key, cells, total, rows }], colTotals: [Map|undefined per col], grand: Map, totals, hidden: { rows, cols }, truncated }
 * A cell is a Map member -> number, `undefined` where Cube had no row (an empty cell is not a zero). With two row dimensions the rows are
 * in groups (a group is a first-dimension value, with its own cells and total), in the order of the first dimension then the rows' own order.
 */
export function pivotModel(def, axes, vals) {
  const [r0, r1] = def.rows, { member, granularity: gran } = pivotColumn(def), lim = { ...PIVOT_LIMIT, ...def.limit };
  const col = gran ? timeKey(member, gran) : member;             // the key a row of Cube's answer carries the column under
  const str = (v) => (v == null ? "" : String(v));
  const join = (...parts) => parts.join("\u0000");
  const index = (results, dims) => new Map(byDims(results || [], dims).map((r) => [join(...dims.map((d) => str(r.dims[d]))), r.values]));
  const colsAll = (axes.cols?.[0]?.rows || []).map((r) => str(r[col]));
  const leavesAll = (axes.rows?.[0]?.rows || []).map((r) => def.rows.map((d) => str(r[d])));
  const cols = colsAll.slice(0, lim.columns), leaves = leavesAll.slice(0, lim.rows);
  const cells = index(vals.cells, [...def.rows, col]), rowTotal = index(vals.rowTotals, def.rows), colTotal = index(vals.colTotals, [col]);
  const rows = leaves.map((keys) => ({ keys, cells: cols.map((c) => cells.get(join(...keys, c))), total: rowTotal.get(join(...keys)) }));
  let groups = null, flat = rows;
  if (r1) {
    const groupCells = index(vals.groupCells, [r0, col]), groupTotal = index(vals.groupTotals, [r0]);
    const seen = new Set(leaves.map((k) => k[0]));
    const order = (axes.groups?.[0]?.rows || []).map((r) => str(r[r0])).filter((g) => seen.has(g));
    for (const g of seen) if (!order.includes(g)) order.push(g);
    groups = order.map((key) => ({ key, cells: cols.map((c) => groupCells.get(join(key, c))), total: groupTotal.get(join(key)), rows: rows.filter((r) => r.keys[0] === key) }));
    flat = groups.flatMap((g) => g.rows);
  }
  const results = [...Object.values(vals)].flat();
  return {
    measures: def.measures.map((m) => m.member), cols, rows: flat, groups,
    colTotals: cols.map((c) => colTotal.get(c)), grand: totals(vals.grand || []), totals: def.totals || "both",
    hidden: { rows: leavesAll.length > lim.rows, cols: colsAll.length > lim.columns },
    truncated: results.some((r) => (r.rows || []).length >= PIVOT_CELLS),
  };
}

/**
 * A pivot model with every number as a share (`mode`: share_of_row | share_of_column | share_of_total), from the totals the model already holds:
 * a cell over its row's, its column's or the grand total; a total over its own total (so 100%) or the grand total. A missing or zero total
 * gives no share (null), never a guess. Additive measures only (the validator sees to that). Same shape as `pivotModel`'s answer.
 */
export function pivotShare(model, mode) {
  const over = (map, denom) => (map ? new Map([...map].map(([k, v]) => { const d = denom?.get(k); return [k, v == null || d == null || d === 0 ? null : v / d]; })) : undefined);
  const grand = model.grand;
  const rowMap = new Map();
  const rows = model.rows.map((r) => {
    const row = { ...r, cells: r.cells.map((c, j) => over(c, mode === "share_of_row" ? r.total : mode === "share_of_column" ? model.colTotals[j] : grand)), total: over(r.total, mode === "share_of_row" ? r.total : grand) };
    rowMap.set(r, row);
    return row;
  });
  const groups = model.groups && model.groups.map((g) => ({
    ...g, rows: g.rows.map((r) => rowMap.get(r)),
    cells: g.cells.map((c, j) => over(c, mode === "share_of_row" ? g.total : mode === "share_of_column" ? model.colTotals[j] : grand)),
    total: over(g.total, mode === "share_of_row" ? g.total : grand),
  }));
  return { ...model, rows, groups, colTotals: model.colTotals.map((c) => over(c, mode === "share_of_column" ? c : grand)), grand: over(grand, grand) };
}

/**
 * The shading of a pivot's cells for one measure: { min, max, level(v) } over the cells (not the totals), `level` 0..1, or null when no
 * cell has a number. An empty cell has no level; when every cell is equal they all sit in the middle.
 */
export function heatScale(model, member) {
  const values = model.rows.flatMap((r) => r.cells.map((c) => c?.get(member))).filter((v) => v != null && Number.isFinite(v));
  if (!values.length) return null;
  const min = Math.min(...values), max = Math.max(...values);
  return { min, max, level: (v) => (v == null || !Number.isFinite(v) ? null : max === min ? 0.5 : (v - min) / (max - min)) };
}

/** Every Cube query a panel sends for these filter values, for the panel's default granularity (a KPI's tiles and sparklines included). */
/**
 * The queries behind a slicer's options: the values of its filter's dimension, as many queries as the measures of the panels the filter applies to need (one measure per cube, so
 * the values are those that have data). The other filters that apply to the slicer narrow them (the dashboard's, its tab's, its own pane filters) and so does a drill-down's period;
 * its own filter never does, so the list does not shrink to what is chosen.
 */
export function slicerQueries(spec, def, values) {
  const f = (spec.filters || []).find((x) => x.id === def.filter);
  if (!f) return [];
  const measures = optionMeasures(spec, f);
  const own = { ...def, ignore_filters: [...(def.ignore_filters || []), f.id], optionMeasures: measures };
  const dims = [...(f.parent ? [f.parent] : []), f.dimension];
  return followPeriod(spec, own, values, queriesPerCube(measures, { dimensions: dims, filters: activeFilters(spec, values, own) }));
}

export function panelQueries(spec, def, values) {
  switch (def.type) {
    case "slicer": return slicerQueries(spec, def, values);
    case "kpi": return def.measures.map(term).flatMap((t) => { const q = kpiQueries(spec, def, t, values); return [...q.now, ...(q.series || [])]; });
    case "timeseries": return timeseriesQueries(spec, def, values, def.granularity);
    case "bar": return barQueries(spec, def, values);
    case "pie": return pieQueries(spec, def, values);
    case "treemap": return treemapQueries(spec, def, values);
    case "table": return [...tableQueries(spec, def, values), ...tableTotalQueries(spec, def, values)];
    case "pivot": return pivotQueryList(spec, def, values);
    default: return [];
  }
}
