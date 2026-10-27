// The draft and its undo history (drafts in dashboard/static/render/builder.js), against a stand-in for localStorage.
//   node --test dashboard/cube/tests/drafts.test.mjs
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

const store = new Map();
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };
const { drafts } = await import("../../static/render/builder.js");

const draft = (yaml, message = "") => ({ yaml, spec: { yaml }, message, prompt: "p", notes: [], savedId: "s1" });
beforeEach(() => store.clear());

test("a new draft starts with no history", () => {
  drafts.setCurrent(draft("a: 1"));
  assert.deepEqual(drafts.history(), { undo: 0, redo: 0, undoLabel: "", redoLabel: "" });
  assert.equal(drafts.undo(), false);
  assert.equal(drafts.redo(), false);
});

test("an edit keeps the draft as it was; undo brings it back, redo goes forward again", () => {
  drafts.setCurrent(draft("a: 1", "built"));
  drafts.edit(draft("a: 2", "changed to 2"));
  drafts.edit(draft("a: 3", "changed to 3"));
  assert.deepEqual(drafts.history(), { undo: 2, redo: 0, undoLabel: "changed to 3", redoLabel: "" }, "the label is the change that produced the draft now");
  assert.ok(drafts.undo((label) => `Undid: ${label}`));
  assert.equal(drafts.current().yaml, "a: 2");
  assert.equal(drafts.current().message, "Undid: changed to 3");
  assert.equal(drafts.current().spec.yaml, "a: 2", "the compiled page comes back with it");
  assert.equal(drafts.current().savedId, "s1", "and nothing else about the draft is lost");
  assert.deepEqual(drafts.history(), { undo: 1, redo: 1, undoLabel: "Undid: changed to 3", redoLabel: "changed to 3" });
  assert.ok(drafts.redo((label) => `Redid: ${label}`));
  assert.equal(drafts.current().yaml, "a: 3");
  assert.equal(drafts.current().message, "Redid: changed to 3");
  assert.ok(drafts.undo() && drafts.undo());
  assert.equal(drafts.current().yaml, "a: 1");
  assert.equal(drafts.undo(), false, "back at the start");
});

test("a new edit after an undo throws away what could have been redone", () => {
  drafts.setCurrent(draft("a: 1"));
  drafts.edit(draft("a: 2"));
  drafts.undo();
  assert.equal(drafts.history().redo, 1);
  drafts.edit(draft("a: 9"));
  assert.equal(drafts.history().redo, 0);
  assert.equal(drafts.redo(), false);
});

test("an edit that changes nothing is not a step; setCurrent resets the history", () => {
  drafts.setCurrent(draft("a: 1"));
  drafts.edit(draft("a: 1", "same file, other words"));
  assert.equal(drafts.history().undo, 0);
  drafts.edit(draft("a: 2"));
  drafts.setCurrent(draft("b: 1"));
  assert.equal(drafts.history().undo, 0, "a different draft does not inherit the old one's steps");
});

test("the history is capped", () => {
  drafts.setCurrent(draft("n: 0"));
  for (let i = 1; i <= 30; i++) drafts.edit(draft(`n: ${i}`));
  assert.equal(drafts.history().undo, 20);
  for (let i = 0; i < 20; i++) drafts.undo();
  assert.equal(drafts.current().yaml, "n: 10", "the oldest steps are gone, the rest can be walked back");
});
