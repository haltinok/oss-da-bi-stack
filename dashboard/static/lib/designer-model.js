// The designer's logic without the page: which fields a panel offers, how an edit changes the dashboard's source spec, and which members may be offered.
// Pure functions, no DOM. The designer never judges a spec itself: it edits the source (the YAML as an object) and the builder service's validator, the same one that
// checks a model's answer, accepts or refuses the result.

export const FORMATS = ["money", "int", "pct", "decimal", "number"];
export const GRANULARITIES = ["hour", "day", "week", "month", "quarter", "year"];
const DIRECTIONS = ["asc", "desc"];
export const RULE_WHEN = ["below", "above", "at_most", "at_least"];
export const RULE_TONES = ["good", "warn", "bad"];

// What each field kind is: "text", "textarea", "color" (a theme name or #rrggbb), "number" (min, max), "choice" (options), "measure", "dimension".
// `optional` means the field may be empty, which removes it from the spec (or, for an item of a list, removes the item).
const f = (path, kind, extra = {}) => ({ path, kind, ...extra });

/** The fields the drawer shows for a panel, in order. Each is { path, kind, key (the words' name), options?, min?, max?, optional?, group? (a heading for a repeated item) }. */
export function fieldsFor(panel, { isMeasure = () => false, filters = [], typeOf = () => undefined } = {}) {
  const out = [];
  const each = (list, make) => (Array.isArray(list) ? list : []).forEach((item, i) => make(item, i));
  // Colour rules of a key figure or a measure column: three fields per rule (with a remove button on the first), then a button for one more.
  const ruleFields = (base, item, canRule) => {
    each(item?.rules, (r, j) => {
      const at = `${base}.rules.${j}`;
      out.push(f(`${at}.when`, "choice", { key: "ruleWhen", options: RULE_WHEN, rm: at }), f(`${at}.value`, "number", { key: "ruleValue", step: "any" }), f(`${at}.tone`, "choice", { key: "ruleTone", options: RULE_TONES }));
    });
    if (canRule && (item?.rules || []).length < 4) out.push({ path: `${base}.rules`, kind: "addrule", key: "addRule", base });
  };
  const measureItem = (name, list, extra = {}) => each(list, (m, i) => {
    const g = { n: i + 1, of: list.length };
    if (extra.formula) out.push(f(`${name}.${i}`, "value", { key: "measure", group: g, list: name, index: i, count: list.length }));
    else if (m && typeof m === "object" && m.member) out.push(f(`${name}.${i}.member`, "measure", { key: "measure", group: g, list: name, index: i, count: list.length }));
    else if (m && typeof m === "object") out.push({ path: `${name}.${i}`, kind: "readonly", key: "formula", group: g });
    else out.push(f(`${name}.${i}`, "measure", { key: "measure", group: g, list: name, index: i, count: list.length }));
    if (m && typeof m === "object") {
      out.push(f(`${name}.${i}.label`, "text", { key: "label", group: g, optional: extra.optionalLabel }));
      if (extra.format !== false) out.push(f(`${name}.${i}.format`, "choice", { key: "format", options: FORMATS, optional: true, group: g }));
      if (extra.rules) ruleFields(`${name}.${i}`, m, true);
    }
  });
  if (panel.type !== "text" && panel.type !== "kpi") out.push(f("title", "text", { key: "title", optional: true }));
  switch (panel.type) {
    case "kpi":
      measureItem("measures", panel.measures, { formula: true, rules: true });
      out.push(f("sparkline.granularity", "choice", { key: "sparkline", options: GRANULARITIES, optional: true }));
      if (panel.sparkline) out.push(f("time_dimension", "timedim", { key: "panelTimeDimension", optional: true }));
      break;
    case "timeseries":
      out.push(f("style", "choice", { key: "style", options: ["line", "area", "stacked-area", "bar", "stacked-bar"] }), f("time_dimension", "timedim", { key: "panelTimeDimension", optional: true }));
      if (!panel.drill) out.push(f("granularity", "choice", { key: "granularity", options: GRANULARITIES }), { path: "granularities", kind: "multicheck", key: "granularities", options: GRANULARITIES });
      out.push({ path: "drill", kind: "drill", key: "drill" });
      each(panel.series, (s, i) => {
        const g = { n: i + 1, of: panel.series.length };
        out.push(f(`series.${i}`, "value", { key: "measure", group: g, list: "series", index: i, count: panel.series.length }));
        out.push(f(`series.${i}.label`, "text", { key: "label", group: g }), f(`series.${i}.color`, "color", { key: "color", optional: true, group: g }), f(`series.${i}.format`, "choice", { key: "format", options: FORMATS, optional: true, group: g }));
      });
      break;
    case "bar":
      out.push({ path: "~kind", kind: "barkind", key: "barValue" });
      if (panel.stack) each(panel.stack, (s, i) => { const g = { n: i + 1, of: panel.stack.length }; out.push(f(`stack.${i}.member`, "measure", { key: "measure", group: g, list: "stack", index: i, count: panel.stack.length }), f(`stack.${i}.label`, "text", { key: "label", group: g }), f(`stack.${i}.color`, "color", { key: "color", optional: true, group: g })); });
      else if (panel.measure) out.push(f("measure", "measure", { key: "measure" }), f("label", "text", { key: "label", optional: true }));
      out.push(f("by", "dimension", { key: "by" }), f("by_label", "text", { key: "byLabel", optional: true }), ...(panel.stack ? [] : [f("split", "dimension", { key: "split", optional: true })]),
        f("sort", "choice", { key: "sort", options: DIRECTIONS, optional: true }), f("limit", "number", { key: "limit", min: 1, max: 1000, optional: true }),
        f("orientation", "choice", { key: "orientation", options: ["horizontal", "vertical"], optional: true }), f("format", "choice", { key: "format", options: FORMATS, optional: true }), f("cross_filter", "crossfilter", { key: "crossFilter" }));
      break;
    case "pie":
      out.push({ path: "~value", kind: "pievalue", key: "measure" }, f("label", "text", { key: "label", optional: true }));
      out.push(f("by", "dimension", { key: "by" }), f("by_label", "text", { key: "byLabel", optional: true }), f("style", "choice", { key: "style", options: ["pie", "donut"], optional: true }), f("limit", "number", { key: "limit", min: 2, max: 30, optional: true }), f("format", "choice", { key: "format", options: FORMATS, optional: true }), f("cross_filter", "crossfilter", { key: "crossFilter" }));
      break;
    case "treemap":
      out.push(f("measure", "measure", { key: "measure" }), f("label", "text", { key: "label", optional: true }), f("group.0", "dimension", { key: "group" }), f("group_labels.0", "text", { key: "groupLabel", optional: true }), f("group.1", "dimension", { key: "group2", optional: true }), f("group_labels.1", "text", { key: "group2Label", optional: true }), f("format", "choice", { key: "format", options: FORMATS, optional: true }), f("cross_filter", "crossfilter", { key: "crossFilter" }));
      break;
    case "table":
      each(panel.columns, (c, i) => {
        const g = { n: i + 1, of: panel.columns.length };
        const isObj = c && typeof c === "object";
        const member = isObj ? c.member : c;
        out.push(f(isObj ? `columns.${i}.member` : `columns.${i}`, "member", { key: "column", group: g, list: "columns", index: i, count: panel.columns.length }));
        if (isObj) out.push(f(`columns.${i}.label`, "text", { key: "label", optional: true, group: g }));
        // A measure has its aggregation built in; a dimension is a group, or a value with an aggregate (sum, max, ...).
        if (isMeasure(member)) out.push({ path: `columns.${i}.~builtin`, kind: "builtin", key: "aggregate", member, group: g });
        else out.push({ path: `columns.${i}.aggregate`, kind: "aggregate", key: "aggregate", type: typeOf(member), index: i, group: g });
        if (isMeasure(member)) ruleFields(`columns.${i}`, isObj ? c : {}, true);
      });
      out.push(f("limit", "number", { key: "limit", min: 1, max: 1000, optional: true }), f("totals", "choice", { key: "totals", options: ["footer", "header"], optional: true }), { path: "order", kind: "tableorder", key: "tableOrder" }, f("cross_filter", "crossfilter", { key: "crossFilter" }));
      break;
    case "pivot":
      out.push(f("rows.0", "dimension", { key: "rows" }), f("rows.1", "dimension", { key: "rows2", optional: true }));
      out.push({ path: "~step", kind: "pivotstep", key: "columnStep" });
      if (typeof panel.columns === "string") out.push(f("columns", "dimension", { key: "columns" }));
      else if (panel.columns && typeof panel.columns === "object") out.push(f("columns.member", "dimension", { key: "columns" }));
      measureItem("measures", panel.measures);
      out.push(f("totals", "choice", { key: "totals", options: ["both", "rows", "columns", "none"], optional: true }), f("show", "choice", { key: "show", options: ["value", "share_of_row", "share_of_column", "share_of_total"], optional: true }));
      out.push(f("heat.measure", "choice", { key: "heat", options: (panel.measures || []).map((m) => (typeof m === "string" ? m : m?.member)).filter(Boolean), optional: true }),
        f("order.by", "choice", { key: "orderBy", options: ["total", "label"], optional: true }), f("order.dir", "choice", { key: "orderDir", options: DIRECTIONS, optional: true }),
        f("limit.rows", "number", { key: "limitRows", min: 1, max: 200, optional: true }), f("limit.columns", "number", { key: "limitColumns", min: 1, max: 24, optional: true }));
      break;
    case "text":
      out.push(f("markdown", "textarea", { key: "markdown" }));
      break;
    case "slicer":
      out.push(f("filter", "choice", { key: "slicerFilter", options: filters.map((x) => x.id), labels: Object.fromEntries(filters.map((x) => [x.id, x.label || x.id])) }),
        f("display", "choice", { key: "slicerDisplay", options: ["list", "chips", "dropdown"], optional: true }));
      break;
    default:
  }
  if (panel.type !== "text") out.push({ path: "ignore_filters", kind: "ignorefilters", key: "ignoreFilters" });
  return out;
}

