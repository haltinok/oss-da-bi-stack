// The designer's edits to the items of a list inside a panel: a KPI's measures, a time chart's series, a pivot's measures, and the formulas (sum, ratio) a KPI or a series may be.
// Pure functions on the dashboard's source spec; each returns a copy (the argument is not touched) or { problem }. The validator has the last word, as for every other edit.
import { getAt } from "./designer-model.js";
import { AGGREGATES } from "./aggregate.js";
import { guessFormat, humanize } from "./designer-structure.js";

const clone = (x) => JSON.parse(JSON.stringify(x));

/** Which lists take more items or fewer, and what an item starts as. `formula`: the items may be a sum or a ratio. */
export const LISTS = {
  "kpi.measures": { min: 1, max: 8, formula: true },
  "timeseries.series": { min: 1, max: 12, formula: true },
  "pivot.measures": { min: 1, max: 3, formula: false },
  "table.columns": { min: 1, max: Infinity, formula: false },             // a table takes any number of fields
  "bar.stack": { min: 2, max: Infinity, formula: false },                 // a stacked bar: two measures or more
};
export const listRule = (panel, name) => LISTS[`${panel.type}.${name}`] || null;

/** What kind of value an item is: a plain "member", a "sum" of several, or a "ratio" of two sums. */
export const kindOf = (item) => (item && typeof item === "object" ? (item.ratio ? "ratio" : item.sum ? "sum" : "member") : "member");

/** The first measure an item is made of (what a change of kind starts from). */
export const firstMember = (item) => (typeof item === "string" ? item : item?.member || item?.sum?.[0] || item?.ratio?.num?.[0] || "");

/** A formula in words: "A + B", "(A + B) ÷ C". `name` turns a member into words. */
export function describe(item, name = humanize) {
  const k = kindOf(item);
  if (k === "sum") return item.sum.map(name).join(" + ");
  if (k === "ratio") {
    const side = (list) => (list.length > 1 ? `(${list.map(name).join(" + ")})` : name(list[0]));
    return `${side(item.ratio.num)} ÷ ${side(item.ratio.den)}`;
  }
  return name(firstMember(item));
}

function at(source, panelId, path) {
  const next = clone(source);
  const panel = next.panels.find((p) => p.id === panelId);
  return { next, panel, item: panel && getAt(panel, path) };
}

/** Turns the item at `path` into a plain measure, a sum or a ratio, keeping its label, format and colour; `spare` is the second measure a sum or ratio needs to start with. */
export function changeKind(source, panelId, path, kind, spare) {
  const { next, item } = at(source, panelId, path);
  if (!item || typeof item !== "object") return { problem: "item" };
  const first = firstMember(item), keep = { ...(item.label ? { label: item.label } : {}), ...(item.color ? { color: item.color } : {}), ...(item.format ? { format: item.format } : {}) };
  if (kind === kindOf(item)) return { source: next };
  let made;
  if (kind === "member") made = { member: first, ...keep, label: keep.label || humanize(first) };
  else if (!spare) return { problem: "spare" };
  else if (kind === "sum") made = { sum: [first, spare], ...keep, label: keep.label || `${humanize(first)} + ${humanize(spare)}` };
  else made = { ratio: { num: [first], den: [spare] }, ...keep, label: keep.label || `${humanize(first)} ÷ ${humanize(spare)}` };
  const steps = path.split("."), last = steps.pop();
  const holder = steps.reduce((o, k) => o[k], next.panels.find((p) => p.id === panelId));
  holder[last] = made;
  return { source: next };
}

const partList = (item, part) => (part === "sum" ? item.sum : item.ratio?.[part]);
const partMin = (part) => (part === "sum" ? 2 : 1);

/** Sets member `index` of a formula's part (`sum`, or `num` / `den` of a ratio). */
export function setPart(source, panelId, path, part, index, value) {
  const { next, item } = at(source, panelId, path);
  const list = item && partList(item, part);
  if (!list || index >= list.length) return { problem: "item" };
  list[index] = value;
  return { source: next };
}

export function addPart(source, panelId, path, part, spare) {
  const { next, item } = at(source, panelId, path);
  const list = item && partList(item, part);
  if (!list) return { problem: "item" };
  list.push(spare);
  return { source: next };
}

/** A part keeps its minimum (two for a sum, one for the sides of a ratio): the button is off at the minimum and this refuses. */
export function removePart(source, panelId, path, part, index) {
  const { next, item } = at(source, panelId, path);
  const list = item && partList(item, part);
  if (!list || list.length <= partMin(part) || index >= list.length) return { problem: "min" };
  list.splice(index, 1);
  return { source: next };
}
export const canRemovePart = (item, part) => (partList(item, part)?.length || 0) > partMin(part);

