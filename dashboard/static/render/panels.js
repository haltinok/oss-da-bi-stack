// DOM for each panel type. A panel is created from its compiled definition and a context (formatting, the Cube runner, tooltips, the
// page's filter values and `pick`); `load(signal)` runs its queries and draws, and `sheet()` returns the loaded data as an Excel sheet.
import { el, esc, svgEl } from "../lib/dom.js";
import { niceTicks, barPath, sparkline, stackBarHtml, squarify, shade } from "../lib/charts.js";
import { tableHtml } from "../lib/table.js";
import {
  activeFilters, barQueries, byBucket, byDims, colorOf, evaluate, humanize, isSelected, kpiQueries, markdown, num, ownFilterIds, runAll, tableParts,
  tableQueries, term, timeKey, timeseriesQueries, totals, treemapQueries, yearOf,
} from "./plan.js";

const XLSX_TYPE = { money: "money", int: "int", pct: "pct", number: "number", decimal: "number" };

/** Why a query failed, in words a reader can act on (Cube answers `{ error }`; the client puts it in the message). */
export function readable(e) {
  const m = String(e?.message || e || "").trim();
  if (/<html|<!doctype/i.test(m)) return "The service answered with a web page instead of data (is it reachable?)";
  return m.length > 240 ? `${m.slice(0, 240)}…` : m || "The query failed";
}

export function createPanel(def, ctx) {
  const make = { kpi: kpiPanel, timeseries: timeseriesPanel, bar: barPanel, treemap: treemapPanel, table: tablePanel, text: textPanel }[def.type] || unsupportedPanel;
  return make(def, ctx);
}

// ------------------------------------------------------------------------------------------------------------------ shared card
function card(def, ctx, { table = true, hint = "", extra = "" } = {}) {
  const root = el("section", { class: "card", "data-panel": def.id });
  const click = ownFilterIds(def).length ? ctx.t.clickHint : "";
  root.innerHTML = `<div class="card-h"><div><h2>${esc(def.title || "")}</h2>${hint || click ? `<div class="hint">${esc(hint || click)}</div>` : ""}</div><div class="spacer"></div>${extra}${
    table ? `<button class="tbl-toggle" aria-pressed="false">${esc(ctx.t.table)}</button>` : ""}<button class="tbl-toggle xls-btn" title="${esc(ctx.t.downloadPanel)}">${esc(ctx.t.excel)}</button></div><div class="panel-body"></div>`;
  return { root, body: root.querySelector(".panel-body") };
}

/**
 * A panel whose body is drawn from a model { columns, rows, draw(host) } built by `fetchModel(signal)`: dimmed while it loads, a readable
 * error in place of the body when it fails, a Table view of the same rows, and an Excel sheet of them. `cacheKey()` names what the queries
 * depend on: when it has not changed since the last load the panel only redraws (a click on this panel changes its selection, not its data).
 */
function modelPanel(def, ctx, fetchModel, opts = {}) {
  const { root, body } = card(def, ctx, opts);
  let model = null, tableView = false, resizeTimer = 0, loadedKey = null;
  const redraw = () => {
    if (!model) return;
    body.innerHTML = "";
    body.style.height = "";
    if (!model.rows.length) { body.innerHTML = `<div class="empty">${esc(ctx.t.noRows)}</div>`; return; }
    if (tableView) { body.innerHTML = tableHtml({ columns: model.columns, rows: model.rows }); model.afterTable?.(body); } else model.draw(body);
  };
  const toggle = root.querySelector(".tbl-toggle:not(.xls-btn)");
  toggle?.addEventListener("click", () => { tableView = !tableView; toggle.setAttribute("aria-pressed", String(tableView)); redraw(); });
  root.querySelector(".xls-btn").addEventListener("click", () => model && ctx.exportSheets([sheet()], def.title || def.id));
  const sheet = () => model && ({
    name: (def.title || def.id).slice(0, 31), title: def.title || def.id, subtitle: ctx.subtitle(),
    columns: model.columns.map((c) => ({ label: c.label, type: c.type })), rows: model.rows.map((r) => model.columns.map((c) => c.get(r))),
  });
  new ResizeObserver(() => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => !tableView && model?.redrawOnResize && redraw(), 120); }).observe(body);
  return {
    root, sheet, redraw,
    async load(signal, { force = false } = {}) {
      const key = JSON.stringify([opts.cacheKey?.(), activeFilters(ctx.spec, ctx.filterValues(), def)]);
      if (model && !force && key === loadedKey) { redraw(); return; }
      root.classList.add("pending");
      try {
        model = await fetchModel(signal);
        loadedKey = key;
        root.classList.remove("error");
        redraw();
      } catch (e) {
        if (e?.name === "AbortError" || signal?.aborted) throw e;
        model = null;
        loadedKey = null;
        root.classList.add("error");
        body.innerHTML = `<div class="panel-error" role="alert">${esc(readable(e))}</div>`;
        console.warn(`panel ${def.id} failed:`, e?.message || e);
      } finally {
        if (!signal?.aborted) root.classList.remove("pending");
      }
    },
  };
}

