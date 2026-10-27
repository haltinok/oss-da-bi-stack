// Unit tests for the shared dashboard modules (dashboard/static/lib): formatting, chart geometry, the xlsx writer.
//   node --test dashboard/cube/tests/lib.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { createFormat, ratio } from "../../static/lib/format.js";
import { arcPath, barPath, niceTicks, pieSlices, shade, squarify, stackBarHtml } from "../../static/lib/charts.js";
import { buildXlsx } from "../../static/lib/xlsx.js";
import { fold, words, matches, filterItems } from "../../static/lib/search.js";

test("en-US / USD formats as the dashboard always did", () => {
  const f = createFormat({ locale: "en-US", currency: "USD" });
  assert.equal(f.money(1290), "$1.29K");
  assert.equal(f.money(0.87), "$0.87");
  assert.equal(f.money(-1500), "−$1.5K");
  assert.equal(f.money(null), "—");
  assert.equal(f.moneyFull(1234567.8), "$1,234,568");
  assert.equal(f.int(1479.4), "1,479");
  assert.equal(f.pct(0.153), "15.3%");
  assert.equal(f.pct(-0.0001), "0.0%", "no minus sign on a tiny negative");
  assert.equal(f.pct(Infinity), "—");
  assert.equal(f.decimal(12.46), "12.5");
  assert.equal(f.monthName(1), "Jan");
  assert.equal(f.monthName("2020-09-01"), "Sep");
});

test("tr-TR / TRY uses Turkish separators, the lira sign and Turkish month names", () => {
  const f = createFormat({ locale: "tr-TR", currency: "TRY" });
  assert.equal(f.symbol, "₺");
  assert.equal(f.int(1234567), "1.234.567");
  assert.equal(f.money(12.5), "₺12,50");
  assert.match(f.moneyFull(1500), /₺1\.500/);
  assert.equal(f.monthName(2), "Şub");
  assert.equal(f.pct(0.153), "%15,3", "the percent sign goes where Turkish puts it");
  assert.equal(f.pct(-0.153, 0), "−%15");
  assert.equal(f.pct(-0.00001), "%0,0");
});

test("ratio is null when the denominator is zero or a value is missing", () => {
  assert.equal(ratio(1, 4), 0.25);
  assert.equal(ratio(1, 0), null);
  assert.equal(ratio(null, 4), null);
});

test("niceTicks covers the range with round steps", () => {
  const t = niceTicks(0, 1830);
  assert.equal(t[0], 0);
  assert.ok(t.at(-1) >= 1830);
  assert.deepEqual(t, [0, 500, 1000, 1500, 2000]);
  assert.deepEqual(niceTicks(5, 5).length > 1, true, "a flat range still gets an axis");
});

test("barPath draws nothing for an empty bar and a closed path otherwise", () => {
  assert.equal(barPath(0, 0, 10, 0), "");
  assert.equal(barPath(0, 0, 0, 10), "");
  assert.match(barPath(10, 20, 30, 40), /^M10,60V24Q10,20 14,20H36Q40,20 40,24V60Z$/);
});

test("squarify tiles the whole rectangle in proportion to the values", () => {
  const items = [{ value: 6 }, { value: 6 }, { value: 4 }, { value: 3 }, { value: 2 }, { value: 2 }, { value: 1 }];
  const out = squarify(items, 0, 0, 600, 400);
  assert.equal(out.length, items.length);
  const area = out.reduce((s, r) => s + r.w * r.h, 0);
  assert.ok(Math.abs(area - 600 * 400) < 1e-6, `areas add up to the rectangle (${area})`);
  for (const r of out) {
    assert.ok(r.x >= -1e-9 && r.y >= -1e-9 && r.x + r.w <= 600 + 1e-9 && r.y + r.h <= 400 + 1e-9, "inside the rectangle");
    assert.ok(Math.abs((r.w * r.h) / (600 * 400) - r.value / 24) < 1e-9, "area proportional to value");
  }
  assert.deepEqual(squarify([], 0, 0, 10, 10), []);
  assert.deepEqual(squarify([{ value: 1 }], 0, 0, 0, 10), []);
});