const tokens = (path) => path.split(".").map((p) => (/^\d+$/.test(p) ? Number(p) : p));

/** The value at a path of a panel (undefined when any step is missing). */
export function getAt(obj, path) {
  let cur = obj;
  for (const k of tokens(path)) { if (cur == null) return undefined; cur = cur[k]; }
  return cur;
}

// Fields that name what a panel groups or lists by: a click rule (on_click.set_filter) depends on them.
const GROUPING = /^(time_dimension|by|group\.\d+|rows\.\d+|columns|columns\.member|columns\.\d+(\.member)?)$/;

/**
 * Sets one field of one panel and returns { source, notes }: a copy of the source with the change (the argument is not touched), and what the person should be told.
 * An empty value (null, "") on an optional field removes it; on an item of a list it removes the item; a number field takes numbers. Changing what a panel groups by
 * drops its click rule (it points at a filter on the old dimension) and says so.
 */
export function setField(source, panelId, path, value, { optional = false } = {}) {
  const next = JSON.parse(JSON.stringify(source));
  const panel = next.panels.find((p) => p.id === panelId);
  if (!panel) throw new Error(`no panel '${panelId}'`);
  const notes = [];
  const steps = tokens(path), last = steps.pop();
  let cur = panel;
  steps.forEach((k, i) => {
    if (cur[k] == null || typeof cur[k] !== "object") cur[k] = typeof (steps[i + 1] ?? last) === "number" ? [] : {};      // a missing step is made: a list before an index, else an object
    cur = cur[k];
  });
  if ((value === null || value === undefined || value === "") && optional) {
    if (Array.isArray(cur)) cur.splice(last, 1); else delete cur[last];
    for (let i = steps.length - 1; i >= 0; i--) {                      // an object or list the removal left empty (`heat: {}`, `limit: {}`, `rules: []`) goes too
      const parent = steps.slice(0, i).reduce((o, k) => o[k], panel), key = steps[i];
      const v = parent[key];
      if (v && typeof v === "object" && !(Array.isArray(v) ? v.length : Object.keys(v).length)) delete parent[key]; else break;
    }
  } else cur[last] = value;
  if (GROUPING.test(path) && panel.on_click) { delete panel.on_click; notes.push("click"); }
  return { source: next, notes };
}

