// Unit tests for the renderer's data logic (dashboard/static/render/plan.js): no DOM, no Cube.
//   node --test dashboard/cube/tests/lib_render.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  appliesPeriod, followPeriod, formatPeriod, parsePeriod, PERIOD, pieQueries, rangeOf, withRange,
  activeFilters, byBucket, byCube, byDims, colorOf, evaluate, humanize, isSelected, markdown, optionMeasures, optionsOf, ownFilterIds, panelMeasures,
  pick, queriesPerCube, tableParts, term, totals, yearOf,
} from "../../static/render/plan.js";
import { stringsFor, translations } from "../../static/render/strings.js";

const spec = {
  time: { dimension: "dates.full_date" },
  filters: [
    { id: "fy", dimension: "dates.fiscal_year" },
    { id: "category", dimension: "products.category" },
    { id: "subcategory", dimension: "products.subcategory", parent: "products.category" },
  ],
  members: { "a.rev": { kind: "measure" }, "a.day": { kind: "dimension", type: "time" }, "b.rev": { kind: "measure" }, "p.name": { kind: "dimension" } },
  panels: [
    { id: "k", type: "kpi", measures: [{ sum: ["a.rev", "b.rev"], label: "Revenue" }] },
    { id: "t", type: "table", columns: [{ member: "p.name" }, { member: "a.rev" }], ignore_filters: ["fy"] },
  ],
};

test("humanize turns a member into a column label", () => {
  assert.equal(humanize("internet_sales.order_number"), "Order number");
  assert.equal(humanize("dates.fiscal_year"), "Fiscal year");
});

test("activeFilters keeps the chosen values and honours ignore_filters", () => {
  const values = { fy: "2021", category: "", subcategory: "Road Bikes" };
  assert.deepEqual(activeFilters(spec, values), [
    { member: "dates.fiscal_year", operator: "equals", values: ["2021"] },
    { member: "products.subcategory", operator: "equals", values: ["Road Bikes"] },
  ]);
  assert.deepEqual(activeFilters(spec, values, { ignore_filters: ["fy"] }).map((f) => f.member), ["products.subcategory"]);
  assert.deepEqual(activeFilters(spec, {}), []);
});

test("a sum term adds across cubes; a sum of nothing is null, not zero", () => {
  const t = term({ sum: ["a.rev", "b.rev"], label: "Revenue" });
  assert.equal(evaluate(t, (m) => ({ "a.rev": 10, "b.rev": 5 })[m]), 15);
  assert.equal(evaluate(t, (m) => ({ "a.rev": 10, "b.rev": null })[m]), 10);
  assert.equal(evaluate(t, () => null), null);
});

test("a ratio term divides the sums, and a zero or missing denominator is null", () => {
  const t = term({ ratio: { num: ["a.gp", "b.gp"], den: ["a.rev", "b.rev"] }, label: "Margin" });
  assert.deepEqual(t.members, ["a.gp", "b.gp", "a.rev", "b.rev"]);
  const v = { "a.gp": 20, "b.gp": 10, "a.rev": 60, "b.rev": 40 };
  assert.equal(evaluate(t, (m) => v[m]), 0.3);
  assert.equal(evaluate(t, (m) => (m.endsWith("rev") ? 0 : v[m])), null);
  assert.equal(evaluate(t, () => null), null);
});

test("a member term is the member's own value", () => {
  assert.equal(evaluate(term({ member: "a.rev" }), () => 7), 7);
  assert.equal(evaluate(term({ member: "a.rev" }), () => undefined), null);
});

test("queriesPerCube makes one query per cube and adds the base to each", () => {
  const qs = queriesPerCube(["a.rev", "b.rev", "a.units"], { filters: [{ member: "x" }] });
  assert.deepEqual(qs, [
    { cube: "a", query: { filters: [{ member: "x" }], measures: ["a.rev", "a.units"] } },
    { cube: "b", query: { filters: [{ member: "x" }], measures: ["b.rev"] } },
  ]);
  assert.deepEqual([...byCube(["a.x", "a.x", "b.y"])], [["a", ["a.x"]], ["b", ["b.y"]]]);
});

test("totals reads the single row of each cube's answer", () => {
  const t = totals([{ rows: [{ "a.rev": "12.5" }] }, { rows: [{ "b.rev": 3 }] }, { rows: [] }]);
  assert.equal(t.get("a.rev"), 12.5);
  assert.equal(t.get("b.rev"), 3);
});

