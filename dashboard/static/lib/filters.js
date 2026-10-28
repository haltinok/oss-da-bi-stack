// Filter values and what they mean to Cube, with no DOM. A filter's value is one string, the same string the URL carries (`?region=in:Ontario,Quebec`):
//   select      the value itself, as it always was ("Bikes")
//   all others  "<op>:<arguments>", values encoded with encodeURIComponent so a comma or a colon in a value is safe
//     in / not          one or more values                  in:Bikes,Road%20Bikes   not:Clothing
//     contains / not_contains / starts / ends    text         contains:bike
//     eq / ne / gt / gte / lt / lte    one number             gte:100
//     between           two numbers or two dates              between:10..20   between:2024-01-01..2024-03-31
//     on / after / on_or_after / before / on_or_before   a date    after:2024-01-01
//     rel               a dynamic date by name                rel:last_30_days   rel:month_to_date
//     set / unset       the dimension has / has no value      unset:
// A dynamic date is kept by its name and turned into dates when the query is built (`env.today`), so a saved dashboard stays current.
// dashboards/dashspec/filters.py is the Python mirror (dashspec lint asks Cube for the same queries); dashboards/tests compares the two on a table of cases.

export const OPS = {
  select: ["equals"],
  multiselect: ["in", "not"],
  text: ["contains", "not_contains", "starts", "ends", "set", "unset"],
  number: ["eq", "ne", "gt", "gte", "lt", "lte", "between", "set", "unset"],
  date: ["between", "on", "after", "on_or_after", "before", "on_or_before", "rel", "set", "unset"],
};
const LIST_OPS = new Set(["in", "not"]), NO_ARG = new Set(["set", "unset"]);
const PAIR = /^(.*)\.\.(.*)$/;

/** "in:a,b" -> { op: "in", args: ["a", "b"] }; null when the text is not one of the forms. */
export function parseValue(text) {
  const m = /^([a-z_]+):(.*)$/.exec(String(text ?? ""));
  if (!m) return null;
  const [, op, rest] = m;
  const all = Object.values(OPS).flat();
  if (!all.includes(op)) return null;
  if (NO_ARG.has(op)) return rest === "" ? { op, args: [] } : null;
  if (op === "between") { const p = PAIR.exec(rest); return p ? { op, args: [dec(p[1]), dec(p[2])] } : null; }
  if (LIST_OPS.has(op)) return rest === "" ? null : { op, args: rest.split(",").map(dec) };
  return rest === "" ? null : { op, args: [dec(rest)] };
}
const dec = (s) => { try { return decodeURIComponent(s); } catch { return s; } };

/** The inverse of parseValue. */
export function formatValue({ op, args = [] }) {
  if (NO_ARG.has(op)) return `${op}:`;
  if (op === "between") return `between:${encodeURIComponent(args[0])}..${encodeURIComponent(args[1])}`;
  return `${op}:${args.map(encodeURIComponent).join(",")}`;
}

// ------------------------------------------------------------------------------------------------------------------ dates
const DAY = 86400000;
/** A calendar day as a UTC Date at midnight (all the arithmetic is done in UTC so no clock change can move a day). */
export const day = (y, m, d) => new Date(Date.UTC(y, m - 1, d));
export const iso = (dt) => dt.toISOString().slice(0, 10);
const add = (dt, n) => new Date(dt.getTime() + n * DAY);
const addMonths = (dt, n) => { const t = dt.getUTCFullYear() * 12 + dt.getUTCMonth() + n; return day(Math.floor(t / 12), (t % 12 + 12) % 12 + 1, 1); };   // the 1st of the month n months on (from a 1st)
const monthStart = (dt) => day(dt.getUTCFullYear(), dt.getUTCMonth() + 1, 1);
const monthEnd = (dt) => add(addMonths(monthStart(dt), 1), -1);
const weekStart = (dt, first) => add(dt, -((dt.getUTCDay() - first + 7) % 7));
const quarterStart = (dt) => day(dt.getUTCFullYear(), Math.floor(dt.getUTCMonth() / 3) * 3 + 1, 1);
const yearStart = (dt) => day(dt.getUTCFullYear(), 1, 1);
/** The fiscal year that contains `dt` starts on the 1st of month `f`; it is named for the year it ends in. */
const fiscalYearStart = (dt, f) => day(dt.getUTCMonth() + 1 >= f ? dt.getUTCFullYear() : dt.getUTCFullYear() - 1, f, 1);
const fiscalQuarterStart = (dt, f) => { const s = fiscalYearStart(dt, f), months = (dt.getUTCFullYear() - s.getUTCFullYear()) * 12 + dt.getUTCMonth() - s.getUTCMonth(); return addMonths(s, Math.floor(months / 3) * 3); };