const colOf = (label, type, get, fmt) => ({ label, type, get, fmt });
const clickable = (node, fn) => {
  node.classList.add("clickable");
  node.setAttribute("role", "button");
  node.addEventListener("click", fn);
  node.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(); } });
};

// ------------------------------------------------------------------------------------------------------------------ kpi
function kpiPanel(def, ctx) {
  const terms = def.measures.map(term);
  const root = el("section", { class: "kpis dyn", "data-panel": def.id, style: `--cols:${terms.length}` });
  const tiles = terms.map((t) => {
    const tile = el("div", { class: "card kpi" }, `<div class="label">${esc(t.label)}</div><div class="value">…</div><div class="delta"></div>`);
    root.append(tile);
    return tile;
  });
  const values = terms.map(() => null);
  const fmtOf = (t) => ctx.formatter(t.format);
  let loadedKey = null;
  const tileLoad = async (t, i, signal) => {
    const tile = tiles[i];
    tile.classList.add("pending");
    const spark = def.sparkline;
    const q = kpiQueries(ctx.spec, def, t, ctx.filterValues());
    try {
      const [now, series] = await Promise.all([runAll(ctx.run, q.now, signal), q.series ? runAll(ctx.run, q.series, signal) : null]);
      const v = evaluate(t, (m) => totals(now).get(m) ?? null);
      values[i] = v;
      tile.querySelector(".value").textContent = fmtOf(t)(v);
      tile.querySelector(".delta").textContent = "";
      tile.querySelector("svg.spark")?.remove();
      if (series) {
        const key = timeKey(ctx.spec.time.dimension, spark.granularity);
        const buckets = byBucket(series, key);
        const line = buckets.map((b) => evaluate(t, (m) => b.values.get(m) ?? null));
        tile.append(sparkline(line, (li, lv) => `${t.label} by ${spark.granularity}, latest ${ctx.bucketLabel(buckets[li].bucket, spark.granularity)}: ${fmtOf(t)(lv)}`));
      }
    } catch (e) {
      if (e?.name === "AbortError" || signal?.aborted) throw e;
      values[i] = null;
      tile.querySelector(".value").textContent = "—";
      tile.querySelector(".delta").textContent = readable(e);
      tile.querySelector(".delta").title = readable(e);
      console.warn(`kpi ${t.label} failed:`, e?.message || e);
    } finally {
      if (!signal?.aborted) tile.classList.remove("pending");
    }
  };
  return {
    root,
    redraw() {},
    sheet: () => ({
      name: (def.title || "Key figures").slice(0, 31), title: def.title || "Key figures", subtitle: ctx.subtitle(),
      columns: [{ label: ctx.t.measure, type: "text" }, { label: ctx.t.value, type: "text" }],
      rows: terms.map((t, i) => [t.label, { v: values[i], t: XLSX_TYPE[t.format] || "number" }]),
    }),
    load(signal, { force = false } = {}) {
      const key = JSON.stringify(activeFilters(ctx.spec, ctx.filterValues(), def));
      if (!force && key === loadedKey) return Promise.resolve();
      loadedKey = key;
      return Promise.all(terms.map((t, i) => tileLoad(t, i, signal))).then(() => {}, (e) => { loadedKey = null; throw e; });
    },
  };
}

