// Colour rules (dashboard/static/lib/rules.js): the first rule that matches gives the tone.
//   node --test dashboard/cube/tests/rules.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { CUES, toneCue, toneOf, toneWord } from "../../static/lib/rules.js";

const R = [{ when: "below", value: 0.2, tone: "bad" }, { when: "below", value: 0.3, tone: "warn" }, { when: "at_least", value: 0.3, tone: "good" }];

test("the first matching rule wins, in order", () => {
  assert.equal(toneOf(R, 0.1), "bad", "below 0.2 is also below 0.3, the first rule decides");
  assert.equal(toneOf(R, 0.25), "warn");
  assert.equal(toneOf(R, 0.3), "good");
});

test("each comparison, at the edge", () => {
  const t = (when, v) => toneOf([{ when, value: 10, tone: "good" }], v);
  assert.deepEqual([t("below", 10), t("below", 9), t("above", 10), t("above", 11), t("at_most", 10), t("at_most", 11), t("at_least", 10), t("at_least", 9)],
    [null, "good", null, "good", "good", null, "good", null]);
});

test("no rules, no value, or a value that is not a number gives no tone", () => {
  assert.equal(toneOf(undefined, 1), null);
  assert.equal(toneOf([], 1), null);
  assert.equal(toneOf(R, null), null);
  assert.equal(toneOf(R, undefined), null);
  assert.equal(toneOf(R, NaN), null);
  assert.equal(toneOf(R, "abc"), null);
  assert.equal(toneOf(R, 0.9), "good");
  assert.equal(toneOf([{ when: "sideways", value: 1, tone: "bad" }], 1), null, "an unknown comparison matches nothing");
});

test("a tone is a symbol for the eye and a word for a screen reader", () => {
  assert.deepEqual(CUES, { good: "✓", warn: "!", bad: "✕" });
  assert.match(toneCue("bad"), /aria-hidden="true">✕</);
  assert.match(toneWord("warn", { warn: "uyarı" }), /sr-only"> \(uyarı\)/);
  assert.equal(toneCue(null) + toneWord(null), "");
});