/** The unit a span of time is counted in: where it starts for a date, and the date a shifted copy of it starts on. */
const UNITS = {
  days: { start: (dt) => dt, shift: (s, n) => add(s, n), end: (s) => s },
  weeks: { start: (dt, env) => weekStart(dt, env.weekStart), shift: (s, n) => add(s, 7 * n), end: (s) => add(s, 6) },
  months: { start: monthStart, shift: (s, n) => addMonths(s, n), end: monthEnd },
  quarters: { start: quarterStart, shift: (s, n) => addMonths(s, 3 * n), end: (s) => add(addMonths(s, 3), -1) },
  years: { start: yearStart, shift: (s, n) => addMonths(s, 12 * n), end: (s) => add(addMonths(s, 12), -1) },
  fiscal_quarters: { start: (dt, env) => fiscalQuarterStart(dt, env.fiscalStart), shift: (s, n) => addMonths(s, 3 * n), end: (s) => add(addMonths(s, 3), -1) },
  fiscal_years: { start: (dt, env) => fiscalYearStart(dt, env.fiscalStart), shift: (s, n) => addMonths(s, 12 * n), end: (s) => add(addMonths(s, 12), -1) },
};
const SINGULAR = { day: "days", week: "weeks", month: "months", quarter: "quarters", year: "years", fiscal_quarter: "fiscal_quarters", fiscal_year: "fiscal_years" };

/** The names a person can choose without a number. */
export const FIXED_PRESETS = [
  "today", "yesterday", "tomorrow",
  "this_week", "last_week", "next_week", "this_month", "last_month", "next_month", "this_quarter", "last_quarter", "next_quarter", "this_year", "last_year", "next_year",
  "week_to_date", "month_to_date", "quarter_to_date", "year_to_date",
  "this_fiscal_quarter", "last_fiscal_quarter", "this_fiscal_year", "last_fiscal_year", "fiscal_year_to_date", "all_time",
];
/** The names with a number in them: last_30_days (the 30 complete days before today), next_2_weeks, past_7_days (7 days ending today). */
export const COUNTED_UNITS = ["days", "weeks", "months", "quarters", "years"];
export const MAX_COUNT = 999;

/**
 * A dynamic date as { from, to } (ISO dates, both included) or { all: true } for all_time; null for a name that is not one.
 * env = { today: Date (a calendar day, see `day`), weekStart: 0 Sunday .. 6, fiscalStart: 1..12 }.
 *   this_X          the whole unit that holds today          last_X / next_X       the whole unit before / after
 *   last_N_units    the N complete units before the current one   next_N_units      the N after it   past_N_units   N units ending today (the current one counts, up to today)
 *   X_to_date       the start of the unit to today
 */
export function resolvePreset(name, env) {
  const today = env.today;
  const range = (from, to) => ({ from: iso(from), to: iso(to) });
  if (name === "all_time") return { all: true };
  if (name === "today") return range(today, today);
  if (name === "yesterday") return range(add(today, -1), add(today, -1));
  if (name === "tomorrow") return range(add(today, 1), add(today, 1));
  let m = /^(this|last|next)_((?:fiscal_)?(?:week|month|quarter|year))$/.exec(name);
  if (m) {
    const u = UNITS[SINGULAR[m[2]]], start = u.shift(u.start(today, env), { this: 0, last: -1, next: 1 }[m[1]]);
    return range(start, u.end(start));
  }
  m = /^((?:fiscal_)?(?:week|month|quarter|year))_to_date$/.exec(name);
  if (m) return range(UNITS[SINGULAR[m[1]]].start(today, env), today);
  m = /^(last|next|past)_(\d{1,3})_(days|weeks|months|quarters|years)$/.exec(name);
  if (m) {
    const n = Number(m[2]);
    if (n < 1 || n > MAX_COUNT) return null;
    const u = UNITS[m[3]], here = u.start(today, env);
    if (m[1] === "last") return range(u.shift(here, -n), u.end(u.shift(here, -1)));
    if (m[1] === "next") return range(u.shift(here, 1), u.end(u.shift(here, n)));
    return range(u.shift(here, -(n - 1)), today);
  }
  return null;
}