/** What a field's input is showing: the value as text ("" when absent). */
export const shown = (panel, path) => { const v = getAt(panel, path); return v == null || typeof v === "object" ? "" : String(v); };

// ------------------------------------------------------------------------------------------------------------------ members
/** The cube of a member name "cube.member". */
export const cubeOf = (member) => String(member).split(".")[0];

const MEMBER = /^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$/;
/** Every "cube.member" string a panel mentions (its measures, series, columns...), once each. */
export function membersIn(value, out = new Set()) {
  if (typeof value === "string") { if (MEMBER.test(value)) out.add(value); }
  else if (Array.isArray(value)) value.forEach((v) => membersIn(v, out));
  else if (value && typeof value === "object") for (const [k, v] of Object.entries(value)) if (k !== "markdown" && k !== "on_click") membersIn(v, out);
  return out;
}

/**
 * The cubes whose dimensions a panel on `fromCubes` can use: those every one of the cubes reaches (their own, or through joins at any distance). A panel that
 * adds two channels together needs a dimension both can join to, so this is the overlap, not the sum. A cube the catalog does not know allows everything (null).
 */
export function reachableCubes(catalog, fromCubes) {
  const byName = Object.fromEntries(catalog.map((c) => [c.cube, c]));
  if (fromCubes.some((c) => !byName[c])) return null;
  const reach = (start) => {
    const seen = new Set([start]), todo = [start];
    while (todo.length) for (const j of byName[todo.pop()].joins || []) if (!seen.has(j) && byName[j]) { seen.add(j); todo.push(j); }
    return seen;
  };
  const sets = fromCubes.map(reach);
  return new Set([...sets[0]].filter((c) => sets.every((s) => s.has(c))));
}

