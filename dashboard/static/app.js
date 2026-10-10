// AdventureWorks live sales dashboard. Plain JS + inline SVG, no dependencies.
// Every panel renders from GET /api/dashboard; the page polls it so new orders
// appear as soon as Airflow's dbt build lands them in analytics.mart.
"use strict";

const POLL_MS = 30_000;
const META_EVERY = 10; // re-read filter options every 10th poll
const CHANNELS = ["Internet", "Reseller"];
const CH_VAR = { Internet: "var(--internet)", Reseller: "var(--reseller)" };
const STATUS = {
  1: "◔ In process", 2: "◑ Approved", 3: "⏸ Backordered",
  4: "✕ Rejected", 5: "✓ Shipped", 6: "✕ Cancelled",
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// Gaps up to this many empty months are drawn as zero months; longer ones as an axis break.
const MAX_FILLED_GAP = 6;

const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, html = "") => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (html) n.innerHTML = html;
  return n;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// ---------------------------------------------------------------- formatting
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });
const money = (v) => (v == null ? "—" : (v < 0 ? "−$" : "$") + (Math.abs(v) >= 1000 ? compact.format(Math.abs(v)) : Math.abs(v).toFixed(2)));
const moneyFull = (v) => (v == null ? "—" : v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }));
const int = (v) => (v == null ? "—" : Math.round(v).toLocaleString("en-US"));
const pct = (v, d = 1) => (v == null || !isFinite(v) ? "—" : (v < 0 ? "−" : "") + Math.abs(v * 100).toFixed(d) + "%");
const ratio = (a, b) => (b ? a / b : null);
const fyOf = (iso) => { const [y, m] = iso.split("-").map(Number); return m >= 7 ? y + 1 : y; };
const fyRange = (fy) => `Jul ${String(fy - 1).slice(2)} – Jun ${String(fy).slice(2)}`;
const monthLabel = (iso, withYear = true) => {
  const [y, m] = iso.split("-").map(Number);
  return withYear ? `${MONTHS[m - 1]} ${y}` : MONTHS[m - 1];
};
const ago = (iso) => {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 0) return "scheduled";
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 45) return `${Math.round(s / 86400)} days ago`;
  return new Date(iso).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" });
};

// --------------------------------------------------------------------- state
const state = {
  filters: { fy: "", channel: "", group: "", region: "", category: "" },
  meta: null,
  data: null,
  tables: new Set(),
  seenOrders: null,
  polls: 0,
  timer: null,
  inflight: null,
};

function readUrl() {
  const q = new URLSearchParams(location.search);
  for (const k of Object.keys(state.filters)) state.filters[k] = q.get(k) || "";
}
function writeUrl() {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(state.filters)) if (v) q.set(k, v);
  history.replaceState(null, "", q.toString() ? `?${q}` : location.pathname);
}

// ------------------------------------------------------------------- tooltip
const tip = $("#tip");
const tips = new Map();
let tipSeq = 0;
function tipAttr(html) { const id = String(++tipSeq); tips.set(id, html); return id; }
function tipLines(title, lines) {
  return `<div class="t">${esc(title)}</div>` + lines.map(([label, value, color]) =>
    `<div class="l"><span>${color ? `<i class="swatch" style="background:${color}"></i>` : ""}${esc(label)}</span><b>${esc(value)}</b></div>`).join("");
}
function placeTip(x, y) {
  const r = tip.getBoundingClientRect();
  let left = x + 14, top = y + 14;
  if (left + r.width > innerWidth - 8) left = x - r.width - 14;
  if (top + r.height > innerHeight - 8) top = y - r.height - 14;
  tip.style.left = `${Math.max(8, left)}px`;
  tip.style.top = `${Math.max(8, top)}px`;
}
function showTip(target, x, y) {
  const html = tips.get(target.dataset.tip);
  if (!html) return;
  tip.innerHTML = html;
  tip.classList.add("on");
  if (x == null) { const b = target.getBoundingClientRect(); x = b.left + b.width / 2; y = b.top; }
  placeTip(x, y);
}
document.addEventListener("pointermove", (e) => {
  const t = e.target.closest?.("[data-tip]");
  if (t) showTip(t, e.clientX, e.clientY); else tip.classList.remove("on");
});
document.addEventListener("focusin", (e) => { const t = e.target.closest?.("[data-tip]"); if (t) showTip(t); });
document.addEventListener("focusout", () => tip.classList.remove("on"));
document.addEventListener("scroll", () => tip.classList.remove("on"), { passive: true });

