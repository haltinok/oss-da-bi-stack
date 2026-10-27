// Unit tests for the renderer's data logic (dashboard/static/render/plan.js): no DOM, no Cube.
//   node --test dashboard/cube/tests/lib_render.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  appliesPeriod, followPeriod, formatPeriod, parsePeriod, PERIOD, pieQueries, rangeOf, withRange,
  activeFilters, byBucket, byCube, byDims, colorOf, evaluate, humanize, isSelected, markdown, optionMeasures, optionsOf, ownFilterIds, panelMeasures,
  pick, nextSort, tableOrder, pivotQueries, pivotModel, pivotQueryList, PIVOT_LIMIT, queriesPerCube, tableParts, tableTotalQueries, panelQueries, term, totals, yearOf,
} from "../../static/render/plan.js";
import { tableHtml, pinTotals } from "../../static/lib/table.js";
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

test("a pie that sums two cubes asks each for its slices, ranked by its own measure", () => {
  const spec = { ...salesSpec, cubes: undefined, members: { "internet_sales.revenue": { kind: "measure" }, "reseller_sales.revenue": { kind: "measure" }, "products.name": { kind: "dimension" } } };
  const q = pieQueries(spec, { id: "p", type: "pie", sum: ["internet_sales.revenue", "reseller_sales.revenue"], label: "Gelir", by: "products.name" }, {});
  assert.deepEqual(q.map((x) => x.cube), ["internet_sales", "reseller_sales"]);
  assert.deepEqual(q.map((x) => x.query.order), [{ "internet_sales.revenue": "desc" }, { "reseller_sales.revenue": "desc" }]);
  assert.ok(q.every((x) => x.query.limit === 100 && x.query.dimensions[0] === "products.name"));
});

test("tableTotalQueries asks for the measures of the whole set: no grouping, no limit, same filters and period", () => {
  const withTotals = { ...spec.panels[1], totals: "footer", limit: 5 };
  assert.deepEqual(tableTotalQueries(spec, spec.panels[1], {}), [], "no totals asked, none queried");
  const q = tableTotalQueries(spec, withTotals, { category: "Bikes", fy: "2021", _period: "2021-03-01..2021-03-31" });
  assert.equal(q.length, 1);
  assert.deepEqual(q[0].query.measures, ["a.rev"]);
  for (const k of ["dimensions", "limit", "order"]) assert.ok(!(k in q[0].query), k);
  assert.deepEqual(q[0].query.filters, [{ member: "products.category", operator: "equals", values: ["Bikes"] }], "the table ignores 'fy' (ignore_filters)");
  assert.deepEqual(q[0].query.timeDimensions[0].dateRange, ["2021-03-01", "2021-03-31"]);
  assert.deepEqual(panelQueries(spec, withTotals, {}).at(-1), tableTotalQueries(spec, withTotals, {})[0], "lint and the page see the total query");
});

test("tableTotalQueries sends one query per measure cube", () => {
  const two = { id: "m", type: "table", totals: "header", columns: [{ member: "p.name" }, { member: "a.rev" }, { member: "b.rev" }] };
  assert.deepEqual(tableTotalQueries(spec, two, {}).map((q) => q.query.measures), [["a.rev"], ["b.rev"]]);
  assert.deepEqual(tableTotalQueries(spec, { ...two, columns: [{ member: "p.name" }] }, {}), [], "no measure column, no total");
});

const cols = [
  { label: "Name", type: "text", get: (r) => r.n, fmt: (v) => v },
  { label: "Revenue", type: "money", get: (r) => r.v, fmt: (v) => `$${v}` },
  { label: "Margin", type: "pct", get: (r) => r.m, fmt: (v) => `${v * 100}%` },
];
const rows = [{ n: "<b>x</b>", v: 1, m: 0.1 }];

