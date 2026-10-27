// The designer's layout edits (dashboard/static/lib/designer-layout.js): moving, dropping, widths, tabs. Every result must still be a valid layout.
//   node --test dashboard/cube/tests/designer-layout.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { columnsMoved, sideOf } from "../../static/render/designer-dnd.js";
import { dropPanel, locate, moveCommand, moveTab, moveToTab, renameTab, rowOf, setWidths, tabsOf } from "../../static/lib/designer-layout.js";

const panels = (...ids) => ids.map((id) => ({ id, type: "text", markdown: "x" }));
const SRC = {
  panels: panels("a", "b", "c", "d", "e"),
  layout: [[{ a: 12 }], [{ b: 8 }, { c: 4 }], [{ d: 6 }, { e: 6 }]],
};
const TABBED = {
  panels: panels("a", "b", "c", "d"),
  tabs: [{ id: "one", title: "One", layout: [[{ a: 12 }], [{ b: 6 }, { c: 6 }]] }, { id: "two", title: "Two", layout: [[{ d: 12 }]] }],
};
const rows = (source) => source.layout.map((row) => row.map((c) => `${Object.keys(c)[0]}${Object.values(c)[0]}`).join(" "));

/** Every row adds up to 12, every panel is placed once (across tabs), nothing unknown is placed. */
function valid(source) {
  const placed = [];
  for (const layout of source.tabs ? source.tabs.map((t) => t.layout) : [source.layout]) {
    assert.ok(layout.length > 0 || source.tabs, "a layout is not empty");
    for (const row of layout) {
      assert.ok(row.length >= 1 && row.length <= 12);
      assert.equal(row.reduce((s, c) => s + Object.values(c)[0], 0), 12, JSON.stringify(row));
      assert.ok(row.every((c) => Object.values(c)[0] >= 1));
      placed.push(...row.map((c) => Object.keys(c)[0]));
    }
  }
  assert.deepEqual([...placed].sort(), source.panels.map((p) => p.id).sort(), "every panel once");
}

test("locate and rowOf say where a panel is, in a plain layout and in tabs", () => {
  assert.deepEqual(locate(SRC, "c") && { tab: locate(SRC, "c").tab, r: locate(SRC, "c").r, c: locate(SRC, "c").c }, { tab: null, r: 1, c: 1 });
  assert.deepEqual(rowOf(SRC, "b"), [{ id: "b", span: 8 }, { id: "c", span: 4 }]);
  assert.equal(locate(TABBED, "d").tab, "two");
  assert.equal(locate(SRC, "zzz"), null);
  assert.deepEqual(rowOf(SRC, "zzz"), []);
});

test("up and down: alone, a panel swaps rows; in a shared row it leaves into a row of its own; the ends say so", () => {
  assert.deepEqual(rows(moveCommand(SRC, "a", "down").source), ["b8 c4", "a12", "d6 e6"]);
  assert.equal(moveCommand(SRC, "a", "up").problem, "edge", "the top row cannot go up");
  assert.deepEqual(rows(moveCommand(SRC, "e", "down").source), ["a12", "b8 c4", "d12", "e12"], "e is in a shared row: it leaves into a row below");
  assert.deepEqual(rows(moveCommand(SRC, "c", "up").source), ["a12", "c12", "b12", "d6 e6"], "c leaves its row upwards; b takes the width");
  assert.deepEqual(rows(moveCommand(SRC, "c", "down").source), ["a12", "b12", "c12", "d6 e6"]);
  assert.equal(moveCommand({ panels: panels("a"), layout: [[{ a: 12 }]] }, "a", "down").problem, "edge");
  valid(moveCommand(SRC, "c", "up").source);
});

