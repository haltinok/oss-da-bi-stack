// Chart primitives: geometry and small SVG pieces with no knowledge of any dashboard's data. Panels compose them.
import { svgEl } from "./dom.js";

/** Round axis ticks covering lo..hi with about `count` steps. */
export function niceTicks(lo, hi, count = 4) {
  if (hi === lo) hi = lo + 1;
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const start = Math.floor(lo / step) * step, end = Math.ceil(hi / step) * step;
  const ticks = [];
  for (let v = start; v <= end + step / 2; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

/** A bar whose data end (top) is rounded and whose baseline end is square. */
export function barPath(x, y, w, h, r = 4) {
  if (h <= 0 || w <= 0) return "";
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/** Squarified treemap: items [{ value, ... }] -> the same items with x, y, w, h filling the rectangle. */
export function squarify(items, x, y, w, h) {
  const total = items.reduce((s, i) => s + i.value, 0);
  const out = [];
  if (!total || w <= 0 || h <= 0) return out;
  const scale = (w * h) / total;
  const rest = items.map((i) => ({ ...i, area: i.value * scale })).sort((a, b) => b.area - a.area);
  const worst = (row, side) => {
    const s = row.reduce((a, r) => a + r.area, 0);
    return Math.max(...row.map((r) => Math.max((side * side * r.area) / (s * s), (s * s) / (side * side * r.area))));
  };
  while (rest.length) {
    const side = Math.min(w, h);
    const row = [rest.shift()];
    while (rest.length && worst([...row, rest[0]], side) <= worst(row, side)) row.push(rest.shift());
    const s = row.reduce((a, r) => a + r.area, 0);
    if (w >= h) {
      const rw = s / h; let yy = y;
      for (const r of row) { const rh = r.area / rw; out.push({ ...r, x, y: yy, w: rw, h: rh }); yy += rh; }
      x += rw; w -= rw;
    } else {
      const rh = s / w; let xx = x;
      for (const r of row) { const rw = r.area / rh; out.push({ ...r, x: xx, y, w: rw, h: rh }); xx += rw; }
      y += rh; h -= rh;
    }
  }
  return out;
}

/**
 * A category's tile colour: palette is { Category: { hue, lightTextFrom? } }, i is the item's rank inside the category (largest first),
 * so neighbouring tiles get the next shade of the same hue. -> { fill, light } (light: use light text on it).
 */
export const SHADES = [100, 78, 62, 50, 40, 32]; // % of the hue, mixed with white
export function shade(palette, fallback, category, i) {
  const { hue, lightTextFrom = Infinity } = palette[category] || fallback;
  const p = SHADES[i % SHADES.length];
  return { fill: p === 100 ? hue : `color-mix(in oklab, ${hue} ${p}%, #fcfcfb)`, light: p >= lightTextFrom };
}

/** Horizontal stacked bar as HTML: parts [{ value, color }] scaled against `max`. */
export function stackBarHtml(parts, max) {
  return `<div class="hbar">${parts.filter((p) => p.value > 0).map((p) => `<i style="width:${(p.value / max) * 100}%;background:${p.color}"></i>`).join("")}</div>`;
}

/**
 * A KPI sparkline: values (null = no value for that step), drawn as one line that breaks at gaps, ending in a dot.
 * ariaLabel(lastIndex, lastValue) -> the text for screen readers.
 */
export function sparkline(values, ariaLabel) {
  const W = 200, H = 34;
  const svg = svgEl("svg", { class: "spark", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", "aria-hidden": "true" });
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v != null && isFinite(v));
  if (pts.length < 2) return svg;
  const lo = Math.min(0, ...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1])) || 1;
  const x = (i) => (i / (values.length - 1)) * W;
  const y = (v) => H - 2 - ((v - lo) / (hi - lo || 1)) * (H - 6);
  // Break the line where a step has no value instead of interpolating across it.
  let d = "", prev = -2;
  for (const [i, v] of pts) { d += `${i === prev + 1 ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; prev = i; }
  svg.append(svgEl("path", { d, fill: "none", stroke: "var(--ink-2)", "stroke-width": 1.5, "vector-effect": "non-scaling-stroke", "stroke-linejoin": "round" }));
  const [li, lv] = pts[pts.length - 1];
  svg.append(svgEl("circle", { cx: x(li), cy: y(lv), r: 2.5, fill: "var(--ink)" }));
  svg.setAttribute("aria-label", ariaLabel(li, lv));
  return svg;
}

/**
 * The outline of a pie slice or a donut segment: centre (cx, cy), outer radius r, inner radius r0 (0 for a pie), from angle a0 to a1 in radians
 * (0 = 12 o'clock, clockwise). A slice that covers the whole circle is drawn as two halves, since one arc cannot start and end on the same point.
 */
export function arcPath(cx, cy, r, r0, a0, a1) {
  const pt = (rad, a) => [cx + rad * Math.sin(a), cy - rad * Math.cos(a)];
  const f = (n) => +n.toFixed(2);
  if (a1 - a0 >= 2 * Math.PI - 1e-6) {
    const ring = (rad, sweep) => `M${f(cx)},${f(cy - rad)}A${rad},${rad} 0 1 ${sweep} ${f(cx)},${f(cy + rad)}A${rad},${rad} 0 1 ${sweep} ${f(cx)},${f(cy - rad)}Z`;
    return r0 > 0 ? ring(r, 1) + ring(r0, 0) : ring(r, 1);
  }
  const large = a1 - a0 > Math.PI ? 1 : 0;
  const [x0, y0] = pt(r, a0), [x1, y1] = pt(r, a1);
  if (r0 <= 0) return `M${f(cx)},${f(cy)}L${f(x0)},${f(y0)}A${r},${r} 0 ${large} 1 ${f(x1)},${f(y1)}Z`;
  const [x2, y2] = pt(r0, a1), [x3, y3] = pt(r0, a0);
  return `M${f(x0)},${f(y0)}A${r},${r} 0 ${large} 1 ${f(x1)},${f(y1)}L${f(x2)},${f(y2)}A${r0},${r0} 0 ${large} 0 ${f(x3)},${f(y3)}Z`;
}

/** Slices for a pie: items [{ label, value }] (any order) -> the largest `limit - 1`, the rest grouped as one { label: otherLabel, other: true }; zero and negative values are dropped. */
export function pieSlices(items, limit, otherLabel) {
  const sorted = items.filter((i) => i.value > 0).sort((a, b) => b.value - a.value);
  if (sorted.length <= limit) return sorted;
  const head = sorted.slice(0, limit - 1), tail = sorted.slice(limit - 1);
  return [...head, { label: otherLabel, value: tail.reduce((a, b) => a + b.value, 0), other: true, count: tail.length }];
}
