// Key figures compared with the previous period: the change, the tile's line under the value, and the queries (dashboard/static/lib/compare.js,
// showChange in render/panels.js, kpiQueries in render/plan.js). No DOM, no Cube. The moving of dates and years is checked against the Python
// mirror in dashboards/tests/test_compare.py.
//   node --test dashboard/cube/tests/compare.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { addMonths, change, compareLabel, previousQueries, shiftQuery } from "../../static/lib/compare.js";
import { kpiQueries, panelQueries, term } from "../../static/render/plan.js";
import { showChange } from "../../static/render/panels.js";
import { createFormat } from "../../static/lib/format.js";
import { stringsFor } from "../../static/render/strings.js";

const YEAR = { fiscal: ["dates.fiscal_year"], calendar: ["dates.calendar_year"] };          // what a model's time.year_fields compiles to

test("months move with the day clamped, and the last day of a month stays the last day when asked", () => {
  assert.equal(addMonths("2024-03-31", -1), "2024-02-29");
  assert.equal(addMonths("2023-02-28", -12, true), "2022-02-28");
  assert.equal(addMonths("2025-02-28", -12, true), "2024-02-29");
  assert.equal(addMonths("2025-02-28", -12), "2024-02-28");
  assert.equal(addMonths("2021-01-15", -13), "2019-12-15");
});

test("the change is relative, or in points for a fraction, and absent when there is nothing to compare with", () => {
  assert.deepEqual(change(110, 100), { value: 0.1, dir: "up" });
  assert.equal(change(90, -100).dir, "up");                         // relative to |before|: from -100 to 90 is a rise
  assert.equal(change(0.40, 0.42, true).dir, "down");
  assert.ok(Math.abs(change(0.40, 0.42, true).value + 2) < 1e-9);
  assert.equal(change(100, 100).dir, "flat");
  assert.equal(change(0.4, 0.4004, true).dir, "flat");
  assert.deepEqual(change(5, 0), { dir: null });
  assert.deepEqual(change(5, null), { dir: null });
  assert.deepEqual(change(null, 5), { dir: null });
});

test("a fiscal-year select is named by its year; anything else by the kind", () => {
  const fy = shiftQuery({ filters: [{ member: "dates.fiscal_year", operator: "equals", values: ["2021"] }] }, "previous_year", YEAR);
  assert.deepEqual(compareLabel(fy.moved, "previous_year", YEAR), { year: "2020", fiscal: true });
  const cy = shiftQuery({ filters: [{ member: "dates.calendar_year", operator: "equals", values: ["2021"] }] }, "previous_period", YEAR);
  assert.deepEqual(compareLabel(cy.moved, "previous_period", YEAR), { year: "2020", fiscal: false });
  const two = shiftQuery({ filters: [{ member: "dates.fiscal_year", operator: "equals", values: ["2021", "2022"] }] }, "previous_year", YEAR);
  assert.deepEqual(compareLabel(two.moved, "previous_year", YEAR), { kind: "previous_year" });
  assert.equal(previousQueries([{ cube: "a", query: { filters: [] } }], "previous_year", YEAR), null);
});

const spec = {
  yearFields: YEAR,
  time: { dimension: "dates.full_date" }, filters: [{ id: "fy", dimension: "dates.fiscal_year" }, { id: "r", dimension: "t.region" }],
  members: { "a.rev": { kind: "measure" }, "b.rev": { kind: "measure" } }, panels: [],
};

test("kpiQueries gives the previous period's queries only with compare, and only when there is a period", () => {
  const def = { id: "k", type: "kpi", compare: "previous_year", measures: [{ sum: ["a.rev", "b.rev"], label: "Revenue" }] };
  const t = term(def.measures[0]);
  assert.equal(kpiQueries(spec, def, t, { r: "Canada" }).previous, null);
  const q = kpiQueries(spec, def, t, { fy: "2021", r: "Canada" });
  assert.deepEqual(q.previous.queries.map((x) => x.query.filters), [
    [{ member: "dates.fiscal_year", operator: "equals", values: ["2020"] }, { member: "t.region", operator: "equals", values: ["Canada"] }],
    [{ member: "dates.fiscal_year", operator: "equals", values: ["2020"] }, { member: "t.region", operator: "equals", values: ["Canada"] }],
  ]);
  const drilled = kpiQueries(spec, { ...def, compare: "previous_period" }, t, { _period: "2021-03-01..2021-03-31" });
  assert.deepEqual(drilled.previous.queries[0].query.timeDimensions, [{ dimension: "dates.full_date", dateRange: ["2021-02-01", "2021-02-28"] }]);
  assert.equal(kpiQueries(spec, { ...def, compare: undefined }, t, { fy: "2021" }).previous, null);
  assert.equal(panelQueries(spec, def, { fy: "2021" }).length, 4);        // two cubes now, two before
  assert.equal(panelQueries(spec, def, {}).length, 2);
});

