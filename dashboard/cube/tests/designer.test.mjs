// The designer's logic (dashboard/static/lib/designer-model.js): which fields a panel offers, how an edit changes the source spec, which members are offered.
//   node --test dashboard/cube/tests/designer.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { anyMemberOptions, cubeOf, dimensionOptions, fieldsFor, getAt, measureOptions, membersIn, reachableCubes, setField, shown } from "../../static/lib/designer-model.js";

const member = (cube, name) => ({ name, member: `${cube}.${name}`, type: "x", description: "" });
const CATALOG = [
  { cube: "internet_sales", joins: ["products", "dates", "territories"], measures: [member("internet_sales", "revenue"), member("internet_sales", "orders")], dimensions: [member("internet_sales", "order_number")] },
  { cube: "reseller_sales", joins: ["products", "dates"], measures: [member("reseller_sales", "revenue")], dimensions: [] },
  { cube: "products", joins: [], measures: [], dimensions: [member("products", "name"), member("products", "category")] },
  { cube: "dates", joins: [], measures: [], dimensions: [member("dates", "year")] },
  { cube: "territories", joins: [], measures: [], dimensions: [member("territories", "region")] },
  { cube: "inventory_health", joins: ["products"], measures: [member("inventory_health", "stock")], dimensions: [member("inventory_health", "status")] },
];
const SOURCE = {
  panels: [
    { id: "top", type: "bar", title: "Top", stack: [{ member: "internet_sales.revenue", label: "Internet", color: "internet" }, { member: "reseller_sales.revenue", label: "Reseller" }], by: "products.name", sort: "desc", limit: 10, on_click: { set_filter: "p" } },
    { id: "mix", type: "treemap", measure: "internet_sales.revenue", group: ["products.category", "products.name"], format: "money" },
    { id: "kpis", type: "kpi", measures: [{ member: "internet_sales.revenue", label: "Revenue", format: "money" }, { sum: ["internet_sales.orders"], label: "Orders" }] },
    { id: "t", type: "table", columns: ["internet_sales.order_number", { member: "internet_sales.revenue", label: "Rev" }], limit: 20 },
    { id: "note", type: "text", markdown: "hello" },
  ],
};
const panel = (id) => SOURCE.panels.find((p) => p.id === id);

test("a bar offers its title, each stacked measure, the grouping, sort, limit, direction and format", () => {
  const paths = fieldsFor(panel("top")).map((f) => f.path);
  assert.deepEqual(paths, ["title", "stack.0.member", "stack.0.label", "stack.0.color", "stack.1.member", "stack.1.label", "stack.1.color", "by", "sort", "limit", "orientation", "format", "cross_filter"]);
  assert.equal(fieldsFor(panel("top")).find((f) => f.path === "by").kind, "dimension");
  assert.equal(fieldsFor(panel("top")).find((f) => f.path === "limit").max, 1000);
});

test("a treemap's second grouping is optional, a text panel offers only its text, a formula is shown and not editable", () => {
  const mix = fieldsFor(panel("mix"));
  assert.equal(mix.find((f) => f.path === "group.1").optional, true);
  assert.equal(mix.find((f) => f.path === "group.0").optional, undefined);
  assert.deepEqual(fieldsFor(panel("note")).map((f) => f.path), ["markdown"]);
  const kpi = fieldsFor(panel("kpis"));
  assert.equal(kpi.find((f) => f.path === "measures.0").kind, "value", "a key figure is a measure, a sum or a ratio: one field that says which");
  assert.equal(kpi.find((f) => f.path === "measures.1").kind, "value");
  assert.deepEqual([kpi.find((f) => f.path === "measures.1").index, kpi.find((f) => f.path === "measures.1").count], [1, 2]);
  assert.ok(!kpi.some((f) => f.path === "title"), "a key-figures row has no title of its own");
});

test("a table column is a member whether it is written short or long", () => {
  const f = fieldsFor(panel("t"));
  assert.equal(f.find((x) => x.path === "columns.0").kind, "member");
  assert.equal(f.find((x) => x.path === "columns.1.member").kind, "member");
  assert.ok(f.some((x) => x.path === "columns.1.label") && !f.some((x) => x.path === "columns.0.label"));
});

test("getAt and shown read a path, and show nothing for what is missing or not a plain value", () => {
  assert.equal(getAt(panel("top"), "stack.1.label"), "Reseller");
  assert.equal(getAt(panel("top"), "stack.5.label"), undefined);
  assert.equal(shown(panel("top"), "limit"), "10");
  assert.equal(shown(panel("top"), "stack.0"), "");
  assert.equal(shown(panel("top"), "orientation"), "");
});