test("tableHtml puts a bold total row in the footer or under the titles, dimension cells empty and a missing value as a dash", () => {
  const cells = [undefined, 10, null];
  const foot = tableHtml({ columns: cols, rows, totals: { position: "footer", cells } });
  assert.match(foot, /<tfoot><tr class="tot"><td class=""><\/td><td class="n">\$10<\/td><td class="n">–<\/td><\/tr><\/tfoot>/);
  assert.ok(foot.indexOf("<tbody>") < foot.indexOf("<tfoot>"));
  const head = tableHtml({ columns: cols, rows, totals: { position: "header", cells } });
  assert.ok(head.indexOf('class="tot"') < head.indexOf("<tbody>") && head.indexOf('class="tot"') > head.indexOf("<th"));
  assert.ok(!head.includes("<tfoot>"));
  assert.ok(!tableHtml({ columns: cols, rows }).includes("tot"), "no totals, no total row");
  assert.ok(tableHtml({ columns: cols, rows }).includes("&#60;b&#62;x&#60;/b&#62;"), "cells are escaped");
});

test("pinTotals hands the height of the title row to the stylesheet, and ignores a table without one", () => {
  const set = [];
  const wrap = { querySelector: () => ({ getBoundingClientRect: () => ({ height: 31 }) }), style: { setProperty: (k, v) => set.push([k, v]) } };
  pinTotals({ querySelector: () => wrap });
  assert.deepEqual(set, [["--head-h", "31px"]]);
  pinTotals({ querySelector: () => null });
});

test("tableOrder: the author's order, else all dimensions ascending; a header click puts its column first", () => {
  const dims = ["p.name", "a.day"];
  assert.deepEqual(tableOrder({}, dims, undefined), { "p.name": "asc", "a.day": "asc" });
  assert.deepEqual(tableOrder({ order: { "a.rev": "desc" } }, dims, undefined), { "a.rev": "desc" });
  assert.deepEqual(tableOrder({ order: { "a.rev": "desc" } }, dims, null), { "p.name": "asc", "a.day": "asc" }, "cleared: dimensions, left to right");
  const q = tableOrder({}, dims, { member: "a.day", dir: "desc" });
  assert.deepEqual(Object.entries(q), [["a.day", "desc"], ["p.name", "asc"]], "the clicked column first, then the other dimensions");
  assert.deepEqual(Object.entries(tableOrder({}, dims, { member: "a.rev", dir: "asc" })), [["a.rev", "asc"], ["p.name", "asc"], ["a.day", "asc"]]);
  assert.deepEqual(tableOrder({}, [], null), {}, "no dimensions, nothing to order by");
});

test("nextSort cycles measures desc, asc, none and dimensions asc, desc, none; another column starts over", () => {
  let s;
  s = nextSort(s, "a.rev", true); assert.deepEqual(s, { member: "a.rev", dir: "desc" });
  s = nextSort(s, "a.rev", true); assert.deepEqual(s, { member: "a.rev", dir: "asc" });
  assert.equal(nextSort(s, "a.rev", true), null);
  s = nextSort(undefined, "p.name", false); assert.deepEqual(s, { member: "p.name", dir: "asc" });
  s = nextSort(s, "p.name", false); assert.deepEqual(s, { member: "p.name", dir: "desc" });
  assert.equal(nextSort(s, "p.name", false), null);
  assert.deepEqual(nextSort({ member: "p.name", dir: "desc" }, "a.rev", true), { member: "a.rev", dir: "desc" });
  assert.deepEqual(nextSort(null, "a.rev", true), { member: "a.rev", dir: "desc" }, "after 'none' the next click starts again");
});

test("tableHtml makes titles with a sortKey clickable and marks the sorted one", () => {
  const sortable = cols.map((c, i) => ({ ...c, sortKey: `m.c${i}` }));
  const html = tableHtml({ columns: sortable, rows, sort: { member: "m.c1", dir: "desc" } });
  assert.match(html, /<th class="n sortable" data-sort="m.c1" tabindex="0" aria-sort="descending">Revenue<i class="arr" aria-hidden="true">↓<\/i><\/th>/);
  assert.match(html, /data-sort="m.c0" tabindex="0" aria-sort="none">Name<i class="arr" aria-hidden="true"><\/i>/);
  assert.ok(!tableHtml({ columns: cols, rows }).includes("sortable"), "columns without a sortKey stay plain");
});