// ------------------------------------------------------------------------------------------------------------------ Cube filters
const NUMBER = /^-?\d+(\.\d+)?$/, DATE = /^\d{4}-\d{2}-\d{2}$/;
const flt = (member, operator, values) => (values === undefined ? { member, operator } : { member, operator, values });

/**
 * The Cube filters a filter's value stands for ([] when it narrows nothing, or the value is empty or not understood: a bad link shows everything, never a half-filter).
 * `filter` is the spec's { type?, dimension }; `env` as for resolvePreset.
 */
export function toCube(filter, text, env) {
  const member = filter.dimension, type = filter.type || "select";
  if (text === undefined || text === null || text === "") return [];
  if (type === "select") return [flt(member, "equals", [String(text)])];
  const v = parseValue(text);
  if (!v || !OPS[type]?.includes(v.op)) return [];
  const [a, b] = v.args;
  switch (v.op) {
    case "in": return [flt(member, "equals", v.args)];
    case "not": return [flt(member, "notEquals", v.args)];
    case "contains": return [flt(member, "contains", [a])];
    case "not_contains": return [flt(member, "notContains", [a])];
    case "starts": return [flt(member, "startsWith", [a])];
    case "ends": return [flt(member, "endsWith", [a])];
    case "set": return [flt(member, "set")];
    case "unset": return [flt(member, "notSet")];
    default:
  }
  if (type === "number") {
    if (!args_ok(v.args, NUMBER)) return [];
    const one = { eq: "equals", ne: "notEquals", gt: "gt", gte: "gte", lt: "lt", lte: "lte" }[v.op];
    if (one) return [flt(member, one, [String(Number(a))])];
    return Number(a) <= Number(b) ? [flt(member, "gte", [String(Number(a))]), flt(member, "lte", [String(Number(b))])] : [];
  }
  if (type === "date") {
    if (v.op === "rel") {
      const r = resolvePreset(a, env);
      return !r || r.all ? [] : [flt(member, "inDateRange", [r.from, r.to])];
    }
    if (!args_ok(v.args, DATE)) return [];
    if (v.op === "between") return a <= b ? [flt(member, "inDateRange", [a, b])] : [];
    const one = { on: "inDateRange", after: "afterDate", on_or_after: "afterOrOnDate", before: "beforeDate", on_or_before: "beforeOrOnDate" }[v.op];
    return [flt(member, one, v.op === "on" ? [a, a] : [a])];
  }
  return [];
}
const args_ok = (args, re) => args.every((x) => re.test(x));

/** The text a reader sees for a value (the Excel header, a chip): the label of the filter and what it is set to. */
export function describeValue(filter, text) {
  if (text === undefined || text === null || text === "") return "";
  if ((filter.type || "select") === "select") return String(text);
  const v = parseValue(text);
  if (!v) return String(text);
  const sym = { eq: "=", ne: "≠", gt: ">", gte: "≥", lt: "<", lte: "≤", contains: "contains", not_contains: "does not contain", starts: "starts with", ends: "ends with",
    on: "on", after: "after", on_or_after: "on or after", before: "before", on_or_before: "on or before", not: "not", in: "", set: "is set", unset: "is empty", rel: "", between: "" }[v.op];
  if (v.op === "between") return `${v.args[0]} – ${v.args[1]}`;
  if (v.op === "rel") return v.args[0].replace(/_/g, " ");
  if (NO_ARG.has(v.op)) return sym;
  return [sym, v.args.join(", ")].filter(Boolean).join(" ");
}

const SUNDAY_FIRST = new Set(["US", "CA", "MX", "BR", "IN", "JP"]);         // where a week starts on Sunday when the browser cannot say

/** The calendar a page's dynamic dates use: today (the reader's own date), the week's first day from the locale, and the fiscal year's first month from `time.fiscal_year_start`. */
export function defaultEnv(spec, now = new Date()) {
  const locale = spec.locale || "en-US";
  let first;
  try { const l = new Intl.Locale(locale); first = (l.getWeekInfo ? l.getWeekInfo() : l.weekInfo)?.firstDay; } catch { /* an odd locale: use the table below */ }
  const weekStart = first != null ? first % 7 : SUNDAY_FIRST.has(locale.split("-")[1]) ? 0 : 1;
  return { today: day(now.getFullYear(), now.getMonth() + 1, now.getDate()), weekStart, fiscalStart: spec.time?.fiscal_year_start || 1 };
}