test("shade steps through the hue's shades and falls back for an unknown category", () => {
  const palette = { Bikes: { hue: "#6250d6", lightTextFrom: 78 } };
  const fallback = { hue: "#898781" };
  // the darkest shades (>= lightTextFrom % of the hue) take light text
  assert.deepEqual(shade(palette, fallback, "Bikes", 0), { fill: "#6250d6", light: true });
  assert.deepEqual(shade(palette, fallback, "Bikes", 1), { fill: "color-mix(in oklab, #6250d6 78%, #fcfcfb)", light: true });
  assert.deepEqual(shade(palette, fallback, "Bikes", 2), { fill: "color-mix(in oklab, #6250d6 62%, #fcfcfb)", light: false });
  assert.equal(shade(palette, fallback, "Bikes", 6).fill, "#6250d6", "wraps around");
  assert.equal(shade(palette, fallback, "Nope", 0).fill, "#898781");
});

test("stackBarHtml scales parts against the max and skips empty parts", () => {
  const html = stackBarHtml([{ value: 25, color: "red" }, { value: 0, color: "green" }, { value: 75, color: "blue" }], 100);
  assert.equal(html, '<div class="hbar"><i style="width:25%;background:red"></i><i style="width:75%;background:blue"></i></div>');
});

test("buildXlsx writes a zip with the workbook parts", async () => {
  const blob = buildXlsx([{ name: "Sales", title: "T", subtitle: "S", columns: [{ label: "Product", type: "text" }, { label: "Revenue", type: "money" }], rows: [["Helmet", 12.5], ["Jersey", null]] }]);
  const bytes = new Uint8Array(await blob.arrayBuffer());
  assert.equal(String.fromCharCode(bytes[0], bytes[1]), "PK");
  const text = new TextDecoder("latin1").decode(bytes);
  for (const part of ["[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml"]) assert.ok(text.includes(part), part);
  assert.ok(text.includes("Helmet") && text.includes("12.5"));
});

test("buildXlsx formats money with the page's currency sign", async () => {
  const sheet = [{ name: "S", title: "T", subtitle: "", columns: [{ label: "A", type: "money" }], rows: [[1.5]] }];
  const text = async (opts) => new TextDecoder("utf-8").decode(new Uint8Array(await buildXlsx(sheet, opts).arrayBuffer()));
  assert.ok((await text({ symbol: "₺" })).includes('formatCode="&quot;₺&quot;#,##0.00"'), "the lira sign is in the number format");
  assert.ok((await text()).includes('formatCode="&quot;$&quot;#,##0.00"'), "the dollar sign is the default");
});

test("arcPath draws a slice, a donut segment and a full circle", () => {
  assert.equal(arcPath(100, 100, 50, 0, 0, Math.PI / 2), "M100,100L100,50A50,50 0 0 1 150,100Z");
  const seg = arcPath(100, 100, 50, 25, 0, Math.PI);
  assert.match(seg, /^M100,50A50,50 0 0 1 100,150L100,125A25,25 0 0 0 100,75Z$/);
  assert.match(arcPath(100, 100, 50, 0, 0, 2 * Math.PI), /^M100,50A50,50 0 1 1 100,150A50,50 0 1 1 100,50Z$/);
  assert.equal((arcPath(100, 100, 50, 25, 0, 2 * Math.PI).match(/Z/g) || []).length, 2, "a full donut is two rings");
  assert.match(arcPath(100, 100, 50, 0, 0, 4), /A50,50 0 1 1/, "a slice over half the circle takes the long way");
});

