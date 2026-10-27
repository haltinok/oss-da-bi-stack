// The viewer's themes (dashboard/static/themes.css, lib/theme.js): every theme in the list has its tokens, and each one reads well on its own surface.
//   node --test dashboard/cube/tests/themes.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const css = readFileSync(new URL("../../static/themes.css", import.meta.url), "utf8");
const source = readFileSync(new URL("../../static/lib/theme.js", import.meta.url), "utf8");

const themes = {};
for (const m of css.matchAll(/:root\[data-theme="([a-z]+)"\]\s*\{([^}]*)\}/g)) {
  themes[m[1]] = Object.fromEntries([...m[2].matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)].map((t) => [t[1], t[2].trim()]));
}
const listed = [...source.matchAll(/\{ id: "([a-z]+)", name:/g)].map((m) => m[1]);

const lum = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  .reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
const ratio = (a, b) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };

const TOKENS = ["page", "surface", "surface-2", "ink", "ink-2", "muted", "grid", "axis", "border", "internet", "reseller", "good", "bad", "warn", "live", "neutral-mid", "focus", "on-focus", "shadow"];

test("every theme in the menu has a block in themes.css, and the other way round (light and dark live in style.css)", () => {
  assert.deepEqual(listed.filter((id) => id !== "light" && id !== "dark").sort(), Object.keys(themes).sort());
  assert.ok(listed.includes("light") && listed.includes("dark"));
  assert.equal(new Set(listed).size, listed.length, "no id twice");
});

test("each theme sets every token the pages read, as plain colours", () => {
  for (const [id, t] of Object.entries(themes)) {
    for (const k of TOKENS) assert.ok(k in t, `${id} lacks --${k}`);
    for (const k of ["page", "surface", "surface-2", "ink", "ink-2", "muted", "internet", "reseller", "good", "bad", "warn", "focus", "on-focus"]) assert.match(t[k], /^#[0-9a-f]{6}$/i, `${id} --${k}`);
  }
});

test("text reads on every surface: 4.5:1 for body, secondary and muted text, on the page, the cards and the shaded cells", () => {
  for (const [id, t] of Object.entries(themes)) {
    for (const bg of ["page", "surface", "surface-2"]) {
      for (const fg of ["ink", "ink-2", "muted"]) assert.ok(ratio(t[fg], t[bg]) >= 4.5, `${id}: ${fg} on ${bg} is ${ratio(t[fg], t[bg]).toFixed(2)}`);
    }
  }
});

test("series colours, status colours and the focus ring stand out from the card (3:1), and a primary button's text reads on --focus (4.5:1)", () => {
  for (const [id, t] of Object.entries(themes)) {
    for (const k of ["internet", "reseller", "good", "bad", "warn", "focus"]) assert.ok(ratio(t[k], t.surface) >= 3, `${id}: ${k} on surface is ${ratio(t[k], t.surface).toFixed(2)}`);
    assert.ok(ratio(t["on-focus"], t.focus) >= 4.5, `${id}: on-focus on focus is ${ratio(t["on-focus"], t.focus).toFixed(2)}`);
  }
});

test("the high-contrast theme reaches 7:1 for its text, and its lines are visible", () => {
  const t = themes.contrast;
  for (const k of ["ink", "ink-2", "muted"]) assert.ok(ratio(t[k], t.surface) >= 7, `${k} is ${ratio(t[k], t.surface).toFixed(2)}`);
  assert.ok(ratio(t.axis, t.surface) >= 3, "the axis line is 3:1");
  assert.ok(ratio(t.focus, t.page) >= 7, "the focus ring is 7:1");
});