test("byBucket merges per-cube rows on the time key, in time order", () => {
  const key = "dates.full_date.month";
  const out = byBucket([
    { rows: [{ [key]: "2020-08-01T00:00:00.000", "a.rev": "2" }, { [key]: "2020-07-01T00:00:00.000", "a.rev": "1" }] },
    { rows: [{ [key]: "2020-08-01T00:00:00.000", "b.rev": "20" }] },
  ], key);
  assert.deepEqual(out.map((b) => b.bucket), ["2020-07-01T00:00:00.000", "2020-08-01T00:00:00.000"]);
  assert.equal(out[1].values.get("a.rev"), 2);
  assert.equal(out[1].values.get("b.rev"), 20);
  assert.equal(out[0].values.has("b.rev"), false, "a cube with no row for a month has no value for it");
});

test("byDims joins per-cube rows on the dimensions they share", () => {
  const rows = byDims([
    { rows: [{ "p.name": "Helmet", "a.rev": "5" }, { "p.name": "Jersey", "a.rev": "3" }] },
    { rows: [{ "p.name": "Helmet", "b.rev": "7" }] },
  ], ["p.name"]);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].values.get("a.rev"), 5);
  assert.equal(rows[0].values.get("b.rev"), 7);
  assert.equal(rows[1].values.has("b.rev"), false);
  assert.deepEqual(rows[0].dims, { "p.name": "Helmet" });
});

test("optionsOf sorts numbers numerically, groups by parent, and narrows by the parent's value", () => {
  const fy = optionsOf([{ rows: [{ "dates.fiscal_year": 2021 }, { "dates.fiscal_year": 2020 }, { "dates.fiscal_year": 2021 }, { "dates.fiscal_year": 10 }] }], spec.filters[0]);
  assert.deepEqual(fy.map((o) => o.value), ["10", "2020", "2021"]);
  const rows = [{ rows: [
    { "products.category": "Bikes", "products.subcategory": "Road Bikes" }, { "products.category": "Clothing", "products.subcategory": "Jerseys" },
    { "products.category": "Bikes", "products.subcategory": "Mountain Bikes" },
  ] }];
  assert.deepEqual(optionsOf(rows, spec.filters[2]).map((o) => o.value), ["Mountain Bikes", "Road Bikes", "Jerseys"]);
  assert.deepEqual(optionsOf(rows, spec.filters[2], "Clothing").map((o) => o.value), ["Jerseys"]);
});

test("optionMeasures picks one measure per cube from the panels that apply the filter", () => {
  assert.deepEqual(optionMeasures(spec, spec.filters[1]).sort(), ["a.rev", "b.rev"]);
  const onlyTable = { ...spec, panels: [spec.panels[1]] };
  assert.deepEqual(optionMeasures(onlyTable, spec.filters[0]), [], "a filter no panel applies has nothing to query");
  assert.deepEqual(optionMeasures(onlyTable, spec.filters[1]), ["a.rev"]);
});

test("panelMeasures and tableParts split a table's members by kind", () => {
  assert.deepEqual(panelMeasures(spec.panels[0], spec.members), ["a.rev", "b.rev"]);
  assert.deepEqual(tableParts(spec.panels[1], spec.members), { measures: ["a.rev"], dimensions: ["p.name"] });
});

test("colorOf maps theme names to CSS variables, passes hex through and cycles a palette", () => {
  assert.equal(colorOf("internet", 0), "var(--internet)");
  assert.equal(colorOf("#112233", 0), "#112233");
  assert.equal(colorOf(undefined, 1), "var(--reseller)");
});

test("markdown escapes html first, then renders bold, code, links and lists", () => {
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
  assert.equal(markdown("<b>x</b>", esc), "<p>&#60;b&#62;x&#60;/b&#62;</p>");
  assert.equal(markdown("**hi** `c` [a](https://e.com/x)", esc), '<p><strong>hi</strong> <code>c</code> <a href="https://e.com/x" rel="noopener noreferrer" target="_blank">a</a></p>');
  assert.equal(markdown("- one\n- two", esc), "<ul><li>one</li><li>two</li></ul>");
  assert.equal(markdown("a\n\nb", esc), "<p>a</p><p>b</p>");
  assert.ok(!markdown("[x](javascript:alert(1))", esc).includes("<a "), "only http(s) links become links");
});

test("a panel leaves out the filters its own clicks set", () => {
  const panel = { on_click: { set_filter: ["category", "subcategory"] } };
  assert.deepEqual(ownFilterIds(panel), ["category", "subcategory"]);
  assert.deepEqual(ownFilterIds({ on_click: { set_filter: "fy" } }), ["fy"]);
  assert.deepEqual(ownFilterIds({}), []);
  const values = { fy: "2021", category: "Bikes", subcategory: "Road Bikes" };
  assert.deepEqual(activeFilters(spec, values, panel).map((f) => f.member), ["dates.fiscal_year"]);
  assert.deepEqual(activeFilters(spec, values, { ...panel, ignore_filters: ["fy"] }), []);
});