// ------------------------------------------------------------------------------------------------------------------ timeseries
function timeseriesPanel(def, ctx) {
  const series = def.series.map((s, i) => { const t = term(s); return { ...t, label: s.label || humanize(t.members[0]), color: colorOf(s.color, i) }; });
  const style = def.style || "line";
  const grans = def.granularities || [];
  let gran = def.granularity;
  const switcher = grans.length > 1
    ? `<div class="seg" role="group" aria-label="${esc(ctx.t.granularity)}">${grans.map((g) => `<button type="button" data-g="${g}" aria-pressed="${g === gran}">${esc(ctx.t.granularities[g] || g)}</button>`).join("")}</div>` : "";
  const panel = modelPanel(def, ctx, async (signal) => {
    const res = await runAll(ctx.run, timeseriesQueries(ctx.spec, def, ctx.filterValues(), gran), signal);
    const rows = byBucket(res, timeKey(ctx.spec.time.dimension, gran)).map(({ bucket, values }) => ({
      bucket, label: ctx.bucketLabel(bucket, gran), v: series.map((s) => evaluate(s, (m) => values.get(m) ?? null)),
    }));
    return {
      rows, redrawOnResize: true,
      columns: [colOf(ctx.t.period, "text", (r) => r.label, (v) => v), ...series.map((s, i) => colOf(s.label, XLSX_TYPE[s.format || "number"] || "number", (r) => r.v[i], ctx.formatter(s.format)))],
      draw: (host) => drawTimeseries(host, rows, series, style, gran, ctx, def),
    };
  }, { extra: switcher, cacheKey: () => gran });
  for (const b of panel.root.querySelectorAll(".seg button")) {
    b.addEventListener("click", () => {
      gran = b.dataset.g;
      for (const x of panel.root.querySelectorAll(".seg button")) x.setAttribute("aria-pressed", String(x === b));
      panel.load(new AbortController().signal).catch(() => {});
    });
  }
  return panel;
}

