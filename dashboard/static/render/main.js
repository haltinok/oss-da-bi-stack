// The dashboard renderer: /d/ lists the dashboards a role may open, /d/<id> draws one compiled spec (dashboards/build/<id>.json).
// Every number comes from Cube (the same sign-in, token and row-level security as the sales dashboard); this page builds queries from
// member names and never writes SQL. Panels load independently and in parallel; changing a filter cancels the queries still running.
import { createCubeClient } from "/cube/cube-client.mjs";
import { $, el, esc } from "../lib/dom.js";
import { createFormat } from "../lib/format.js";
import { createTooltip } from "../lib/tooltip.js";
import { downloadXlsx, slugify } from "../lib/table.js";
import { createPanel, readable } from "./panels.js";
import { formatPeriod, optionMeasures, optionsOf, parsePeriod, PERIOD, pick, queriesPerCube, runAll } from "./plan.js";
import { stringsFor } from "./strings.js";
import { createBuilderApi, drafts, mountDraftBar, mountPromptBox, mountSavedBar, mountSavedList, mountSemantic } from "./builder.js";

const REFRESH_MS = 5 * 60_000;
const C = window.STACK;
const show = (msg) => { const e = $("#error"); e.textContent = msg; e.hidden = !msg; };

try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch { /* storage unavailable */ }
$("#theme").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch { /* ignore */ }
});

// ------------------------------------------------------------------ dataset (the same choice and storage as the sales dashboard)
const DATASETS = C.datasets || [{ id: "live", label: "Live (simulator)", mart: "mart", cube: C.cube }];
const keep = { get: () => { try { return localStorage.getItem("dataset"); } catch { return null; } }, set: (v) => { try { localStorage.setItem("dataset", v); } catch { /* ignore */ } } };
const wanted = new URLSearchParams(location.search).get("dataset") || keep.get();
const dataset = DATASETS.find((d) => d.id === wanted) || DATASETS[0];
keep.set(dataset.id);

const id = decodeURIComponent(location.pathname.replace(/^\/d\/?/, "").replace(/\/$/, ""));
const client = createCubeClient({
  stack: C, apiUrl: dataset.cube, redirect: `${location.origin}${location.pathname}`,
  onSession(s) {
    if ($("#who")) return;
    const who = el("div", { id: "who", class: "who", title: `Signed in as ${s.user}, role ${s.role}` }, `${esc(s.user)} · <a href="#" id="signout">Sign out</a>`);
    $("#tools").append(who);
    $("#signout").addEventListener("click", (e) => { e.preventDefault(); client.signOut(); });
  },
});

function initDatasetControl() {
  const badge = $("#dataset-badge");
  badge.textContent = dataset.label;
  badge.title = `Dataset: ${dataset.label} (${dataset.mart})`;
  badge.classList.toggle("ro", !!dataset.readOnly);
  badge.hidden = false;
  if (DATASETS.length < 2) return;
  const sel = $("#f-dataset");
  sel.replaceChildren(...DATASETS.map((d) => el("option", { value: d.id }, esc(d.label))));
  sel.value = dataset.id;
  $("#dataset-field").hidden = false;
  sel.addEventListener("change", () => {
    keep.set(sel.value);
    const q = new URLSearchParams(location.search);
    q.set("dataset", sel.value);
    location.search = q.toString();
  });
}

function setStatus(text, cls = "") {
  $("#live").className = `live ${cls}`.trim();
  $("#live-text").innerHTML = text;
}

/** A dashboard's own look: a name and logo in the header, and colours for the theme tokens (a series `color: internet` follows them). */
function applyTheme(theme = {}) {
  if (theme.name) { $("#brand-name").textContent = theme.name; $("#brand-name").hidden = false; }
  if (theme.logo) { $("#logo").src = theme.logo; $("#logo").hidden = false; }
  for (const [token, hex] of Object.entries(theme.colors || {})) document.documentElement.style.setProperty(`--${token}`, hex);
}