test("left and right swap places and each keeps its width", () => {
  assert.deepEqual(rows(moveCommand(SRC, "b", "right").source), ["a12", "c4 b8", "d6 e6"]);
  assert.deepEqual(rows(moveCommand(SRC, "c", "left").source), ["a12", "c4 b8", "d6 e6"]);
  assert.equal(moveCommand(SRC, "b", "left").problem, "edge");
  assert.equal(moveCommand(SRC, "a", "right").problem, "edge");
});

test("join-up and join-down share the next row, taking half of its widest cell; an empty row goes", () => {
  assert.deepEqual(rows(moveCommand(SRC, "a", "join-down").source), ["b4 c4 a4", "d6 e6"], "alone: its row goes, b (the widest, 8) gives half");
  assert.deepEqual(rows(moveCommand(SRC, "d", "join-up").source), ["a12", "b4 c4 d4", "e12"], "d joins the row above: b halves; e widens");
  assert.equal(moveCommand(SRC, "a", "join-up").problem, "edge");
  assert.equal(moveCommand(SRC, "e", "join-down").problem, "edge");
  valid(moveCommand(SRC, "a", "join-down").source);
  const full = { panels: panels("a", ..."bcdefghijklm".split("")), layout: [[{ a: 12 }], "bcdefghijklm".split("").map((id) => ({ [id]: 1 }))] };
  assert.equal(moveCommand(full, "a", "join-down").problem, "full", "a row of twelve has no room");
});

test("own-row takes a panel out of a shared row", () => {
  assert.deepEqual(rows(moveCommand(SRC, "c", "own-row").source), ["a12", "b12", "c12", "d6 e6"]);
  assert.equal(moveCommand(SRC, "a", "own-row").problem, "alone");
});

test("wider and narrower move a column with the right neighbour (the left one for the last), and stop at 1", () => {
  assert.deepEqual(rows(moveCommand(SRC, "b", "wider").source), ["a12", "b9 c3", "d6 e6"]);
  assert.deepEqual(rows(moveCommand(SRC, "b", "narrower").source), ["a12", "b7 c5", "d6 e6"]);
  assert.deepEqual(rows(moveCommand(SRC, "c", "wider").source), ["a12", "b7 c5", "d6 e6"], "the last cell takes from the left one");
  assert.equal(moveCommand(SRC, "a", "wider").problem, "alone");
  let s = SRC;
  for (let i = 0; i < 3; i++) s = moveCommand(s, "c", "narrower").source;
  assert.deepEqual(rows(s)[1], "b11 c1");
  assert.equal(moveCommand(s, "c", "narrower").problem, "edge", "1 is the least");
  valid(s);
});

test("a panel dropped on the top or bottom edge of another gets a row of its own there", () => {
  assert.deepEqual(rows(dropPanel(SRC, "e", { ref: "a", side: "top" }).source), ["e12", "a12", "b8 c4", "d12"]);
  assert.deepEqual(rows(dropPanel(SRC, "a", { ref: "e", side: "bottom" }).source), ["b8 c4", "d6 e6", "a12"]);
  assert.deepEqual(rows(dropPanel(SRC, "b", { ref: "c", side: "bottom" }).source), ["a12", "c12", "b12", "d6 e6"], "dragged out of its own row, the other one widens");
});

test("a panel dropped on the left or right edge shares that panel's row, splitting its width", () => {
  assert.deepEqual(rows(dropPanel(SRC, "a", { ref: "d", side: "right" }).source), ["b8 c4", "d3 a3 e6"]);
  assert.deepEqual(rows(dropPanel(SRC, "a", { ref: "d", side: "left" }).source), ["b8 c4", "a3 d3 e6"]);
  assert.deepEqual(rows(dropPanel(SRC, "e", { ref: "d", side: "right" }).source), ["a12", "b8 c4", "d6 e6"], "dropped back where it was: the same layout");
  assert.deepEqual(rows(dropPanel(SRC, "c", { ref: "b", side: "left" }).source), ["a12", "c6 b6", "d6 e6"], "c beside b: b is alone in its row once c has left, and is halved");
  assert.equal(dropPanel(SRC, "a", { ref: "a", side: "left" }).problem, "same");
  assert.equal(dropPanel(SRC, "a", { ref: "nope", side: "left" }).problem, "missing");
  valid(dropPanel(SRC, "a", { ref: "d", side: "right" }).source);
});