function drawTimeseries(host, rows, series, style, granularity, ctx, def) {
  const W = Math.max(320, host.clientWidth || 640), H = 250, L = 54, R = 8, T = 10, B = 26;
  const stacked = style === "stacked-bar";
  const totalsOf = (r) => r.v.map((x) => x || 0);
  const hiV = Math.max(0, ...rows.map((r) => (stacked ? totalsOf(r).filter((x) => x > 0).reduce((a, b) => a + b, 0) : Math.max(...totalsOf(r)))));
  const loV = Math.min(0, ...rows.map((r) => (stacked ? totalsOf(r).filter((x) => x < 0).reduce((a, b) => a + b, 0) : Math.min(...totalsOf(r)))));
  const ticks = niceTicks(loV, hiV || 1);
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const y = (v) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
  const band = (W - L - R) / rows.length;
  const fmtTick = ctx.formatter(series[0].format);
  // A click sets a year filter: the bars of other years are dimmed while one is selected.
  const ids = ownFilterIds(def);
  const filter = ctx.spec.filters.find((f) => f.id === ids[0]);
  const yearKind = filter?.dimension.split(".")[1];
  const yearFor = (bucket) => yearOf(bucket, ctx.spec.time.fiscal_year_start || 1, yearKind);
  const chosen = filter ? ctx.filterValues()[filter.id] : "";
  const dimmed = (r) => !!chosen && String(yearFor(r.bucket)) !== String(chosen);
  host.innerHTML = "";
  if (series.length > 1) host.append(el("div", { class: "legend" }, series.map((s) => `<span><i class="swatch" style="background:${s.color}"></i>${esc(s.label)}</span>`).join("")));
  const chart = el("div", { class: "chart" });
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": `${series.map((s) => s.label).join(", ")} by ${granularity}` });
  for (const t of ticks) {
    svg.append(svgEl("line", { x1: L, x2: W - R, y1: y(t), y2: y(t), class: t === 0 ? "base-line" : "grid-line" }));
    const lab = svgEl("text", { x: L - 8, y: y(t) + 4, "text-anchor": "end" });
    lab.textContent = fmtTick(t);
    svg.append(lab);
  }
  const step = Math.max(1, Math.ceil(46 / band));
  rows.forEach((r, i) => {
    const cx = L + band * (i + 0.5);
    if (i % step === 0) { const t = svgEl("text", { x: cx, y: H - 8, "text-anchor": "middle" }); t.textContent = ctx.shortBucketLabel(r.bucket, granularity); svg.append(t); }
    if (style === "line") return;
    const g = svgEl("g", dimmed(r) ? { class: "dim" } : {});
    const barW = Math.min(48, band * 0.66);
    if (stacked) {
      let pos = 0, neg = 0;
      r.v.forEach((v, k) => {
        if (!v) return;
        const from = v >= 0 ? pos : neg, to = from + v;
        if (v >= 0) pos = to; else neg = to;
        const y1 = y(Math.max(from, to)), h = Math.abs(y(from) - y(to));
        const top = v >= 0 && !r.v.slice(k + 1).some((x) => x > 0);
        g.append(top && h > 0 ? svgEl("path", { d: barPath(cx - barW / 2, y1, barW, h, Math.min(4, barW / 3)), fill: series[k].color }) : svgEl("rect", { x: cx - barW / 2, y: y1, width: barW, height: h, fill: series[k].color }));
      });
    } else {
      const w = Math.min(28, (band * 0.7) / series.length);
      r.v.forEach((v, k) => {
        if (v == null) return;
        const x = cx - (w * series.length) / 2 + k * w, y1 = y(Math.max(0, v)), h = Math.abs(y(v) - y(0));
        g.append(svgEl("rect", { x, y: y1, width: Math.max(1, w - 1), height: h, fill: series[k].color }));
      });
    }
    svg.append(g);
  });
  if (style === "line") {
    series.forEach((s, k) => {
      let d = "", prev = -2;
      rows.forEach((r, i) => { const v = r.v[k]; if (v == null) return; d += `${i === prev + 1 ? "L" : "M"}${(L + band * (i + 0.5)).toFixed(1)},${y(v).toFixed(1)}`; prev = i; });
      svg.append(svgEl("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round" }));
      rows.forEach((r, i) => r.v[k] != null && svg.append(svgEl("circle", { cx: L + band * (i + 0.5), cy: y(r.v[k]), r: 2.5, fill: s.color, class: dimmed(r) ? "dim" : "" })));
    });
  }
  rows.forEach((r, i) => {
    const lines = series.map((s, k) => [s.label, ctx.formatter(s.format, true)(r.v[k]), s.color]);
    if (stacked && series.length > 1) lines.push([ctx.t.total, ctx.formatter(series[0].format, true)(r.v.reduce((a, b) => a + (b || 0), 0))]);
    const hit = svgEl("rect", { class: "hit", x: L + band * i, y: T, width: band, height: H - T - B, tabindex: 0, "data-tip": ctx.tooltip.tipAttr(ctx.tooltip.tipLines(ctx.bucketLabel(r.bucket, granularity), lines)), "aria-label": `${ctx.bucketLabel(r.bucket, granularity)}: ${lines.map(([a, b]) => `${a} ${b}`).join(", ")}` });
    if (filter) {
      hit.addEventListener("click", () => ctx.pick([filter.id], [yearFor(r.bucket)]));
      hit.addEventListener("keydown", (e) => { if (e.key === "Enter") ctx.pick([filter.id], [yearFor(r.bucket)]); });
    }
    svg.append(hit);
  });
  chart.append(svg);
  host.append(chart);
}