// ------------------------------------------------------------------ the list
async function showList() {
  document.title = "Dashboards";
  const index = await (await fetch("/dashboards/index.json", { cache: "no-store" })).json().catch(() => []);
  const role = client.session().role;
  const mine = index.filter((d) => !d.roles?.length || d.roles.includes(role));
  const t = stringsFor(navigator.language);
  document.title = t.dashboards;
  $("#title").textContent = t.dashboards;
  $("#export-label").textContent = t.exportAll;
  setStatus(`<strong>${esc(t.signedIn)}</strong>`);
  const api = createBuilderApi({ stack: C, client, t });
  $("#main").innerHTML = (api.available ? `<div id="builder-host"></div><div id="drafts-host" class="drafts-host" hidden></div>` : "") + (mine.length
    ? `<div class="dlist">${mine.map((d) => `<a href="/d/${encodeURIComponent(d.id)}"><div class="card"><h2>${esc(d.title)}</h2><p>${esc(d.description)}</p></div></a>`).join("")}</div>`
    : `<div class="empty">${esc(t.noDashboards)}</div>`) + (api.available ? `<details class="card sem-wrap" id="sem-wrap"><summary>${esc(t.semantic)}</summary><div id="sem-host"></div></details>` : "");
  if (!api.available) return;
  mountPromptBox($("#builder-host"), api, t);
  mountSavedList($("#drafts-host"), api, t);
  $("#sem-wrap").addEventListener("toggle", () => { if ($("#sem-wrap").open && !$("#sem-host").dataset.ready) { $("#sem-host").dataset.ready = "1"; mountSemantic($("#sem-host"), api, t); } });
}

