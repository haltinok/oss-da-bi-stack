// The designer's structural edits (dashboard/static/lib/designer-structure.js): new panels, removing and duplicating, filters, the page's own fields.
//   node --test dashboard/cube/tests/designer-structure.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { addFilter, addPanel, defaultPanel, duplicatePanel, guessFormat, newPanelId, pickDimension, pickMeasure, removeFilter, removePanel, setFilter, setPageField, timeDimensions } from "../../static/lib/designer-structure.js";

const m = (cube, name, type = "number") => ({ name, member: `${cube}.${name}`, type, description: "" });
const CATALOG = [
  { cube: "internet_sales", joins: ["products", "dates", "territories"], measures: [m("internet_sales", "revenue"), m("internet_sales", "orders"), m("internet_sales", "margin_pct")], dimensions: [m("internet_sales", "order_number", "string")] },
  { cube: "reseller_sales", joins: ["products", "dates"], measures: [m("reseller_sales", "revenue")], dimensions: [] },
  { cube: "products", joins: [], measures: [], dimensions: [m("products", "key"), m("products", "name", "string"), m("products", "category", "string")] },
  { cube: "dates", joins: [], measures: [], dimensions: [m("dates", "full_date", "time"), m("dates", "fiscal_year", "string")] },
  { cube: "territories", joins: [], measures: [], dimensions: [m("territories", "region", "string")] },
  { cube: "inventory_health", joins: ["products"], measures: [m("inventory_health", "stock")], dimensions: [m("inventory_health", "status", "string")] },
];
const SOURCE = {
  spec: 1, id: "draft", title: "T", time: { dimension: "dates.full_date" },
  filters: [{ id: "region", dimension: "territories.region", label: "Region" }],
  panels: [
    { id: "kpis", type: "kpi", measures: [{ member: "internet_sales.revenue", label: "Revenue" }] },
    { id: "trend", type: "timeseries", series: [{ member: "internet_sales.revenue", label: "Internet" }], granularity: "month", style: "line", on_click: { set_filter: "region" } },
    { id: "top", type: "bar", measure: "reseller_sales.revenue", by: "products.name", ignore_filters: ["region"] },
    { id: "note", type: "text", markdown: "x" },
  ],
  layout: [[{ kpis: 12 }], [{ trend: 8 }, { top: 4 }], [{ note: 12 }]],
};

test("a format is guessed from the name: money, whole numbers, percent, else a plain number", () => {
  assert.equal(guessFormat("internet_sales.revenue"), "money");
  assert.equal(guessFormat("internet_sales.orders"), "int");
  assert.equal(guessFormat("internet_sales.margin_pct"), "pct");
  assert.equal(guessFormat("x.weird"), "number");
});

test("a new panel starts with a measure the role may read, preferring revenue, and a grouping its cube can join to", () => {
  assert.equal(pickMeasure(CATALOG, SOURCE), "internet_sales.revenue");
  assert.equal(pickMeasure([CATALOG[5]], SOURCE), "inventory_health.stock");
  assert.equal(pickMeasure([CATALOG[5], CATALOG[3]], SOURCE, { time: true }), null, "a measure that cannot be put on the time axis is not picked for a time chart");
  assert.equal(pickDimension(CATALOG, "internet_sales.revenue"), "products.category", "not a key, not a time dimension, a preferred name first");
  assert.equal(pickDimension(CATALOG, "inventory_health.stock"), "products.category");
  assert.equal(pickDimension(CATALOG, "internet_sales.revenue", ["products.category"]), "territories.region");
});