// ---- pivot
const pv = (over = {}) => ({ id: "x", type: "pivot", rows: ["p.name"], columns: "d.year", measures: [{ member: "a.rev" }], ...over });

test("pivotQueries wave 1 asks only the first measure's cube for the axes; wave 2 asks every measure's cube", () => {
  const def = pv({ measures: [{ member: "a.rev" }, { member: "b.rev" }] });
  const { axes, values } = pivotQueries(spec, def, { category: "Bikes" });
  assert.deepEqual(axes.rows.map((q) => q.cube), ["a"]);
  assert.deepEqual(axes.rows[0].query, { measures: ["a.rev"], filters: [{ member: "products.category", operator: "equals", values: ["Bikes"] }], dimensions: ["p.name"], order: { "a.rev": "desc", "p.name": "asc" }, limit: PIVOT_LIMIT.rows + 1 });
  assert.deepEqual(axes.cols[0].query.order, { "d.year": "asc" });
  assert.equal(axes.cols[0].query.limit, PIVOT_LIMIT.columns + 1);
  assert.deepEqual(axes.groups, [], "one row dimension has no groups");
  assert.deepEqual(values.cells.map((q) => [q.cube, q.query.measures]), [["a", ["a.rev"]], ["b", ["b.rev"]]]);
  assert.deepEqual(values.cells[0].query.dimensions, ["p.name", "d.year"]);
  assert.deepEqual(values.grand.map((q) => q.query.dimensions), [undefined, undefined], "the grand total has no grouping");
  assert.deepEqual(values.rowTotals[0].query.dimensions, ["p.name"]);
  assert.deepEqual(values.colTotals[0].query.dimensions, ["d.year"]);
  assert.deepEqual(values.groupCells.concat(values.groupTotals), []);
});

test("pivotQueries: the order, the limits and the totals mode", () => {
  assert.deepEqual(pivotQueries(spec, pv({ order: { by: "label" } }), {}).axes.rows[0].query.order, { "p.name": "asc" });
  assert.deepEqual(pivotQueries(spec, pv({ order: { by: "label", dir: "desc" } }), {}).axes.rows[0].query.order, { "p.name": "desc" });
  assert.deepEqual(pivotQueries(spec, pv({ order: { dir: "asc" } }), {}).axes.rows[0].query.order, { "a.rev": "asc", "p.name": "asc" });
  const lim = pivotQueries(spec, pv({ limit: { rows: 5, columns: 3 } }), {}).axes;
  assert.deepEqual([lim.rows[0].query.limit, lim.cols[0].query.limit], [6, 4]);
  const none = pivotQueries(spec, pv({ totals: "none" }), {}).values;
  assert.deepEqual([none.rowTotals, none.colTotals, none.grand, none.groupCells].map((q) => q.length), [0, 0, 0, 0]);
  const rowsOnly = pivotQueries(spec, pv({ totals: "rows" }), {}).values;
  assert.deepEqual([rowsOnly.rowTotals.length, rowsOnly.colTotals.length, rowsOnly.grand.length], [1, 0, 1]);
  const colsOnly = pivotQueries(spec, pv({ totals: "columns" }), {}).values;
  assert.deepEqual([colsOnly.rowTotals.length, colsOnly.colTotals.length, colsOnly.grand.length], [0, 1, 1]);
});

