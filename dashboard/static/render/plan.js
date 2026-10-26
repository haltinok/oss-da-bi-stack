// The renderer's data logic, with no DOM: which Cube queries a panel needs, and how their rows become numbers. A panel names Cube
// members only; this module never writes SQL. Cube cannot join two fact cubes in one query, so a panel that lists measures of several
// cubes gets one query per cube and the rows are merged here, on the dimensions the panel groups by.

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
export function activeFilters(spec, values, panel = {}) {
  const ignored = new Set([...(panel.ignore_filters || []), ...ownFilterIds(panel)]);
  return (spec.filters || [])
    .filter((f) => values[f.id] !== undefined && values[f.id] !== "" && !ignored.has(f.id))
    .map((f) => ({ member: f.dimension, operator: "equals", values: [String(values[f.id])] }));
}

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
export function optionMeasures(spec, filter) {
  const per = new Map();
  for (const p of spec.panels) {
    if ((p.ignore_filters || []).includes(filter.id)) continue;
    for (const m of panelMeasures(p, spec.members)) if (!per.has(cubeOf(m))) per.set(cubeOf(m), m);
  }
  return [...per.values()];
}

/** Every measure a panel reads (`members` is the compiled spec's member map, needed to tell a table's measures from its dimensions). */
export function panelMeasures(p, members = {}) {
  switch (p.type) {
    case "kpi": return p.measures.flatMap((m) => term(m).members);
    case "timeseries": return p.series.flatMap((s) => term(s).members);
    case "bar": return p.stack ? p.stack.map((s) => s.member) : [p.measure];
    case "treemap": return [p.measure];
    case "table": return tableParts(p, members).measures;
    default: return [];
  }
}

/** The members a table shows, split by kind with the compiled `members` map: { measures, dimensions }. */
export function tableParts(p, members) {
  const cols = p.columns.map((c) => c.member);
  return { measures: cols.filter((m) => members[m]?.kind === "measure"), dimensions: cols.filter((m) => members[m]?.kind !== "measure") };
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

// ------------------------------------------------------------------ the queries of each panel type
// One place builds them: the panels run them, and `dashspec lint` (which asks Cube whether a rollup serves each) mirrors them in Python;
// dashboards/tests checks the two agree on every dashboard.

/** KPI tile `t` (a term): { now, series } queries per cube; series is null without a sparkline. */
export function kpiQueries(spec, def, t, values) {
  const filters = activeFilters(spec, values, def);
  return {
    now: queriesPerCube(t.members, { filters }),
    series: def.sparkline
      ? queriesPerCube(t.members, { filters, timeDimensions: [{ dimension: spec.time.dimension, granularity: def.sparkline.granularity }] }) : null,
  };
}

export function timeseriesQueries(spec, def, values, granularity) {
  const members = [...new Set(def.series.flatMap((s) => term(s).members))];
  return queriesPerCube(members, { timeDimensions: [{ dimension: spec.time.dimension, granularity }], filters: activeFilters(spec, values, def) });
}

export function barQueries(spec, def, values) {
  const measures = def.stack ? def.stack.map((s) => s.member) : [def.measure];
  const single = !def.stack && !def.split;       // then the database ranks and limits; otherwise totals per row are needed first
  return queriesPerCube(measures, {
    dimensions: [def.by, ...(def.split ? [def.split] : [])], filters: activeFilters(spec, values, def),
    ...(single ? { order: { [def.measure]: def.sort || "desc" }, limit: def.limit || 10 } : {}),
  });
}

export const treemapQueries = (spec, def, values) => queriesPerCube([def.measure], { dimensions: def.group, filters: activeFilters(spec, values, def) });

export function tableQueries(spec, def, values) {
  const { measures, dimensions } = tableParts(def, spec.members);
  const order = Object.fromEntries(Object.entries(def.order || {}));
  const single = new Set(measures.map((m) => m.split(".")[0])).size <= 1;
  const base = { dimensions, filters: activeFilters(spec, values, def), ...(single ? { order, limit: def.limit || 100 } : {}) };
  if (!measures.length) return [{ cube: "", query: { ...base, order, limit: def.limit || 100 } }];
  return queriesPerCube(measures, base);
}

/** Every Cube query a panel sends for these filter values, for the panel's default granularity (a KPI's tiles and sparklines included). */
export function panelQueries(spec, def, values) {
  switch (def.type) {
    case "kpi": return def.measures.map(term).flatMap((t) => { const q = kpiQueries(spec, def, t, values); return [...q.now, ...(q.series || [])]; });
    case "timeseries": return timeseriesQueries(spec, def, values, def.granularity);
    case "bar": return barQueries(spec, def, values);
    case "treemap": return treemapQueries(spec, def, values);
    case "table": return tableQueries(spec, def, values);
    default: return [];
  }
}