test("every type has a default that names only members of the catalog and reads as a panel of its type", () => {
  const members = new Set(CATALOG.flatMap((c) => [...c.measures, ...c.dimensions].map((x) => x.member)));
  for (const type of ["kpi", "timeseries", "bar", "pie", "treemap", "table", "pivot", "text"]) {
    const { panel, problem } = defaultPanel(type, CATALOG, SOURCE, `${type}_x`);
    assert.ok(panel && !problem, type);
    assert.equal(panel.type, type);
    const used = JSON.stringify(panel).match(/[a-z_]+\.[a-z_]+/g) || [];
    for (const u of type === "text" ? [] : used) assert.ok(members.has(u), `${type}: ${u}`);
  }
  assert.deepEqual(defaultPanel("treemap", CATALOG, SOURCE, "t").panel.group, ["products.category"]);
  assert.notEqual(defaultPanel("pivot", CATALOG, SOURCE, "p").panel.rows[0], defaultPanel("pivot", CATALOG, SOURCE, "p").panel.columns);
  assert.equal(defaultPanel("bar", [], SOURCE, "b").problem, "measure", "no readable measure: a reason, not a broken panel");
  assert.equal(defaultPanel("bar", [{ cube: "x", joins: [], measures: [m("x", "revenue")], dimensions: [] }], SOURCE, "b").problem, "dimension", "a measure but nothing to group by");
  assert.equal(defaultPanel("text", [], SOURCE, "n").panel.markdown.length > 0, true);
  assert.equal(defaultPanel("bar", CATALOG, SOURCE, "b", () => "My title").panel.title, "My title", "the title is worded by the caller, for the page's language");
});

test("addPanel gives the panel an unused id and a full-width row at the end", () => {
  assert.equal(newPanelId(SOURCE, "bar"), "bar");
  assert.equal(newPanelId(SOURCE, "top"), "top_2");
  const { source, id } = addPanel(SOURCE, "bar", CATALOG);
  assert.equal(id, "bar");
  assert.equal(source.panels.at(-1).id, "bar");
  assert.deepEqual(source.layout.at(-1), [{ bar: 12 }]);
  assert.equal(SOURCE.panels.length, 4, "the original is untouched");
  assert.equal(addPanel(addPanel(SOURCE, "bar", CATALOG).source, "bar", CATALOG).id, "bar_2");
  assert.equal(addPanel(SOURCE, "bar", []).problem, "measure");
});

test("with tabs a panel goes to the tab asked for, else the last", () => {
  const tabbed = { ...SOURCE, layout: undefined, tabs: [{ id: "a", title: "A", layout: [[{ kpis: 12 }], [{ trend: 8 }, { top: 4 }]] }, { id: "b", title: "B", layout: [[{ note: 12 }]] }] };
  delete tabbed.layout;
  assert.deepEqual(addPanel(tabbed, "pie", CATALOG, { tab: "a" }).source.tabs[0].layout.at(-1), [{ pie: 12 }]);
  assert.deepEqual(addPanel(tabbed, "pie", CATALOG).source.tabs[1].layout.at(-1), [{ pie: 12 }]);
});

test("removing a panel takes it out of the layout, drops an empty row and widens the neighbour so the row is still 12", () => {
  const { source } = removePanel(SOURCE, "top");
  assert.ok(!source.panels.some((p) => p.id === "top"));
  assert.deepEqual(source.layout[1], [{ trend: 12 }]);
  assert.deepEqual(removePanel(SOURCE, "note").source.layout, [[{ kpis: 12 }], [{ trend: 8 }, { top: 4 }]]);
  assert.equal(removePanel({ ...SOURCE, panels: [SOURCE.panels[0]] }, "kpis").problem, "last");
  const three = { ...SOURCE, layout: [[{ kpis: 4 }, { trend: 4 }, { top: 4 }], [{ note: 12 }]] };
  assert.deepEqual(removePanel(three, "kpis").source.layout[0], [{ trend: 4 }, { top: 8 }], "the freed width goes to the last in the row");
});