// --------------------------------------------------------------------- data
async function getJSON(url, signal) {
  const res = await fetch(url, { signal, cache: "no-store" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
  return body;
}

async function loadMeta() {
  state.meta = await getJSON("/api/meta");
  fillFilters();
}

async function load({ quiet = false } = {}) {
  clearTimeout(state.timer);
  state.inflight?.abort();
  const ctrl = new AbortController();
  state.inflight = ctrl;
  if (!quiet) document.body.classList.add("loading");
  const q = new URLSearchParams(Object.entries(state.filters).filter(([, v]) => v));
  try {
    if (!state.meta || state.polls % META_EVERY === 0) await loadMeta();
    state.data = await getJSON(`/api/dashboard?${q}`, ctrl.signal);
    state.polls++;
    $("#error").hidden = true;
    renderAll();
    setLive(true);
  } catch (err) {
    if (err.name === "AbortError") return;
    setLive(false, err.message);
    if (!state.data) { $("#error").hidden = false; $("#error").textContent = `Could not load the dashboard: ${err.message}`; }
  } finally {
    if (state.inflight === ctrl) {
      document.body.classList.remove("loading");
      state.timer = setTimeout(() => !document.hidden && load({ quiet: true }), POLL_MS);
    }
  }
}

document.addEventListener("visibilitychange", () => { if (!document.hidden) load({ quiet: true }); });

function setLive(ok, message) {
  const live = $("#live");
  live.classList.toggle("stale", !ok);
  const t = new Date().toLocaleTimeString("en-GB");
  const last = state.data?.latest_orders?.[0]?.order_date;
  $("#live-text").innerHTML = ok
    ? `<strong>Live</strong> · updated ${t}${last ? ` · last order ${esc(ago(last))}` : ""}`
    : `<strong>Stale</strong> · ${esc(message || "unavailable")} · retrying`;
}

// ------------------------------------------------------------------ filters
function fillFilters() {
  const { fiscal_years = [], territories = [], categories = [] } = state.meta;
  const f = state.filters;
  const opts = (sel, first, items) => {
    const s = $(sel);
    s.innerHTML = `<option value="">${first}</option>` + items.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
  };
  opts("#f-fy", "All years", fiscal_years.slice().reverse().map((y) => [y, `FY${y} (${fyRange(y)})`]));
  opts("#f-group", "All groups", [...new Set(territories.map((t) => t.grp))].map((g) => [g, g]));
  opts("#f-region", "All regions", territories.filter((t) => !f.group || t.grp === f.group).map((t) => [t.region, t.region]));
  opts("#f-category", "All categories", categories.map((c) => [c, c]));
  syncControls();
}

function syncControls() {
  const f = state.filters;
  for (const k of ["fy", "group", "region", "category"]) {
    const s = $(`#f-${k}`);
    s.value = f[k];
    if (s.value !== f[k]) { f[k] = ""; s.value = ""; } // value no longer offered
    s.classList.toggle("set", !!f[k]);
  }
  for (const b of $("#f-channel").children) b.setAttribute("aria-pressed", String(b.dataset.v === f.channel));
  $("#reset").hidden = !Object.values(f).some(Boolean);
}

function setFilter(patch) {
  Object.assign(state.filters, patch);
  if ("group" in patch && state.meta) {
    // A region outside the chosen group is meaningless; re-derive the region list.
    const t = state.meta.territories.find((x) => x.region === state.filters.region);
    if (t && state.filters.group && t.grp !== state.filters.group) state.filters.region = "";
    fillFilters();
  }
  if (patch.region && state.meta) {
    const t = state.meta.territories.find((x) => x.region === patch.region);
    if (t) { state.filters.group = t.grp; fillFilters(); }
  }
  syncControls();
  writeUrl();
  load();
}

$("#f-channel").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (b) setFilter({ channel: b.dataset.v });
});
for (const k of ["fy", "group", "region", "category"]) {
  $(`#f-${k}`).addEventListener("change", (e) => setFilter({ [k]: e.target.value }));
}
$("#reset").addEventListener("click", () => {
  for (const k of Object.keys(state.filters)) state.filters[k] = "";
  fillFilters(); writeUrl(); load();
});
$("#refresh").addEventListener("click", () => load());
$("#theme").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch { /* storage unavailable */ }
  renderAll();
});
try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch { /* ignore */ }

for (const btn of document.querySelectorAll(".tbl-toggle")) {
  btn.addEventListener("click", () => {
    const p = btn.closest("[data-panel]").dataset.panel;
    state.tables.has(p) ? state.tables.delete(p) : state.tables.add(p);
    btn.setAttribute("aria-pressed", String(state.tables.has(p)));
    renderAll();
  });
}

