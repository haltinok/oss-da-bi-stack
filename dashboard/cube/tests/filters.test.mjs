// Filter values and dynamic dates (dashboard/static/lib/filters.js). The same cases run against the Python mirror in dashboards/tests/test_filters.py.
//   node --test dashboard/cube/tests/filters.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { day, describeValue, formatValue, parseValue, resolvePreset, toCube } from "../../static/lib/filters.js";

const env = (y, m, d, weekStart = 1, fiscalStart = 7) => ({ today: day(y, m, d), weekStart, fiscalStart });
const range = (name, e) => { const r = resolvePreset(name, e); return r && (r.all ? "all" : `${r.from}..${r.to}`); };

test("a value reads back as it was written, commas and colons inside a value included", () => {
  assert.deepEqual(parseValue("in:Smith%2C%20John,Lee"), { op: "in", args: ["Smith, John", "Lee"] });
  for (const t of ["in:a,b", "not:x%3Ay", "between:10..20", "gte:5", "unset:", "rel:last_7_days"]) assert.equal(formatValue(parseValue(t)), t);
  for (const t of ["Bikes", "", null, "bogus:1", "in:", "between:5", "set:x"]) assert.equal(parseValue(t), null, String(t));
});

test("dynamic dates at the awkward edges", () => {
  assert.equal(range("yesterday", env(2024, 3, 1)), "2024-02-29..2024-02-29", "a leap day");
  assert.equal(range("this_week", env(2024, 3, 15, 1)), "2024-03-11..2024-03-17", "a week that starts on Monday");
  assert.equal(range("this_week", env(2024, 3, 15, 0)), "2024-03-10..2024-03-16", "and on Sunday");
  assert.equal(range("last_month", env(2024, 1, 5)), "2023-12-01..2023-12-31", "across a year");
  assert.equal(range("next_month", env(2024, 12, 31)), "2025-01-01..2025-01-31");
  assert.equal(range("this_fiscal_year", env(2024, 3, 15)), "2023-07-01..2024-06-30", "a July fiscal year, named for the year it ends in");
  assert.equal(range("this_fiscal_year", env(2024, 3, 15, 1, 1)), "2024-01-01..2024-12-31", "a January fiscal year is the calendar year");
  assert.equal(range("last_fiscal_quarter", env(2024, 3, 15)), "2023-10-01..2023-12-31");
  assert.equal(range("last_30_days", env(2024, 3, 15)), "2024-02-14..2024-03-14", "the 30 complete days before today");
  assert.equal(range("past_7_days", env(2024, 3, 15)), "2024-03-09..2024-03-15", "7 days ending today");
  assert.equal(range("last_3_months", env(2024, 3, 15)), "2023-12-01..2024-02-29");
  assert.equal(range("all_time", env(2024, 3, 15)), "all");
  for (const bad of ["last_0_days", "last_1000_days", "last_5_hours", "bogus", "this_decade"]) assert.equal(resolvePreset(bad, env(2024, 3, 15)), null, bad);
});

test("values become Cube filters; a value that makes no sense narrows nothing", () => {
  const e = env(2024, 3, 15), f = (type) => ({ dimension: "a.dim", type });
  assert.deepEqual(toCube({ dimension: "a.dim" }, "Bikes", e), [{ member: "a.dim", operator: "equals", values: ["Bikes"] }]);
  assert.deepEqual(toCube(f("multiselect"), "not:A,B", e), [{ member: "a.dim", operator: "notEquals", values: ["A", "B"] }]);
  assert.deepEqual(toCube(f("number"), "between:10..20", e).map((x) => x.operator + x.values), ["gte10", "lte20"]);
  assert.deepEqual(toCube(f("number"), "between:20..10", e), []);
  assert.deepEqual(toCube(f("text"), "unset:", e), [{ member: "a.dim", operator: "notSet" }]);
  assert.deepEqual(toCube(f("date"), "rel:last_month", e), [{ member: "a.dim", operator: "inDateRange", values: ["2024-02-01", "2024-02-29"] }]);
  assert.deepEqual(toCube(f("date"), "rel:all_time", e), []);
  assert.deepEqual(toCube(f("number"), "after:2024-01-01", e), [], "an operator the type does not have");
  assert.deepEqual(toCube(f("multiselect"), "garbage", e), []);
});

test("a value in words, for the Excel header", () => {
  assert.equal(describeValue({}, "Bikes"), "Bikes");
  assert.equal(describeValue({ type: "number" }, "gte:100"), "≥ 100");
  assert.equal(describeValue({ type: "multiselect" }, "not:A,B"), "not A, B");
  assert.equal(describeValue({ type: "date" }, "rel:last_30_days"), "last 30 days");
  assert.equal(describeValue({ type: "date" }, "between:2024-01-01..2024-02-01"), "2024-01-01 – 2024-02-01");
  assert.equal(describeValue({ type: "text" }, "unset:"), "is empty");
});
