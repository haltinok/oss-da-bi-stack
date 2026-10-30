// DOM for each panel type. A panel is created from its compiled definition and a context (formatting, the Cube runner, tooltips, the
// page's filter values and `pick`); `load(signal)` runs its queries and draws, and `sheet()` returns the loaded data as an Excel sheet.
import { el, esc, svgEl } from "../lib/dom.js";
import { niceTicks, barPath, sparkline, stackBarHtml, squarify, shade, arcPath, pieSlices } from "../lib/charts.js";
import { addTimers } from "../lib/timer.js";
import { pinTotals, pivotHtml, tableHtml } from "../lib/table.js";
import { toneCue, toneOf, toneWord } from "../lib/rules.js";
import { AGGREGATE_LIMIT, grandAggregates, groupAggregates } from "../lib/aggregate.js";
import {
  activeFilters, appliesPeriod, barQueries, byBucket, byDims, colorOf, evaluate, humanize, isSelected, kpiQueries, markdown, num, ownFilterIds, parsePeriod,
  PERIOD, periodKey, timeDimOf, heatScale, nextSort, sortKeyOf, pieQueries, pivotColumn, pivotModel, pivotQueries, pivotShare, rangeOf, runAll, PIVOT_LIMIT, tableOrder, tableParts, tableQueries, term, timeKey, tableTotalQueries, timeseriesQueries, totals, treemapQueries, yearOf,
} from "./plan.js";

const XLSX_TYPE = { money: "money", int: "int", pct: "pct", number: "number", decimal: "number", year: "text" };

/** Why a query failed, in words a reader can act on (Cube answers `{ error }`; the client puts it in the message). */
export function readable(e) {
  const m = String(e?.message || e || "").trim();
  if (/<html|<!doctype/i.test(m)) return "The service answered with a web page instead of data (is it reachable?)";
  return m.length > 240 ? `${m.slice(0, 240)}…` : m || "The query failed";
}

export function createPanel(def, ctx) {
  const make = { kpi: kpiPanel, timeseries: timeseriesPanel, bar: barPanel, pie: piePanel, treemap: treemapPanel, table: tablePanel, pivot: pivotPanel, text: textPanel, slicer: slicerPanel }[def.type] || unsupportedPanel;
  const panel = make(def, ctx);
  addTimers(panel.root);
  return panel;
}

// ------------------------------------------------------------------------------------------------------------------ shared card
function card(def, ctx, { table = true, hint = "", extra = "" } = {}) {
  const root = el("section", { class: "card", "data-panel": def.id });
  const click = def.drill ? ctx.t.drillHint : ownFilterIds(def).length ? ctx.t.clickHint : "";
  root.innerHTML = `<div class="card-h"><div><h2>${esc(def.title || "")}</h2>${hint || click ? `<div class="hint">${esc(hint || click)}</div>` : ""}</div><div class="spacer"></div>${extra}${
    table ? `<button class="tbl-toggle" aria-pressed="false">${esc(ctx.t.table)}</button>` : ""}<button class="tbl-toggle xls-btn" title="${esc(ctx.t.downloadPanel)}">${esc(ctx.t.excel)}</button></div><div class="panel-body"></div>`;
  return { root, body: root.querySelector(".panel-body") };
}

/**
 * A panel whose body is drawn from a model { columns, rows, draw(host) } built by `fetchModel(signal)`: dimmed while it loads, a readable
 * error in place of the body when it fails, a Table view of the same rows, and an Excel sheet of them. `cacheKey()` names what the queries
 * depend on: when it has not changed since the last load the panel only redraws (a click on this panel changes its selection, not its data).
 */
const withTotal = (rows, totals) => (!totals ? rows : totals.position === "header" ? [totals.cells.map((v) => v ?? ""), ...rows] : [...rows, totals.cells.map((v) => v ?? "")]);

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
  const toggle = root.querySelector(".tbl-toggle:not(.xls-btn):not(.tot-btn)");
  toggle?.addEventListener("click", () => { tableView = !tableView; toggle.setAttribute("aria-pressed", String(tableView)); redraw(); });
  root.querySelector(".xls-btn").addEventListener("click", () => model && ctx.exportSheets([sheet()], def.title || def.id));
  const sheet = () => model && ({
    name: (def.title || def.id).slice(0, 31), title: def.title || def.id, subtitle: ctx.subtitle(),
    ...(model.toSheet ? model.toSheet() : {
      columns: model.columns.map((c) => ({ label: c.label, type: c.type })),
      rows: withTotal(model.rows.map((r) => model.columns.map((c) => c.get(r))), model.totals),
    }),
  });
  new ResizeObserver(() => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => !tableView && body.clientWidth > 0 && model?.redrawOnResize && redraw(), 120); }).observe(body);          // a hidden tab has no width: redrawn when it is shown
  return {
    root, sheet, redraw,
    async load(signal, { force = false } = {}) {
      const key = JSON.stringify([opts.cacheKey?.(), activeFilters(ctx.spec, ctx.filterValues(), def), appliesPeriod(ctx.spec, def) ? ctx.filterValues()[periodKey(ctx.spec, timeDimOf(ctx.spec, def))] : ""]);
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

/** A key figure's colour: the tone its rules give the value, as a class on the tile plus a symbol and a hidden word inside the value (never colour alone). */
function toneTile(tile, rules, value, words = {}) {
  const tone = toneOf(rules, value), box = tile.querySelector(".value");
  tile.classList.remove("tone-good", "tone-warn", "tone-bad");
  if (!tone) return;
  tile.classList.add(`tone-${tone}`);
  box.insertAdjacentHTML("afterbegin", toneCue(tone));
  box.insertAdjacentHTML("beforeend", toneWord(tone, words));
}
const clickable = (node, fn) => {
  node.classList.add("clickable");
  node.setAttribute("role", "button");
  node.addEventListener("click", fn);
  node.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(); } });
};