/** Adds an item (a measure) to a list of a panel: a KPI's measures, a chart's series, a pivot's measures. */
export function addItem(source, panelId, name, spare) {
  const { next, panel } = at(source, panelId, "id");
  const rule = panel && listRule(panel, name);
  if (!rule || !spare) return { problem: "item" };
  const list = (panel[name] ||= []);
  if (list.length >= rule.max) return { problem: "max" };
  const item = { member: spare, label: humanize(spare), format: guessFormat(spare) };
  list.push(panel.type === "pivot" ? { member: spare, label: item.label, format: item.format } : name === "stack" ? { member: spare, label: item.label } : item);
  return { source: next };
}

/** Removes item `index` from a list; the heat map of a pivot that pointed at it goes too. The last item stays (the button is off, and this refuses). */
export function removeItem(source, panelId, name, index) {
  const { next, panel } = at(source, panelId, "id");
  const rule = panel && listRule(panel, name);
  if (!rule || !Array.isArray(panel[name]) || panel[name].length <= rule.min || index >= panel[name].length) return { problem: "min" };
  const [gone] = panel[name].splice(index, 1);
  if (panel.type === "pivot" && panel.heat && firstMember(gone) === panel.heat.measure) delete panel.heat;
  if (panel.type === "table" && panel.order && !panel.columns.some((c) => firstMember(c) === firstMember(gone))) {           // a sort on a field that is gone
    delete panel.order[firstMember(gone)];
    if (!Object.keys(panel.order).length) delete panel.order;
  }
  return { source: next };
}

// ------------------------------------------------------------------------------------------------------------------ colour rules
export const MAX_RULES = 4;

/** Adds a colour rule to the key figure or table column at `path` (`measures.0`, `columns.2`); a column written as a plain member becomes { member } first. */
export function addRule(source, panelId, path) {
  const { next, panel, item } = at(source, panelId, path);
  if (!panel || item == null) return { problem: "item" };
  const target = typeof item === "string" ? { member: item } : item;
  if ((target.rules || []).length >= MAX_RULES) return { problem: "max" };
  (target.rules ||= []).push({ when: "below", value: 0, tone: "bad" });
  const steps = path.split("."), last = steps.pop();
  steps.reduce((o, k) => o[k], panel)[last] = target;
  return { source: next };
}

// ------------------------------------------------------------------------------------------------------------------ table fields
/** The aggregates a dimension field of this type can have: sum and average need a number. */
export const aggregatesFor = (type) => (type === "number" ? AGGREGATES : AGGREGATES.filter((a) => a !== "sum" && a !== "avg"));
const KEYLIKE = /(^|_)(key|id)$/;                                              // a number that names a thing (a key, an id) is a group, not something to add up

/**
 * Adds a field to the end of a table. `type` is what the catalog says it is ("measure", or the dimension's "string", "number", "time"): a measure keeps its own aggregation, a number
 * field starts as a Sum (Power BI's way), anything else is a group (a column of the table's rows).
 */
export function addColumn(source, panelId, member, type) {
  const { next, panel } = at(source, panelId, "id");
  if (!panel || panel.type !== "table" || !member) return { problem: "item" };
  panel.columns = [...(panel.columns || []), type === "number" && !KEYLIKE.test(member.split(".")[1] || "") ? { member, aggregate: "sum" } : { member }];
  return { source: next };
}

/** Sets a dimension field's aggregate ("" makes it a group again). A field written as a plain member becomes { member } first. */
export function setColumnAggregate(source, panelId, index, aggregate) {
  const { next, panel } = at(source, panelId, "id");
  const col = panel?.columns?.[index];
  if (!col) return { problem: "item" };
  const made = typeof col === "string" ? { member: col } : col;
  if (aggregate) made.aggregate = aggregate; else delete made.aggregate;
  panel.columns[index] = made;
  return { source: next };
}

/** Moves a field one place earlier (-1) or later (1). */
export function moveColumn(source, panelId, index, dir) {
  const { next, panel } = at(source, panelId, "id");
  const cols = panel?.columns;
  if (!cols || !cols[index] || !cols[index + dir]) return { problem: "edge" };
  [cols[index], cols[index + dir]] = [cols[index + dir], cols[index]];
  return { source: next };
}

// ------------------------------------------------------------------------------------------------------------------ a pie's value
/** What a pie's slices are sized by: one `measure`, or the `sum` of several (with a `label`). */
export const pieKind = (panel) => (panel.sum ? "sum" : "member");

/** Switches a pie between one measure and a sum of measures (`spare` is the second measure a sum starts with). */
export function setPieKind(source, panelId, kind, spare) {
  const { next, panel } = at(source, panelId, "id");
  if (!panel || panel.type !== "pie") return { problem: "item" };
  if (kind === pieKind(panel)) return { source: next };
  if (kind === "member") { panel.measure = panel.sum[0]; delete panel.sum; return { source: next }; }
  if (!spare) return { problem: "spare" };
  panel.sum = [panel.measure, spare];
  panel.label ||= `${humanize(panel.measure)} + ${humanize(spare)}`;
  delete panel.measure;
  return { source: next };
}