// ------------------------------------------------------------------- render
function renderAll() {
  if (!state.data) return;
  tips.clear();
  const months = monthSeries(state.data.monthly);
  renderKpis(months);
  renderTrend(months);
  renderFeed();
  renderMix();
  renderProducts();
  renderTerritories();
  renderNotes();
}

function table(cols, rows) {
  const head = cols.map((c) => `<th class="${c.num ? "n" : ""}">${esc(c.label)}</th>`).join("");
  const body = rows.map((r) => `<tr>${cols.map((c) => `<td class="${c.num ? "n" : ""}">${esc(c.fmt ? c.fmt(r[c.k], r) : r[c.k])}</td>`).join("")}</tr>`).join("");
  return `<div class="tbl-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

// Monthly rows -> one entry per month (both channels), zero-filling short gaps
// and marking long ones as breaks.
function monthSeries(rows) {
  const by = new Map();
  for (const r of rows) {
    const m = by.get(r.month) || { month: r.month, revenue: 0, gross_profit: 0, orders: 0, units: 0, ch: {} };
    m.ch[r.channel] = r;
    m.revenue += r.revenue; m.gross_profit += r.gross_profit; m.orders += r.orders; m.units += r.units;
    by.set(r.month, m);
  }
  const keys = [...by.keys()].sort();
  const out = [];
  const idx = (iso) => { const [y, m] = iso.split("-").map(Number); return y * 12 + m - 1; };
  const iso = (i) => `${Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}-01`;
  keys.forEach((k, n) => {
    if (n > 0) {
      const gap = idx(k) - idx(keys[n - 1]) - 1;
      if (gap > MAX_FILLED_GAP) out.push({ break: true, months: gap });
      else for (let i = 1; i <= gap; i++) out.push({ month: iso(idx(keys[n - 1]) + i), revenue: 0, gross_profit: 0, orders: 0, units: 0, ch: {} });
    }
    out.push(by.get(k));
  });
  return out;
}

// ---- KPI tiles
const KPIS = [
  { label: "Revenue", get: (r) => r.revenue, fmt: money },
  { label: "Gross profit", get: (r) => r.gross_profit, fmt: money },
  { label: "Gross margin", get: (r) => ratio(r.gross_profit, r.revenue), fmt: (v) => pct(v), points: true },
  { label: "Orders", get: (r) => r.orders, fmt: int },
  { label: "Avg order value", get: (r) => ratio(r.revenue, r.orders), fmt: money },
  { label: "Units sold", get: (r) => r.units, fmt: int },
];

function renderKpis(months) {
  const { current, previous } = state.data.kpis;
  const fy = state.filters.fy;
  const host = $("#kpis");
  host.innerHTML = "";
  const series = months.filter((m) => !m.break);
  for (const k of KPIS) {
    const v = current ? k.get(current) : null;
    const p = previous ? k.get(previous) : null;
    let delta = `<span class="vs">${fy ? `No FY${fy - 1} data to compare` : "All fiscal years"}</span>`;
    let cls = "";
    if (fy && v != null && p != null && p !== 0) {
      const d = k.points ? (v - p) * 100 : (v - p) / Math.abs(p);
      cls = d >= 0 ? "up" : "down";
      const txt = k.points ? `${Math.abs(d).toFixed(1)} pp` : pct(Math.abs(d));
      delta = `<span role="img" aria-label="${d >= 0 ? "up" : "down"}">${d >= 0 ? "▲" : "▼"}</span>${txt} <span class="vs">vs FY${fy - 1}</span>`;
    }
    const tile = el("div", { class: "card kpi" },
      `<div class="label">${k.label}</div><div class="value">${k.fmt(v)}</div><div class="delta ${cls}">${delta}</div>`);
    tile.append(sparkline(series.map((m) => (m.revenue ? k.get(m) : null)), series, k));
    host.append(tile);
  }
}

function sparkline(values, months, k) {
  const W = 200, H = 34;
  const svg = svgEl("svg", { class: "spark", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", "aria-hidden": "true" });
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v != null && isFinite(v));
  if (pts.length < 2) return svg;
  const lo = Math.min(0, ...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1])) || 1;
  const x = (i) => (i / (values.length - 1)) * W;
  const y = (v) => H - 2 - ((v - lo) / (hi - lo || 1)) * (H - 6);
  // Break the line where a month has no value instead of interpolating across it.
  let d = "", prev = -2;
  for (const [i, v] of pts) { d += `${i === prev + 1 ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; prev = i; }
  svg.append(svgEl("path", { d, fill: "none", stroke: "var(--ink-2)", "stroke-width": 1.5, "vector-effect": "non-scaling-stroke", "stroke-linejoin": "round" }));
  const [li, lv] = pts[pts.length - 1];
  const last = months[li];
  svg.append(svgEl("circle", { cx: x(li), cy: y(lv), r: 2.5, fill: "var(--ink)" }));
  svg.setAttribute("aria-label", `${k.label} by month, latest ${last ? monthLabel(last.month) : ""}: ${k.fmt(lv)}`);
  return svg;
}

