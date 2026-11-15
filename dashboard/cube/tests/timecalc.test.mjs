// prior() and rolling() on the page: the queries a panel sends (lib/timecalc.js, via render/plan.js queriesPerCube and runAll) answered by a small fake Cube over daily
// data, and the values put together on each row. The members here are made up; the app knows no model.
import assert from "node:assert/strict";
import { test } from "node:test";
import { queriesPerCube, runAll } from "../../static/render/plan.js";
import { bucketForward } from "../../static/lib/timecalc.js";

const DAY = "t.day", FY = "t.fy", CAT = "p.cat";
const YEAR_FIELDS = { fiscal: [FY], calendar: [] };

// Daily facts from 2019-01-01 to 2021-12-31: x = the month number (1-12) + 100 * (year - 2019), on each day of the month's 1st (so a month's sum is that number); y = 1 on
// every 1st of the month, in two categories. `skip` leaves months out (a gap).
function facts(skip = []) {
  const out = [];
  for (let y = 2019; y <= 2021; y++) for (let m = 1; m <= 12; m++) {
    const d = `${y}-${String(m).padStart(2, "0")}-01`;
    if (skip.includes(d.slice(0, 7))) continue;
    out.push({ [DAY]: d, [CAT]: "a", "s.x": m + 100 * (y - 2019), "s.y": 1 }, { [CAT]: "b", [DAY]: d, "s.x": 1000, "s.y": 2 });
  }
  return out;
}
const fyOf = (d) => { const [y, m] = d.split("-").map(Number); return m >= 7 ? y + 1 : y; };
const bucketOf = (d, g) => {
  if (g === "month") return `${d.slice(0, 7)}-01T00:00:00.000`;
  if (g === "quarter") { const m = Number(d.slice(5, 7)); return `${d.slice(0, 4)}-${String(Math.floor((m - 1) / 3) * 3 + 1).padStart(2, "0")}-01T00:00:00.000`; }
  if (g === "year") return `${d.slice(0, 4)}-01-01T00:00:00.000`;
  return `${d}T00:00:00.000`;
};

/** A fake Cube: groups the facts by the query's dimensions and time axis, after its filters and date range; counts what it is asked. */
function fakeCube(rows = facts()) {
  const asked = [];
  const run = async (q) => {
    asked.push(q);
    const ok = (r) => (q.filters || []).every((f) => {
      const v = f.member === FY ? fyOf(r[DAY]) : r[f.member];
      if (f.operator === "equals") return f.values.map(String).includes(String(v));
      if (f.operator === "inDateRange") return r[DAY] >= f.values[0] && r[DAY] <= f.values[1];
      return true;
    }) && (q.timeDimensions || []).every((t) => !t.dateRange || (r[DAY] >= t.dateRange[0] && r[DAY] <= t.dateRange[1]));
    const groups = new Map();
    for (const r of rows.filter(ok)) {
      const dims = {};
      for (const d of q.dimensions || []) dims[d] = d === FY ? fyOf(r[DAY]) : r[d];
      for (const t of q.timeDimensions || []) if (t.granularity) dims[`${t.dimension}.${t.granularity}`] = bucketOf(r[DAY], t.granularity);
      const k = JSON.stringify(dims);
      if (!groups.has(k)) groups.set(k, { ...dims, ...Object.fromEntries(q.measures.map((m) => [m, 0])) });
      for (const m of q.measures) groups.get(k)[m] += r[m];
    }
    return [...groups.values()].map((g) => Object.fromEntries(Object.entries(g).map(([k, v]) => [k, q.measures.includes(k) ? String(v) : v])));
  };
  return { run, asked };
}

