// Aggregating the fields of a table (Power BI style): the table's groups are its dimension columns without an `aggregate`; every column with one is summarised over the rows
// of each group. The rows come from Cube one per row of the fields' cube (see plan.js tableQueries), so these are exact as long as no row is missing. Pure, no DOM.
export const AGGREGATES = ["sum", "max", "min", "avg", "count", "count_distinct", "first", "last"];
export const AGGREGATE_LIMIT = 20000;                 // rows fetched for a table's aggregates; dashspec/queries.py has the same number

const present = (v) => v !== null && v !== undefined && v !== "";
const numeric = (v) => (present(v) && Number.isFinite(Number(v)) ? Number(v) : null);

/**
 * One aggregate of a list of raw values (Cube's strings, numbers, nulls), in row order. Missing values are left out: a sum or an average of nothing is null, a count of nothing is 0.
 * max and min compare numbers when every value is one, else text; first and last are the first and last value there is.
 */
export function aggregateValues(kind, values) {
  const have = values.filter(present);
  switch (kind) {
    case "count": return have.length;
    case "count_distinct": return new Set(have.map(String)).size;
    case "first": return have.length ? have[0] : null;
    case "last": return have.length ? have[have.length - 1] : null;
    case "sum": case "avg": {
      const nums = have.map(numeric).filter((n) => n !== null);
      if (!nums.length) return null;
      const total = nums.reduce((a, b) => a + b, 0);
      return kind === "sum" ? total : total / nums.length;
    }
    case "max": case "min": {
      if (!have.length) return null;
      const nums = have.map(numeric);
      const pick = kind === "max" ? (a, b) => (a >= b ? a : b) : (a, b) => (a <= b ? a : b);
      if (nums.every((n) => n !== null)) return nums.reduce(pick);
      return have.map(String).reduce((a, b) => (kind === "max" ? (a.localeCompare(b) >= 0 ? a : b) : (a.localeCompare(b) <= 0 ? a : b)));
    }
    default: return null;
  }
}

/**
 * Groups the rows by `keyDims` (their values, joined the way plan.js byDims does) and aggregates each value column over a group's rows: Map(key -> { dims, aggs: Map(member -> value) }),
 * in the order the groups first appear. `valueCols` is [{ member, aggregate }]; `carry` names other columns to keep (the first row's value) for each group, such as a sort key.
 */
export function groupAggregates(rows, keyDims, valueCols, carry = []) {
  const groups = new Map();
  for (const r of rows) {
    const key = keyDims.map((d) => r[d]).join("\u0000");
    if (!groups.has(key)) groups.set(key, { key, dims: Object.fromEntries(keyDims.map((d) => [d, r[d]])), carried: Object.fromEntries(carry.map((c) => [c, r[c]])), rows: [] });
    groups.get(key).rows.push(r);
  }
  const out = new Map();
  for (const [key, g] of groups) out.set(key, { key, dims: g.dims, carried: g.carried, aggs: new Map(valueCols.map((c) => [c.member, aggregateValues(c.aggregate, g.rows.map((r) => r[c.member]))])) });
  return out;
}

/** The same over all the rows at once: the total row's cells. */
export const grandAggregates = (rows, valueCols) => new Map(valueCols.map((c) => [c.member, aggregateValues(c.aggregate, rows.map((r) => r[c.member]))]));
