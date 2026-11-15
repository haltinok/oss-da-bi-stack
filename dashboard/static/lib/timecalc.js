// The queries behind a calculation's prior() and rolling() (see dashboards/dashspec/calculations.py). Pure, no DOM; dashboards/dashspec/timecalc.py is the Python mirror,
// and dashboards/tests/test_timecalc.py runs both on a table of cases.
//
// prior(m, unit): one more query per cube and unit, holding the measures read that way: the panel's query with its time constraints moved back by the unit (lib/compare.js
//   with a fixed shift). It is tagged `prior: unit`. No query when nothing can be moved (all time, an open range): a panel grouped by time then finds the earlier bucket among its
//   own rows; any other panel has no value.
// rolling(m, N): no extra query. The query's date range on its time axis starts N-1 buckets earlier, and a year select takes in the years the window reaches; `widened` lists
//   what changed, so the page can drop the rows it only asked for to fill the first windows.

import { timeCalls } from "./calc.js";
import { addDays, addMonths, isRange, isYearField, shiftQuery } from "./compare.js";

export const PRIOR_UNITS = ["year", "quarter", "month", "week", "day"];
export const ROLLING_GRANULARITIES = ["year", "quarter", "month", "week", "day"];

/** How far prior(·, unit) moves on a panel grouped by `granularity` (null: no time axis). A year on a weekly axis is 52 weeks, so a Monday meets a Monday. */
export function priorShift(unit, granularity) {
  if (unit === "year") return granularity === "week" ? { days: 364 } : { months: 12, years: 1 };
  return { quarter: { months: 3 }, month: { months: 1 }, week: { days: 7 }, day: { days: 1 } }[unit];
}

/** The first day of the bucket of `granularity` that the ISO date `s` falls in (weeks start on Monday, as Cube's do). */
export function bucketStart(s, granularity) {
  const [y, m] = s.split("-").map(Number);
  if (granularity === "week") { const dow = (new Date(`${s}T00:00:00Z`).getUTCDay() + 6) % 7; return addDays(s, -dow); }
  if (granularity === "month") return `${s.slice(0, 7)}-01`;
  if (granularity === "quarter") return `${String(y).padStart(4, "0")}-${String(Math.floor((m - 1) / 3) * 3 + 1).padStart(2, "0")}-01`;
  if (granularity === "year") return `${s.slice(0, 4)}-01-01`;
  return s;
}

/** The bucket start `k` buckets of `granularity` before the bucket start `s`. */
export function bucketsBack(s, k, granularity) {
  if (granularity === "week") return addDays(s, -7 * k);
  if (granularity === "month") return addMonths(s, -k);
  if (granularity === "quarter") return addMonths(s, -3 * k);
  if (granularity === "year") return addMonths(s, -12 * k);
  return addDays(s, -k);
}

/** How many years before a year value `k` buckets of `granularity` can reach (at least: a few rows too many are dropped, never too few). */
export function yearsBack(k, granularity) {
  if (granularity === "month") return Math.ceil(k / 12);
  if (granularity === "quarter") return Math.ceil(k / 4);
  if (granularity === "year") return k;
  return Math.floor((granularity === "week" ? 7 * k : k) / 365) + 1;
}

const INT = /^-?\d+$/;

/**
 * `query` asking for the n-1 buckets before its range as well: { query, widened } or null when nothing narrows its time axis (all time: the first windows of the data are
 * incomplete). `widened` lists each change as { member, from, to } (from/to: a date range, or a list of years).
 */
export function widenQuery(query, n, yearFields) {
  const axis = (query.timeDimensions || []).find((t) => t.granularity);
  if (!axis || !ROLLING_GRANULARITIES.includes(axis.granularity) || n < 2) return null;
  const gran = axis.granularity, k = n - 1, widened = [];
  const widen = (member, range) => {
    const to = [bucketsBack(bucketStart(range[0], gran), k, gran), range[1]];
    widened.push({ member, from: [...range], to });
    return to;
  };
  const timeDimensions = query.timeDimensions.map((t) => (t.dimension === axis.dimension && isRange(t.dateRange) ? { ...t, dateRange: widen(t.dimension, t.dateRange) } : t));
  const filters = (query.filters || []).map((f) => {
    if (f.operator === "inDateRange" && f.member === axis.dimension && isRange(f.values)) return { ...f, values: widen(f.member, f.values) };
    if (f.operator === "equals" && isYearField(f.member, yearFields) && f.values?.length && f.values.every((v) => INT.test(String(v)))) {
      const back = yearsBack(k, gran), ys = new Set();
      for (const v of f.values) for (let j = 0; j <= back; j++) ys.add(Number(v) - j);
      const to = [...ys].sort((a, b) => a - b).map(String);
      widened.push({ member: f.member, from: f.values.map(String), to });
      return { ...f, values: to };
    }
    return f;
  });
  if (!widened.length) return null;
  const out = { ...query, timeDimensions };
  if (query.filters) out.filters = filters;
  return { query: out, widened };
}

/**
 * A panel's queries ([{ cube, query, post? }]) with what its calculations' prior() and rolling() need: the widened query in place of the one it widens (tagged `widened`), and after
 * it the moved queries (tagged `prior`). Queries without such a calculation are left as they are.
 */
export function withTimeCalcs(queries, yearFields) {
  const out = [];
  for (const q of queries) {
    const calls = q.post?.calcs ? timeCalls(Object.values(q.post.calcs)) : null;
    if (!calls || (!Object.keys(calls.prior).length && !Object.keys(calls.rolling).length)) { out.push(q); continue; }
    const measures = q.query.measures || [];
    const gran = (q.query.timeDimensions || []).find((t) => t.granularity)?.granularity || null;
    const ns = measures.flatMap((m) => calls.rolling[m] || []);
    const w = ns.length && gran ? widenQuery(q.query, Math.max(...ns), yearFields) : null;
    out.push(w ? { ...q, query: w.query, widened: w.widened } : q);
    for (const unit of PRIOR_UNITS) {
      const read = measures.filter((m) => (calls.prior[unit] || []).includes(m));
      if (!read.length) continue;
      const s = shiftQuery({ ...q.query, measures: read }, priorShift(unit, gran), yearFields);
      if (s) out.push({ ...q, query: s.query, prior: unit });
    }
  }
  return out;
}
