// A filter's `allowed` values (the designer's limit on what the page's filter offers) become a Cube filter on every panel the filter applies to, picked or not.
//   node --test dashboard/cube/tests/allowed.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { activeFilters } from "../../static/render/plan.js";

const spec = { filters: [{ id: "m", dimension: "products.category", type: "multiselect", allowed: ["A", "B"] }], panels: [{ id: "p" }, { id: "q", ignore_filters: ["m"] }] };
const limit = { member: "products.category", operator: "equals", values: ["A", "B"] };

test("allowed values limit a panel with nothing picked, and a pick narrows inside them", () => {
  assert.deepEqual(activeFilters(spec, {}, { id: "p" }), [limit]);
  assert.deepEqual(activeFilters(spec, { m: "in:A" }, { id: "p" }), [{ member: "products.category", operator: "equals", values: ["A"] }, limit]);
});

test("a panel that ignores the filter is not limited by it", () => {
  assert.deepEqual(activeFilters(spec, {}, { id: "q", ignore_filters: ["m"] }), []);
});