test("yearOf: a fiscal year is named after the year it ends in; a calendar year is the year", () => {
  assert.equal(yearOf("2020-07-01T00:00:00.000", 7, "fiscal_year"), 2021);
  assert.equal(yearOf("2020-06-01", 7, "fiscal_year"), 2020);
  assert.equal(yearOf("2021-01-01", 7, "fiscal_year"), 2021);
  assert.equal(yearOf("2020-12-01", 1, "fiscal_year"), 2020, "a fiscal year starting in January is the calendar year");
  assert.equal(yearOf("2020-12-01", 7, "calendar_year"), 2020);
});

test("pick sets the filters, and picking the same thing again restores what was there before", () => {
  const saved = {};
  const ids = ["category", "subcategory"];
  let cur = { category: "Bikes", subcategory: "" };
  let patch = pick(cur, ids, ["Clothing", "Jerseys"], saved);
  assert.deepEqual(patch, { category: "Clothing", subcategory: "Jerseys" });
  cur = { ...cur, ...patch };
  patch = pick(cur, ids, ["Clothing", "Caps"], saved);          // another tile: the original category is still remembered
  cur = { ...cur, ...patch };
  assert.deepEqual(cur, { category: "Clothing", subcategory: "Caps" });
  patch = pick(cur, ids, ["Clothing", "Caps"], saved);          // the same again: undo
  assert.deepEqual(patch, { category: "Bikes", subcategory: "" });
  assert.deepEqual(saved, {}, "nothing is left over");
});

test("picking when nothing was chosen before clears on the second click", () => {
  const saved = {};
  let cur = { fy: "" };
  cur = { ...cur, ...pick(cur, ["fy"], [2021], saved) };
  assert.equal(cur.fy, "2021");
  cur = { ...cur, ...pick(cur, ["fy"], [2021], saved) };
  assert.equal(cur.fy, "");
});

test("isSelected compares every named filter; `only` means the later ones are empty (a category heading)", () => {
  const cur = { category: "Bikes", subcategory: "" };
  assert.equal(isSelected(cur, ["category", "subcategory"], ["Bikes", ""]), true);
  assert.equal(isSelected(cur, ["category", "subcategory"], ["Bikes", "Road Bikes"]), false);
  assert.equal(isSelected(cur, ["category", "subcategory"], ["Bikes"], true), true);
  assert.equal(isSelected({ category: "Bikes", subcategory: "Road Bikes" }, ["category", "subcategory"], ["Bikes"], true), false);
  assert.equal(isSelected({ fy: 2021 }, ["fy"], ["2021"]), true, "numbers and strings compare as text");
});

test("a stacked bar and a ratio series count as reading all their measures", () => {
  assert.deepEqual(panelMeasures({ type: "bar", stack: [{ member: "a.rev" }, { member: "b.rev" }] }), ["a.rev", "b.rev"]);
  assert.deepEqual(panelMeasures({ type: "bar", measure: "a.rev" }), ["a.rev"]);
  assert.deepEqual(panelMeasures({ type: "timeseries", series: [{ ratio: { num: ["a.gp"], den: ["a.rev"] }, label: "m" }] }), ["a.gp", "a.rev"]);
});

test("every language has every word the page uses, and an unknown language falls back to English", () => {
  const keys = Object.keys(translations.en).sort();
  for (const [lang, words] of Object.entries(translations)) assert.deepEqual(Object.keys(words).sort(), keys, `${lang} is missing or has extra words`);
  assert.equal(stringsFor("tr-TR").all, "Tümü");
  assert.equal(stringsFor("de-DE").all, "All");
  assert.equal(stringsFor(undefined).reset, "Reset filters");
  assert.match(stringsFor("tr").notForRole("Pano", "rep"), /rolünüz \(rep\)/);
  assert.deepEqual(Object.keys(translations.tr.granularities), Object.keys(translations.en.granularities));
});