// ------------------------------------------------------------------------------------------------------------------ bar
function barPanel(def, ctx) {
  const f = ctx.formatter(def.format);
  const fullF = ctx.formatter(def.format, true);
  const ids = ownFilterIds(def);
  const stack = (def.stack || []).map((s, i) => ({ ...s, label: s.label || humanize(s.member), color: colorOf(s.color, i) }));
  const measures = def.stack ? stack.map((s) => s.member) : [def.measure];
  return modelPanel(def, ctx, async (signal) => {
    const sort = def.sort || "desc";
    const limit = def.limit || 10;
    const res = await runAll(ctx.run, barQueries(ctx.spec, def, ctx.filterValues()), signal);
    const by = new Map();
    for (const r of res.flatMap((x) => x.rows)) {
      const k = String(r[def.by]);
      if (!by.has(k)) by.set(k, { label: k, parts: new Map(), total: 0 });
      const cur = by.get(k);
      for (const m of measures) {
        if (!(m in r)) continue;
        const v = num(r[m]) || 0;
        const part = def.stack ? m : def.split ? String(r[def.split]) : m;
        cur.parts.set(part, (cur.parts.get(part) || 0) + v);
        cur.total += v;
      }
    }
    const rows = [...by.values()].sort((a, b) => (sort === "asc" ? a.total - b.total : b.total - a.total)).slice(0, limit);
    const splits = def.split ? [...new Set(res[0].rows.map((r) => String(r[def.split])))].sort() : [];
    const parts = def.stack ? stack.map((s) => ({ key: s.member, name: s.label, color: s.color })) : splits.map((s, i) => ({ key: s, name: s, color: colorOf(null, i) }));
    const max = Math.max(...rows.map((r) => Math.abs(r.total)), 1);
    const type = XLSX_TYPE[def.format || "number"] || "number";
    const totalLabel = parts.length ? ctx.t.total : humanize(def.measure);
    return {
      rows, redrawOnResize: false,
      columns: [colOf(humanize(def.by), "text", (r) => r.label, (v) => v), ...parts.map((p) => colOf(p.name, type, (r) => r.parts.get(p.key) ?? 0, f)), colOf(totalLabel, type, (r) => r.total, f)],
      afterTable: (host) => ids.length && wireRows(host.querySelectorAll("tbody tr"), rows),
      draw(host) {
        host.innerHTML = "";
        if (parts.length) host.append(el("div", { class: "legend" }, parts.map((p) => `<span><i class="swatch" style="background:${p.color}"></i>${esc(p.name)}</span>`).join("")));
        const list = el("div", { class: "rrows" });
        for (const r of rows) {
          const segs = parts.length ? parts.map((p) => ({ value: r.parts.get(p.key) || 0, color: p.color })) : [{ value: r.total, color: colorOf("internet", 0) }];
          const lines = parts.map((p) => [p.name, fullF(r.parts.get(p.key) || 0), p.color]);
          const row = el("div", { class: "rrow", tabindex: 0, "data-tip": ctx.tooltip.tipAttr(ctx.tooltip.tipLines(r.label, [...lines, [totalLabel, fullF(r.total)]])) },
            `<span class="name">${esc(r.label)}</span>${stackBarHtml(segs, max)}<span class="num">${esc(f(r.total))}</span>`);
          if (ids.length) {
            clickable(row, () => ctx.pick(ids, [r.label]));
            const on = isSelected(ctx.filterValues(), ids, [r.label]);
            row.classList.toggle("sel", on);
            row.setAttribute("aria-pressed", String(on));
          }
          list.append(row);
        }
        host.append(list);
      },
    };
  }, { cacheKey: () => "bar" });
  function wireRows(trs, rows) {
    trs.forEach((tr, i) => clickable(tr, () => ctx.pick(ids, [rows[i].label])));
  }
}

// ------------------------------------------------------------------------------------------------------------------ treemap
const HUES = [{ hue: "#6250d6", lightTextFrom: 78 }, { hue: "#1baf7a" }, { hue: "#e87ba4" }, { hue: "#eda100" }, { hue: "#2a78d6", lightTextFrom: 78 }, { hue: "#eb6834" }];