/** Sets, adds or removes a member of a pie's sum (two stay). */
export function setPieSum(source, panelId, index, value) {
  const { next, panel } = at(source, panelId, "id");
  if (!panel?.sum || index >= panel.sum.length) return { problem: "item" };
  panel.sum[index] = value;
  return { source: next };
}
export function addPieSum(source, panelId, spare) {
  const { next, panel } = at(source, panelId, "id");
  if (!panel?.sum || !spare) return { problem: "item" };
  panel.sum.push(spare);
  return { source: next };
}
export function removePieSum(source, panelId, index) {
  const { next, panel } = at(source, panelId, "id");
  if (!panel?.sum || panel.sum.length <= 2 || index >= panel.sum.length) return { problem: "min" };
  panel.sum.splice(index, 1);
  return { source: next };
}

// ------------------------------------------------------------------------------------------------------------------ the rest of the panels' own fields
export const GRAN_ORDER = ["hour", "day", "week", "month", "quarter", "year"];
/** The drill-down paths the designer offers (`drill` goes from coarse to fine; a week does not fit in a month or quarter). */
export const DRILL_PRESETS = { off: null, ymd: ["year", "month", "day"], yqm: ["year", "quarter", "month"], ym: ["year", "month"], md: ["month", "day"], wd: ["week", "day"] };
export const drillKeyOf = (panel) => Object.entries(DRILL_PRESETS).find(([, v]) => JSON.stringify(v) === JSON.stringify(panel.drill ?? null))?.[0] || "custom";

/** Sets a time chart's drill-down path. The chart starts at its first level; a drill-down replaces `granularities` and a click rule (the file may not have both). */
export function setDrill(source, panelId, key) {
  const { next, panel } = at(source, panelId, "id");
  if (!panel || panel.type !== "timeseries") return { problem: "item" };
  const notes = [];
  const levels = DRILL_PRESETS[key];
  if (!levels) { delete panel.drill; return { source: next, notes }; }
  panel.drill = [...levels];
  panel.granularity = levels[0];
  if (panel.granularities) { delete panel.granularities; notes.push("granularitiesDropped"); }
  if (panel.on_click) { delete panel.on_click; notes.push("click"); }
  return { source: next, notes };
}

/** The time steps a reader may switch a time chart between (two or more; the chart's own step is always one of them). Fewer than two removes the switch. */
export function setGranularities(source, panelId, list) {
  const { next, panel } = at(source, panelId, "id");
  if (!panel || panel.type !== "timeseries") return { problem: "item" };
  if (panel.drill) return { problem: "drill" };
  const set = new Set([...list, panel.granularity]);                      // the chart's own step is always one of them
  if (set.size < 2) { delete panel.granularities; return { source: next }; }
  panel.granularities = GRAN_ORDER.filter((g) => set.has(g));
  return { source: next };
}

/** The filters a panel does not follow (`ignore_filters`); an empty list removes the field. */
export function setIgnoredFilters(source, panelId, ids) {
  const { next, panel } = at(source, panelId, "id");
  if (!panel) return { problem: "item" };
  if (ids.length) panel.ignore_filters = [...ids]; else delete panel.ignore_filters;
  return { source: next };
}

/** A table's sort: by one field, ascending or descending ("" removes it; the table then sorts by its groups). */
export function setTableOrder(source, panelId, member, dir) {
  const { next, panel } = at(source, panelId, "id");
  if (!panel || panel.type !== "table") return { problem: "item" };
  if (!member) delete panel.order; else panel.order = { [member]: dir === "asc" ? "asc" : "desc" };
  return { source: next };
}

/** Switches a bar between one measure and stacked measures (`spare` is the second measure). A stack has no `split` (the file may not have both) and a measure has no stack. */
export function setBarKind(source, panelId, kind, spare) {
  const { next, panel } = at(source, panelId, "id");
  if (!panel || panel.type !== "bar") return { problem: "item" };
  const stacked = !!panel.stack;
  if (kind === (stacked ? "stack" : "member")) return { source: next };
  if (kind === "member") { panel.measure = panel.stack[0].member; panel.label = panel.stack[0].label || humanize(panel.measure); delete panel.stack; return { source: next }; }
  if (!spare) return { problem: "spare" };
  panel.stack = [{ member: panel.measure, label: panel.label || humanize(panel.measure) }, { member: spare, label: humanize(spare) }];
  delete panel.measure;
  delete panel.label;
  delete panel.split;
  return { source: next };
}

/** A pivot's columns: a plain field, or a time field grouped by a step (`{ member, granularity }`); "" makes it plain again. */
export function setPivotColumnStep(source, panelId, step) {
  const { next, panel } = at(source, panelId, "id");
  if (!panel || panel.type !== "pivot") return { problem: "item" };
  const member = typeof panel.columns === "string" ? panel.columns : panel.columns?.member;
  panel.columns = step ? { member, granularity: step } : member;
  return { source: next };
}
