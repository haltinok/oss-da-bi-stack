// The recent-dashboards list of the start page (dashboard/static/lib/recent.js): `node --test dashboard/cube/tests/recent.test.mjs`
import assert from "node:assert/strict";
import { test } from "node:test";
import { MAX_RECENT, cleanRecent, noteRecent, pushRecent, readRecent } from "../../static/lib/recent.js";

const memory = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }; };

test("the newest visit comes first and a repeat visit moves, not duplicates", () => {
  let l = pushRecent([], { kind: "built", id: "a", title: "A" }, 1);
  l = pushRecent(l, { kind: "saved", id: "b", title: "B" }, 2);
  l = pushRecent(l, { kind: "built", id: "a", title: "A again" }, 3);
  assert.deepEqual(l.map((x) => [x.kind, x.id, x.title, x.at]), [["built", "a", "A again", 3], ["saved", "b", "B", 2]]);
});

test("a built and a saved dashboard with the same id are two dashboards", () => {
  const l = pushRecent(pushRecent([], { kind: "built", id: "x", title: "" }, 1), { kind: "saved", id: "x", title: "" }, 2);
  assert.equal(l.length, 2);
});

test("only the last few are kept", () => {
  let l = [];
  for (let i = 0; i < MAX_RECENT + 5; i++) l = pushRecent(l, { kind: "built", id: `d${i}`, title: "" }, i);
  assert.equal(l.length, MAX_RECENT);
  assert.equal(l[0].id, `d${MAX_RECENT + 4}`);
});

test("what comes out of storage is made safe", () => {
  assert.deepEqual(cleanRecent("nonsense"), []);
  assert.deepEqual(cleanRecent([{ kind: "evil", id: "x", at: 1 }, { kind: "built", id: "", at: 1 }, null, { kind: "built", id: "ok", at: 5 }, { kind: "saved", id: "later", at: 9 }]).map((x) => x.id), ["later", "ok"]);
});

test("storage that throws or holds junk gives an empty list and never an error", () => {
  const broken = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.deepEqual(readRecent(broken), []);
  assert.equal(noteRecent({ kind: "built", id: "a", title: "A" }, broken), false);
  const junk = { getItem: () => "{not json", setItem() {} };
  assert.deepEqual(readRecent(junk), []);
});

test("noteRecent then readRecent round-trips", () => {
  const s = memory();
  noteRecent({ kind: "built", id: "a", title: "A" }, s, 1);
  noteRecent({ kind: "saved", id: "b", title: "B" }, s, 2);
  assert.deepEqual(readRecent(s).map((x) => x.id), ["b", "a"]);
});
