// The queries behind a calculation's prior() and rolling() (see dashboards/dashspec/calculations.py). Pure, no DOM; dashboards/dashspec/timecalc.py is the Python mirror,
// and dashboards/tests/test_timecalc.py runs both on a table of cases.
//
// prior(m, unit): one more query per cube and unit, holding the measures read that way: the panel's query with its time constraints moved back by the unit (lib/compare.js
//   with a fixed shift). It is tagged `prior: unit`. No query when nothing can be moved (all time, an open range): a panel grouped by time then finds the earlier bucket among its
//   own rows; any other panel has no value.
// rolling(m, N): no extra query. The query's date range on its time axis starts N-1 buckets earlier, and a year select takes in the years the window reaches; `widened` lists
//   what changed, so the page can drop the rows it only asked for to fill the first windows.

import { priorKey, rollingKey, timeCalls } from "./calc.js";
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

// ---- putting the rows together (the page, after the queries above came back; render/plan.js `combine` calls this). Browser only: Python never sees rows.

const day = (b) => String(b).slice(0, 10);
const isDay = (v) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v);
/** Is `key` one of the values withTimeValues puts on a row (not a dimension)? */
export const isTimeCalcKey = (key) => key.startsWith("prior:") || key.startsWith("rolling:");

/** A time bucket ("2020-03-01T00:00:00.000") moved forward by `shift`, the time part kept; null when a day has no match (Jan 31 + 1 month: the 31st does not exist). */
export function bucketForward(bucket, shift) {
  const d = day(bucket);
  const to = Number.isInteger(shift.months) ? addMonths(d, shift.months) : addDays(d, shift.days);
  if (Number.isInteger(shift.months) && to.slice(8) !== d.slice(8)) return null;
  return `${to}${String(bucket).slice(10)}`;
}

/** A row's dimensions moved forward by `shift`: the time keys by the shift, year fields by its years. -> { row, moved } (moved: something changed), or null when a bucket has no match. */
function moveForward(r, shift, timeKeys, yearFields) {
  const out = { ...r };
  let moved = false;
  for (const k of timeKeys) {
    if (!isDay(r[k])) continue;
    const to = bucketForward(r[k], shift);
    if (to == null) return null;
    out[k] = to;
    moved = true;
  }
  if (Number.isInteger(shift.years)) {
    for (const k of Object.keys(r)) {
      if (!isYearField(k, yearFields) || r[k] == null || !INT.test(String(r[k]))) continue;
      out[k] = typeof r[k] === "number" ? r[k] + shift.years : String(Number(r[k]) + shift.years);
      moved = true;
    }
  }
  return { row: out, moved };
}

/** The first day of the earliest data a set of widened constraints asked for, or null (nothing widened). */
function widenedStart(widened, axis, gran, yearFields, fiscalStart) {
  const range = widened.find((w) => w.member === axis && isRange(w.to));
  if (range) return bucketStart(range.to[0], gran);
  const years = widened.filter((w) => isYearField(w.member, yearFields));
  if (!years.length) return null;
  const starts = years.map((w) => {
    const y = Math.min(...w.to.map(Number));
    const fiscal = (yearFields?.fiscal || []).includes(w.member) && fiscalStart > 1;
    return bucketStart(fiscal ? `${String(y - 1).padStart(4, "0")}-${String(fiscalStart).padStart(2, "0")}-01` : `${String(y).padStart(4, "0")}-01-01`, gran);
  });
  return starts.sort()[starts.length - 1];
}

/** The year a bucket falls in for a year field (fiscal: named after the year it ends in). */
const yearOfBucket = (b, member, yearFields, fiscalStart) => {
  const [y, m] = day(b).split("-").map(Number);
  return (yearFields?.fiscal || []).includes(member) && fiscalStart > 1 && m >= fiscalStart ? y + 1 : y;
};

/**
 * The merged rows of a calculation's parts with the values prior() and rolling() read put on each row (under priorKey / rollingKey), then the rows that were only asked
 * for to fill the first windows dropped. `parts` are the results with their tags ({ rows, query, prior?, widened? }); `keyOf(row)` tells rows apart by their dimensions
 * (combine's own key). Pure; mutates and returns `rows`.
 */
export function withTimeValues(rows, parts, { calls, yearFields, fiscalStart = 1, keyOf }) {
  const td = parts.map((p) => (p.query?.timeDimensions || []).find((t) => t.granularity)).find(Boolean);
  const gran = td?.granularity || null, axis = td?.dimension;
  const timeKeys = gran ? [`${axis}.${gran}`, axis] : [];
  const index = new Map(rows.map((r) => [keyOf(r), r]));
  const now = rows.slice();

  for (const unit of PRIOR_UNITS) {
    const ms = calls.prior[unit];
    if (!ms?.length) continue;
    const shift = priorShift(unit, gran);
    const own = parts.filter((p) => p.prior === unit);
    const source = own.length ? own.flatMap((p) => p.rows) : now;                // no moved query: the earlier rows are among the panel's own (a time axis, a year field)
    for (const r of source) {
      const m = moveForward(r, shift, timeKeys, yearFields);
      if (!m || (!own.length && !m.moved)) continue;                            // a row moved onto itself is not the one before
      const target = index.get(keyOf(m.row));
      if (!target) continue;
      for (const x of ms) if (x in r) target[priorKey(unit, x)] = r[x];
    }
  }

  const rolling = Object.entries(calls.rolling);
  const widened = parts.flatMap((p) => p.widened || []);
  if (gran && rolling.length) {
    const tk = timeKeys[0];
    const timed = now.filter((r) => isDay(r[tk]));
    const start = widenedStart(widened, axis, gran, yearFields, fiscalStart) ?? timed.map((r) => bucketStart(day(r[tk]), gran)).sort()[0];
    const groups = new Map();
    for (const r of timed) {
      const g = keyOf(Object.fromEntries(Object.entries(r).filter(([k]) => !timeKeys.includes(k))));
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(r);
    }
    for (const list of groups.values()) {
      list.sort((a, b) => (day(a[tk]) < day(b[tk]) ? -1 : 1));
      for (const r of list) {
        const b = day(r[tk]);
        for (const [member, ns] of rolling) {
          for (const n of ns) {
            const from = bucketsBack(b, n - 1, gran);
            let sum = null;
            if (start != null && from >= start) {
              for (const o of list) {
                const d = day(o[tk]);
                if (d < from || d > b) continue;
                const v = o[member] == null || o[member] === "" ? null : Number(o[member]);
                if (v != null && Number.isFinite(v)) sum = (sum ?? 0) + v;            // a bucket with no row adds nothing (0)
              }
            }
            r[rollingKey(n, member)] = sum;
          }
        }
      }
    }
  }

  if (!widened.length || !gran) return rows;
  const tk = timeKeys[0];
  const keep = (r) => {
    if (!isDay(r[tk])) return true;
    const b = day(r[tk]);
    return widened.every((w) => {
      if (w.member === axis && isRange(w.from)) return b >= bucketStart(w.from[0], gran);
      if (isYearField(w.member, yearFields)) return w.from.map(Number).includes(yearOfBucket(b, w.member, yearFields, fiscalStart));
      return true;
    });
  };
  return rows.filter(keep);
}
