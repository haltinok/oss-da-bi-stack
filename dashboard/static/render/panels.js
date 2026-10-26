// DOM for each panel type. A panel is created from its compiled definition and a context (formatting, the Cube runner, tooltips, the
// page's filter values); `load(signal)` runs its queries and draws, and `sheet()` returns the loaded data as an Excel sheet.
import { el, esc, svgEl } from "../lib/dom.js";
import { niceTicks, barPath, sparkline, stackBarHtml } from "../lib/charts.js";
import { tableHtml } from "../lib/table.js";
import {
  activeFilters, byBucket, byDims, colorOf, evaluate, humanize, markdown, num, queriesPerCube, runAll, tableParts, term, timeKey, totals,
} from "./plan.js";

const XLSX_TYPE = { money: "money", int: "int", pct: "pct", number: "number", decimal: "number" };

/** Why a query failed, in words a reader can act on (Cube answers `{ error }`; the client puts it in the message). */
export function readable(e) {
  const m = String(e?.message || e || "").trim();
  if (/<html|<!doctype/i.test(m)) return "The service answered with a web page instead of data (is it reachable?)";
  return m.length > 240 ? `${m.slice(0, 240)}…` : m || "The query failed";
}

export function createPanel(def, ctx) {
  const make = { kpi: kpiPanel, timeseries: timeseriesPanel, bar: barPanel, table: tablePanel, text: textPanel }[def.type] || unsupportedPanel;
  return make(def, ctx);
}

// ------------------------------------------------------------------------------------------------------------------ shared card
function card(def, ctx, { table = true, hint = "" } = {}) {
  const root = el("section", { class: "card", "data-panel": def.id });
  root.innerHTML = `<div class="card-h"><div><h2>${esc(def.title || "")}</h2>${hint ? `<div class="hint">${esc(hint)}</div>` : ""}</div><div class="spacer"></div>${
    table ? '<button class="tbl-toggle" aria-pressed="false">Table</button>' : ""}<button class="tbl-toggle xls-btn" title="Download this panel\'s data as an Excel file">Excel</button></div><div class="panel-body"></div>`;
  return { root, body: root.querySelector(".panel-body") };
}

/**
 * A panel whose body is drawn from a model { columns, rows, draw(host) } built by `fetchModel(signal)`: dimmed while it loads, a readable
 * error in place of the body when it fails, a Table view of the same rows, and an Excel sheet of them.
 */
