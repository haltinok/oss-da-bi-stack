// The designer's list and formula edits (dashboard/static/lib/designer-items.js) and the pivot fields of designer-model.js.
//   node --test dashboard/cube/tests/designer-items.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { addItem, addPart, canRemovePart, changeKind, describe, kindOf, removeItem, removePart, setPart } from "../../static/lib/designer-items.js";
import { fieldsFor, setField } from "../../static/lib/designer-model.js";

const SOURCE = () => ({
  panels: [
    { id: "k", type: "kpi", measures: [{ member: "internet_sales.revenue", label: "Revenue", format: "money" }, { ratio: { num: ["internet_sales.revenue"], den: ["internet_sales.orders"] }, label: "AOV" }] },
    { id: "t", type: "timeseries", granularity: "month", series: [{ member: "internet_sales.revenue", label: "Internet", color: "internet" }] },
    { id: "p", type: "pivot", rows: ["products.category"], columns: { member: "dates.year", granularity: "year" }, measures: [{ member: "internet_sales.revenue", label: "Revenue" }, "internet_sales.orders"], heat: { measure: "internet_sales.revenue" } },
  ],
});
const get = (src, id) => src.panels.find((p) => p.id === id);

test("a measure becomes a sum or a ratio and back, keeping its label, format and colour", () => {
  const src = SOURCE();
  const sum = changeKind(src, "t", "series.0", "sum", "reseller_sales.revenue").source;
  assert.deepEqual(get(sum, "t").series[0], { sum: ["internet_sales.revenue", "reseller_sales.revenue"], label: "Internet", color: "internet" });
  const ratio = changeKind(src, "k", "measures.0", "ratio", "internet_sales.orders").source;
  assert.deepEqual(get(ratio, "k").measures[0].ratio, { num: ["internet_sales.revenue"], den: ["internet_sales.orders"] });
  assert.equal(get(ratio, "k").measures[0].format, "money");
  const back = changeKind(ratio, "k", "measures.0", "member").source;
  assert.deepEqual(get(back, "k").measures[0], { member: "internet_sales.revenue", label: "Revenue", format: "money" });
  assert.equal(get(src, "t").series[0].member, "internet_sales.revenue", "the argument is not touched");
  assert.equal(changeKind(src, "t", "series.0", "sum").problem, "spare", "a sum needs a second measure to start with");
});

test("a formula is told in words", () => {
  assert.equal(describe({ sum: ["internet_sales.revenue", "reseller_sales.revenue"] }), "Revenue + Revenue");
  assert.equal(describe({ ratio: { num: ["a.gross_profit", "a.tax"], den: ["a.revenue"] } }), "(Gross profit + Tax) ÷ Revenue");
  assert.equal(describe({ member: "a.orders" }), "Orders");
  assert.deepEqual(["x.y", { sum: ["a.b", "a.c"] }, { ratio: {} }, { member: "a.b" }].map(kindOf), ["member", "sum", "ratio", "member"]);
});

test("the members of a formula can be changed, added and removed, down to the minimum", () => {
  let src = changeKind(SOURCE(), "t", "series.0", "sum", "reseller_sales.revenue").source;
  src = setPart(src, "t", "series.0", "sum", 1, "internet_sales.orders").source;
  assert.deepEqual(get(src, "t").series[0].sum, ["internet_sales.revenue", "internet_sales.orders"]);
  assert.equal(removePart(src, "t", "series.0", "sum", 0).problem, "min", "a sum keeps two");
  assert.equal(canRemovePart(get(src, "t").series[0], "sum"), false);
  src = addPart(src, "t", "series.0", "sum", "reseller_sales.revenue").source;
  assert.equal(get(src, "t").series[0].sum.length, 3);
  assert.deepEqual(get(removePart(src, "t", "series.0", "sum", 0).source, "t").series[0].sum, ["internet_sales.orders", "reseller_sales.revenue"]);
  const k = SOURCE();
  assert.equal(removePart(k, "k", "measures.1", "den", 0).problem, "min", "each side of a ratio keeps one");
  assert.equal(get(addPart(k, "k", "measures.1", "den", "internet_sales.units").source, "k").measures[1].ratio.den.length, 2);
});