const calc = (ast, members) => ({ kind: "measure", type: "number", calc: { ast, members } });
const SPEC = {
  yearFields: YEAR_FIELDS, time: { dimension: DAY, fiscal_year_start: 7 },
  members: {
    "calc.yoy": calc({ op: "-", a: { op: "/", a: { m: "s.x" }, b: { prior: "s.x", by: "year" } }, b: { n: 1 } }, ["s.x"]),
    "calc.py": calc({ prior: "s.x", by: "year" }, ["s.x"]),
    "calc.pm": calc({ prior: "s.x", by: "month" }, ["s.x"]),
    "calc.r3": calc({ rolling: "s.x", over: 3 }, ["s.x"]),
    "calc.r12": calc({ rolling: "s.x", over: 12 }, ["s.x"]),
    "calc.avg3": calc({ op: "/", a: { rolling: "s.x", over: 3 }, b: { rolling: "s.y", over: 3 } }, ["s.x", "s.y"]),
  },
};
const monthly = (range) => ({ timeDimensions: [{ dimension: DAY, granularity: "month", ...(range ? { dateRange: range } : {}) }], filters: [{ member: CAT, operator: "equals", values: ["a"] }] });
const byMonth = (res, id) => Object.fromEntries(res[0].rows.map((r) => [r[`${DAY}.month`].slice(0, 7), r[id]]));

test("a bucket moves forward by months or days, and a day a month does not have has no match", () => {
  assert.equal(bucketForward("2020-03-01T00:00:00.000", { months: 12, years: 1 }), "2021-03-01T00:00:00.000");
  assert.equal(bucketForward("2020-02-29T00:00:00.000", { months: 12, years: 1 }), null);
  assert.equal(bucketForward("2021-01-31", { months: 1 }), null);
  assert.equal(bucketForward("2021-03-15T00:00:00.000", { days: 364 }), "2022-03-14T00:00:00.000");
});

test("year on year on a monthly chart: each month meets the same month a year before, from a moved query", async () => {
  const cube = fakeCube();
  const res = await runAll(cube.run, queriesPerCube(SPEC, ["calc.py", "calc.yoy"], monthly(["2021-03-01", "2021-05-31"])));
  assert.deepEqual(byMonth(res, "calc.py"), { "2021-03": 103, "2021-04": 104, "2021-05": 105 });
  assert.equal(byMonth(res, "calc.yoy")["2021-03"], 203 / 103 - 1);
  assert.deepEqual(cube.asked.map((q) => q.timeDimensions[0].dateRange), [["2021-03-01", "2021-05-31"], ["2020-03-01", "2020-05-31"]]);
});

test("month on month with no period: the month before is found among the chart's own rows, and the first month has none", async () => {
  const cube = fakeCube();
  const res = await runAll(cube.run, queriesPerCube(SPEC, ["calc.pm"], monthly()));
  const pm = byMonth(res, "calc.pm");
  assert.equal(cube.asked.length, 1, "nothing to move: no second query");
  assert.equal(pm["2019-01"], null);
  assert.equal(pm["2019-02"], 1);
  assert.equal(pm["2021-01"], 112, "across a year end");
});

test("a rolling sum asks for the buckets before the range, sums them and shows only the asked range", async () => {
  const cube = fakeCube();
  const res = await runAll(cube.run, queriesPerCube(SPEC, ["calc.r3", "calc.avg3"], monthly(["2021-03-01", "2021-05-31"])));
  assert.deepEqual(byMonth(res, "calc.r3"), { "2021-03": 201 + 202 + 203, "2021-04": 202 + 203 + 204, "2021-05": 203 + 204 + 205 });
  assert.equal(byMonth(res, "calc.avg3")["2021-03"], (201 + 202 + 203) / 3, "a ratio of two rolling sums");
  assert.deepEqual(cube.asked[0].timeDimensions[0].dateRange, ["2021-01-01", "2021-05-31"]);
});

test("rolling with no period: the first windows of the data are incomplete, so they have no value; a missing month adds nothing", async () => {
  const res = await runAll(fakeCube(facts(["2020-06"])).run, queriesPerCube(SPEC, ["calc.r3"], monthly()));
  const r3 = byMonth(res, "calc.r3");
  assert.equal(r3["2019-01"], null);
  assert.equal(r3["2019-02"], null);
  assert.equal(r3["2019-03"], 1 + 2 + 3);
  assert.equal(r3["2020-07"], 105 + 0 + 107, "June 2020 has no row: 0");
});