// ------------------------------------------------------------------------------------------------------------------ kpi
function kpiPanel(def, ctx) {
  const terms = def.measures.map(term);
  const root = el("section", { class: "kpis dyn", "data-panel": def.id, style: `--cols:${Math.max(terms.length, 4)}` });
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
      toneTile(tile, def.measures[i].rules, v, ctx.t.tones);
      tile.querySelector(".delta").textContent = "";
      tile.querySelector("svg.spark")?.remove();
      if (series) {
        const key = timeKey(timeDimOf(ctx.spec, def), spark.granularity);
        const buckets = byBucket(series, key);
        const line = buckets.map((b) => evaluate(t, (m) => b.values.get(m) ?? null));
        const full = ctx.formatter(t.format, true);
        tile.append(sparkline(line, (li, lv) => ctx.t.sparkAria(t.label, ctx.t.granularities?.[spark.granularity] ?? spark.granularity, ctx.bucketLabel(buckets[li].bucket, spark.granularity), fmtOf(t)(lv)), {
          tip: (i, v) => ctx.tooltip.tipAttr(ctx.tooltip.tipLines(ctx.bucketLabel(buckets[i].bucket, spark.granularity), [[t.label, full(v)]])),
        }));
      }
    } catch (e) {
      if (e?.name === "AbortError" || signal?.aborted) throw e;
      values[i] = null;
      tile.querySelector(".value").textContent = "—";
      toneTile(tile, null, null);
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
      const key = JSON.stringify([activeFilters(ctx.spec, ctx.filterValues(), def), appliesPeriod(ctx.spec, def) ? ctx.filterValues()[periodKey(ctx.spec, timeDimOf(ctx.spec, def))] : ""]);
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
  const levels = def.drill || null;                                  // a drill-down: year > month > day
  const grans = def.granularities || [];
  let gran = levels ? levels[0] : def.granularity;
  let path = levels ? ctx.drillPath(def.id) : [];                    // the buckets drilled into, coarse to fine (kept in the URL)
  const level = () => (levels ? levels[Math.min(path.length, levels.length - 1)] : gran);
  const dim = timeDimOf(ctx.spec, def);                              // the date field this chart is on (a drill-down sets the period of that field)
  const ownRange = () => (path.length ? rangeOf(path.at(-1), levels[path.length - 1]) : null);
  const same = (a, b) => !!a && !!b && a[0] === b[0] && a[1] === b[1];
  const switcher = grans.length > 1 && !levels
    ? `<div class="seg" role="group" aria-label="${esc(ctx.t.granularity)}">${grans.map((g) => `<button type="button" data-g="${g}" aria-pressed="${g === gran}">${esc(ctx.t.granularities[g] || g)}</button>`).join("")}</div>` : "";
  const goTo = (i) => { path = path.slice(0, i + 1); ctx.setDrill(def.id, path); ctx.setPeriod(i >= 0 ? rangeOf(path[i], levels[i]) : null, dim); };
  const hooks = levels ? {
    // a click opens the next level for that period and filters the other panels to it; on the last level it picks the day (again: back to the period above)
    onPoint(bucket) {
      const i = path.length, last = i >= levels.length - 1;
      if (!last) { path = [...path, String(bucket).slice(0, 10)]; ctx.setDrill(def.id, path); ctx.setPeriod(rangeOf(bucket, levels[i]), dim); return; }
      const mine = rangeOf(bucket, levels[i]);
      ctx.setPeriod(same(ctx.period(dim), mine) ? ownRange() : mine, dim);
    },
    selected: (bucket) => (path.length >= levels.length - 1 ? same(ctx.period(dim), rangeOf(bucket, levels[levels.length - 1])) : null),
    crumbs() {
      const nav = el("nav", { class: "crumbs", "aria-label": ctx.t.drillHint });
      const items = [{ label: ctx.t.all, i: -1 }, ...path.map((b, i) => ({ label: ctx.bucketLabel(b, levels[i]), i }))];
      items.forEach((it, n) => {
        if (n) nav.append(el("span", { class: "sep", "aria-hidden": "true" }, "›"));
        const last = n === items.length - 1;
        const b = el("button", { type: "button", class: `crumb${last ? " now" : ""}`, ...(last ? { "aria-current": "true" } : {}) }, esc(it.label));
        if (!last) b.addEventListener("click", () => goTo(it.i));
        nav.append(b);
      });
      return nav;
    },
  } : null;
  const panel = modelPanel(def, ctx, async (signal) => {
    const g = level();
    const res = await runAll(ctx.run, timeseriesQueries(ctx.spec, def, ctx.filterValues(), g, levels ? ownRange() : null), signal);
    const rows = byBucket(res, timeKey(dim, g)).map(({ bucket, values }) => ({
      bucket, label: ctx.bucketLabel(bucket, g), v: series.map((s) => evaluate(s, (m) => values.get(m) ?? null)),
    }));
    return {
      rows, redrawOnResize: true,
      columns: [colOf(ctx.t.period, "text", (r) => r.label, (v) => v), ...series.map((s, i) => colOf(s.label, XLSX_TYPE[s.format || "number"] || "number", (r) => r.v[i], ctx.formatter(s.format)))],
      draw: (host) => drawTimeseries(host, rows, series, style, g, ctx, def, hooks),
    };
  }, { extra: switcher, cacheKey: () => (levels ? path.join(",") : gran) });
  for (const b of panel.root.querySelectorAll(".seg button")) {
    b.addEventListener("click", () => {
      gran = b.dataset.g;
      for (const x of panel.root.querySelectorAll(".seg button")) x.setAttribute("aria-pressed", String(x === b));
      panel.load(new AbortController().signal).catch(() => {});
    });
  }
  if (levels) ctx.onPeriodCleared(() => { path = []; ctx.setDrill(def.id, []); }, dim);     // the chip's x or Reset filters brings the chart back to the top level
  return panel;
}