test("rangeOf gives the first and last day a bucket stands for", () => {
  assert.deepEqual(rangeOf("2021-01-01T00:00:00.000", "year"), ["2021-01-01", "2021-12-31"]);
  assert.deepEqual(rangeOf("2021-04-01T00:00:00.000", "quarter"), ["2021-04-01", "2021-06-30"]);
  assert.deepEqual(rangeOf("2020-10-01", "quarter"), ["2020-10-01", "2020-12-31"]);
  assert.deepEqual(rangeOf("2021-02-01T00:00:00.000", "month"), ["2021-02-01", "2021-02-28"]);
  assert.deepEqual(rangeOf("2020-02-01", "month"), ["2020-02-01", "2020-02-29"], "a leap year");
  assert.deepEqual(rangeOf("2021-12-01", "month"), ["2021-12-01", "2021-12-31"]);
  assert.deepEqual(rangeOf("2021-03-29T00:00:00.000", "week"), ["2021-03-29", "2021-04-04"]);
  assert.deepEqual(rangeOf("2021-03-05T00:00:00.000", "day"), ["2021-03-05", "2021-03-05"]);
});

test("a period parses only as two ISO dates and formats back", () => {
  assert.deepEqual(parsePeriod("2021-03-01..2021-03-31"), ["2021-03-01", "2021-03-31"]);
  for (const bad of ["", null, "2021-03-01", "2021-3-1..2021-3-31", "x..y", "2021-03-01..2021-03-31;drop"]) assert.equal(parsePeriod(bad), null, String(bad));
  assert.equal(formatPeriod("2021-01-01", "2021-12-31"), "2021-01-01..2021-12-31");
});

const salesSpec = {
  time: { dimension: "dates.full_date" }, filters: [],
  cubes: { internet_sales: { joins: ["dates", "products"] }, dates: { joins: [] }, inventory_health: { joins: ["products"] }, products: { joins: [] } },
  members: { "internet_sales.revenue": { kind: "measure" }, "inventory_health.on_hand": { kind: "dimension" }, "inventory_health.product_count": { kind: "measure" }, "products.name": { kind: "dimension" } },
};

test("the period narrows the panels that can reach the time dimension, and not the drill panel, text, an opt-out or an inventory panel", () => {
  const bar = { id: "b", type: "bar", measure: "internet_sales.revenue", by: "products.name" };
  assert.equal(appliesPeriod(salesSpec, bar), true);
  assert.equal(appliesPeriod(salesSpec, { ...bar, ignore_filters: ["period"] }), false, "opted out");
  assert.equal(appliesPeriod(salesSpec, { id: "t", type: "timeseries", series: [{ member: "internet_sales.revenue" }], drill: ["year", "month"] }), false, "the drill panel keeps its own range");
  assert.equal(appliesPeriod(salesSpec, { id: "x", type: "text", markdown: "hi" }), false);
  assert.equal(appliesPeriod(salesSpec, { id: "i", type: "bar", measure: "inventory_health.product_count", by: "products.name" }), false, "no join from inventory to dates");
  assert.equal(appliesPeriod({ ...salesSpec, cubes: undefined }, { id: "i", type: "bar", measure: "inventory_health.product_count", by: "products.name" }), true, "without join info a panel is assumed to follow");
});

test("withRange adds a date range to the time dimension, merging into an existing time entry", () => {
  const range = ["2021-03-01", "2021-03-31"];
  assert.deepEqual(withRange(salesSpec, { measures: ["m"] }, range).timeDimensions, [{ dimension: "dates.full_date", dateRange: range }]);
  const merged = withRange(salesSpec, { timeDimensions: [{ dimension: "dates.full_date", granularity: "month" }] }, range);
  assert.deepEqual(merged.timeDimensions, [{ dimension: "dates.full_date", granularity: "month", dateRange: range }]);
  assert.deepEqual(withRange(salesSpec, { timeDimensions: [{ dimension: "x.y", granularity: "day" }] }, range).timeDimensions.length, 2);
});

test("followPeriod narrows a following panel's queries only while a period is set", () => {
  const bar = { id: "b", type: "bar", measure: "internet_sales.revenue", by: "products.name" };
  const queries = [{ cube: "internet_sales", query: { measures: ["internet_sales.revenue"] } }];
  assert.deepEqual(followPeriod(salesSpec, bar, {}, queries), queries);
  const out = followPeriod(salesSpec, bar, { [PERIOD]: "2021-03-01..2021-03-31" }, queries);
  assert.deepEqual(out[0].query.timeDimensions, [{ dimension: "dates.full_date", dateRange: ["2021-03-01", "2021-03-31"] }]);
  assert.equal(queries[0].query.timeDimensions, undefined, "the input is not changed");
});

test("a pie reads its slices ranked, so the rest can be grouped", () => {
  const q = pieQueries(salesSpec, { id: "p", type: "pie", measure: "internet_sales.revenue", by: "products.name" }, {});
  assert.deepEqual(q[0].query, { dimensions: ["products.name"], filters: [], order: { "internet_sales.revenue": "desc" }, limit: 100, measures: ["internet_sales.revenue"] });
});