const node = () => {
  const classes = new Set();
  return { title: "", innerHTML: "", classList: { add: (...c) => c.forEach((x) => classes.add(x)), has: (c) => classes.has(c) } };
};
const ctx = (lang = "en") => { const f = createFormat({ locale: lang === "tr" ? "tr-TR" : "en-US" }); return { t: stringsFor(lang), formatter: (k) => f[k], spec: { yearFields: YEAR } }; };
const fyMoved = { queries: [], moved: [{ member: "dates.fiscal_year", from: ["2021"], to: ["2020"] }] };

test("the tile's line: arrow, change, what it is compared with, and green or red by `better`", () => {
  const n = node();
  showChange(n, { now: 110, before: 100, previous: fyMoved, kind: "previous_year", points: false, better: "higher" }, ctx());
  assert.match(n.innerHTML, /aria-label="up">▲<\/span>10\.0% <span class="vs">vs FY2020<\/span>/);
  assert.ok(n.classList.has("good") && n.classList.has("cmp"));
  assert.match(n.title, /Fiscal year 2020/);

  const costs = node();
  showChange(costs, { now: 110, before: 100, previous: fyMoved, kind: "previous_year", points: false, better: "lower" }, ctx());
  assert.ok(costs.classList.has("bad"));

  const margin = node();
  showChange(margin, { now: 0.40, before: 0.412, previous: { queries: [], moved: [{ member: "dates.full_date", from: ["2021-03-01", "2021-03-31"], to: ["2021-02-01", "2021-02-28"] }] }, kind: "previous_period", points: true, better: "higher" }, ctx());
  assert.match(margin.innerHTML, /▼<\/span>1\.2 pts <span class="vs">vs previous period<\/span>/);
  assert.match(margin.title, /2021-02-01 – 2021-02-28/);
  assert.ok(margin.classList.has("bad"));
});

test("no period, no data before, no change: quiet words and no colour", () => {
  const none = node();
  showChange(none, { now: 5, before: null, previous: null, kind: "previous_year", points: false }, ctx());
  assert.match(none.innerHTML, /No period chosen to compare/);
  assert.ok(!none.classList.has("good") && !none.classList.has("bad"));
  const empty = node();
  showChange(empty, { now: 5, before: 0, previous: fyMoved, kind: "previous_year", points: false }, ctx());
  assert.match(empty.innerHTML, /No data to compare \(vs FY2020\)/);
  const flat = node();
  showChange(flat, { now: 5, before: 5, previous: fyMoved, kind: "previous_year", points: false }, ctx());
  assert.match(flat.innerHTML, /^no change <span class="vs">vs FY2020/);
  assert.ok(!flat.classList.has("good") && !flat.classList.has("bad"));
});

test("Turkish words", () => {
  const n = node();
  showChange(n, { now: 90, before: 100, previous: fyMoved, kind: "previous_year", points: false, better: "higher" }, ctx("tr"));
  assert.match(n.innerHTML, /aria-label="düşüş">▼<\/span>%10,0 <span class="vs">önceki: MY2020<\/span>/);
});

test("without year fields a year filter is not a year to move: nothing is compared by name", () => {
  const q = { filters: [{ member: "dates.fiscal_year", operator: "equals", values: ["2021"] }] };
  assert.equal(shiftQuery(q, "previous_year"), null);
  assert.equal(shiftQuery(q, "previous_year", { calendar: ["calendar.calendar_year"] }), null, "a name that this model does not list is not a year field");
  const own = shiftQuery({ filters: [{ member: "calendar.calendar_year", operator: "equals", values: ["2025"] }] }, "previous_year", { calendar: ["calendar.calendar_year"] });
  assert.deepEqual(own.query.filters[0].values, ["2024"]);
  assert.deepEqual(compareLabel(own.moved, "previous_year", { calendar: ["calendar.calendar_year"] }), { year: "2024", fiscal: false });
});
