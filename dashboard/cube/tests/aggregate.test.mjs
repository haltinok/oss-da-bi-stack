// Aggregating a table's fields (dashboard/static/lib/aggregate.js).
//   node --test dashboard/cube/tests/aggregate.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { AGGREGATES, aggregateValues, grandAggregates, groupAggregates } from "../../static/lib/aggregate.js";

test("each aggregate of the same values", () => {
  const v = ["3", 5, null, "", "2", 5];
  assert.deepEqual(Object.fromEntries(AGGREGATES.map((a) => [a, aggregateValues(a, v)])),
    { sum: 15, max: 5, min: 2, avg: 3.75, count: 4, count_distinct: 3, first: "3", last: 5 });
});

test("nothing to aggregate: a sum or average is null, a count is 0, first and last are null", () => {
  for (const empty of [[], [null, ""], [undefined]]) {
    assert.deepEqual(AGGREGATES.map((a) => aggregateValues(a, empty)), [null, null, null, null, 0, 0, null, null]);
  }
});

test("max and min compare numbers as numbers (10 is more than 9) and text as text; sum and average skip what is not a number", () => {
  assert.equal(aggregateValues("max", ["9", "10", "8"]), 10);
  assert.equal(aggregateValues("min", ["9", "10", "8"]), 8);
  assert.equal(aggregateValues("max", ["pear", "apple", "zebra"]), "zebra");
  assert.equal(aggregateValues("min", ["pear", "apple", "zebra"]), "apple");
  assert.equal(aggregateValues("max", ["9", "n/a"]), "n/a", "one value that is not a number makes the comparison text");
  assert.equal(aggregateValues("sum", ["4", "x", "6"]), 10);
  assert.equal(aggregateValues("avg", ["4", "x", "6"]), 5);
  assert.equal(aggregateValues("count_distinct", ["1", 1, "1.0"]), 2, "values are compared as written");
});

test("rows are grouped by the key columns and each value is aggregated over its group, in first-seen order", () => {
  const rows = [
    { "p.cat": "Bikes", "p.on_hand": "10", "p.vendor": "A" },
    { "p.cat": "Clothing", "p.on_hand": "1", "p.vendor": "B" },
    { "p.cat": "Bikes", "p.on_hand": "30", "p.vendor": "A" },
    { "p.cat": "Bikes", "p.on_hand": "5", "p.vendor": "C" },
  ];
  const cols = [{ member: "p.on_hand", aggregate: "sum" }, { member: "p.vendor", aggregate: "count_distinct" }];
  const g = groupAggregates(rows, ["p.cat"], cols);
  assert.deepEqual([...g.keys()], ["Bikes", "Clothing"]);
  assert.deepEqual([...g.get("Bikes").aggs], [["p.on_hand", 45], ["p.vendor", 2]]);
  assert.deepEqual(g.get("Clothing").dims, { "p.cat": "Clothing" });
  assert.deepEqual([...grandAggregates(rows, cols)], [["p.on_hand", 46], ["p.vendor", 3]]);
  const whole = groupAggregates(rows, [], cols);
  assert.equal(whole.size, 1, "no key column: one group for everything");
  assert.equal(whole.get("").aggs.get("p.on_hand"), 46);
});