test("setField changes one field in a copy and leaves the original alone", () => {
  const before = JSON.stringify(SOURCE);
  const { source, notes } = setField(SOURCE, "top", "limit", 5);
  assert.equal(source.panels[0].limit, 5);
  assert.equal(JSON.stringify(SOURCE), before);
  assert.deepEqual(notes, []);
  assert.equal(setField(SOURCE, "top", "stack.1.label", "Dealers").source.panels[0].stack[1].label, "Dealers");
  assert.equal(setField(SOURCE, "kpis", "measures.0.format", "int").source.panels[2].measures[0].format, "int");
});

test("an empty optional field is removed; an empty optional list item is removed from its list", () => {
  assert.ok(!("sort" in setField(SOURCE, "top", "sort", "", { optional: true }).source.panels[0]));
  assert.ok(!("title" in setField(SOURCE, "top", "title", null, { optional: true }).source.panels[0]));
  assert.deepEqual(setField(SOURCE, "mix", "group.1", "", { optional: true }).source.panels[1].group, ["products.category"]);
  assert.deepEqual(setField(SOURCE, "mix", "group.1", "territories.region").source.panels[1].group, ["products.category", "territories.region"]);
  assert.equal(setField(SOURCE, "top", "title", "").source.panels[0].title, "", "a required field is not removed: the validator says what is wrong");
});

test("a field that is missing is created, a list before an index", () => {
  assert.equal(setField(SOURCE, "top", "orientation", "horizontal").source.panels[0].orientation, "horizontal");
  const note = { panels: [{ id: "n", type: "bar" }] };
  assert.deepEqual(setField(note, "n", "stack.0.member", "a.b").source.panels[0].stack, [{ member: "a.b" }]);
  assert.deepEqual(setField(note, "n", "x.y.z", 1).source.panels[0].x, { y: { z: 1 } });
});

test("changing what a panel groups by drops its click rule and says so; other fields keep it", () => {
  const changed = setField(SOURCE, "top", "by", "territories.region");
  assert.ok(!("on_click" in changed.source.panels[0]));
  assert.deepEqual(changed.notes, ["click"]);
  assert.ok("on_click" in setField(SOURCE, "top", "limit", 3).source.panels[0]);
  assert.deepEqual(setField({ panels: [{ id: "g", type: "treemap", group: ["a.b"], on_click: { set_filter: ["x"] } }] }, "g", "group.0", "c.d").notes, ["click"]);
  assert.throws(() => setField(SOURCE, "nope", "title", "x"), /no panel/);
});

test("members in a panel are found, once each, without the text or the click rule", () => {
  assert.deepEqual([...membersIn(panel("top"))].sort(), ["internet_sales.revenue", "products.name", "reseller_sales.revenue"]);
  assert.deepEqual([...membersIn({ markdown: "a.b", on_click: { set_filter: "c.d" }, measure: "x.y" })], ["x.y"]);
  assert.equal(cubeOf("internet_sales.revenue"), "internet_sales");
});

test("a grouping list holds only what the panel's measures can reach, through joins, and keeps the current value", () => {
  const names = (opts) => opts.map((o) => o.value).sort();
  assert.deepEqual(names(dimensionOptions(CATALOG, panel("top"))), ["dates.year", "products.category", "products.name"], "revenue of both channels: only what both can join to (no territories: reseller sales does not join to it)");
  assert.ok(names(dimensionOptions(CATALOG, panel("mix"))).includes("territories.region"), "internet revenue joins to territories");
  assert.ok(names(dimensionOptions(CATALOG, { type: "bar", by: "inventory_health.status" }, "inventory_health.status")).length > 3, "no measure yet: everything is offered");
  assert.ok(dimensionOptions(CATALOG, panel("top"), "territories.region").some((o) => o.value === "territories.region"), "the value already in the spec stays in the list, so the select can show it");
});

test("reachability follows joins any distance, and an unknown cube allows everything", () => {
  assert.deepEqual([...reachableCubes(CATALOG, ["inventory_health"])].sort(), ["inventory_health", "products"]);
  assert.deepEqual([...reachableCubes(CATALOG, ["internet_sales"])].sort(), ["dates", "internet_sales", "products", "territories"]);
  assert.deepEqual([...reachableCubes(CATALOG, ["internet_sales", "reseller_sales"])].sort(), ["dates", "products"], "two cubes: what both reach");
  assert.equal(reachableCubes(CATALOG, ["mystery"]), null);
  const chain = [{ cube: "a", joins: ["b"], measures: [], dimensions: [] }, { cube: "b", joins: ["c"], measures: [], dimensions: [] }, { cube: "c", joins: [], measures: [], dimensions: [] }];
  assert.deepEqual([...reachableCubes(chain, ["a"])].sort(), ["a", "b", "c"]);
});

test("measure and member lists carry the cube, the full name and the description", () => {
  const m = measureOptions(CATALOG);
  assert.equal(m.length, 4);
  assert.deepEqual(m[0], { value: "internet_sales.revenue", label: "internet_sales.revenue", cube: "internet_sales", description: "" });
  assert.equal(anyMemberOptions(CATALOG).length, 4 + 1 + 2 + 1 + 1 + 1);
});