test("measures and series are added and removed within each list's limits", () => {
  let src = addItem(SOURCE(), "t", "series", "reseller_sales.revenue").source;
  assert.equal(get(src, "t").series.length, 2);
  assert.equal(get(src, "t").series[1].label, "Revenue");
  assert.equal(removeItem(src, "t", "series", 0).source.panels[1].series.length, 1);
  assert.equal(removeItem(removeItem(src, "t", "series", 0).source, "t", "series", 0).problem, "min");
  let k = SOURCE();
  for (let i = 0; i < 6; i++) k = addItem(k, "k", "measures", "internet_sales.units").source;
  assert.equal(get(k, "k").measures.length, 8);
  assert.equal(addItem(k, "k", "measures", "internet_sales.units").problem, "max");
  assert.equal(addItem(SOURCE(), "p", "measures", "internet_sales.units").source.panels[2].measures.length, 3);
  assert.equal(addItem(addItem(SOURCE(), "p", "measures", "a.b").source, "p", "measures", "a.c").problem, "max", "a pivot holds three");
});

test("removing the measure a pivot's heat map is on removes the heat map", () => {
  const out = removeItem(SOURCE(), "p", "measures", 0).source;
  assert.equal(get(out, "p").heat, undefined);
  assert.equal(get(removeItem(SOURCE(), "p", "measures", 1).source, "p").heat.measure, "internet_sales.revenue");
});

test("a pivot offers its heat map, order and limits, and a time column its step", () => {
  const paths = fieldsFor(get(SOURCE(), "p")).map((f) => f.path);
  for (const p of ["columns.member", "columns.granularity", "heat.measure", "order.by", "order.dir", "limit.rows", "limit.columns", "measures.0.label", "measures.1"]) assert.ok(paths.includes(p), p);
  const heat = fieldsFor(get(SOURCE(), "p")).find((f) => f.path === "heat.measure");
  assert.deepEqual(heat.options, ["internet_sales.revenue", "internet_sales.orders"]);
  assert.equal(heat.optional, true);
});

test("emptying an optional field leaves no empty object behind", () => {
  const off = setField(SOURCE(), "p", "heat.measure", "", { optional: true }).source;
  assert.equal("heat" in get(off, "p"), false);
  const lim = setField(setField(SOURCE(), "p", "limit.rows", 10, { optional: true }).source, "p", "limit.rows", "", { optional: true }).source;
  assert.equal("limit" in get(lim, "p"), false);
});

// ---- colour rules
import { addRule } from "../../static/lib/designer-items.js";

test("a rule is added to a key figure or to a table column (a plain member becomes an object first), four at most", () => {
  const src = { panels: [{ id: "k", type: "kpi", measures: [{ member: "a.revenue", label: "R" }] }, { id: "t", type: "table", columns: ["a.name", "a.revenue", { member: "a.orders", label: "O" }] }] };
  let out = addRule(src, "k", "measures.0").source;
  assert.deepEqual(out.panels[0].measures[0].rules, [{ when: "below", value: 0, tone: "bad" }]);
  for (let i = 0; i < 3; i++) out = addRule(out, "k", "measures.0").source;
  assert.equal(addRule(out, "k", "measures.0").problem, "max");
  assert.deepEqual(addRule(src, "t", "columns.1").source.panels[1].columns[1], { member: "a.revenue", rules: [{ when: "below", value: 0, tone: "bad" }] });
  assert.equal(addRule(src, "t", "columns.2").source.panels[1].columns[2].label, "O", "an object column keeps its label");
  assert.equal(addRule(src, "t", "columns.9").problem, "item");
  assert.equal(src.panels[0].measures[0].rules, undefined, "the argument is not touched");
});

test("the rule fields appear for a key figure and for a table's measure columns, and removing the last rule leaves no empty list", () => {
  const src = { panels: [{ id: "k", type: "kpi", measures: [{ member: "a.revenue", label: "R", rules: [{ when: "above", value: 5, tone: "good" }] }] },
    { id: "t", type: "table", columns: ["a.name", { member: "a.revenue", rules: [{ when: "below", value: 1, tone: "bad" }] }] }] };
  const kf = fieldsFor(src.panels[0]).map((f) => f.path);
  for (const p of ["measures.0.rules.0.when", "measures.0.rules.0.value", "measures.0.rules.0.tone", "measures.0.rules"]) assert.ok(kf.includes(p), p);
  assert.equal(fieldsFor(src.panels[0]).find((f) => f.path === "measures.0.rules.0.when").rm, "measures.0.rules.0");
  const isMeasure = (m) => m === "a.revenue";
  const tf = fieldsFor(src.panels[1], { isMeasure });
  assert.ok(tf.some((f) => f.path === "columns.1.rules.0.tone") && tf.some((f) => f.kind === "addrule" && f.base === "columns.1"));
  assert.ok(!tf.some((f) => f.base === "columns.0"), "a dimension column is not offered rules");
  assert.ok(!fieldsFor(src.panels[1]).some((f) => f.kind === "addrule"), "without a catalog no column is known to be a measure");
  const gone = setField(src, "k", "measures.0.rules.0", "", { optional: true }).source;
  assert.equal("rules" in gone.panels[0].measures[0], false);
});