function treemapPanel(def, ctx) {
  const f = ctx.formatter(def.format);
  const fullF = ctx.formatter(def.format, true);
  const ids = ownFilterIds(def);
  const [d1, d2] = def.group;
  return modelPanel(def, ctx, async (signal) => {
    const res = await runAll(ctx.run, treemapQueries(ctx.spec, def, ctx.filterValues()), signal);
    const rows = res[0].rows.map((r) => ({ a: String(r[d1]), b: d2 ? String(r[d2]) : null, value: num(r[def.measure]) || 0 })).filter((r) => r.value > 0)
      .sort((x, y) => y.value - x.value);
    return {
      rows, redrawOnResize: true,
      columns: [colOf(humanize(d1), "text", (r) => r.a, (v) => v), ...(d2 ? [colOf(humanize(d2), "text", (r) => r.b, (v) => v)] : []),
        colOf(humanize(def.measure), XLSX_TYPE[def.format || "number"] || "number", (r) => r.value, f)],
      draw: (host) => drawTreemap(host, rows, !!d2),
    };
  });

  function drawTreemap(host, rows, nested) {
    const cur = ctx.filterValues();
    const W = Math.max(host.clientWidth, 260), H = W < 500 ? 380 : 330, HEAD = nested ? 20 : 0, GAP = 2;
    host.classList.add("tm");
    host.style.height = `${H}px`;
    const total = rows.reduce((s, r) => s + r.value, 0);
    const groups = new Map();
    for (const r of rows) {
      const g = groups.get(r.a) || { name: r.a, value: 0, subs: [] };
      g.value += r.value;
      g.subs.push(r);
      groups.set(r.a, g);
    }
    const order = [...groups.values()].sort((x, y) => y.value - x.value);
    const palette = Object.fromEntries(order.map((g, i) => [g.name, HUES[i % HUES.length]]));
    const pickIds = (n) => ids.slice(0, n);
    for (const g of squarify(order, 0, 0, W, H)) {
      const catSel = nested ? isSelected(cur, pickIds(2), [g.name], true) && !!ids.length : false;
      if (nested) {
        const lab = el("div", { class: `group-label${catSel ? " sel" : ""}`, tabindex: 0, "aria-pressed": String(catSel),
          style: `left:${g.x + 2}px;top:${g.y}px;width:${Math.max(0, g.w - 4)}px;height:${HEAD}px;line-height:${HEAD}px` },
        `${catSel ? "✓ " : ""}${esc(g.name)} · ${esc(f(g.value))}`);
        if (catSel) host.append(el("div", { class: "group-ring", "aria-hidden": "true", style: `left:${g.x}px;top:${g.y + HEAD}px;width:${g.w}px;height:${Math.max(0, g.h - HEAD)}px` }));
        if (ids.length) clickable(lab, () => ctx.pick(pickIds(1), [g.name]));
        host.append(lab);
      }
      const inner = squarify(g.subs.map((s) => ({ ...s })), g.x, g.y + HEAD, g.w, Math.max(0, g.h - HEAD));
      inner.forEach((s, i) => {
        const { fill, light } = shade(palette, HUES[0], g.name, i);
        const w = s.w - GAP, h = s.h - GAP;
        if (w < 1 || h < 1) return;
        const label = nested ? s.b : s.a;
        const isSel = ids.length ? (nested ? isSelected(cur, pickIds(2), [s.a, s.b]) : isSelected(cur, pickIds(1), [s.a])) : false;
        const cell = el("div", { class: `cell${light ? " ink-light" : ""}${isSel ? " sel" : ""}`, tabindex: 0, "aria-pressed": String(isSel),
          style: `left:${s.x + GAP / 2}px;top:${s.y + GAP / 2}px;width:${w}px;height:${h}px;background:${fill}`,
          "data-tip": ctx.tooltip.tipAttr(ctx.tooltip.tipLines(nested ? `${s.a} › ${s.b}` : s.a, [[humanize(def.measure), fullF(s.value)], [ctx.t.share, ctx.formatter("pct")(s.value / total)]])),
          "aria-label": `${label}: ${fullF(s.value)}` });
        const name = `${isSel ? "✓ " : ""}${esc(label)}`;
        if (w > 64 && h > 34) cell.innerHTML = `<div class="n">${name}</div><div class="v">${esc(f(s.value))}</div>`;
        else if (w > 48 && h > 20) cell.innerHTML = `<div class="n">${name}</div>`;
        if (ids.length) clickable(cell, () => ctx.pick(nested ? pickIds(2) : pickIds(1), nested ? [s.a, s.b] : [s.a]));
        host.append(cell);
      });
    }
  }
}