// ---- SVG helpers
function svgEl(tag, attrs = {}) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}
function niceTicks(lo, hi, count = 4) {
  if (hi === lo) hi = lo + 1;
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const start = Math.floor(lo / step) * step, end = Math.ceil(hi / step) * step;
  const ticks = [];
  for (let v = start; v <= end + step / 2; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}
// A bar whose data end (top) is rounded and whose baseline end is square.
function barPath(x, y, w, h, r = 4) {
  if (h <= 0 || w <= 0) return "";
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

// ---- Monthly trend + margin
function layoutMonths(months, width, left, right) {
  const units = months.reduce((s, m) => s + (m.break ? 2 : 1), 0) || 1;
  const band = (width - left - right) / units;
  let u = 0;
  return { band, pos: months.map((m) => { const x = left + u * band; u += m.break ? 2 : 1; return x; }) };
}

function renderTrend(months) {
  const host = $("#trend"), mHost = $("#margin");
  const marginHead = mHost.previousElementSibling;
  const data = months.filter((m) => !m.break);
  const fy = state.filters.fy;
  $("#trend-hint").textContent = fy ? `FY${fy} · ${fyRange(+fy)} · click a month to clear` : "Click a month to focus its fiscal year";
  if (state.tables.has("trend")) {
    marginHead.hidden = true; mHost.innerHTML = "";
    host.innerHTML = table([
      { k: "month", label: "Month", fmt: (v) => monthLabel(v) },
      { k: "i", label: "Internet", num: true, fmt: (_, r) => moneyFull(r.ch.Internet?.revenue ?? 0) },
      { k: "r", label: "Reseller", num: true, fmt: (_, r) => moneyFull(r.ch.Reseller?.revenue ?? 0) },
      { k: "revenue", label: "Total", num: true, fmt: moneyFull },
      { k: "orders", label: "Orders", num: true, fmt: int },
      { k: "gm", label: "Margin", num: true, fmt: (_, r) => pct(ratio(r.gross_profit, r.revenue)) },
    ], data);
    return;
  }
  marginHead.hidden = false;
  if (!data.length) { host.innerHTML = `<div class="empty">No orders match these filters</div>`; mHost.innerHTML = ""; return; }

  const W = Math.max(host.clientWidth, 280), H = 240, L = 52, R = 8, T = 10, B = 26;
  const { band, pos } = layoutMonths(months, W, L, R);
  const ticks = niceTicks(0, Math.max(...data.map((m) => m.revenue), 1));
  const yMax = ticks[ticks.length - 1];
  const y = (v) => T + (H - T - B) * (1 - v / yMax);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": "Monthly revenue by channel, stacked columns" });

  for (const t of ticks) {
    svg.append(svgEl("line", { x1: L, x2: W - R, y1: y(t), y2: y(t), class: t === 0 ? "base-line" : "grid-line" }));
    const lab = svgEl("text", { x: L - 8, y: y(t) + 4, "text-anchor": "end" }); lab.textContent = money(t); svg.append(lab);
  }
  const barW = Math.max(1, Math.min(band - 2, band * 0.74, 34));
  const fewMonths = data.length <= 15;
  let lastLabelX = -Infinity;
  months.forEach((m, i) => {
    const x0 = pos[i];
    if (m.break) {
      const cx = x0 + band;
      const g = svgEl("g", { "aria-hidden": "true" });
      for (const dx of [-3, 3]) g.append(svgEl("line", { x1: cx + dx - 3, x2: cx + dx + 3, y1: y(0) + 6, y2: y(0) - 6, stroke: "var(--muted)", "stroke-width": 1.5 }));
      svg.append(g);
      const t = svgEl("text", { x: cx, y: T + 12, "text-anchor": "middle", class: "break-label" });
      t.textContent = `${m.months} mo. without data`; svg.append(t);
      return;
    }
    const bx = x0 + (band - barW) / 2;
    let base = 0;
    const segs = CHANNELS.map((c) => [c, m.ch[c]?.revenue || 0]).filter(([, v]) => v > 0);
    segs.forEach(([c, v], si) => {
      const top = si === segs.length - 1;
      const y1 = y(base + v), y0 = y(base) - (si > 0 ? 2 : 0); // 2px surface gap between stacked fills
      const h = Math.max(0, y0 - y1);
      svg.append(top ? svgEl("path", { d: barPath(bx, y1, barW, h, Math.min(4, barW / 3)), fill: CH_VAR[c] })
        : svgEl("rect", { x: bx, y: y1, width: barW, height: h, fill: CH_VAR[c] }));
      base += v;
    });
    // x labels: every month in a single fiscal year, otherwise each January (and the first month).
    const [yy, mm] = m.month.split("-").map(Number);
    const want = fewMonths || mm === 1 || i === 0;
    const cx = x0 + band / 2;
    if (want && cx - lastLabelX > (fewMonths ? 28 : 44)) {
      const t = svgEl("text", { x: cx, y: H - 8, "text-anchor": "middle" });
      t.textContent = fewMonths ? monthLabel(m.month, mm === 1 || i === 0).replace(/ (\d\d)(\d\d)$/, " ’$2") : (mm === 1 ? String(yy) : monthLabel(m.month).replace(/ (\d\d)(\d\d)$/, " ’$2"));
      svg.append(t); lastLabelX = cx;
    }
    const hit = svgEl("rect", {
      x: x0, y: T, width: band, height: H - T - B, class: "hit", tabindex: 0,
      "data-tip": tipAttr(tipLines(`${monthLabel(m.month)} · FY${fyOf(m.month)}`, [
        ...CHANNELS.map((c) => [c, moneyFull(m.ch[c]?.revenue || 0), CH_VAR[c]]),
        ["Total", moneyFull(m.revenue)], ["Orders", int(m.orders)], ["Margin", pct(ratio(m.gross_profit, m.revenue))],
      ])),
      "aria-label": `${monthLabel(m.month)}: ${moneyFull(m.revenue)}`,
    });
    hit.addEventListener("click", () => setFilter({ fy: fy && +fy === fyOf(m.month) ? "" : String(fyOf(m.month)) }));
    hit.addEventListener("keydown", (e) => { if (e.key === "Enter") hit.dispatchEvent(new Event("click")); });
    svg.append(hit);
  });
  host.replaceChildren(svg);
  renderMargin(months, W, L, R, band, pos);
}

function renderMargin(months, W, L, R, band, pos) {
  const host = $("#margin");
  const H = 120, T = 8, B = 8;
  const vals = months.map((m) => (m.break || !m.revenue ? null : m.gross_profit / m.revenue));
  const real = vals.filter((v) => v != null);
  if (!real.length) { host.innerHTML = ""; return; }
  const ticks = niceTicks(Math.min(0, ...real), Math.max(0.05, ...real), 3);
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": "Gross margin percent by month" });
  for (const t of ticks) {
    svg.append(svgEl("line", { x1: L, x2: W - R, y1: y(t), y2: y(t), class: t === 0 ? "base-line" : "grid-line" }));
    const lab = svgEl("text", { x: L - 8, y: y(t) + 4, "text-anchor": "end" }); lab.textContent = pct(t, 0); svg.append(lab);
  }
  let d = "", prev = false;
  vals.forEach((v, i) => {
    if (v == null) { prev = false; return; }
    d += `${prev ? "L" : "M"}${(pos[i] + band / 2).toFixed(1)},${y(v).toFixed(1)}`; prev = true;
  });
  svg.append(svgEl("path", { d, fill: "none", stroke: "var(--ink-2)", "stroke-width": 2, "stroke-linejoin": "round" }));
  // Markers on every point when there are few, otherwise only on isolated points a line can't show.
  const isolated = (i) => vals[i - 1] == null && vals[i + 1] == null;
  vals.forEach((v, i) => {
    if (v != null && (real.length <= 18 || isolated(i))) svg.append(svgEl("circle", { cx: pos[i] + band / 2, cy: y(v), r: 4, fill: v < 0 ? "var(--bad)" : "var(--ink-2)", stroke: "var(--surface)", "stroke-width": 2 }));
  });
  months.forEach((m, i) => {
    if (m.break || vals[i] == null) return;
    svg.append(svgEl("rect", {
      x: pos[i], y: T, width: band, height: H - T - B, class: "hit",
      "data-tip": tipAttr(tipLines(monthLabel(m.month), [["Gross margin", pct(vals[i])], ["Gross profit", moneyFull(m.gross_profit)]])),
    }));
  });
  host.replaceChildren(svg);
}

// ---- Live feed
function renderFeed() {
  const rows = state.data.latest_orders;
  const host = $("#feed");
  if (state.tables.has("feed")) {
    host.innerHTML = table([
      { k: "sales_order_number", label: "Order" }, { k: "channel", label: "Channel" },
      { k: "order_date", label: "Date", fmt: (v) => new Date(v).toLocaleString("en-GB") },
      { k: "region", label: "Region" }, { k: "order_status", label: "Status", fmt: (v) => STATUS[v] || v },
      { k: "revenue", label: "Revenue", num: true, fmt: moneyFull },
    ], rows);
    return;
  }
  const seen = state.seenOrders;
  host.innerHTML = rows.length ? "" : `<div class="empty">No orders</div>`;
  for (const o of rows) {
    const isNew = seen && !seen.has(o.sales_order_number);
    host.append(el("div", { class: `order${isNew ? " new" : ""}` },
      `<i class="swatch" style="background:${CH_VAR[o.channel]}" title="${o.channel}"></i>
       <span class="no">${esc(o.sales_order_number)}</span>
       <span class="amt">${money(o.revenue)}</span>
       <span class="meta">${esc(ago(o.order_date))} · ${esc(o.channel)} · ${esc(o.region)} · ${o.lines} line${o.lines === 1 ? "" : "s"}</span>
       <span class="status">${esc(STATUS[o.order_status] || o.order_status)}</span>`));
  }
  state.seenOrders = new Set([...(seen || []), ...rows.map((o) => o.sales_order_number)]);
}

// ---- Product mix treemap (area = revenue, colour = gross margin, diverging around 0)
const MARGIN_BINS = [ // [upper bound, fill, light text?]
  [-0.30, "#9a2526", true], [-0.20, "#c13534", true], [-0.10, "#e34948", true], [-0.02, "#f4a9a8", false],
  [0.02, "#e6e5e0", false],
  [0.10, "#9ec5f4", false], [0.20, "#5598e7", false], [0.30, "#2a78d6", true], [Infinity, "#184f95", true],
];
const marginBin = (m) => MARGIN_BINS.find(([ub]) => m < ub) || MARGIN_BINS[MARGIN_BINS.length - 1];

function squarify(items, x, y, w, h) {
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

function renderMix() {
  const rows = state.data.mix.filter((r) => r.revenue > 0);
  const host = $("#mix"), scale = $("#mix-scale");
  const sel = state.filters.category;
  if (state.tables.has("mix")) {
    scale.innerHTML = "";
    host.style.height = "";
    host.innerHTML = table([
      { k: "category", label: "Category" }, { k: "subcategory", label: "Subcategory" },
      { k: "revenue", label: "Revenue", num: true, fmt: moneyFull },
      { k: "gross_profit", label: "Gross profit", num: true, fmt: moneyFull },
      { k: "m", label: "Margin", num: true, fmt: (_, r) => pct(ratio(r.gross_profit, r.revenue)) },
      { k: "units", label: "Units", num: true, fmt: int },
    ], rows);
    return;
  }
  if (!rows.length) { host.style.height = ""; host.innerHTML = `<div class="empty">No product sales match these filters</div>`; scale.innerHTML = ""; return; }
  const W = Math.max(host.clientWidth, 260), H = W < 500 ? 380 : 330, HEAD = 20, GAP = 2;
  host.style.height = `${H}px`;
  host.innerHTML = "";
  const total = rows.reduce((s, r) => s + r.revenue, 0);
  const cats = new Map();
  for (const r of rows) {
    const c = cats.get(r.category) || { name: r.category, value: 0, gp: 0, subs: [] };
    c.value += r.revenue; c.gp += r.gross_profit; c.subs.push(r); cats.set(r.category, c);
  }
  for (const c of squarify([...cats.values()], 0, 0, W, H)) {
    const dim = sel && sel !== c.name;
    const toggle = () => setFilter({ category: sel === c.name ? "" : c.name });
    const lab = el("div", { class: `group-label${dim ? " dim" : ""}`, role: "button", tabindex: 0,
      style: `left:${c.x + 2}px;top:${c.y}px;width:${Math.max(0, c.w - 4)}px;height:${HEAD}px;line-height:${HEAD}px` },
      `${esc(c.name)} · ${money(c.value)} · ${pct(ratio(c.gp, c.value), 0)}`);
    lab.addEventListener("click", toggle);
    lab.addEventListener("keydown", (e) => { if (e.key === "Enter") toggle(); });
    host.append(lab);
    // Fold slivers (< 1.2% of the total) into one "Other" tile per category; the table keeps every row.
    const big = c.subs.filter((s) => s.revenue / total >= 0.012);
    const small = c.subs.filter((s) => s.revenue / total < 0.012);
    if (small.length > 1) {
      const agg = (k) => small.reduce((a, s) => a + s[k], 0);
      big.push({ category: c.name, subcategory: `Other (${small.length})`, revenue: agg("revenue"), gross_profit: agg("gross_profit"), units: agg("units") });
    } else big.push(...small);
    const inner = squarify(big.map((s) => ({ ...s, value: s.revenue })), c.x, c.y + HEAD, c.w, Math.max(0, c.h - HEAD));
    for (const s of inner) {
      const m = ratio(s.gross_profit, s.revenue);
      const [, fill, light] = marginBin(m);
      const w = s.w - GAP, h = s.h - GAP;
      if (w < 1 || h < 1) continue;
      const cell = el("div", {
        class: `cell${light ? " ink-light" : ""}${dim ? " dim" : ""}`, role: "button", tabindex: 0,
        style: `left:${s.x + GAP / 2}px;top:${s.y + GAP / 2}px;width:${w}px;height:${h}px;background:${fill}`,
        "data-tip": tipAttr(tipLines(`${s.category} › ${s.subcategory}`, [
          ["Revenue", moneyFull(s.revenue)], ["Share of total", pct(s.revenue / total)],
          ["Gross profit", moneyFull(s.gross_profit)], ["Gross margin", pct(m)], ["Units", int(s.units)],
        ])),
        "aria-label": `${s.subcategory}: ${moneyFull(s.revenue)}, margin ${pct(m)}`,
      });
      // Only label a tile when the text fits with padding; the tooltip and table carry the rest.
      if (w > 64 && h > 34) cell.innerHTML = `<div class="n">${esc(s.subcategory)}</div><div class="v">${money(s.revenue)} · ${pct(m, 0)}</div>`;
      else if (w > 48 && h > 20) cell.innerHTML = `<div class="n">${esc(s.subcategory)}</div>`;
      cell.addEventListener("click", toggle);
      cell.addEventListener("keydown", (e) => { if (e.key === "Enter") toggle(); });
      host.append(cell);
    }
  }
  const labels = ["< −30%", "−20%", "−10%", "−2%", "0", "2%", "10%", "20%", "> 30%"];
  scale.innerHTML = `<span>Gross margin</span>` + MARGIN_BINS.map(([, f], i) =>
    `<span style="display:inline-flex;flex-direction:column;align-items:center;gap:2px"><i class="swatch" style="background:${f};width:22px;height:8px;border-radius:2px"></i>${i % 2 === 0 ? labels[i] : "&nbsp;"}</span>`).join("");
}

// ---- Ranked rows shared by top products and territories
function stackBar(r, max) {
  const parts = CHANNELS.map((c) => [c, r[c.toLowerCase()] || 0]).filter(([, v]) => v > 0);
  return `<div class="hbar">${parts.map(([c, v]) => `<i style="width:${(v / max) * 100}%;background:${CH_VAR[c]}"></i>`).join("")}</div>`;
}
function rowTip(title, r, extra = []) {
  return tipAttr(tipLines(title, [
    ...CHANNELS.map((c) => [c, moneyFull(r[c.toLowerCase()] || 0), CH_VAR[c]]),
    ["Total", moneyFull(r.revenue)], ["Gross margin", pct(ratio(r.gross_profit, r.revenue))], ...extra,
  ]));
}

function renderProducts() {
  const rows = state.data.top_products;
  const host = $("#products");
  if (state.tables.has("products")) {
    host.innerHTML = table([
      { k: "product_name", label: "Product" }, { k: "category", label: "Category" },
      { k: "internet", label: "Internet", num: true, fmt: moneyFull }, { k: "reseller", label: "Reseller", num: true, fmt: moneyFull },
      { k: "revenue", label: "Revenue", num: true, fmt: moneyFull },
      { k: "m", label: "Margin", num: true, fmt: (_, r) => pct(ratio(r.gross_profit, r.revenue)) },
      { k: "units", label: "Units", num: true, fmt: int },
    ], rows);
    return;
  }
  if (!rows.length) { host.innerHTML = `<div class="empty">No products match these filters</div>`; return; }
  const max = Math.max(...rows.map((r) => r.revenue));
  host.innerHTML = `<div class="row row-head"><span>Product</span><span></span><span class="num">Revenue</span><span class="num">Margin</span></div>`;
  const list = el("div", { class: "rows" });
  for (const r of rows) {
    const m = ratio(r.gross_profit, r.revenue);
    list.append(el("div", { class: "row", tabindex: 0, "data-tip": rowTip(r.product_name, r, [["Units", int(r.units)]]) },
      `<span class="name">${esc(r.product_name)}<small>${esc(r.category)}</small></span>${stackBar(r, max)}
       <span class="num">${money(r.revenue)}</span><span class="num muted${m < 0 ? " neg" : ""}">${pct(m, 0)}</span>`));
  }
  host.append(list);
}

function renderTerritories() {
  const rows = state.data.territories;
  const host = $("#territories");
  const { group: selG, region: selR } = state.filters;
  if (state.tables.has("territories")) {
    host.innerHTML = table([
      { k: "grp", label: "Group" }, { k: "region", label: "Region" },
      { k: "internet", label: "Internet", num: true, fmt: moneyFull }, { k: "reseller", label: "Reseller", num: true, fmt: moneyFull },
      { k: "revenue", label: "Revenue", num: true, fmt: moneyFull },
      { k: "m", label: "Margin", num: true, fmt: (_, r) => pct(ratio(r.gross_profit, r.revenue)) },
      { k: "orders", label: "Orders", num: true, fmt: int },
    ], rows);
    return;
  }
  if (!rows.length) { host.innerHTML = `<div class="empty">No territory sales match these filters</div>`; return; }
  const max = Math.max(...rows.map((r) => r.revenue));
  const groups = new Map();
  for (const r of rows) { const g = groups.get(r.grp) || []; g.push(r); groups.set(r.grp, g); }
  const cols = el("div", { class: "terr-cols" });
  for (const [g, list] of [...groups].sort((a, b) => sum(b[1]) - sum(a[1]))) {
    const col = el("div", { class: "rows" });
    const gh = el("div", { class: "group-h", role: "button", tabindex: 0 }, `<span>${esc(g)}</span><span>${money(sum(list))}</span>`);
    const tg = () => setFilter({ group: selG === g && !selR ? "" : g, region: "" });
    gh.addEventListener("click", tg); gh.addEventListener("keydown", (e) => { if (e.key === "Enter") tg(); });
    col.append(gh);
    for (const r of list) {
      const dim = (selR && selR !== r.region) || (!selR && selG && selG !== r.grp);
      const m = ratio(r.gross_profit, r.revenue);
      const row = el("div", {
        class: `row clickable${dim ? " dim" : ""}${selR === r.region ? " sel" : ""}`, role: "button", tabindex: 0,
        "data-tip": rowTip(`${r.region} · ${r.grp}`, r, [["Orders", int(r.orders)]]),
      }, `<span class="name">${esc(r.region)}</span>${stackBar(r, max)}<span class="num">${money(r.revenue)}</span><span class="num muted${m < 0 ? " neg" : ""}">${pct(m, 0)}</span>`);
      const t = () => setFilter({ region: selR === r.region ? "" : r.region });
      row.addEventListener("click", t); row.addEventListener("keydown", (e) => { if (e.key === "Enter") t(); });
      col.append(row);
    }
    cols.append(col);
  }
  host.replaceChildren(cols);
}
const sum = (list) => list.reduce((s, r) => s + r.revenue, 0);

function renderNotes() {
  const m = state.meta || {};
  $("#notes").innerHTML = `Revenue is <code>sales_amount</code> from <code>mart.fact_internet_sales</code> + <code>mart.fact_reseller_sales</code>;
    gross profit subtracts <code>total_product_cost</code> (standard cost on the order date). Rejected and cancelled orders are excluded.
    Fiscal years run July–June. The historical AdventureWorks sample is shifted forward by dbt (<code>date_shift_years</code>) so it runs into the live simulator orders.
    ${m.fact_rows ? `${int(m.fact_rows)} fact rows. ` : ""}This page re-queries the mart every ${POLL_MS / 1000} s; Airflow rebuilds the mart every 15 min.`;
}

// Re-layout width-dependent charts when the viewport changes.
let lastW = 0;
new ResizeObserver(() => {
  const w = $("#trend").clientWidth;
  if (Math.abs(w - lastW) > 4) { lastW = w; renderAll(); }
}).observe($("#trend"));

readUrl();
load();
