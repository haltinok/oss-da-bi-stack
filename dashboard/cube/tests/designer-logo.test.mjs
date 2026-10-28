// The logo helpers (dashboard/static/lib/designer-logo.js).
//   node --test dashboard/cube/tests/designer-logo.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { ACCEPTED, ENCODINGS, MAX_LOGO_CHARS, fits, sizesToTry } from "../../static/lib/designer-logo.js";

test("sizes shrink step by step, keep the shape, and never grow a small picture", () => {
  assert.deepEqual(sizesToTry(400, 200), [{ w: 112, h: 56 }, { w: 80, h: 40 }, { w: 56, h: 28 }, { w: 40, h: 20 }]);
  assert.deepEqual(sizesToTry(30, 20), [{ w: 30, h: 20 }], "a picture smaller than every step stays as it is");
  assert.equal(sizesToTry(0, 10).length, 0);
  assert.equal(sizesToTry(5000, 100).length, 0, "a banner is not a logo");
  for (const s of sizesToTry(333, 111)) assert.ok(Math.abs(s.w / s.h - 3) < 0.1);
});

test("a result fits when it is an accepted image type within the limit", () => {
  assert.equal(fits("data:image/png;base64,AAAA"), true);
  assert.equal(fits("data:image/svg+xml;base64,AAAA"), false);
  assert.equal(fits("data:image/png;base64," + "A".repeat(MAX_LOGO_CHARS)), false);
  assert.equal(fits(null), false);
  assert.deepEqual(ACCEPTED, ["image/png", "image/jpeg", "image/webp"]);
  assert.equal(ENCODINGS[0].type, "image/png");
  assert.ok(ENCODINGS.filter((e) => e.type === "image/jpeg").every((e) => e.onWhite), "a JPEG is drawn on white, it has no transparency");
});