// ---- table fields
import { addColumn, aggregatesFor, moveColumn, setColumnAggregate } from "../../static/lib/designer-items.js";

const TABLE = () => ({ panels: [{ id: "t", type: "table", columns: ["inventory_health.status", { member: "inventory_health.stockout_items", label: "Out" }], order: { "inventory_health.stockout_items": "desc" }, limit: 20 }] });

test("a table takes any number of fields: a number field starts as a Sum, a key or a text field is a group, a measure is left as it is", () => {
  let src = TABLE();
  src = addColumn(src, "t", "inventory_health.on_hand", "number").source;
  assert.deepEqual(src.panels[0].columns.at(-1), { member: "inventory_health.on_hand", aggregate: "sum" });
  src = addColumn(src, "t", "inventory_health.key", "number").source;
  assert.deepEqual(src.panels[0].columns.at(-1), { member: "inventory_health.key" }, "a key is a group, not something to add up");
  src = addColumn(src, "t", "inventory_health.vendor_name", "string").source;
  assert.deepEqual(src.panels[0].columns.at(-1), { member: "inventory_health.vendor_name" });
  src = addColumn(src, "t", "inventory_health.reorder_items", "measure").source;
  assert.deepEqual(src.panels[0].columns.at(-1), { member: "inventory_health.reorder_items" });
  for (let i = 0; i < 30; i++) src = addColumn(src, "t", `inventory_health.f${i}`, "string").source;
  assert.equal(src.panels[0].columns.length, 36, "no limit");
  assert.equal(addColumn(src, "nope", "a.b", "string").problem, "item");
  assert.equal(addColumn({ panels: [{ id: "k", type: "kpi", measures: [] }] }, "k", "a.b", "string").problem, "item");
  assert.equal(TABLE().panels[0].columns.length, 2, "the argument is not touched");
});

test("each field's aggregate: set, changed, and removed (a group again); sum and average are for numbers", () => {
  const set = setColumnAggregate(TABLE(), "t", 0, "count_distinct").source;
  assert.deepEqual(set.panels[0].columns[0], { member: "inventory_health.status", aggregate: "count_distinct" }, "a plain member becomes an object");
  const kept = setColumnAggregate(set, "t", 1, "max").source;
  assert.deepEqual(kept.panels[0].columns[1], { member: "inventory_health.stockout_items", label: "Out", aggregate: "max" }, "the label stays");
  assert.deepEqual(setColumnAggregate(kept, "t", 0, "").source.panels[0].columns[0], { member: "inventory_health.status" });
  assert.equal(setColumnAggregate(TABLE(), "t", 9, "sum").problem, "item");
  assert.deepEqual(aggregatesFor("number"), ["sum", "max", "min", "avg", "count", "count_distinct", "first", "last"]);
  assert.deepEqual(aggregatesFor("string"), ["max", "min", "count", "count_distinct", "first", "last"]);
  assert.deepEqual(aggregatesFor("time"), aggregatesFor("string"));
});

test("a field is moved earlier or later, and removed down to the last one; its sort goes with it", () => {
  const moved = moveColumn(TABLE(), "t", 0, 1).source;
  assert.deepEqual(moved.panels[0].columns.map((c) => c.member || c), ["inventory_health.stockout_items", "inventory_health.status"]);
  assert.equal(moveColumn(TABLE(), "t", 0, -1).problem, "edge");
  assert.equal(moveColumn(TABLE(), "t", 1, 1).problem, "edge");
  const gone = removeItem(TABLE(), "t", "columns", 1).source;
  assert.equal(gone.panels[0].columns.length, 1);
  assert.equal("order" in gone.panels[0], false, "the sort on the removed field is dropped, and an empty sort with it");
  assert.equal(removeItem(gone, "t", "columns", 0).problem, "min");
  const twice = { panels: [{ id: "t", type: "table", columns: ["a.x", { member: "a.y", aggregate: "sum" }], order: { "a.y": "asc", "a.x": "asc" } }] };
  assert.deepEqual(removeItem(twice, "t", "columns", 1).source.panels[0].order, { "a.x": "asc" });
});