test("drops never break a layout: every result has rows of 12 and every panel once", () => {
  let seed = 7;
  const rnd = (n) => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed % n; };
  const ids = SRC.panels.map((p) => p.id), sides = ["top", "bottom", "left", "right"];
  const cmds = ["up", "down", "left", "right", "join-up", "join-down", "own-row", "narrower", "wider"];
  let s = SRC, moved = 0;
  for (let i = 0; i < 400; i++) {
    const id = ids[rnd(ids.length)];
    const r = rnd(2) ? dropPanel(s, id, { ref: ids[rnd(ids.length)], side: sides[rnd(4)] }) : moveCommand(s, id, cmds[rnd(cmds.length)]);
    if (r.source) { s = r.source; moved++; valid(s); }
  }
  assert.ok(moved > 150, `${moved} moves went through`);
});

test("setWidths sets the widths of a panel's row when they fit", () => {
  assert.deepEqual(rows(setWidths(SRC, "b", [3, 9]).source), ["a12", "b3 c9", "d6 e6"]);
  assert.equal(setWidths(SRC, "b", [3, 8]).problem, "sum");
  assert.equal(setWidths(SRC, "b", [12]).problem, "count");
  assert.equal(setWidths(SRC, "b", [0, 12]).problem, "sum");
  assert.equal(setWidths(SRC, "b", [4.5, 7.5]).problem, "sum");
});

test("tabs: a panel dropped on a tab goes to its end; tabs reorder and rename", () => {
  assert.deepEqual(tabsOf(TABBED).map((t) => [t.id, t.panels]), [["one", ["a", "b", "c"]], ["two", ["d"]]]);
  assert.deepEqual(tabsOf(SRC), []);
  const moved = moveToTab(TABBED, "a", "two").source;
  assert.deepEqual(tabsOf(moved).map((t) => t.panels), [["b", "c"], ["d", "a"]]);
  valid(moved);
  const wholeTab = moveToTab(moveToTab(TABBED, "d", "one").source, "a", "two").source;
  assert.deepEqual(tabsOf(wholeTab)[1].panels, ["a"], "a tab may be emptied and filled again");
  assert.equal(dropPanel(TABBED, "a", { tab: "nope", end: true }).problem, "tab");
  assert.deepEqual(tabsOf(moveTab(TABBED, "one", 1).source).map((t) => t.id), ["two", "one"]);
  assert.equal(moveTab(TABBED, "one", -1).problem, "edge");
  assert.equal(moveTab(TABBED, "zzz", 1).problem, "missing");
  assert.equal(renameTab(TABBED, "two", "Details").source.tabs[1].title, "Details");
  assert.equal(TABBED.tabs[1].title, "Two", "the original is untouched");
});

test("the pointer layer: which edge a point is nearest, and how many columns a drag moved", () => {
  const rect = { left: 100, top: 100, width: 400, height: 200 };
  assert.equal(sideOf(rect, 110, 200), "left");
  assert.equal(sideOf(rect, 490, 200), "right");
  assert.equal(sideOf(rect, 300, 120), "top");
  assert.equal(sideOf(rect, 300, 280), "bottom");
  assert.equal(sideOf(rect, 110, 120, true), "top", "on a narrow screen every panel is a full row: only top and bottom");
  assert.equal(sideOf(rect, 490, 280, true), "bottom");
  assert.equal(columnsMoved(0, 984), 0);
  assert.equal(columnsMoved(83, 984), 1);
  assert.equal(columnsMoved(-170, 984), -2, "a drag to the left is negative");
  assert.equal(columnsMoved(40, 984), 0, "less than half a column is not a move");
});