test("pivotQueries with two row dimensions adds the group queries; with keys it narrows wave 2 but never the grand or the column totals' rows", () => {
  const def = pv({ rows: ["p.cat", "p.name"] });
  const { axes, values } = pivotQueries(spec, def, {});
  assert.deepEqual(axes.groups[0].query.dimensions, ["p.cat"]);
  assert.deepEqual(axes.groups[0].query.order, { "a.rev": "desc", "p.cat": "asc" });
  assert.deepEqual(values.groupCells[0].query.dimensions, ["p.cat", "d.year"]);
  assert.deepEqual(values.groupTotals[0].query.dimensions, ["p.cat"]);
  const keys = { rows: [["Bikes", "Road"], ["Bikes", "Mountain"], ["Clothing", "Socks"]], cols: ["2020", "2021"] };
  const narrowed = pivotQueries(spec, def, {}, keys).values;
  const f = (q) => q.query.filters.map((x) => [x.member, x.values]);
  assert.deepEqual(f(narrowed.cells[0]), [["p.cat", ["Bikes", "Clothing"]], ["p.name", ["Road", "Mountain", "Socks"]], ["d.year", ["2020", "2021"]]]);
  assert.deepEqual(f(narrowed.rowTotals[0]), [["p.cat", ["Bikes", "Clothing"]], ["p.name", ["Road", "Mountain", "Socks"]]], "a row's total covers all columns");
  assert.deepEqual(f(narrowed.colTotals[0]), [["d.year", ["2020", "2021"]]], "a column's total covers all rows, shown or not");
  assert.deepEqual(f(narrowed.grand[0]), [], "the grand total is the whole set");
  assert.deepEqual(f(narrowed.groupCells[0]), [["p.cat", ["Bikes", "Clothing"]], ["d.year", ["2020", "2021"]]]);
});

test("pivotQueries follows the page's period like any panel, and panelQueries lists every query once, axes first", () => {
  const def = pv();
  const all = pivotQueries(spec, def, { _period: "2021-03-01..2021-03-31" });
  for (const q of [...all.axes.rows, ...all.values.cells, ...all.values.grand]) assert.deepEqual(q.query.timeDimensions[0].dateRange, ["2021-03-01", "2021-03-31"]);
  const flat = pivotQueryList(spec, def, {});
  assert.equal(flat.length, 1 + 1 + 1 + 1 + 1 + 1, "rows, cols, cells, rowTotals, colTotals, grand");
  assert.deepEqual(panelQueries(spec, def, {}), flat);
  assert.deepEqual(panelMeasures(def), ["a.rev"]);
});

// results as runAll returns them
const R = (cube, rows) => ({ cube, rows });

test("pivotModel: cells, totals from the totals queries, empty cells stay empty, rows in the order Cube gave", () => {
  const def = pv({ measures: [{ member: "a.rev" }, { member: "a.pct" }] });
  const axes = { rows: [R("a", [{ "p.name": "Bikes" }, { "p.name": "Socks" }])], groups: [], cols: [R("a", [{ "d.year": 2020 }, { "d.year": 2021 }])] };
  const vals = {
    cells: [R("a", [
      { "p.name": "Bikes", "d.year": 2020, "a.rev": "10", "a.pct": "0.5" }, { "p.name": "Bikes", "d.year": 2021, "a.rev": "30", "a.pct": "0.25" },
      { "p.name": "Socks", "d.year": 2021, "a.rev": "5", "a.pct": "0.2" },
    ])],
    rowTotals: [R("a", [{ "p.name": "Bikes", "a.rev": "40", "a.pct": "0.3" }, { "p.name": "Socks", "a.rev": "5", "a.pct": "0.2" }])],
    colTotals: [R("a", [{ "d.year": 2020, "a.rev": "10", "a.pct": "0.5" }, { "d.year": 2021, "a.rev": "35", "a.pct": "0.24" }])],
    grand: [R("a", [{ "a.rev": "45", "a.pct": "0.28" }])], groupCells: [], groupTotals: [],
  };
  const m = pivotModel(def, axes, vals);
  assert.deepEqual(m.cols, ["2020", "2021"]);
  assert.deepEqual(m.rows.map((r) => r.keys), [["Bikes"], ["Socks"]]);
  assert.equal(m.rows[0].cells[1].get("a.rev"), 30);
  assert.equal(m.rows[1].cells[0], undefined, "no row from Cube: an empty cell, not a zero");
  assert.equal(m.rows[0].total.get("a.pct"), 0.3, "the row's ratio is Cube's ratio of the row, not the mean of its cells");
  assert.equal(m.colTotals[1].get("a.pct"), 0.24);
  assert.equal(m.grand.get("a.rev"), 45);
  assert.equal(m.groups, null);
  assert.deepEqual(m.hidden, { rows: false, cols: false });
  assert.equal(m.truncated, false);
});