// ------------------------------------------------------------------ one dashboard
async function showDashboard() {
  const t0 = stringsFor(navigator.language);
  const draft = id === "draft" ? drafts.current() : null;       // a draft lives in this browser (see builder.js); a saved dashboard (s/<id>) comes from the builder service; every other id is a built file
  let spec, savedDash = null;
  if (id.startsWith("s/")) {
    const api = createBuilderApi({ stack: C, client, t: t0 });
    try { savedDash = await api.openSaved(id.slice(2)); } catch (e) { throw new Error(e.problems?.length ? `${e.message} ${e.problems[0]}` : e.message); }
    spec = savedDash.spec;
  } else if (id === "draft") {
    if (!draft?.spec) throw new Error(t0.noDraft);
    spec = draft.spec;
  } else {
    const res = await fetch(`/dashboards/${encodeURIComponent(id)}.json`, { cache: "no-store" });
    if (!res.ok) throw new Error(res.status === 404 ? t0.noSuchDashboard(id) : t0.loadFailed(res.status));
    spec = await res.json();
  }
  const role = client.session().role;
  const t = stringsFor(spec.locale);
  document.documentElement.lang = (spec.locale || "en-US").split("-")[0];
  if (spec.roles?.length && !spec.roles.includes(role)) throw new Error(t.notForRole(spec.title, role));
  applyTheme(spec.theme);
  $("#export-label").textContent = t.exportAll;
  $("#refresh").title = $("#refresh").ariaLabel = t.refresh;
  if ($("#signout")) $("#signout").textContent = t.signOut;

  document.title = `${draft ? `${t.draft}: ` : ""}${spec.title} · ${dataset.label}`;
  $("#title").textContent = spec.title;
  $("#brand-sub").textContent = spec.description || "";
  const fmt = createFormat({ locale: spec.locale || "en-US", currency: spec.currency || "USD" });
  const tooltip = createTooltip($("#tip"));
  const dateFmt = new Intl.DateTimeFormat(fmt.locale, { dateStyle: "medium", timeZone: "UTC" });
  const dateTimeFmt = new Intl.DateTimeFormat(fmt.locale, { dateStyle: "medium", timeStyle: "short" });
  const asDate = (b) => new Date(`${String(b).slice(0, 19)}Z`);

  const qs = new URLSearchParams(location.search);
  const values = Object.fromEntries((spec.filters || []).map((f) => [f.id, qs.get(f.id) || ""]));
  values[PERIOD] = parsePeriod(qs.get("period")) ? qs.get("period") : "";             // the date range a drill-down sets (other panels follow it)
  const drills = Object.fromEntries(spec.panels.filter((p) => p.drill).map((p) => [p.id, (qs.get(`drill_${p.id}`) || "").split(",").filter((b) => /^\d{4}-\d{2}-\d{2}/.test(b))]));
  const clearedHooks = [];
  const span = Object.fromEntries(spec.layout.flat().map((c) => [c.panel, c.span]));

  const ctx = {
    spec, t, run: (q, signal) => client.run(q, signal), tooltip,
    filterValues: () => values,
    formatter: (format, full = false) => {
      const f = format === "money" && full ? fmt.moneyFull : fmt[format || "number"] || fmt.number;
      return format === "pct" ? (v) => fmt.pct(v) : f;
    },
    bucketLabel(b, g) {
      const [y, m] = String(b).split("-");
      if (g === "year") return y;
      if (g === "quarter") return `Q${Math.floor((+m - 1) / 3) + 1} ${y}`;
      if (g === "month") return `${fmt.monthName(+m)} ${y}`;
      return g === "hour" ? dateTimeFmt.format(new Date(`${String(b).slice(0, 19)}`)) : dateFmt.format(asDate(b));
    },
    shortBucketLabel(b, g) {
      if (g === "month") { const [y, m] = String(b).split("-"); return `${fmt.monthName(+m)} '${y.slice(2)}`; }
      return ctx.bucketLabel(b, g);
    },
    dateTime: (v) => dateTimeFmt.format(new Date(v)),
    subtitle() {
      const parts = (spec.filters || []).filter((f) => values[f.id]).map((f) => `${f.label || f.id}: ${values[f.id]}`);
      return `${t.filters}: ${parts.length ? parts.join(" · ") : t.none} · ${t.exported} ${dateTimeFmt.format(new Date())} ${t.from} ${dataset.mart}`;
    },
    exportSheets: (sheets, name) => downloadXlsx(sheets.filter(Boolean), { prefix: spec.id, slug: slugify(name), symbol: fmt.symbol }),
    // A drill-down: where each time chart is (kept in the URL) and the period it hands to the other panels.
    period: () => parsePeriod(values[PERIOD]),
    setPeriod(range) { values[PERIOD] = range ? formatPeriod(range[0], range[1]) : ""; if (!range) clearedHooks.forEach((h) => h()); renderPeriod(); writeUrl(); loadAll(); },
    drillPath: (id) => drills[id] || [],
    setDrill(id, path) { drills[id] = path; },
    onPeriodCleared: (fn) => clearedHooks.push(fn),
    bodyWidth: (id) => panels.get(id)?.root.querySelector(".panel-body")?.clientWidth || 640,
    // A click on a panel sets filters (see plan.js `pick`): the page applies them like a change in the filter bar.
    pick: (ids, vals) => apply(pick(values, ids, vals, saved)),
  };
  const saved = {};                                     // what the filters held before a click, so that clicking again can undo it

  const panels = new Map(spec.panels.map((p) => [p.id, createPanel(p, ctx)]));
  const periodBar = el("div", { id: "period-bar", class: "period-bar", hidden: "" });
  function renderPeriod() {
    const range = parsePeriod(values[PERIOD]);
    periodBar.hidden = !range;
    if (!range) return;
    const show = (d) => dateFmt.format(new Date(`${d}T00:00:00Z`));
    periodBar.innerHTML = `<span class="chip on">${esc(t.periodLabel)}: ${esc(range[0] === range[1] ? show(range[0]) : `${show(range[0])} – ${show(range[1])}`)}</span>`;
    const x = el("button", { type: "button", class: "chip-x", "aria-label": t.clearPeriod, title: t.clearPeriod }, "✕");
    x.addEventListener("click", () => ctx.setPeriod(null));
    periodBar.append(x);
  }
  const grid = el("div", { class: "rgrid" });
  for (const row of spec.layout) for (const cell of row) {
    const root = panels.get(cell.panel).root;
    root.style.gridColumn = `span ${span[cell.panel]}`;
    grid.append(root);
  }
  $("#main").replaceChildren(periodBar, grid);
  renderPeriod();

  // ---- filters
  const optionRows = new Map();                         // filter id -> per-cube query results ([parent?, dimension] pairs)
  const bar = $("#filters");
  const selects = new Map();
  const parentFilter = (f) => (spec.filters || []).find((g) => g.dimension === f.parent);
  function fillOptions(f) {
    const sel = selects.get(f.id);
    const pf = parentFilter(f);
    const opts = optionsOf(optionRows.get(f.id) || [], f, pf ? values[pf.id] : "");
    if (values[f.id] && !opts.some((o) => o.value === values[f.id])) values[f.id] = "";
    const groups = new Map();
    for (const o of opts) {
      const k = !pf && o.parent !== undefined ? o.parent : "";
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(o);
    }
    const opt = (o) => el("option", { value: o.value }, esc(o.value));
    const optgroup = (label, os) => { const og = el("optgroup", { label }); og.append(...os.map(opt)); return og; };
    sel.replaceChildren(el("option", { value: "" }, esc(t.all)), ...[...groups].flatMap(([g, os]) => (g ? [optgroup(g, os)] : os.map(opt))));
    sel.value = values[f.id];
    sel.classList.toggle("set", !!values[f.id]);
  }
  async function loadOptions(signal) {
    await Promise.all((spec.filters || []).map(async (f) => {
      const measures = optionMeasures(spec, f);
      const dims = [...(f.parent ? [f.parent] : []), f.dimension];
      optionRows.set(f.id, measures.length ? await runAll(ctx.run, queriesPerCube(measures, { dimensions: dims }), signal) : []);
    }));
    for (const f of spec.filters || []) fillOptions(f);
  }
  function buildFilters() {
    if (!(spec.filters || []).length) return;
    bar.innerHTML = "";
    for (const f of spec.filters) {
      const sel = el("select", { "aria-label": f.label || f.id });
      selects.set(f.id, sel);
      const field = el("label", { class: "field" }, `${esc(f.label || f.id)} `);
      field.append(sel);
      bar.append(field);
      sel.addEventListener("change", () => {
        for (const k of Object.keys(saved)) delete saved[k];
        values[f.id] = sel.value;
        for (const g of spec.filters) if (parentFilter(g)?.id === f.id) fillOptions(g);   // a child's options follow its parent's value
        for (const g of spec.filters) selects.get(g.id).classList.toggle("set", !!values[g.id]);
        writeUrl();
        loadAll();
      });
    }
    const reset = el("button", { class: "reset", type: "button", hidden: "" }, esc(t.reset));
    reset.addEventListener("click", () => {
      for (const k of Object.keys(saved)) delete saved[k];
      for (const f of spec.filters) values[f.id] = "";
      values[PERIOD] = "";
      clearedHooks.forEach((h) => h());
      renderPeriod();
      for (const f of spec.filters) fillOptions(f);
      writeUrl();
      loadAll();
    });
    bar.append(reset);
    bar.hidden = false;
    ctx.syncReset = () => { reset.hidden = !Object.values(values).some(Boolean); };
  }
  /** Set filters from a patch { filterId: value } (a click on a panel): children's options follow, the selects show it, the URL records it. */
  function apply(patch) {
    Object.assign(values, patch);
    for (const f of spec.filters) if (parentFilter(f) && parentFilter(f).id in patch) fillOptions(f);
    for (const f of spec.filters) { const sel = selects.get(f.id); sel.value = values[f.id]; sel.classList.toggle("set", !!values[f.id]); }
    writeUrl();
    loadAll();
  }
  function writeUrl() {
    const q = new URLSearchParams(location.search);
    for (const f of spec.filters || []) { if (values[f.id]) q.set(f.id, values[f.id]); else q.delete(f.id); }
    if (values[PERIOD]) q.set("period", values[PERIOD]); else q.delete("period");
    for (const [id, path] of Object.entries(drills)) { if (path.length) q.set(`drill_${id}`, path.join(",")); else q.delete(`drill_${id}`); }
    history.replaceState(null, "", q.toString() ? `?${q}` : location.pathname);
    ctx.syncReset?.();
  }

  // ---- loading
  let ctrl = null, lastLoad = 0, seq = 0;
  async function loadAll({ force = false } = {}) {
    ctrl?.abort();
    ctrl = new AbortController();
    const mine = ++seq, signal = ctrl.signal;
    show("");
    const results = await Promise.allSettled([...panels.values()].map((p) => p.load(signal, { force })));
    if (mine !== seq) return;                           // a newer load took over
    const failed = results.filter((r) => r.status === "rejected" && r.reason?.name !== "AbortError");
    lastLoad = Date.now();
    const clock = new Date().toLocaleTimeString(fmt.locale, { hour12: false });
    if (failed.length === results.length && failed.length) { setStatus(`<strong>${esc(t.stale)}</strong> · ${esc(t.couldNotLoad)}`, "stale"); show(readable(failed[0].reason)); }
    else setStatus(`<strong>${esc(t.updated)}</strong> ${clock}`);
  }
  window.__render = { spec, values, panels, loadAll, ready: null };

  $("#export-all").hidden = false;
  $("#export-all").addEventListener("click", () => ctx.exportSheets([...panels.values()].map((p) => p.sheet()), "dashboard"));
  $("#refresh").hidden = false;
  $("#refresh").addEventListener("click", () => { loadOptions(new AbortController().signal).catch(() => {}); loadAll({ force: true }); });
  if (draft || savedDash) {
    const api = createBuilderApi({ stack: C, client, t });
    if (api.available) { const host = el("div", { id: "builder-host" }); $("#filters").before(host); if (draft) mountDraftBar(host, api, t, draft); else mountSavedBar(host, api, t, savedDash); }
  }
  buildFilters();
  ctx.syncReset?.();
  setStatus(esc(t.loading));
  await loadOptions(new AbortController().signal).catch((e) => console.warn("filter options failed:", e?.message || e));
  await loadAll();
  setInterval(() => { if (!document.hidden && Date.now() - lastLoad > REFRESH_MS) loadAll({ force: true }); }, 30_000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - lastLoad > REFRESH_MS) loadAll({ force: true }); });
}

// ------------------------------------------------------------------ start
(async () => {
  initDatasetControl();
  try {
    await client.token();                               // signs in (redirecting if needed) before the first request
    if (id) await showDashboard(); else await showList();
  } catch (e) {
    setStatus("<strong>Stale</strong> · not loaded", "stale");
    show(readable(e));
  }
})();