test("duplicating a panel copies it under a new id, marks the title, and puts it in a row under the original's", () => {
  const withTitle = { ...SOURCE, panels: SOURCE.panels.map((p) => (p.id === "top" ? { ...p, title: "Top" } : p)) };
  const { source, id } = duplicatePanel(withTitle, "top");
  assert.equal(id, "top_2");
  const copy = source.panels.find((p) => p.id === id);
  assert.equal(copy.title, "Top (copy)");
  assert.deepEqual(copy.ignore_filters, ["region"]);
  assert.deepEqual(source.layout[2], [{ top_2: 12 }]);
  assert.equal(source.layout.length, 4);
  assert.equal(duplicatePanel(source, "top_2").id, "top_3", "a copy of a copy does not become top_2_2");
  assert.equal(duplicatePanel(SOURCE, "nope").problem, "missing");
});

test("a new filter ignores the panels that cannot join to its dimension, and says so", () => {
  const { source, id, notes } = addFilter(SOURCE, CATALOG, "products.category");
  assert.equal(id, "category");
  assert.deepEqual(source.filters.at(-1), { id: "category", dimension: "products.category", label: "Category" });
  assert.ok(!source.panels.some((p) => (p.ignore_filters || []).includes("category")), "everything here joins to products");
  assert.deepEqual(notes, []);
  const unreachable = addFilter(SOURCE, CATALOG, "territories.region");
  assert.equal(unreachable.id, "region_2", "an id is never reused");
  assert.deepEqual(unreachable.source.panels.find((p) => p.id === "top").ignore_filters, ["region", "region_2"], "reseller sales has no join to territories");
  assert.deepEqual(unreachable.notes, ["ignored"]);
  assert.ok(!unreachable.source.panels.find((p) => p.id === "note").ignore_filters, "a text panel has no data to ignore");
  assert.equal(addFilter({ ...SOURCE, filters: undefined }, CATALOG, "products.name").source.filters.length, 1);
});

test("changing a filter's dimension re-decides who ignores it and drops click rules that named it for the old dimension", () => {
  const r = setFilter(SOURCE, CATALOG, "region", "dimension", "products.category");
  assert.equal(r.source.filters[0].dimension, "products.category");
  assert.ok(!r.source.panels.find((p) => p.id === "top").ignore_filters, "reseller sales joins to products: no need to ignore it now");
  assert.ok(!("on_click" in r.source.panels.find((p) => p.id === "trend")));
  assert.deepEqual(r.notes, ["click"]);
  assert.equal(setFilter(SOURCE, CATALOG, "region", "label", "Area").source.filters[0].label, "Area");
  assert.ok(!("parent" in setFilter({ ...SOURCE, filters: [{ id: "region", dimension: "territories.region", parent: "x.y" }] }, CATALOG, "region", "parent", "").source.filters[0]));
  assert.throws(() => setFilter(SOURCE, CATALOG, "nope", "label", "x"), /no filter/);
});

test("removing a filter removes every mention of it", () => {
  const { source, notes } = removeFilter(SOURCE, "region");
  assert.ok(!("filters" in source), "no filters left: the key goes");
  assert.ok(!source.panels.find((p) => p.id === "top").ignore_filters);
  assert.ok(!source.panels.find((p) => p.id === "trend").on_click);
  assert.deepEqual(notes, ["click"]);
  assert.equal(removeFilter(addFilter(SOURCE, CATALOG, "products.name").source, "name").source.filters.length, 1);
});

test("the page's own fields: a description may be empty (and goes), a title may not be removed here", () => {
  assert.equal(setPageField(SOURCE, "title", "New").source.title, "New");
  assert.equal(setPageField(SOURCE, "description", "About").source.description, "About");
  assert.ok(!("description" in setPageField({ ...SOURCE, description: "x" }, "description", "").source));
  assert.equal(setPageField(SOURCE, "title", "").source.title, "", "the validator says a title is needed");
  assert.equal(setPageField(SOURCE, "time.dimension", "dates.full_date").source.time.dimension, "dates.full_date");
  assert.equal(setPageField({ ...SOURCE, time: { dimension: "a.b", fiscal_year_start: 7 } }, "time.fiscal_year_start", "").source.time.fiscal_year_start, undefined);
  assert.deepEqual(timeDimensions(CATALOG).map((d) => d.value), ["dates.full_date"]);
});