test("a fiscal-year select: rolling takes in the year before and shows only the chosen year; year on year moves the select", async () => {
  const cube = fakeCube();
  const base = { ...monthly(), filters: [...monthly().filters, { member: FY, operator: "equals", values: ["2021"] }] };
  const res = await runAll(cube.run, queriesPerCube(SPEC, ["calc.r12", "calc.py"], base));
  const r12 = byMonth(res, "calc.r12"), py = byMonth(res, "calc.py");
  assert.deepEqual(Object.keys(r12).sort()[0], "2020-07");
  assert.equal(Object.keys(r12).length, 12, "July 2020 to June 2021: FY2021 only");
  let want = 0;
  for (let m = 8; m <= 12; m++) want += m;                                 // Aug-Dec 2019
  for (let m = 1; m <= 7; m++) want += 100 + m;                            // Jan-Jul 2020
  assert.equal(r12["2020-07"], want);
  assert.equal(py["2020-07"], 7, "July 2019");
  assert.deepEqual(cube.asked.map((q) => q.filters.find((f) => f.member === FY).values), [["2020", "2021"], ["2020"]]);
});

test("a key figure and a bar compare by their own groupings", async () => {
  const kpi = await runAll(fakeCube().run, queriesPerCube(SPEC, ["calc.yoy"], { filters: [{ member: FY, operator: "equals", values: ["2021"] }] }));
  let now = 0, before = 0;
  for (let m = 1; m <= 12; m++) { now += m >= 7 ? 100 + m : 200 + m; before += m >= 7 ? m : 100 + m; }
  now += 12000; before += 12000;                                           // category b: 1000 a month
  assert.equal(kpi[0].rows.length, 1);
  assert.equal(kpi[0].rows[0]["calc.yoy"], now / before - 1);
  const bar = await runAll(fakeCube().run, queriesPerCube(SPEC, ["calc.py"], { dimensions: [CAT], filters: [{ member: FY, operator: "equals", values: ["2021"] }] }));
  assert.deepEqual(Object.fromEntries(bar[0].rows.map((r) => [r[CAT], r["calc.py"]])), { a: before - 12000, b: 12000 });
});

test("a bar by fiscal year with no period finds the year before among its own rows", async () => {
  const cube = fakeCube();
  const res = await runAll(cube.run, queriesPerCube(SPEC, ["calc.py"], { dimensions: [FY], filters: [{ member: CAT, operator: "equals", values: ["b"] }] }));
  assert.equal(cube.asked.length, 1);
  const py = Object.fromEntries(res[0].rows.map((r) => [r[FY], r["calc.py"]]));
  assert.equal(py[2019], null);
  assert.equal(py[2021], 12000);
  assert.equal(py[2020], 6000, "FY2019 has only January to June 2019");
});

test("prior() on a panel with no time to move and no time grouping has no value", async () => {
  const res = await runAll(fakeCube().run, queriesPerCube(SPEC, ["calc.py"], { dimensions: [CAT] }));
  assert.ok(res[0].rows.every((r) => r["calc.py"] == null));
});

test("the same query is sent once", async () => {
  const cube = fakeCube();
  const q = { cube: "s", query: { measures: ["s.x"], dimensions: [CAT] } };
  const res = await runAll(cube.run, [q, { ...q }]);
  assert.equal(cube.asked.length, 1);
  assert.equal(res.length, 2);
});

test("daily year on year: Feb 29 has no day a year later, and the day after it is not disturbed", async () => {
  const rows = [];
  for (const d of ["2020-02-28", "2020-02-29", "2020-03-01", "2021-02-28", "2021-03-01"]) rows.push({ [DAY]: d, [CAT]: "a", "s.x": Number(d.slice(8)) + (d < "2021" ? 0 : 100), "s.y": 1 });
  const res = await runAll(fakeCube(rows).run, queriesPerCube(SPEC, ["calc.py"], { timeDimensions: [{ dimension: DAY, granularity: "day", dateRange: ["2021-02-27", "2021-03-01"] }] }));
  const py = Object.fromEntries(res[0].rows.map((r) => [r[`${DAY}.day`].slice(0, 10), r["calc.py"]]));
  assert.deepEqual(py, { "2021-02-28": 28, "2021-03-01": 1 });
});
