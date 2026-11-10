// A key figure's comparison with the previous period (the kpi panel's `compare`): the tile's own queries with their time constraints moved back.
// Pure, no DOM. dashboards/dashspec/compare.py is the Python mirror; dashboards/tests/test_compare.py runs both on a table of cases and compares.
//
// Time constraints are date ranges (a timeDimensions `dateRange`, a filter's `inDateRange`) and year values (`equals` on a dimension named
// fiscal_year or calendar_year). Everything else in the query stays as it is. No time constraint, or one that cannot be moved (an open range,
// `notEquals` on a year, a year that is not a number, years that are not consecutive for previous_period): no comparison.

export const COMPARE_KINDS = ["previous_year", "previous_period"];
const OPEN = ["beforeDate", "afterDate", "beforeOrOnDate", "afterOrOnDate", "notInDateRange"];
const ISO = /^\d{4}-\d{2}-\d{2}$/;
const INT = /^-?\d+$/;

const pad = (n, w = 2) => String(n).padStart(w, "0");
const parts = (s) => s.split("-").map(Number);
const daysIn = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();          // m is 1-12
const isoOf = (y, m, d) => `${pad(y, 4)}-${pad(m)}-${pad(d)}`;
const toDay = (s) => { const [y, m, d] = parts(s); return Date.UTC(y, m - 1, d) / 86400000; };
const fromDay = (n) => { const t = new Date(n * 86400000); return isoOf(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate()); };

/** `s` moved by `n` months; the day is clamped to the month's length, and with `keepEnd` the last day of a month stays the last day. */
export function addMonths(s, n, keepEnd = false) {
  const [y, m, d] = parts(s);
  const k = y * 12 + (m - 1) + n, ty = Math.floor(k / 12), tm = (k % 12 + 12) % 12 + 1;
  const last = daysIn(ty, tm);
  return isoOf(ty, tm, keepEnd && d === daysIn(y, m) ? last : Math.min(d, last));
}

/** The range [from, to] moved back, or null when it cannot be. */
export function shiftRange(range, kind) {
  if (!Array.isArray(range) || range.length !== 2 || !range.every((s) => typeof s === "string" && ISO.test(s))) return null;
  const [a, b] = range;
  if (a > b) return null;
  if (kind === "previous_year") return [addMonths(a, -12), addMonths(b, -12, true)];
  const [ay, am, ad] = parts(a), [by, bm, bd] = parts(b);
  if (ad === 1 && bd === daysIn(by, bm)) {                    // whole months: back by that many months
    const n = (by * 12 + bm) - (ay * 12 + am) + 1;
    return [addMonths(a, -n), addMonths(b, -n, true)];
  }
  const len = toDay(b) - toDay(a) + 1;
  return [fromDay(toDay(a) - len), fromDay(toDay(a) - 1)];
}

/** Year values (strings) moved back, or null. */
export function shiftYears(values, kind) {
  if (!values?.length || !values.every((v) => INT.test(String(v)))) return null;
  const ys = values.map(Number);
  let by = 1;
  if (kind === "previous_period" && ys.length > 1) {
    const sorted = [...new Set(ys)].sort((x, y) => x - y);
    if (sorted.length !== ys.length || sorted.some((y, i) => i > 0 && y !== sorted[i - 1] + 1)) return null;
    by = sorted.length;
  }
  return ys.map((y) => String(y - by));
}

/** Is `member` one of the model's year fields? `yearFields` is { fiscal: [members], calendar: [members] } (the compiled spec's `yearFields`, from `time.year_fields` in model.config.yml); a model with none has no year to move. */
export const isYearField = (member, yearFields) => [...(yearFields?.fiscal || []), ...(yearFields?.calendar || [])].includes(member);

/**
 * One Cube query with its time constraints moved back: { query, moved } or null when it has none, or one cannot be moved.
 * `moved` lists what changed, each { member, from, to } (from/to: a [from, to] date range, or a list of years).
 */
export function shiftQuery(query, kind, yearFields) {
  if (!COMPARE_KINDS.includes(kind)) return null;
  const moved = [];
  let ok = true;
  const filters = (query.filters || []).map((f) => {
    if (OPEN.includes(f.operator)) { ok = false; return f; }
    if (f.operator === "inDateRange") {
      const to = shiftRange(f.values, kind);
      if (!to) { ok = false; return f; }
      moved.push({ member: f.member, from: [...f.values], to });
      return { ...f, values: to };
    }
    if (isYearField(f.member, yearFields) && !["set", "notSet"].includes(f.operator)) {
      const to = f.operator === "equals" ? shiftYears(f.values, kind) : null;
      if (!to) { ok = false; return f; }
      moved.push({ member: f.member, from: f.values.map(String), to });
      return { ...f, values: to };
    }
    return f;
  });
  const timeDimensions = (query.timeDimensions || []).map((t) => {
    if (t.dateRange == null) return t;
    const to = shiftRange(t.dateRange, kind);
    if (!to) { ok = false; return t; }
    moved.push({ member: t.dimension, from: [...t.dateRange], to });
    return { ...t, dateRange: to };
  });
  if (!ok || !moved.length) return null;
  const out = { ...query };
  if (query.filters) out.filters = filters;
  if (query.timeDimensions) out.timeDimensions = timeDimensions;
  return { query: out, moved };
}

/**
 * The comparison queries for a tile's `now` queries ([{ cube, query, post? }]): { queries, moved } or null. Each query is moved on its own;
 * `moved` is what changed, once per member and range (the per-cube queries share their filters).
 */
export function previousQueries(queries, kind, yearFields) {
  if (!kind || !queries?.length) return null;
  const out = [], moved = [], seen = new Set();
  for (const q of queries) {
    const s = shiftQuery(q.query, kind, yearFields);
    if (!s) return null;
    out.push({ ...q, query: s.query });
    for (const m of s.moved) {
      const key = JSON.stringify([m.member, m.from, m.to]);
      if (!seen.has(key)) { seen.add(key); moved.push(m); }
    }
  }
  return { queries: out, moved };
}

/**
 * What the tile names the comparison by: { year, fiscal } when the only thing moved is a single year value (`vs FY2020`, `vs 2020`), else { kind }.
 */
export function compareLabel(moved, kind, yearFields) {
  if (moved.length === 1 && isYearField(moved[0].member, yearFields) && moved[0].to.length === 1) {
    return { year: moved[0].to[0], fiscal: (yearFields.fiscal || []).includes(moved[0].member) };
  }
  return { kind };
}

/**
 * The change shown under a value: { text?, dir: "up" | "down" | "flat" | null } from the value now and before. `points`: the difference of two
 * fractions in percentage points (a margin), else the change relative to before. null `dir` (no text) when there is nothing to compare with.
 */
export function change(now, before, points = false) {
  if (now == null || before == null || !isFinite(now) || !isFinite(before)) return { dir: null };
  if (points) {
    const d = (now - before) * 100;
    return { value: d, dir: Math.abs(d) < 0.05 ? "flat" : d > 0 ? "up" : "down" };
  }
  if (before === 0) return { dir: null };
  const d = (now - before) / Math.abs(before);
  return { value: d, dir: Math.abs(d) < 0.0005 ? "flat" : d > 0 ? "up" : "down" };
}