// ---- filter types
import { dimensionTypeOf, setFilterType, typesFor } from "../../static/lib/designer-structure.js";

test("a dimension's type decides which filter types it can have", () => {
  assert.deepEqual(typesFor("string"), ["select", "multiselect", "text"]);
  assert.deepEqual(typesFor("number"), ["select", "multiselect", "number"]);
  assert.deepEqual(typesFor("time"), ["select", "multiselect", "date"]);
  assert.deepEqual(typesFor(undefined), ["select", "multiselect"]);
  assert.equal(dimensionTypeOf(CATALOG, "dates.full_date"), "time");
  assert.equal(dimensionTypeOf(CATALOG, "nope.x"), undefined);
});

test("changing a filter's type drops the default, and what cannot work with the new type, saying so", () => {
  const src = { ...SOURCE, filters: [{ id: "region", dimension: "territories.region", label: "Region", default: "France", parent: "territories.group" }, { id: "kid", dimension: "territories.country", parent: "territories.region" }] };
  const multi = setFilterType(src, CATALOG, "region", "multiselect");
  assert.equal(multi.source.filters[0].type, "multiselect");
  assert.equal("default" in multi.source.filters[0], false);
  assert.equal(multi.source.filters[0].parent, "territories.group", "a multiselect may keep its parent");
  assert.deepEqual(multi.notes.sort(), ["click", "defaultDropped", "parentDropped"].sort(), "a click rule on it, and a child filter that took it as its parent, cannot stay");
  assert.equal("on_click" in multi.source.panels.find((p) => p.id === "trend"), false);
  assert.equal("parent" in multi.source.filters[1], false);
  const text = setFilterType(src, CATALOG, "region", "text");
  assert.equal("parent" in text.source.filters[0], false, "a text filter has no parent");
  const back = setFilterType(multi.source, CATALOG, "region", "select");
  assert.equal("type" in back.source.filters[0], false, "select is the absence of a type");
  assert.equal(src.filters[0].default, "France", "the argument is not touched");
});

test("a type that does not fit the filter's dimension is refused", () => {
  assert.equal(setFilterType(SOURCE, CATALOG, "region", "date").problem, "type");
  assert.equal(setFilterType(SOURCE, CATALOG, "region", "number").problem, "type");
  assert.equal(setFilterType(SOURCE, CATALOG, "nope", "text").problem, "missing");
  const dated = { ...SOURCE, filters: [{ id: "d", dimension: "dates.full_date" }] };
  assert.equal(setFilterType(dated, CATALOG, "d", "date").source.filters[0].type, "date");
});

test("a default is set and emptied like the other optional fields; a new dimension that the type no longer fits resets it", () => {
  const withDefault = setFilter(SOURCE, CATALOG, "region", "default", "France").source;
  assert.equal(withDefault.filters[0].default, "France");
  assert.equal("default" in setFilter(withDefault, CATALOG, "region", "default", "").source.filters[0], false);
  const dated = { ...SOURCE, filters: [{ id: "d", dimension: "dates.full_date", type: "date", default: "rel:last_30_days" }] };
  const moved = setFilter(dated, CATALOG, "d", "dimension", "products.name");
  assert.equal("type" in moved.source.filters[0] || "default" in moved.source.filters[0], false);
  assert.ok(moved.notes.includes("typeReset"));
  const kept = setFilter({ ...SOURCE, filters: [{ id: "t", dimension: "products.name", type: "text", default: "contains:x" }] }, CATALOG, "t", "dimension", "products.category");
  assert.equal(kept.source.filters[0].type, "text", "a type that still fits stays");
});
