// The SQL lab's grid helpers (dashboard/static/lib/lab-grid.js): `node --test dashboard/cube/tests/lab-grid.test.mjs`
import assert from "node:assert/strict";
import { test } from "node:test";
import { cleanTabs, formatCell, insertAt, pushHistory, sortRows, toTsv } from "../../static/lib/lab-grid.js";

test("numbers sort by value, text by text, empty values last either way, ties keep the query's order", () => {
  const rows = [["b", 10], ["a", 9], ["c", null], ["d", 9], ["e", 100]];
  assert.deepEqual(sortRows(rows, 1, "asc", "number").map((r) => r[0]), ["a", "d", "b", "e", "c"]);
  assert.deepEqual(sortRows(rows, 1, "desc", "number").map((r) => r[0]), ["e", "b", "a", "d", "c"]);
  assert.deepEqual(sortRows(rows, 0, "asc", "string").map((r) => r[0]), ["a", "b", "c", "d", "e"]);
  assert.deepEqual(sortRows([["ı"], ["i"], ["İ"]], 0, "asc", "string").length, 3);
  assert.deepEqual(rows.map((r) => r[0]), ["b", "a", "c", "d", "e"], "the input is not changed");
});

test("text sorts with numbers inside it in a human order", () => {
  assert.deepEqual(sortRows([["SO10"], ["SO9"], ["SO100"]], 0, "asc", "string").map((r) => r[0]), ["SO9", "SO10", "SO100"]);
});

test("cells: empty is blank, a midnight time loses its time, a boolean is words", () => {
  assert.equal(formatCell(null, "string"), "");
  assert.equal(formatCell("2026-01-02T00:00:00", "time"), "2026-01-02");
  assert.equal(formatCell("2026-01-02T10:30:00.000000", "time"), "2026-01-02 10:30:00.000000".replace(/\.0+$/, ""));
  assert.equal(formatCell(true, "boolean"), "true");
  assert.equal(formatCell(12.5, "number"), "12.5");
});

test("copied text has a header, tabs between cells, and no tab or line break inside one", () => {
  const cols = [{ name: "a", type: "string" }, { name: "b\tx", type: "number" }];
  assert.equal(toTsv(cols, [["x\ty", 1], ["line\nbreak", null]]), "a\tb x\nx y\t1\nline break\t");
});

test("tabs from storage are made safe and never empty", () => {
  assert.deepEqual(cleanTabs("junk"), [{ id: 1, sql: "" }]);
  assert.deepEqual(cleanTabs([{ id: 3, sql: "select 1" }, { id: "x", sql: "bad" }, null, { id: 4, sql: 5 }]), [{ id: 3, sql: "select 1" }]);
  assert.equal(cleanTabs(Array.from({ length: 30 }, (_, i) => ({ id: i, sql: "" }))).length, 12);
  assert.deepEqual(cleanTabs([{ id: 1, sql: "select 1", queryId: "abc" }, { id: 2, sql: "x", queryId: 5 }, { id: 3, sql: "y", queryId: "" }]), [{ id: 1, sql: "select 1", queryId: "abc" }, { id: 2, sql: "x" }, { id: 3, sql: "y" }], "a tab remembers the saved query it is open on");
});

test("history keeps the newest first, no duplicates, at most the limit, nothing for an empty query", () => {
  let h = pushHistory([], "select 1", 1);
  h = pushHistory(h, "select 2", 2);
  h = pushHistory(h, " select 1 ", 3);
  assert.deepEqual(h.map((x) => [x.sql, x.at]), [["select 1", 3], ["select 2", 2]]);
  assert.equal(pushHistory(h, "   ").length, 2);
  let big = [];
  for (let i = 0; i < 40; i++) big = pushHistory(big, `select ${i}`, i, 30);
  assert.equal(big.length, 30);
});

test("a field name is put where the cursor is, replacing a selection", () => {
  assert.deepEqual(insertAt("select  from t", 7, 7, "category"), { text: "select category from t", cursor: 15 });
  assert.deepEqual(insertAt("select * from t", 7, 8, "MEASURE(revenue)"), { text: "select MEASURE(revenue) from t", cursor: 23 });
});