function drawTimeseries(host, rows, series, style, granularity, ctx, def, hooks = null) {
  const W = Math.max(320, host.clientWidth || 640), H = 250, L = 54, R = 8, T = 10, B = 26;
  const area = style === "area" || style === "stacked-area", stackedArea = style === "stacked-area";
  const stacked = style === "stacked-bar" || stackedArea;
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
  const picked = hooks ? rows.some((x) => hooks.selected(x.bucket) === true) : false;       // a drill-down on its last level with a day chosen
  const dimmed = (r) => (hooks ? picked && hooks.selected(r.bucket) !== true : !!chosen && String(yearFor(r.bucket)) !== String(chosen));
  host.innerHTML = "";
  if (hooks) host.append(hooks.crumbs());
  if (series.length > 1) host.append(el("div", { class: "legend" }, series.map((s) => `<span><i class="swatch" style="background:${s.color}"></i>${esc(s.label)}</span>`).join("")));
  const chart = el("div", { class: "chart" });
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": ctx.t.seriesAria(series.map((s) => s.label).join(", "), ctx.t.granularities?.[granularity] ?? granularity) });
  for (const t of ticks) {
    svg.append(svgEl("line", { x1: L, x2: W - R, y1: y(t), y2: y(t), class: t === 0 ? "base-line" : "grid-line" }));
    const lab = svgEl("text", { x: L - 8, y: y(t) + 4, "text-anchor": "end" });
    lab.textContent = fmtTick(t);
    svg.append(lab);
  }
  const step = Math.max(1, Math.ceil(46 / band));
  const cxOf = (i) => L + band * (i + 0.5);
  rows.forEach((r, i) => {
    if (i % step === 0) { const t = svgEl("text", { x: cxOf(i), y: H - 8, "text-anchor": "middle" }); t.textContent = ctx.shortBucketLabel(r.bucket, granularity); svg.append(t); }
  });
  if (style === "bar" || style === "stacked-bar") {
    rows.forEach((r, i) => {
      const cx = cxOf(i);
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
  } else if (stackedArea) {
    // each series fills the band between the running total below it and its own: the tops are cumulative
    const cum = rows.map((r) => { let acc = 0; return r.v.map((v) => (acc += Math.max(0, v || 0))); });
    series.forEach((s, k) => {
      const top = rows.map((_, i) => `${cxOf(i).toFixed(1)},${y(cum[i][k]).toFixed(1)}`);
      const bottom = rows.map((_, i) => `${cxOf(i).toFixed(1)},${y(k ? cum[i][k - 1] : 0).toFixed(1)}`).reverse();
      svg.append(svgEl("path", { d: `M${top.join("L")}L${bottom.join("L")}Z`, fill: s.color, "fill-opacity": 0.85, stroke: "var(--surface)", "stroke-width": 1 }));
    });
  } else {
    series.forEach((s, k) => {
      let d = "", prev = -2;
      const runs = [];
      rows.forEach((r, i) => {
        const v = r.v[k];
        if (v == null) return;
        d += `${i === prev + 1 ? "L" : "M"}${cxOf(i).toFixed(1)},${y(v).toFixed(1)}`;
        if (i === prev + 1) runs.at(-1).push(i); else runs.push([i]);
        prev = i;
      });
      if (area) {
        for (const run of runs) {
          const pts = run.map((i) => `${cxOf(i).toFixed(1)},${y(rows[i].v[k]).toFixed(1)}`);
          svg.append(svgEl("path", { d: `M${pts.join("L")}L${cxOf(run.at(-1)).toFixed(1)},${y(0).toFixed(1)}L${cxOf(run[0]).toFixed(1)},${y(0).toFixed(1)}Z`, fill: s.color, "fill-opacity": 0.18 }));
        }
      }
      svg.append(svgEl("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round" }));
      rows.forEach((r, i) => r.v[k] != null && svg.append(svgEl("circle", { cx: cxOf(i), cy: y(r.v[k]), r: 2.5, fill: s.color, class: dimmed(r) ? "dim" : "" })));
    });
  }
  const onPoint = hooks ? (bucket) => hooks.onPoint(bucket) : filter ? (bucket) => ctx.pick([filter.id], [yearFor(bucket)]) : null;
  rows.forEach((r, i) => {
    const lines = series.map((s, k) => [s.label, ctx.formatter(s.format, true)(r.v[k]), s.color]);
    if (stacked && series.length > 1) lines.push([ctx.t.total, ctx.formatter(series[0].format, true)(r.v.reduce((a, b) => a + (b || 0), 0))]);
    const hit = svgEl("rect", { class: "hit", x: L + band * i, y: T, width: band, height: H - T - B, tabindex: 0, "data-tip": ctx.tooltip.tipAttr(ctx.tooltip.tipLines(ctx.bucketLabel(r.bucket, granularity), lines)), "aria-label": `${ctx.bucketLabel(r.bucket, granularity)}: ${lines.map(([a, b]) => `${a} ${b}`).join(", ")}` });
    if (onPoint) {
      hit.addEventListener("click", () => onPoint(r.bucket));
      hit.addEventListener("keydown", (e) => { if (e.key === "Enter") onPoint(r.bucket); });
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
    const rankKey = sortKeyOf(ctx.spec, def.by);                  // a month's name sorts by its number
    for (const r of res.flatMap((x) => x.rows)) {
      const k = String(r[def.by]);
      if (!by.has(k)) by.set(k, { label: k, parts: new Map(), total: 0, rank: rankKey && r[rankKey] != null ? Number(r[rankKey]) : undefined });
      const cur = by.get(k);
      for (const m of measures) {
        if (!(m in r)) continue;
        const v = num(r[m]) || 0;
        const part = def.stack ? m : def.split ? String(r[def.split]) : m;
        cur.parts.set(part, (cur.parts.get(part) || 0) + v);
        cur.total += v;
      }
    }
    const byName = (a, b) => (a.rank !== undefined && b.rank !== undefined ? a.rank - b.rank : a.label.localeCompare(b.label, undefined, { numeric: true }));
    const rows = [...by.values()].sort((a, b) => (def.sort_by === "label" ? (sort === "asc" ? byName(a, b) : byName(b, a)) : sort === "asc" ? a.total - b.total : b.total - a.total)).slice(0, limit);
    const splits = def.split ? [...new Set(res[0].rows.map((r) => String(r[def.split])))].sort() : [];
    const parts = def.stack ? stack.map((s) => ({ key: s.member, name: s.label, color: s.color })) : splits.map((s, i) => ({ key: s, name: s, color: colorOf(null, i) }));
    const max = Math.max(...rows.map((r) => Math.abs(r.total)), 1);
    const type = XLSX_TYPE[def.format || "number"] || "number";
    const totalLabel = parts.length ? ctx.t.total : def.label || humanize(def.measure);
    return {
      rows, redrawOnResize: false,
      columns: [colOf(def.by_label || humanize(def.by), "text", (r) => r.label, (v) => v), ...parts.map((p) => colOf(p.name, type, (r) => r.parts.get(p.key) ?? 0, f)), colOf(totalLabel, type, (r) => r.total, f)],
      afterTable: (host) => ids.length && wireRows(host.querySelectorAll("tbody tr"), rows),
      redrawOnResize: def.orientation === "vertical",
      draw(host) {
        host.innerHTML = "";
        if (parts.length) host.append(el("div", { class: "legend" }, parts.map((p) => `<span><i class="swatch" style="background:${p.color}"></i>${esc(p.name)}</span>`).join("")));
        if (def.orientation === "vertical") { host.append(columnChart(rows, parts, ctx, def, f, fullF, totalLabel)); return; }
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

/** A bar panel drawn as columns (orientation: vertical): one column per row, stacked when there are parts; a click picks the row's filter. */
function columnChart(rows, parts, ctx, def, f, fullF, totalLabel) {
  const ids = ownFilterIds(def);
  const W = Math.max(320, ctx.bodyWidth(def.id)), H = 270, L = 54, R = 8, T = 10, B = 46;
  const ticks = niceTicks(0, Math.max(...rows.map((r) => Math.max(r.total, 0)), 1));
  const hi = ticks.at(-1);
  const y = (v) => T + (1 - v / (hi || 1)) * (H - T - B);
  const band = (W - L - R) / rows.length;
  const colW = Math.min(56, band * 0.7);
  const cur = ctx.filterValues();
  const picked = ids.length && rows.some((r) => isSelected(cur, ids, [r.label]));
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": def.title || humanize(def.by) });
  for (const t of ticks) {
    svg.append(svgEl("line", { x1: L, x2: W - R, y1: y(t), y2: y(t), class: t === 0 ? "base-line" : "grid-line" }));
    const lab = svgEl("text", { x: L - 8, y: y(t) + 4, "text-anchor": "end" });
    lab.textContent = f(t);
    svg.append(lab);
  }
  rows.forEach((r, i) => {
    const cx = L + band * (i + 0.5);
    const on = ids.length ? isSelected(cur, ids, [r.label]) : false;
    const g = svgEl("g", picked && !on ? { class: "dim" } : {});
    let acc = 0;
    const segs = parts.length ? parts.map((p) => ({ v: r.parts.get(p.key) || 0, color: p.color })) : [{ v: r.total, color: colorOf("internet", 0) }];
    segs.forEach((sg, k) => {
      if (sg.v <= 0) return;
      const y1 = y(acc + sg.v), h = y(acc) - y1;
      acc += sg.v;
      g.append(k === segs.length - 1 || segs.slice(k + 1).every((x) => x.v <= 0)
        ? svgEl("path", { d: barPath(cx - colW / 2, y1, colW, h, Math.min(4, colW / 3)), fill: sg.color }) : svgEl("rect", { x: cx - colW / 2, y: y1, width: colW, height: h, fill: sg.color }));
    });
    svg.append(g);
    const label = r.label.length > 14 ? `${r.label.slice(0, 13)}…` : r.label;
    const t = svgEl("text", { x: cx, y: H - B + 16, "text-anchor": rows.length > 6 ? "end" : "middle", ...(rows.length > 6 ? { transform: `rotate(-30 ${cx} ${H - B + 16})` } : {}) });
    t.textContent = label;
    svg.append(t);
    const lines = parts.map((p) => [p.name, fullF(r.parts.get(p.key) || 0), p.color]);
    const hit = svgEl("rect", { class: "hit", x: L + band * i, y: T, width: band, height: H - T, tabindex: 0, "aria-pressed": ids.length ? String(on) : undefined,
      "data-tip": ctx.tooltip.tipAttr(ctx.tooltip.tipLines(r.label, [...lines, [totalLabel, fullF(r.total)]])), "aria-label": `${r.label}: ${fullF(r.total)}` });
    if (ids.length) {
      hit.addEventListener("click", () => ctx.pick(ids, [r.label]));
      hit.addEventListener("keydown", (e) => { if (e.key === "Enter") ctx.pick(ids, [r.label]); });
    }
    svg.append(hit);
  });
  const chart = el("div", { class: "chart" });
  chart.append(svg);
  return chart;
}

// ------------------------------------------------------------------------------------------------------------------ pie
const PIE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6", "#e87ba4", "#2a9d8f", "#8d99ae", "#c0392b", "#7f8c8d"];

function piePanel(def, ctx) {
  const f = ctx.formatter(def.format), fullF = ctx.formatter(def.format, true), pctF = ctx.formatter("pct");
  const ids = ownFilterIds(def), limit = def.limit || 8, donut = (def.style || "donut") === "donut";
  const measures = def.sum || [def.measure];
  const measureLabel = def.label || humanize(measures[0]);                  // the author's word (a Turkish dashboard writes `label: Gelir`)
  const byLabel = def.by_label || humanize(def.by);
  return modelPanel(def, ctx, async (signal) => {
    const res = await runAll(ctx.run, pieQueries(ctx.spec, def, ctx.filterValues()), signal);
    const sums = new Map();                                                // slices of several cubes are added up by name
    for (const { rows } of res) for (const r of rows) sums.set(String(r[def.by]), (sums.get(String(r[def.by])) || 0) + measures.reduce((a, m) => a + (num(r[m]) || 0), 0));
    const slices = pieSlices([...sums].map(([label, value]) => ({ label, value })), limit, ctx.t.other);
    const total = slices.reduce((a, b) => a + b.value, 0);
    const rows = slices.map((s, i) => ({ ...s, share: total ? s.value / total : 0, color: s.other ? "#b8b8b0" : PIE[i % PIE.length] }));
    return {
      rows, redrawOnResize: true,
      columns: [colOf(byLabel, "text", (r) => r.label, (v) => v), colOf(measureLabel, XLSX_TYPE[def.format || "number"] || "number", (r) => r.value, f), colOf(ctx.t.share, "pct", (r) => r.share, pctF)],
      draw(host) {
        host.innerHTML = "";
        const cur = ctx.filterValues();
        const selected = (r) => !r.other && ids.length > 0 && isSelected(cur, ids, [r.label]);
        const picked = rows.some(selected);
        const size = Math.max(180, Math.min(260, ctx.bodyWidth(def.id) * 0.5 || 240)), R = size / 2 - 10, cx = size / 2, cy = size / 2;
        const wrap = el("div", { class: "pie" });
        const svg = svgEl("svg", { viewBox: `0 0 ${size} ${size}`, width: size, height: size, role: "img", "aria-label": def.title || humanize(def.by) });
        let angle = 0;
        const pick = (r) => { if (ids.length && !r.other) ctx.pick(ids, [r.label]); };
        for (const r of rows) {
          const a0 = angle, a1 = angle + r.share * 2 * Math.PI;
          angle = a1;
          if (r.share <= 0) continue;
          const mid = (a0 + a1) / 2, on = selected(r), out = on ? 7 : 0;
          const slice = svgEl("path", { d: arcPath(cx, cy, R, donut ? R * 0.58 : 0, a0, Math.max(a1, a0 + 0.0001)), fill: r.color, stroke: "var(--surface)", "stroke-width": 1.5, tabindex: 0,
            class: `slice${picked && !on ? " dim" : ""}${ids.length && !r.other ? " clickable" : ""}`, transform: out ? `translate(${(Math.sin(mid) * out).toFixed(1)},${(-Math.cos(mid) * out).toFixed(1)})` : undefined,
            "data-tip": ctx.tooltip.tipAttr(ctx.tooltip.tipLines(r.label, [[measureLabel, fullF(r.value)], [ctx.t.share, pctF(r.share)]])),
            "aria-label": `${r.label}: ${fullF(r.value)}, ${pctF(r.share)}`, ...(ids.length && !r.other ? { role: "button", "aria-pressed": String(on) } : {}) });
          slice.addEventListener("click", () => pick(r));
          slice.addEventListener("keydown", (e) => { if (e.key === "Enter") pick(r); });
          svg.append(slice);
        }
        if (donut) {
          const t1 = svgEl("text", { x: cx, y: cy - 2, "text-anchor": "middle", class: "pie-total" });
          t1.textContent = f(rows.reduce((a, b) => a + b.value, 0));
          const t2 = svgEl("text", { x: cx, y: cy + 15, "text-anchor": "middle", class: "pie-sub" });
          t2.textContent = ctx.t.total;
          svg.append(t1, t2);
        }
        wrap.append(svg);
        const legend = el("ul", { class: "pie-legend" });
        for (const r of rows) {
          const li = el("li", { class: `${selected(r) ? "sel" : ""}${ids.length && !r.other ? " clickable" : ""}` }, `<i class="swatch" style="background:${r.color}"></i><span class="name">${esc(r.label)}</span><span class="num">${esc(f(r.value))}</span><span class="pct">${esc(pctF(r.share))}</span>`);
          if (ids.length && !r.other) { li.tabIndex = 0; li.addEventListener("click", () => pick(r)); li.addEventListener("keydown", (e) => { if (e.key === "Enter") pick(r); }); }
          legend.append(li);
        }
        wrap.append(legend);
        host.append(wrap);
      },
    };
  }, { cacheKey: () => "pie" });
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
      columns: [colOf(def.group_labels?.[0] || humanize(d1), "text", (r) => r.a, (v) => v), ...(d2 ? [colOf(def.group_labels?.[1] || humanize(d2), "text", (r) => r.b, (v) => v)] : []),
        colOf(def.label || humanize(def.measure), XLSX_TYPE[def.format || "number"] || "number", (r) => r.value, f)],
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
          "data-tip": ctx.tooltip.tipAttr(ctx.tooltip.tipLines(nested ? `${s.a} › ${s.b}` : s.a, [[def.label || humanize(def.measure), fullF(s.value)], [ctx.t.share, ctx.formatter("pct")(s.value / total)]])),
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
  const { measures, dimensions, values: valueCols } = tableParts(def, ctx.spec.members);
  const kindOf = (m) => ctx.spec.members[m] || {};
  const aggOf = new Map(valueCols.map((v) => [v.member, v.aggregate]));
  // What an aggregated field comes out as: counts and sums and averages are numbers; max, min, first and last keep the field's own kind (a number, a date, or text).
  const aggKind = (m) => { const a = aggOf.get(m), t = kindOf(m).type; return ["sum", "avg", "count", "count_distinct"].includes(a) || t === "number" ? "number" : t === "time" ? "date" : "text"; };
  const colFor = (c) => {
    const m = c.member, kind = kindOf(m);
    const label = c.label || humanize(m);
    if (aggOf.has(m)) {
      const a = aggOf.get(m), k = aggKind(m), name = c.label || `${ctx.t.aggregates?.[a] || a} ${humanize(m)}`;
      const get = (r) => r.aggs?.get(m) ?? null;
      if (k === "number") { const f = c.format || (a.startsWith("count") ? "int" : undefined); return colOf(name, XLSX_TYPE[f || "number"] || "number", (r) => num(get(r)), ctx.formatter(f, true)); }
      if (k === "date") return colOf(name, "date", (r) => get(r) && String(get(r)).replace(/\.\d+$/, ""), (v) => (v ? ctx.dateTime(v) : ""));
      return colOf(name, "text", (r) => get(r), (v) => (v == null ? "" : String(v)));
    }
    if (kind.kind === "measure") return { ...colOf(label, XLSX_TYPE[c.format || "number"] || "number", (r) => r.values.get(m) ?? null, ctx.formatter(c.format, true)), ...(c.rules ? { tone: (v) => toneOf(c.rules, v) } : {}) };
    if (kind.type === "time") return colOf(label, "date", (r) => r.dims[m] && String(r.dims[m]).replace(/\.\d+$/, ""), (v) => (v ? ctx.dateTime(v) : ""));
    // A year is not a quantity: `year`, or an `int` format on a field named ..._year, is shown as the digits (2024, not 2,024).
    const yearLike = c.format === "year" || (c.format === "int" && /(^|_)year$/.test(m.split(".")[1]));
    if (yearLike) return colOf(label, "text", (r) => (r.dims[m] == null || r.dims[m] === "" ? "" : String(Math.round(Number(r.dims[m])))), (v) => v);
    if (c.format) return colOf(label, XLSX_TYPE[c.format] || "text", (r) => num(r.dims[m]), ctx.formatter(c.format, true));
    return colOf(label, "text", (r) => (r.dims[m] == null ? "" : String(r.dims[m])), (v) => v);
  };
  const shownCols = cols.filter((c) => !c.hidden);                    // a hidden field is queried (to sort or limit by) but not drawn, exported or totalled
  const columns = () => shownCols.map((c) => ({ ...colFor(c), sortKey: c.member }));
  // The viewer can hide the total row (a per-viewer view setting, like the Table toggle; the spec's `totals` says where it goes when shown).
  let showTotals = true;
  // The viewer's header click (see plan.js tableOrder): undefined = untouched, null = cleared, { member, dir }. Cube re-sorts, because `limit` cuts the rows.
  let sort;
  let sorting = null;
  const panel = modelPanel(def, ctx, async (signal) => {
    const order = Object.entries(tableOrder(def, dimensions, sort));
    const single = new Set(measures.map((m) => m.split(".")[0])).size <= 1 && !valueCols.length;          // with aggregated fields the rows are merged and ordered here
    const [res, tot] = await Promise.all([
      runAll(ctx.run, tableQueries(ctx.spec, def, ctx.filterValues(), sort), signal),
      // A failed total must not take the rows down with it: its cells show "–".
      runAll(ctx.run, tableTotalQueries(ctx.spec, def, ctx.filterValues()), signal).catch((e) => { if (signal?.aborted) throw e; return null; }),
    ]);
    // The rows of a table with aggregated fields: the measures grouped by the key columns, and the value fields aggregated over the rows of each group (one query of rows, `agg:<cube>`).
    const aggRes = res.filter((r) => String(r.cube).startsWith("agg:")), plain = res.filter((r) => !String(r.cube).startsWith("agg:"));
    const aggRows = aggRes.flatMap((r) => r.rows);
    let rows = valueCols.length && !measures.length ? [] : byDims(plain, dimensions);
    let aggTotals = null;
    const truncated = valueCols.length > 0 && aggRows.length >= AGGREGATE_LIMIT;
    if (valueCols.length) {
      const sortKeys = dimensions.map((d) => sortKeyOf(ctx.spec, d)).filter(Boolean);
      const groups = groupAggregates(aggRows, dimensions, valueCols, sortKeys);
      if (measures.length) for (const r of rows) r.aggs = groups.get(r.key)?.aggs ?? null;
      else rows = [...groups.values()].map((g) => ({ key: g.key, dims: g.dims, values: new Map(Object.entries(g.carried).map(([k, v]) => [k, num(v)])), aggs: g.aggs }));
      aggTotals = grandAggregates(aggRows, valueCols);
    }
    if (!single) {                                    // several measure cubes (or aggregated fields) were merged here: order and limit apply after the merge
      const get = (r, m) => (aggOf.has(m) ? r.aggs?.get(m) : kindOf(m).kind === "measure" ? r.values.get(m) : sortKeyOf(ctx.spec, m) ? r.values.get(sortKeyOf(ctx.spec, m)) : r.dims[m]);          // a month's name sorts by its number
      const cmp = (x, y) => (x == null) - (y == null) || (x !== "" && y !== "" && isFinite(x) && isFinite(y) ? x - y : x > y ? 1 : x < y ? -1 : 0);
      for (const [m, dir] of [...order].reverse()) rows.sort((a, b) => cmp(get(a, m), get(b, m)) * (dir === "desc" ? -1 : 1));
      rows = rows.slice(0, def.limit || 100);
    }
    // A click on a row sets each named filter from the row's value of that filter's dimension.
    const filterDims = ids.map((id) => ctx.spec.filters.find((x) => x.id === id).dimension);
    const rowValues = (r) => filterDims.map((d) => String(r.dims[d] ?? ""));
    // The total row: dimension cells empty, each measure as Cube aggregated it over the whole set (a ratio is the set's ratio, not an average of rows).
    let totalsRow = null;
    if (def.totals) {
      const t = tot && totals(tot);
      totalsRow = { position: def.totals, cells: shownCols.map((c) => (aggOf.has(c.member) ? (aggTotals?.get(c.member) ?? null) : kindOf(c.member).kind === "measure" ? (t?.get(c.member) ?? null) : undefined)) };
    }
    const draw = (host) => {
      const shown = showTotals ? totalsRow : null;
      host.innerHTML = tableHtml({ columns: columns(), rows, totals: shown, sort, toneWords: ctx.t.tones });
      if (truncated) host.insertAdjacentHTML("beforeend", `<div class="pivot-note">${esc(ctx.t.aggTruncated(AGGREGATE_LIMIT))}</div>`);
      if (shown?.position === "header") pinTotals(host);
      host.querySelectorAll("th.sortable").forEach((h) => {
        const go = () => sortBy(h.dataset.sort);
        h.addEventListener("click", go);
        h.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
      });
      if (!ids.length) return;
      host.querySelectorAll("tbody tr").forEach((tr, i) => {
        clickable(tr, () => ctx.pick(ids, rowValues(rows[i])));
        tr.classList.toggle("sel", isSelected(ctx.filterValues(), ids, rowValues(rows[i])));
      });
    };
    return { rows, columns: columns(), draw, get totals() { return showTotals ? totalsRow : null; } };
  }, { table: false, extra: def.totals ? `<button class="tbl-toggle tot-btn" aria-pressed="true">${esc(ctx.t.totals)}</button>` : "" });
  function sortBy(member) {
    sort = nextSort(sort, member, kindOf(member).kind === "measure" || (aggOf.has(member) && aggKind(member) === "number"));
    sorting?.abort();
    sorting = new AbortController();
    panel.load(sorting.signal, { force: true }).catch(() => {});      // an older click's answer must not land after a newer one
  }
  const totBtn = panel.root.querySelector(".tot-btn");
  totBtn?.addEventListener("click", () => { showTotals = !showTotals; totBtn.setAttribute("aria-pressed", String(showTotals)); panel.redraw(); });
  return panel;
}

// ------------------------------------------------------------------------------------------------------------------ pivot
function pivotPanel(def, ctx) {
  const ids = ownFilterIds(def);
  const dimOf = (id) => ctx.spec.filters.find((x) => x.id === id).dimension;
  const share = def.show && def.show !== "value" ? def.show : null;           // the cells as shares of a total: percentages, whatever the measure's own format
  const measures = def.measures.map((m) => ({ member: m.member, label: m.label || humanize(m.member), fmt: share ? ctx.formatter("pct") : ctx.formatter(m.format, true), type: share ? "pct" : XLSX_TYPE[m.format || "number"] || "number" }));
  const rowLabels = def.rows.map(humanize);
  const { member: colMember, granularity: gran } = pivotColumn(def);
  const colLabel = gran ? (bucket) => ctx.shortBucketLabel(bucket, gran) : (key) => key;
  const heatMeasure = def.heat && measures.find((m) => m.member === def.heat.measure);
  const lim = { ...PIVOT_LIMIT, ...def.limit };
  const waves = async (queries, signal, hard = []) => Object.fromEntries(await Promise.all(Object.entries(queries).map(async ([k, qs]) => {
    try { return [k, await runAll(ctx.run, qs, signal)]; }
    catch (e) { if (signal?.aborted || hard.includes(k)) throw e; return [k, []]; }       // a failed total leaves a dash, not a blank panel
  })));
  return modelPanel(def, ctx, async (signal) => {
    const values = ctx.filterValues();
    const axes = await waves(pivotQueries(ctx.spec, def, values).axes, signal, ["rows", "groups", "cols"]);
    const chosen = pivotModel(def, axes, {});
    if (!chosen.rows.length || !chosen.cols.length) return { rows: [], columns: [], draw() {} };
    const answers = await waves(pivotQueries(ctx.spec, def, values, { rows: chosen.rows.map((r) => r.keys), cols: chosen.cols }).values, signal, ["cells", "groupCells"]);
    const model = pivotModel(def, axes, answers);
    const shown = share ? pivotShare(model, share) : model;                 // what is drawn and exported; clicks use `model` (same rows and columns)
    const rowTot = model.totals === "both" || model.totals === "rows";
    // What a click on a piece of the pivot carries: the dimensions of its row (or group) and column, for the filters whose dimension is among them.
    const carry = ({ r, g, c }) => {
      const dims = {};
      if (r !== undefined) def.rows.forEach((d, i) => { dims[d] = model.rows[r].keys[i]; });
      else if (g !== undefined) dims[def.rows[0]] = model.groups[g].key;
      if (c !== undefined && !gran) dims[colMember] = model.cols[c];          // a time column carries no filter
      const use = ids.filter((id) => dimOf(id) in dims);
      return { ids: use, values: use.map((id) => dims[dimOf(id)]) };
    };
    const draw = (host) => {
      const notes = [model.hidden.rows && ctx.t.moreRows(lim.rows), model.hidden.cols && ctx.t.moreCols(lim.columns), model.truncated && ctx.t.truncatedPivot].filter(Boolean);
      const scale = heatMeasure && heatScale(shown, heatMeasure.member);
      const colTitle = `${humanize(colMember)}${gran ? ` (${ctx.t.granularities?.[gran] || gran})` : ""}`;
      host.innerHTML = pivotHtml({
        model: shown, measures, heat: scale && { member: heatMeasure.member, level: scale.level },
        texts: { corner: `${rowLabels.join(" / ")} ↓ · ${colTitle} →`, total: ctx.t.total, notes, colLabel,
          legend: scale && { label: `${ctx.t.shading}: ${heatMeasure.label}`, min: heatMeasure.fmt(scale.min), max: heatMeasure.fmt(scale.max) } },
      });
      pinTotals(host);
      if (!ids.length) return;
      host.querySelectorAll("[data-r], [data-g], [data-c]").forEach((node) => {
        const at = Object.fromEntries(["r", "g", "c"].map((k) => [k, node.dataset[k] === undefined ? undefined : +node.dataset[k]]));
        const { ids: use, values: vals } = carry(at);
        if (!use.length) return;
        clickable(node, () => ctx.pick(use, vals));
        // Marked when its own selection is the whole selection: a cell when both its row and column are chosen, a title when only it is.
        const cur = ctx.filterValues();
        node.classList.toggle("sel", isSelected(cur, use, vals) && ids.every((id) => use.includes(id) || !cur[id]));
      });
    };
    // Excel: one row per pivot row (a group is a row of its own with its figures), a column per column and measure, then the totals.
    const toSheet = () => {
      const several = measures.length > 1, labelCols = shown.groups ? 2 : 1;
      const colName = (name, m) => (several ? `${name} · ${m.label}` : name);
      const cellsOf = (maps) => maps.flatMap((map) => measures.map((m) => map?.get(m.member) ?? null));
      const totalOf = (map) => (rowTot ? measures.map((m) => map?.get(m.member) ?? null) : []);
      const columns = [...rowLabels.map((label) => ({ label, type: "text" })).slice(0, labelCols), ...shown.cols.flatMap((c) => measures.map((m) => ({ label: colName(colLabel(c), m), type: m.type }))),
        ...(rowTot ? measures.map((m) => ({ label: colName(ctx.t.total, m), type: m.type })) : [])];
      const leafRow = (r) => [...(shown.groups ? ["", r.keys[1]] : [r.keys[0]]), ...cellsOf(r.cells), ...totalOf(r.total)];
      const rows = shown.groups ? shown.groups.flatMap((g) => [[g.key, "", ...cellsOf(g.cells), ...totalOf(g.total)], ...g.rows.map(leafRow)]) : shown.rows.map(leafRow);
      if (shown.totals === "both" || shown.totals === "columns") rows.push([ctx.t.total, ...(labelCols > 1 ? [""] : []), ...cellsOf(shown.colTotals), ...totalOf(shown.grand)]);
      return { columns, rows };
    };
    return { rows: model.rows, columns: [], draw, toSheet };
  }, { table: false });
}

// ------------------------------------------------------------------------------------------------------------------ text / unsupported
function textPanel(def, ctx) {
  const root = el("section", { class: "card text-panel", "data-panel": def.id });
  root.innerHTML = `${def.title ? `<div class="card-h"><div><h2>${esc(def.title)}</h2></div></div>` : ""}<div class="md">${markdown(def.markdown, esc)}</div>`;
  return { root, redraw() {}, load: async () => {}, sheet: () => null };
}

/** A slicer: a filter drawn in the layout. It has no data of its own; the page puts the filter's control into `.slicer-body` (render/main.js `attach`). */
function slicerPanel(def) {
  const root = el("section", { class: "card slicer-panel", "data-panel": def.id });
  root.innerHTML = `${def.title ? `<div class="card-h"><div><h2>${esc(def.title)}</h2></div></div>` : ""}<div class="slicer-body"></div>`;
  return { root, redraw() {}, load: async () => {}, sheet: () => null };
}

function unsupportedPanel(def, ctx) {
  const { root, body } = card(def, ctx, { table: false });
  root.querySelector(".xls-btn").remove();
  body.innerHTML = `<div class="empty">The '${esc(def.type)}' panel is not drawn by this renderer.</div>`;
  return { root, redraw() {}, load: async () => {}, sheet: () => null };
}