test("pivotModel: limits show the first rows and columns and say that more exist; totals stay the whole set's", () => {
  const def = pv({ limit: { rows: 2, columns: 2 } });
  const axes = {
    rows: [R("a", [{ "p.name": "A" }, { "p.name": "B" }, { "p.name": "C" }])],                      // limit + 1 rows came back
    cols: [R("a", [{ "d.year": 1 }, { "d.year": 2 }, { "d.year": 3 }])],
  };
  const vals = { cells: [R("a", [{ "p.name": "A", "d.year": 1, "a.rev": "1" }, { "p.name": "C", "d.year": 3, "a.rev": "9" }])], colTotals: [R("a", [{ "d.year": 1, "a.rev": "100" }])], grand: [R("a", [{ "a.rev": "1000" }])] };
  const m = pivotModel(def, axes, vals);
  assert.deepEqual([m.rows.length, m.cols.length], [2, 2]);
  assert.deepEqual(m.hidden, { rows: true, cols: true });
  assert.equal(m.colTotals[0].get("a.rev"), 100);
  assert.equal(m.grand.get("a.rev"), 1000, "not the sum of what is shown");
  assert.equal(m.rows.some((r) => r.keys.includes("C")), false);
});

test("pivotModel: two row dimensions give groups with their own cells and total, in the order of the groups and then of the rows", () => {
  const def = pv({ rows: ["p.cat", "p.name"] });
  const axes = {
    rows: [R("a", [{ "p.cat": "Clothing", "p.name": "Socks" }, { "p.cat": "Bikes", "p.name": "Road" }, { "p.cat": "Clothing", "p.name": "Hats" }, { "p.cat": "Bikes", "p.name": "Mtb" }])],
    groups: [R("a", [{ "p.cat": "Bikes" }, { "p.cat": "Clothing" }, { "p.cat": "Parts" }])], cols: [R("a", [{ "d.year": 2021 }])],
  };
  const vals = {
    cells: [R("a", [{ "p.cat": "Bikes", "p.name": "Road", "d.year": 2021, "a.rev": "7" }])],
    groupCells: [R("a", [{ "p.cat": "Bikes", "d.year": 2021, "a.rev": "20" }, { "p.cat": "Clothing", "d.year": 2021, "a.rev": "4" }])],
    groupTotals: [R("a", [{ "p.cat": "Bikes", "a.rev": "22" }])],
  };
  const m = pivotModel(def, axes, vals);
  assert.deepEqual(m.groups.map((g) => g.key), ["Bikes", "Clothing"], "groups in Cube's order, only those with a row shown");
  assert.deepEqual(m.groups[0].rows.map((r) => r.keys[1]), ["Road", "Mtb"], "rows keep their own order inside the group");
  assert.deepEqual(m.rows.map((r) => r.keys[1]), ["Road", "Mtb", "Socks", "Hats"]);
  assert.equal(m.groups[0].cells[0].get("a.rev"), 20);
  assert.equal(m.groups[0].total.get("a.rev"), 22);
  assert.equal(m.groups[1].total, undefined);
});

test("pivotModel merges several measure cubes on the row and column, and flags a result that reached Cube's ceiling", () => {
  const def = pv({ measures: [{ member: "a.rev" }, { member: "b.rev" }] });
  const axes = { rows: [R("a", [{ "p.name": "A" }])], cols: [R("a", [{ "d.year": 1 }])] };
  const vals = { cells: [R("a", [{ "p.name": "A", "d.year": 1, "a.rev": "2" }]), R("b", [{ "p.name": "A", "d.year": 1, "b.rev": "3" }])] };
  const m = pivotModel(def, axes, vals);
  assert.deepEqual([...m.rows[0].cells[0]], [["a.rev", 2], ["b.rev", 3]]);
  assert.equal(pivotModel(def, axes, { cells: [R("a", Array.from({ length: 50000 }, () => ({})))] }).truncated, true);
  assert.deepEqual(pivotModel(def, { rows: [], cols: [] }, {}).rows, [], "no rows at all is an empty pivot, not an error");
});
