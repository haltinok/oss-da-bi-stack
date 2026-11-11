// Which model a page is in (dashboard/static/lib/model.js): the address, a hint, the last one used, else the first; and the address of the same page in another model.
//   node --test dashboard/cube/tests/model.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { addressIn, dashboardsBase, modelParam, modelsOf, mountModelSwitch, pickModel } from "../../static/lib/model.js";

const store = {};
globalThis.location = { pathname: "/lab/", search: "?model=dist" };
globalThis.localStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); } };
const TWO = { cube: "http://c", models: [{ id: "aw", label: "AdventureWorks", cube: "http://c" }, { id: "dist", label: "Dağıtım", cube: "http://d" }] };

test("a stack with no models has one nameless model on its own Cube, and no parameters", () => {
  const one = pickModel({ cube: "http://c" }, { search: "" });
  assert.deepEqual([one.multiple, one.model.id, one.model.cube, one.isDefault], [false, "default", "http://c", true]);
  assert.equal(modelParam(one), undefined);
  assert.equal(dashboardsBase(one), "/dashboards/");
  assert.equal(modelsOf({ cube: "x" }).length, 1);
});

test("the address wins over a hint, a hint over the last model used, and the first is the default", () => {
  delete store.model;
  assert.equal(pickModel(TWO, { search: "" }).model.id, "aw");
  assert.equal(store.model, "aw", "the choice is remembered");
  assert.equal(pickModel(TWO, { search: "?model=dist" }).model.id, "dist");
  assert.equal(pickModel(TWO, { search: "", hint: "aw" }).model.id, "aw");
  assert.equal(pickModel(TWO, { search: "" }).model.id, "aw", "the last one used (the hint's)");
  assert.equal(pickModel(TWO, { search: "?model=dist", hint: "aw" }).model.id, "dist");
  assert.equal(pickModel(TWO, { search: "?model=atlantis" }).model.id, "aw", "an unknown model is the default");
  const p = pickModel(TWO, { search: "?model=dist" });
  assert.deepEqual([p.multiple, p.isDefault, modelParam(p), dashboardsBase(p)], [true, false, "dist", "/dashboards/dist/"]);
});

test("the same page in another model: a dashboard goes to the list, the dataset and the list's own state are dropped", () => {
  assert.equal(addressIn("dist", { pathname: "/lab/", search: "?model=aw" }), "/lab/?model=dist");
  assert.equal(addressIn("dist", { pathname: "/d/", search: "?model=aw&dataset=250m&tag=sales" }), "/d/?model=dist&tag=sales", "on the list itself only the dataset goes");
  assert.equal(addressIn("dist", { pathname: "/d/sales-overview", search: "?model=aw&tab=x&fy=2021" }), "/d/?model=dist&fy=2021", "a dashboard page goes to the list (the dashboard does not exist there)");
  assert.equal(addressIn("dist", { pathname: "/home/", search: "" }), "/home/?model=dist");
});

test("the header switch lists the models, shows the current one and opens the page in the chosen one", () => {
  const made = [];
  const sel = { children: [], value: "", listeners: {}, setAttribute() {}, replaceChildren(...c) { this.children = c; }, addEventListener(ev, fn) { this.listeners[ev] = fn; } };
  const field = { hidden: true };
  const doc = { getElementById: (id) => ({ "model-field": field, "f-model": sel, "model-label": { replaceChildren() {} } })[id], createElement: () => { const o = {}; made.push(o); return o; } };
  const went = [];
  mountModelSwitch(pickModel(TWO, { search: "?model=dist" }), { doc, go: (u) => went.push(u) });
  assert.deepEqual(made.map((o) => [o.value, o.textContent]), [["aw", "AdventureWorks"], ["dist", "Dağıtım"]]);
  assert.equal(sel.value, "dist");
  assert.equal(field.hidden, false);
  sel.value = "aw";
  sel.listeners.change();
  assert.equal(went.length, 1);
  assert.equal(went[0], "/lab/?model=aw");
  const hidden = { hidden: true };
  mountModelSwitch(pickModel({ cube: "http://c" }, { search: "" }), { doc: { getElementById: (id) => (id === "model-field" ? hidden : { replaceChildren() {} }), createElement: () => ({}) } });
  assert.equal(hidden.hidden, true, "no choice, no switch");
});