// ------------------------------------------------------------------------------------------------------------------ table
function tablePanel(def, ctx) {
  const cols = def.columns;
  const ids = ownFilterIds(def);
  const { measures, dimensions } = tableParts(def, ctx.spec.members);
  const kindOf = (m) => ctx.spec.members[m] || {};
  const colFor = (c) => {
    const m = c.member, kind = kindOf(m);
    const label = c.label || humanize(m);
    if (kind.kind === "measure") return colOf(label, XLSX_TYPE[c.format || "number"] || "number", (r) => r.values.get(m) ?? null, ctx.formatter(c.format, true));
    if (kind.type === "time") return colOf(label, "date", (r) => r.dims[m] && String(r.dims[m]).replace(/\.\d+$/, ""), (v) => (v ? ctx.dateTime(v) : ""));
    if (c.format) return colOf(label, XLSX_TYPE[c.format] || "text", (r) => num(r.dims[m]), ctx.formatter(c.format, true));
    return colOf(label, "text", (r) => (r.dims[m] == null ? "" : String(r.dims[m])), (v) => v);
  };
  return modelPanel(def, ctx, async (signal) => {
    const order = Object.entries(def.order || {});
    const single = new Set(measures.map((m) => m.split(".")[0])).size <= 1;
    const res = await runAll(ctx.run, tableQueries(ctx.spec, def, ctx.filterValues()), signal);
    let rows = byDims(res, dimensions);
    if (!single) {                                    // several measure cubes were merged here: order and limit apply after the merge
      const get = (r, m) => (kindOf(m).kind === "measure" ? r.values.get(m) : r.dims[m]);
      for (const [m, dir] of [...order].reverse()) rows.sort((a, b) => (get(a, m) > get(b, m) ? 1 : get(a, m) < get(b, m) ? -1 : 0) * (dir === "desc" ? -1 : 1));
      rows = rows.slice(0, def.limit || 100);
    }
    // A click on a row sets each named filter from the row's value of that filter's dimension.
    const filterDims = ids.map((id) => ctx.spec.filters.find((x) => x.id === id).dimension);
    const rowValues = (r) => filterDims.map((d) => String(r.dims[d] ?? ""));
    const draw = (host) => {
      host.innerHTML = tableHtml({ columns: cols.map(colFor), rows });
      if (!ids.length) return;
      host.querySelectorAll("tbody tr").forEach((tr, i) => {
        clickable(tr, () => ctx.pick(ids, rowValues(rows[i])));
        tr.classList.toggle("sel", isSelected(ctx.filterValues(), ids, rowValues(rows[i])));
      });
    };
    return { rows, columns: cols.map(colFor), draw };
  }, { table: false });
}

// ------------------------------------------------------------------------------------------------------------------ text / unsupported
function textPanel(def, ctx) {
  const root = el("section", { class: "card text-panel", "data-panel": def.id });
  root.innerHTML = `${def.title ? `<div class="card-h"><div><h2>${esc(def.title)}</h2></div></div>` : ""}<div class="md">${markdown(def.markdown, esc)}</div>`;
  return { root, redraw() {}, load: async () => {}, sheet: () => null };
}

function unsupportedPanel(def, ctx) {
  const { root, body } = card(def, ctx, { table: false });
  root.querySelector(".xls-btn").remove();
  body.innerHTML = `<div class="empty">The '${esc(def.type)}' panel is not drawn by this renderer.</div>`;
  return { root, redraw() {}, load: async () => {}, sheet: () => null };
}