test("pieSlices keeps the largest slices, groups the rest, and drops zero and negative values", () => {
  const items = [{ label: "a", value: 5 }, { label: "b", value: 50 }, { label: "c", value: 0 }, { label: "d", value: 20 }, { label: "e", value: 10 }, { label: "f", value: -3 }];
  assert.deepEqual(pieSlices(items, 8, "Other").map((s) => s.label), ["b", "d", "e", "a"]);
  const grouped = pieSlices(items, 3, "Other");
  assert.deepEqual(grouped.map((s) => s.label), ["b", "d", "Other"]);
  assert.deepEqual(grouped[2], { label: "Other", value: 15, other: true, count: 2 });
  assert.deepEqual(pieSlices([], 5, "Other"), []);
});

// ---- search
test("fold ignores case and accents with Turkish rules, and dotless i is i", () => {
  assert.equal(fold("Satış"), "satis");
  assert.equal(fold("SATIŞ"), "satis");
  assert.equal(fold("İstanbul ışık"), "istanbul isik");
  assert.equal(fold("ISI haritası"), "isi haritasi", "capital I is dotless in Turkish and still meets i");
  assert.equal(fold("Çok güzel öğrenci ÜRÜN"), "cok guzel ogrenci urun");
  assert.equal(fold("Café"), "cafe");
  assert.equal(fold(null), "");
  assert.equal(fold(undefined), "");
  assert.equal(fold(42), "42");
});

test("words splits a query on any spaces and drops the empty ones", () => {
  assert.deepEqual(words("  Revenue   by\tregion "), ["revenue", "by", "region"]);
  assert.deepEqual(words("   "), []);
  assert.deepEqual(words(""), []);
});

test("matches needs every word, in any order, anywhere in the text; an empty query matches everything", () => {
  assert.ok(matches("Sales overview: revenue and margin", "margin sales"));
  assert.ok(matches("Sales overview", "OVERVIEW"));
  assert.ok(matches("Sales overview", "ales ove"), "a part of a word is enough");
  assert.ok(!matches("Sales overview", "sales inventory"));
  assert.ok(matches("anything", ""));
  assert.ok(matches("anything", "   "));
  assert.ok(matches("Envanter sağlığı", "saglig"), "ğ and ı fold");
  assert.ok(!matches("Envanter sağlığı", "saglik"), "no stemming: sağlık and sağlığı differ by a letter, as in Turkish itself");
  assert.ok(matches("Satış panosu", "SATIS"));
  assert.ok(matches("Ürün stok", "urun"));
});

test("a query is plain text: pattern characters mean themselves", () => {
  assert.ok(!matches("Sales overview", "("));
  assert.ok(!matches("Sales overview", ".*"));
  assert.ok(matches("Margin (%) by region", "(%)"));
  assert.ok(matches("a+b", "a+b"));
  assert.ok(!matches("aab", "a+b"));
  assert.ok(!matches("Sales", "\\"));
});

test("filterItems keeps the matching items in their order, over named fields or functions of the item", () => {
  const items = [{ title: "Sales overview", description: "Revenue by region", owner: "olga" }, { title: "Stok raporu", description: "Ürün", owner: "ahmet" }, { title: "Pivot gallery", description: "", owner: null }];
  assert.deepEqual(filterItems(items, "olga", ["title", "owner"]).map((i) => i.title), ["Sales overview"]);
  assert.deepEqual(filterItems(items, "olga", ["title"]).map((i) => i.title), [], "only the fields it was told to look in");
  assert.deepEqual(filterItems(items, "urun", ["title", "description"]).map((i) => i.title), ["Stok raporu"]);
  assert.deepEqual(filterItems(items, "", ["title"]), items, "no query, everything");
  assert.deepEqual(filterItems(items, "pivot", ["title", (i) => i.owner]).map((i) => i.title), ["Pivot gallery"], "a null field does not break it");
  assert.deepEqual(filterItems(items, "o", [(i) => i.title.toUpperCase()]).map((i) => i.title), ["Sales overview", "Stok raporu", "Pivot gallery"]);
});