/** Measure choices for a panel: every measure the role may read, as { value, label, cube, description }. */
/** A member's description for a tooltip, with what it sorts by when the model says so. */
export const noted = (d) => (d.sort_by ? `${d.description || ""} Sorted by ${d.sort_by}.`.trim() : d.description);

export const measureOptions = (catalog) => catalog.flatMap((c) => c.measures.map((m) => ({ value: m.member, label: m.member, cube: c.cube, description: m.description })));

/**
 * Dimension choices for a panel: the dimensions of the cubes its measures can reach, so the list never offers a grouping Cube could not answer.
 * With no measure in the panel yet, every dimension is offered. The current value is always kept in the list.
 */
export function dimensionOptions(catalog, panel, current = "") {
  const measureCubes = new Set([...membersIn(panel)].filter((m) => catalog.some((c) => c.measures.some((x) => x.member === m))).map(cubeOf));
  const allowed = measureCubes.size ? reachableCubes(catalog, [...measureCubes]) : null;
  return catalog.flatMap((c) => c.dimensions.map((d) => ({ value: d.member, label: d.member, cube: c.cube, description: noted(d) })))
    .filter((o) => !allowed || allowed.has(o.cube) || o.value === current);
}

/** Table columns may be either kind. */
export const anyMemberOptions = (catalog) => [...measureOptions(catalog), ...catalog.flatMap((c) => c.dimensions.map((d) => ({ value: d.member, label: d.member, cube: c.cube, description: noted(d) })))];