function modelPanel(def, ctx, fetchModel, opts = {}) {
  const { root, body } = card(def, ctx, opts);
  let model = null, tableView = false, resizeTimer = 0;
  const redraw = () => {
    if (!model) return;
    body.innerHTML = "";
    if (!model.rows.length) { body.innerHTML = '<div class="empty">No rows match these filters</div>'; return; }
    if (tableView) body.innerHTML = tableHtml({ columns: model.columns, rows: model.rows });
    else model.draw(body);
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
    root, sheet,
    async load(signal) {
      root.classList.add("pending");
      try {
        model = await fetchModel(signal);
        root.classList.remove("error");
        redraw();
      } catch (e) {
        if (e?.name === "AbortError" || signal?.aborted) throw e;
        model = null;
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
  const tileLoad = async (t, i, signal) => {
    const tile = tiles[i];
    tile.classList.add("pending");
    const filters = activeFilters(ctx.spec, ctx.filterValues(), def);
    const spark = def.sparkline;
    try {
      const [now, series] = await Promise.all([
        runAll(ctx.run, queriesPerCube(t.members, { filters }), signal),
        spark ? runAll(ctx.run, queriesPerCube(t.members, { filters, timeDimensions: [{ dimension: ctx.spec.time.dimension, granularity: spark.granularity }] }), signal) : null,
      ]);
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
    sheet: () => ({
      name: (def.title || "Key figures").slice(0, 31), title: def.title || "Key figures", subtitle: ctx.subtitle(),
      columns: [{ label: "Measure", type: "text" }, { label: "Value", type: "text" }],
      rows: terms.map((t, i) => [t.label, { v: values[i], t: XLSX_TYPE[t.format] || "number" }]),
    }),
    load: (signal) => Promise.all(terms.map((t, i) => tileLoad(t, i, signal))).then(() => {}),
  };
}

// ------------------------------------------------------------------------------------------------------------------ timeseries
function timeseriesPanel(def, ctx) {
  const series = def.series.map((s, i) => ({ ...s, label: s.label || humanize(s.member), color: colorOf(s.color, i) }));
  const style = def.style || "line";
  return modelPanel(def, ctx, async (signal) => {
    const key = timeKey(ctx.spec.time.dimension, def.granularity);
    const res = await runAll(ctx.run, queriesPerCube(series.map((s) => s.member), {
      timeDimensions: [{ dimension: ctx.spec.time.dimension, granularity: def.granularity }], filters: activeFilters(ctx.spec, ctx.filterValues(), def),
    }), signal);
    const rows = byBucket(res, key).map(({ bucket, values }) => ({ bucket, label: ctx.bucketLabel(bucket, def.granularity), v: series.map((s) => values.get(s.member) ?? null) }));
    return {
      rows, redrawOnResize: true,
      columns: [colOf("Period", "text", (r) => r.label, (v) => v), ...series.map((s, i) => colOf(s.label, XLSX_TYPE[s.format || "number"] || "number", (r) => r.v[i], ctx.formatter(s.format)))],
      draw: (host) => drawTimeseries(host, rows, series, style, def.granularity, ctx),
    };
  });
}

function drawTimeseries(host, rows, series, style, granularity, ctx) {
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
    const barW = Math.min(48, band * 0.66);
    if (stacked) {
      let pos = 0, neg = 0;
      r.v.forEach((v, k) => {
        if (!v) return;
        const from = v >= 0 ? pos : neg, to = from + v;
        if (v >= 0) pos = to; else neg = to;
        const y1 = y(Math.max(from, to)), h = Math.abs(y(from) - y(to));
        const top = v >= 0 && !r.v.slice(k + 1).some((x) => x > 0);
        svg.append(top && h > 0 ? svgEl("path", { d: barPath(cx - barW / 2, y1, barW, h, Math.min(4, barW / 3)), fill: series[k].color }) : svgEl("rect", { x: cx - barW / 2, y: y1, width: barW, height: h, fill: series[k].color }));
      });
    } else {
      const w = Math.min(28, (band * 0.7) / series.length);
      r.v.forEach((v, k) => {
        if (v == null) return;
        const x = cx - (w * series.length) / 2 + k * w, y1 = y(Math.max(0, v)), h = Math.abs(y(v) - y(0));
        svg.append(svgEl("rect", { x, y: y1, width: Math.max(1, w - 1), height: h, fill: series[k].color }));
      });
    }
  });
  if (style === "line") {
    series.forEach((s, k) => {
      let d = "", prev = -2;
      rows.forEach((r, i) => { const v = r.v[k]; if (v == null) return; d += `${i === prev + 1 ? "L" : "M"}${(L + band * (i + 0.5)).toFixed(1)},${y(v).toFixed(1)}`; prev = i; });
      svg.append(svgEl("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round" }));
      rows.forEach((r, i) => r.v[k] != null && svg.append(svgEl("circle", { cx: L + band * (i + 0.5), cy: y(r.v[k]), r: 2.5, fill: s.color })));
    });
  }
  rows.forEach((r, i) => {
    const lines = series.map((s, k) => [s.label, ctx.formatter(s.format, true)(r.v[k]), s.color]);
    if (stacked && series.length > 1) lines.push(["Total", ctx.formatter(series[0].format, true)(r.v.reduce((a, b) => a + (b || 0), 0))]);
    svg.append(svgEl("rect", { class: "hit", x: L + band * i, y: T, width: band, height: H - T - B, tabindex: 0, "data-tip": ctx.tooltip.tipAttr(ctx.tooltip.tipLines(ctx.bucketLabel(r.bucket, granularity), lines)), "aria-label": `${ctx.bucketLabel(r.bucket, granularity)}: ${lines.map(([a, b]) => `${a} ${b}`).join(", ")}` }));
  });
  chart.append(svg);
  host.append(chart);
}

// ------------------------------------------------------------------------------------------------------------------ bar
function barPanel(def, ctx) {
  const f = ctx.formatter(def.format);
  const fullF = ctx.formatter(def.format, true);
  return modelPanel(def, ctx, async (signal) => {
    const dims = [def.by, ...(def.split ? [def.split] : [])];
    const sort = def.sort || "desc";
    const res = await runAll(ctx.run, queriesPerCube([def.measure], {
      dimensions: dims, filters: activeFilters(ctx.spec, ctx.filterValues(), def),
      // without a split the database ranks and limits; with one, the totals per `by` are needed first
      ...(def.split ? {} : { order: { [def.measure]: sort }, limit: def.limit || 10 }),
    }), signal);
    const by = new Map();
    for (const r of res[0].rows) {
      const k = String(r[def.by]);
      if (!by.has(k)) by.set(k, { label: k, parts: new Map(), total: 0 });
      const v = num(r[def.measure]) || 0;
      const cur = by.get(k);
      cur.parts.set(def.split ? String(r[def.split]) : def.measure, v);
      cur.total += v;
    }
    let rows = [...by.values()].sort((a, b) => (sort === "asc" ? a.total - b.total : b.total - a.total));
    rows = rows.slice(0, def.limit || 10);
    const splits = def.split ? [...new Set(res[0].rows.map((r) => String(r[def.split])))].sort() : [];
    const colors = splits.map((s, i) => colorOf(null, i));
    const max = Math.max(...rows.map((r) => Math.abs(r.total)), 1);
    return {
      rows, redrawOnResize: false,
      columns: [colOf(humanize(def.by), "text", (r) => r.label, (v) => v),
        ...(def.split ? splits.map((s) => colOf(s, XLSX_TYPE[def.format || "number"] || "number", (r) => r.parts.get(s) ?? 0, f)) : []),
        colOf(def.split ? "Total" : humanize(def.measure), XLSX_TYPE[def.format || "number"] || "number", (r) => r.total, f)],
      draw(host) {
        host.innerHTML = "";
        if (def.split) host.append(el("div", { class: "legend" }, splits.map((s, i) => `<span><i class="swatch" style="background:${colors[i]}"></i>${esc(s)}</span>`).join("")));
        const list = el("div", { class: "rrows" });
        for (const r of rows) {
          const parts = def.split ? splits.map((s, i) => ({ value: r.parts.get(s) || 0, color: colors[i] })) : [{ value: r.total, color: colorOf("internet", 0) }];
          const lines = def.split ? splits.map((s, i) => [s, fullF(r.parts.get(s) || 0), colors[i]]) : [];
          list.append(el("div", { class: "rrow", tabindex: 0, "data-tip": ctx.tooltip.tipAttr(ctx.tooltip.tipLines(r.label, [...lines, [def.split ? "Total" : humanize(def.measure), fullF(r.total)]])) },
            `<span class="name">${esc(r.label)}</span>${stackBarHtml(parts, max)}<span class="num">${esc(f(r.total))}</span>`));
        }
        host.append(list);
      },
    };
  });
}

// ------------------------------------------------------------------------------------------------------------------ table
function tablePanel(def, ctx) {
  const cols = def.columns;
  const { measures, dimensions } = tableParts(def, ctx.spec.members);
  const kindOf = (m) => ctx.spec.members[m] || {};
  const colFor = (c) => {
    const m = c.member, kind = kindOf(m);
    const label = c.label || humanize(m);
    if (kind.kind === "measure") return colOf(label, XLSX_TYPE[c.format || "number"] || "number", (r) => r.values.get(m) ?? null, ctx.formatter(c.format));
    if (kind.type === "time") return colOf(label, "date", (r) => r.dims[m] && String(r.dims[m]).replace(/\.\d+$/, ""), (v) => (v ? ctx.dateTime(v) : ""));
    if (c.format) return colOf(label, XLSX_TYPE[c.format] || "text", (r) => num(r.dims[m]), ctx.formatter(c.format));
    return colOf(label, "text", (r) => (r.dims[m] == null ? "" : String(r.dims[m])), (v) => v);
  };
  return modelPanel(def, ctx, async (signal) => {
    const filters = activeFilters(ctx.spec, ctx.filterValues(), def);
    const order = Object.entries(def.order || {});
    const single = new Set(measures.map((m) => m.split(".")[0])).size <= 1;
    const base = { dimensions, filters, ...(single ? { order: Object.fromEntries(order), limit: def.limit || 100 } : {}) };
    const res = measures.length
      ? await runAll(ctx.run, queriesPerCube(measures, base), signal)
      : [{ cube: "", rows: await ctx.run({ ...base, order: Object.fromEntries(order), limit: def.limit || 100 }, signal) }];
    let rows = byDims(res, dimensions);
    if (!single) {                                    // several measure cubes were merged here: order and limit apply after the merge
      const get = (r, m) => (kindOf(m).kind === "measure" ? r.values.get(m) : r.dims[m]);
      for (const [m, dir] of [...order].reverse()) rows.sort((a, b) => (get(a, m) > get(b, m) ? 1 : get(a, m) < get(b, m) ? -1 : 0) * (dir === "desc" ? -1 : 1));
      rows = rows.slice(0, def.limit || 100);
    }
    return { rows, columns: cols.map(colFor), draw: (host) => { host.innerHTML = tableHtml({ columns: cols.map(colFor), rows }); } };
  }, { table: false });
}

// ------------------------------------------------------------------------------------------------------------------ text / unsupported
function textPanel(def, ctx) {
  const root = el("section", { class: "card text-panel", "data-panel": def.id });
  root.innerHTML = `${def.title ? `<div class="card-h"><div><h2>${esc(def.title)}</h2></div></div>` : ""}<div class="md">${markdown(def.markdown, esc)}</div>`;
  return { root, load: async () => {}, sheet: () => null };
}

function unsupportedPanel(def, ctx) {
  const { root, body } = card(def, ctx, { table: false });
  root.querySelector(".xls-btn").remove();
  body.innerHTML = `<div class="empty">The '${esc(def.type)}' panel is not drawn by this renderer yet.</div>`;
  return { root, load: async () => {}, sheet: () => null };
}
