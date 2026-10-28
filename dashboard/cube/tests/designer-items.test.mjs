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
