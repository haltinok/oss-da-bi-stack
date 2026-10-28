// The dashboard renderer: /d/ lists the dashboards a role may open, /d/<id> draws one compiled spec (dashboards/build/<id>.json).
// Every number comes from Cube (the same sign-in, token and row-level security as the sales dashboard); this page builds queries from
// member names and never writes SQL. Panels load independently and in parallel; changing a filter cancels the queries still running.
import { createCubeClient } from "/cube/cube-client.mjs";
import { $, el, esc } from "../lib/dom.js";
import { createFormat } from "../lib/format.js";
import { describeValue } from "../lib/filters.js";
import { createTooltip } from "../lib/tooltip.js";
import { downloadXlsx, slugify } from "../lib/table.js";
import { createPanel, readable } from "./panels.js";
import { formatPeriod, normalizeTabs, optionMeasures, optionsOf, parsePeriod, PERIOD, pick, pickTab, queriesPerCube, runAll, slicerQueries, tabKeyTarget, tabPanelIds } from "./plan.js";
import { langOf, stringsFor, uiLocale } from "./strings.js";
import { initTheme, mountThemeMenu } from "../lib/theme.js";
import { mountLangSwitch } from "./lang.js";
import { createControl, createSlicer } from "./filter-controls.js";
import { createBuilderApi, drafts, mountDraftBar, mountSavedBar } from "./builder.js";
import { mountDesigner } from "./designer.js";
import { mountList } from "./list.js";

const REFRESH_MS = 5 * 60_000;
const C = window.STACK;
const show = (msg) => { const e = $("#error"); e.textContent = msg; e.hidden = !msg; };

initTheme();
mountThemeMenu($("#theme"), { locale: () => document.documentElement.lang || "en" });

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
    const t = stringsFor(uiLocale(navigator.language));
    const who = el("div", { id: "who", class: "who", title: t.signedInAs(s.user, s.role) }, `${esc(s.user)} · <a href="#" id="signout">${esc(t.signOut)}</a>`);
    who.dataset.user = s.user;
    who.dataset.role = s.role;
    $("#tools").append(who);
    $("#signout").addEventListener("click", (e) => { e.preventDefault(); client.signOut(); });
  },
});

/** The words the page's HTML holds in English (dataset, theme button, signed-in line, first status), in the page's language; the EN | TR switch too. */
function localizeChrome(t, locale) {
  const lang = langOf(locale);
  document.documentElement.lang = lang;
  mountLangSwitch(t, lang);
  $("#dataset-badge").title = t.datasetTitle(dataset.label, dataset.mart);
  $("#dataset-label").textContent = t.datasetLabel;
  $("#f-dataset").setAttribute("aria-label", t.datasetLabel);
  $("#theme").title = t.themeToggle;
  $("#theme").setAttribute("aria-label", t.themeToggle);
  const who = $("#who");
  if (who) {
    who.title = t.signedInAs(who.dataset.user, who.dataset.role);
    if ($("#signout")) $("#signout").textContent = t.signOut;
  }
}

function initDatasetControl() {
  const badge = $("#dataset-badge");
  badge.textContent = dataset.label;
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
/** The link back to the list, in the page's own language; the whole line is hidden on the list itself. */
function setHomeLink(t, hidden = false) {
  const link = $("#home-link");
  if (!link) return;
  $("#home-label").textContent = t.dashboards;
  link.title = t.dashboards;
  link.closest("nav").setAttribute("aria-label", t.dashboards);
  link.closest("nav").hidden = hidden;
}

async function showList() {
  document.title = "Dashboards";
  const index = await (await fetch("/dashboards/index.json", { cache: "no-store" })).json().catch(() => []);
  const role = client.session().role;
  const mine = index.filter((d) => !d.roles?.length || d.roles.includes(role));
  const locale = uiLocale(navigator.language);
  const t = stringsFor(locale);
  setHomeLink(t, true);
  localizeChrome(t, locale);
  document.title = t.dashboards;
  $("#title").textContent = t.dashboards;
  $("#export-label").textContent = t.exportAll;
  setStatus(`<strong>${esc(t.signedIn)}</strong>`);
  const api = createBuilderApi({ stack: C, client, t });
  mountList({ main: $("#main"), mine, api, t });
}

// ------------------------------------------------------------------ one dashboard
async function showDashboard() {
  const locale0 = uiLocale(navigator.language);
  const t0 = stringsFor(locale0);
  localizeChrome(t0, locale0);
  setHomeLink(t0);                                              // visible from the start, so an error page (no such dashboard, wrong role) still leads back
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
  const locale = uiLocale(spec.locale || "en-US");              // the person's choice (EN | TR), else the dashboard's own locale
  const t = stringsFor(locale);
  setHomeLink(t);
  localizeChrome(t, locale);
  $("#filters").setAttribute("aria-label", t.filters);
  if (spec.roles?.length && !spec.roles.includes(role)) throw new Error(t.notForRole(spec.title, role));
  applyTheme(spec.theme);
  $("#export-label").textContent = t.exportAll;
  $("#refresh").title = $("#refresh").ariaLabel = t.refresh;
  if ($("#signout")) $("#signout").textContent = t.signOut;

  document.title = `${draft ? `${t.draft}: ` : ""}${spec.title} · ${dataset.label}`;
  $("#title").textContent = spec.title;
  $("#brand-sub").textContent = spec.description || "";
  const fmt = createFormat({ locale, currency: spec.currency || "USD" });
  const tooltip = createTooltip($("#tip"));
  const dateFmt = new Intl.DateTimeFormat(fmt.locale, { dateStyle: "medium", timeZone: "UTC" });
  const dateTimeFmt = new Intl.DateTimeFormat(fmt.locale, { dateStyle: "medium", timeStyle: "short" });
  const asDate = (b) => new Date(`${String(b).slice(0, 19)}Z`);

  const qs = new URLSearchParams(location.search);
  // A filter opens at its `default` unless the address says otherwise (an address with `?id=` and nothing after it means "cleared", see writeUrl).
  // A hidden filter always holds its default, whatever the address says.
  const values = Object.fromEntries((spec.filters || []).map((f) => [f.id, f.visible !== false && qs.has(f.id) ? qs.get(f.id) : f.default || ""]));
  const visibleFilters = () => (spec.filters || []).filter((f) => f.visible !== false);
  values[PERIOD] = parsePeriod(qs.get("period")) ? qs.get("period") : "";             // the date range a drill-down sets (other panels follow it)
  const drills = Object.fromEntries(spec.panels.filter((p) => p.drill).map((p) => [p.id, (qs.get(`drill_${p.id}`) || "").split(",").filter((b) => /^\d{4}-\d{2}-\d{2}/.test(b))]));
  const clearedHooks = [];
  const tabs = normalizeTabs(spec);
  const tabbed = !!spec.tabs?.length;                    // a plain `layout` is one untitled tab and has no tab bar
  let activeTab = pickTab(tabs, qs.get("tab"));
  const span = Object.fromEntries(tabs.flatMap((tab) => tab.layout.flat()).map((c) => [c.panel, c.span]));

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
      const parts = (spec.filters || []).filter((f) => values[f.id]).map((f) => `${f.label || f.id}: ${describeValue(f, values[f.id])}`);
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
  // One grid per tab, all in the page; the open one is shown and only its panels are loaded (a panel's `load` is cached by filters and period).
  const tabBar = tabbed ? el("div", { class: "rtabs", role: "tablist", "aria-label": t.tabsLabel }) : null;
  const grids = new Map();
  for (const tab of tabs) {
    const grid = el("div", { class: "rgrid", ...(tabbed ? { id: `tabpanel-${tab.id}`, role: "tabpanel", "aria-labelledby": `tab-${tab.id}` } : {}) });
    for (const row of tab.layout) for (const cell of row) {
      const root = panels.get(cell.panel).root;
      root.style.gridColumn = `span ${span[cell.panel]}`;
      grid.append(root);
    }
    grid.hidden = tab.id !== activeTab;
    grids.set(tab.id, grid);
    if (tabbed) {
      const b = el("button", { type: "button", role: "tab", id: `tab-${tab.id}`, "aria-controls": `tabpanel-${tab.id}`, "data-tab": tab.id, "aria-selected": String(tab.id === activeTab), tabindex: tab.id === activeTab ? "0" : "-1" });
      b.textContent = tab.title;
      tabBar.append(b);
    }
  }
  // The selection bar: what clicks on cross-filtering panels have chosen (the filters `cross_filter` made, marked `implicit`), one chip each with a way to remove it.
  const selectionBar = el("div", { id: "selection-bar", class: "period-bar selection-bar", role: "group", "aria-label": t.selection, hidden: "" });
  function renderSelection() {
    const shown = (spec.filters || []).filter((f) => f.implicit && values[f.id] && (!f.tab || f.tab === activeTab));          // a tab's own filters show on that tab
    selectionBar.hidden = !shown.length;
    selectionBar.replaceChildren(...shown.flatMap((f) => {
      const text = `${f.label || f.id}: ${values[f.id]}`;
      const chip = el("span", { class: "chip on" }, esc(text));
      const x = el("button", { type: "button", class: "chip-x", "aria-label": t.removeSelection(text), title: t.removeSelection(text) }, "✕");
      x.addEventListener("click", () => changeFilter(f, ""));
      return [chip, x];
    }));
  }
  $("#main").replaceChildren(periodBar, selectionBar, ...(tabbed ? [tabBar] : []), ...grids.values());
  renderPeriod();

  // ---- filters
  const optionRows = new Map();                         // filter id -> per-cube query results ([parent?, dimension] pairs)
  const bar = $("#filters");
  const selects = new Map();                            // select filters: the <select>
  const controls = new Map();                           // every other type: a control from filter-controls.js
  /** Shows a filter's value in its control, and marks it as set. */
  const showValue = (f) => {
    const sel = selects.get(f.id);
    if (sel) { sel.value = values[f.id]; sel.classList.toggle("set", !!values[f.id]); } else controls.get(f.id)?.show(values[f.id]);
  };
  const parentFilter = (f) => (spec.filters || []).find((g) => g.dimension === f.parent);
  function fillOptions(f) {
    const sel = selects.get(f.id);
    const pf = parentFilter(f);
    const opts = optionsOf(optionRows.get(f.id) || [], f, pf ? values[pf.id] : "");
    if (controls.get(f.id)?.setOptions && (f.type === "multiselect" || slicerOf.has(f.id))) { controls.get(f.id).setOptions(opts); return; }       // its chosen values stay, even ones the options do not hold now
    if (!sel) return;                                                                      // text, number and date filters have no options
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
    await Promise.all(visibleFilters().filter((f) => !f.implicit && (!f.type || f.type === "select" || f.type === "multiselect")).map(async (f) => {
      if (slicerOf.has(f.id)) { optionRows.set(f.id, await runAll(ctx.run, slicerQueries(spec, slicerOf.get(f.id), values), signal)); return; }          // narrowed by the other filters
      const measures = optionMeasures(spec, f);
      const dims = [...(f.parent ? [f.parent] : []), f.dimension];
      optionRows.set(f.id, measures.length ? await runAll(ctx.run, queriesPerCube(measures, { dimensions: dims }), signal) : []);
    }));
    for (const f of visibleFilters()) fillOptions(f);
  }
  // Where a filter is drawn: the header (dashboard), above one tab's panels (page), or in one panel's card (pane). `filterEls` keeps each control's element so a rebuilt card gets its filter back.
  const filterEls = new Map();
  const tabBars = new Map();
  /** filter id -> the slicer panel that draws it (a slicer draws a filter in the layout instead of the header, the tab's bar or a card). */
  const slicerOf = new Map(spec.panels.filter((p) => p.type === "slicer").map((p) => [p.filter, p]));
  function attach(f) {
    const node = filterEls.get(f.id);
    if (!node) return;
    if (slicerOf.has(f.id)) {
      panels.get(slicerOf.get(f.id).id)?.root.querySelector(".slicer-body")?.append(node);
      return;
    }
    if (f.scope === "page") {
      let host = tabBars.get(f.tab);
      if (!host) { host = el("nav", { class: "filters rfilters tab-filters", "aria-label": t.filters }); tabBars.set(f.tab, host); grids.get(f.tab)?.prepend(host); }
      host.append(node);
    } else if (f.scope === "panel") {
      const root = panels.get(f.panel)?.root;
      if (!root) return;
      const head = root.querySelector(".card-h");                                  // a row of key figures has no card header: its filters go above the tiles
      let host = root.querySelector(".pane-filters");
      if (!host) { host = el("div", { class: "pane-filters" }); if (head) head.querySelector(".spacer")?.before(host); else root.prepend(host); }
      host.append(node);
    } else bar.append(node);
  }
  ctx.attachPaneFilters = (panelId) => { for (const f of visibleFilters()) if ((slicerOf.get(f.id)?.id ?? (f.scope === "panel" ? f.panel : null)) === panelId) attach(f); };
  /** The reader changed filter `f` to `value` (the bar, a slicer, or a chip's remove button). */
  function changeFilter(f, value) {
    if ((values[f.id] || "") === value) return;                                           // Enter and then leaving the box say the same thing twice: load once
    for (const k of Object.keys(saved)) delete saved[k];
    values[f.id] = value;
    for (const g of spec.filters) if (parentFilter(g)?.id === f.id) fillOptions(g);       // a child's options follow its parent's value
    for (const g of spec.filters) { const sel = selects.get(g.id); if (sel) sel.classList.toggle("set", !!values[g.id]); }
    writeUrl();
    loadAll();
  }
  function buildFilters() {
    if (!visibleFilters().length) return;
    bar.innerHTML = "";
    /** The reader changed filter `f` to `value` (the bar, either kind of control). */
    const changed = changeFilter;
    for (const f of visibleFilters()) {
      if (f.implicit) continue;                                                              // drawn as a chip in the selection bar, not as a control
      const slicer = slicerOf.get(f.id);
      if (slicer && (slicer.display || "list") !== "dropdown" && (!f.type || f.type === "select" || f.type === "multiselect")) {
        const control = createSlicer(f, t, slicer.display || "list");
        controls.set(f.id, control);
        control.onChange = (v) => changed(f, v);
        control.show(values[f.id]);
        filterEls.set(f.id, control.el);
        attach(f);
        continue;
      }
      if (f.type && f.type !== "select") {
        const control = createControl(f, t);
        controls.set(f.id, control);
        control.onChange = (v) => changed(f, v);
        control.show(values[f.id]);
        filterEls.set(f.id, control.el);
        attach(f);
        continue;
      }
      const sel = el("select", { "aria-label": f.label || f.id });
      selects.set(f.id, sel);
      const field = el("label", { class: "field" }, `${esc(f.label || f.id)} `);
      field.append(sel);
      filterEls.set(f.id, field);
      attach(f);
      sel.addEventListener("change", () => changed(f, sel.value));
    }
    const reset = el("button", { class: "reset", type: "button", hidden: "" }, esc(t.reset));
    reset.addEventListener("click", () => {
      for (const k of Object.keys(saved)) delete saved[k];
      for (const f of visibleFilters()) values[f.id] = f.default || "";                     // Reset goes back to where the page opened (a hidden filter never moved)
      values[PERIOD] = "";
      clearedHooks.forEach((h) => h());
      renderPeriod();
      for (const f of visibleFilters()) { fillOptions(f); showValue(f); }
      writeUrl();
      loadAll();
    });
    bar.append(reset);
    const dashboardBar = visibleFilters().some((f) => (!f.scope || f.scope === "dashboard") && !slicerOf.has(f.id) && !f.implicit);
    bar.hidden = !dashboardBar;                                                              // with only page and pane filters the header bar shows when Reset is needed
    ctx.syncReset = () => {
      const needed = visibleFilters().some((f) => (values[f.id] || "") !== (f.default || "")) || !!values[PERIOD];
      reset.hidden = !needed;
      bar.hidden = !(dashboardBar || needed);
    };
  }
  /** Set filters from a patch { filterId: value } (a click on a panel): children's options follow, the selects show it, the URL records it. */
  function apply(patch) {
    Object.assign(values, patch);
    for (const f of visibleFilters()) if (parentFilter(f) && parentFilter(f).id in patch) fillOptions(f);
    for (const f of visibleFilters()) showValue(f);
    writeUrl();
    loadAll();
  }
  /** A slicer's options follow the other filters and the period: after any change they are asked for again (one request at a time, the last one wins). */
  let slicerCtrl = null, slicerTimer = 0;
  function refreshSlicers() {
    if (!slicerOf.size) return;
    clearTimeout(slicerTimer);
    slicerTimer = setTimeout(async () => {
      slicerCtrl?.abort();
      slicerCtrl = new AbortController();
      const signal = slicerCtrl.signal;
      await Promise.all([...slicerOf].map(async ([id, panel]) => {
        const f = (spec.filters || []).find((x) => x.id === id);
        if (!f || f.visible === false || !["select", "multiselect"].includes(f.type || "select")) return;
        try { optionRows.set(id, await runAll(ctx.run, slicerQueries(spec, panel, values), signal)); fillOptions(f); } catch (e) { if (e?.name !== "AbortError") console.warn(`slicer ${panel.id} options failed:`, e?.message || e); }
      }));
    }, 120);
  }
  function writeUrl() {
    const q = new URLSearchParams(location.search);
    // Only what differs from the default is written; a filter cleared while it has a default is written as `?id=` (so a reload does not bring the default back).
    for (const f of spec.filters || []) { const v = values[f.id] || ""; if (f.visible === false || v === (f.default || "")) q.delete(f.id); else q.set(f.id, v); }
    if (values[PERIOD]) q.set("period", values[PERIOD]); else q.delete("period");
    for (const [id, path] of Object.entries(drills)) { if (path.length) q.set(`drill_${id}`, path.join(",")); else q.delete(`drill_${id}`); }
    if (tabbed && activeTab !== tabs[0].id) q.set("tab", activeTab); else q.delete("tab");
    history.replaceState(null, "", q.toString() ? `?${q}` : location.pathname);
    ctx.syncReset?.();
    refreshSlicers();
    renderSelection();
  }

  // ---- loading
  let ctrl = null, lastLoad = 0, seq = 0;
  const tabLoadedAt = new Map();                        // tab id -> when its panels last finished loading
  const openPanels = () => tabPanelIds(tabs.find((tab) => tab.id === activeTab)).map((id) => panels.get(id));
  /** Loads the open tab's panels (a newer load cancels an older one, so moving quickly between tabs costs nothing). */
  async function loadAll({ force = false } = {}) {
    ctrl?.abort();
    ctrl = new AbortController();
    const mine = ++seq, signal = ctrl.signal, loading = activeTab;
    show("");
    const results = await Promise.allSettled(openPanels().map((p) => p.load(signal, { force })));
    if (mine !== seq) return;                           // a newer load took over
    const failed = results.filter((r) => r.status === "rejected" && r.reason?.name !== "AbortError");
    lastLoad = Date.now();
    tabLoadedAt.set(loading, lastLoad);
    const clock = new Date().toLocaleTimeString(fmt.locale, { hour12: false });
    if (failed.length === results.length && failed.length) { setStatus(`<strong>${esc(t.stale)}</strong> · ${esc(t.couldNotLoad)}`, "stale"); show(readable(failed[0].reason)); }
    else setStatus(`<strong>${esc(t.updated)}</strong> ${clock}`);
  }
  /** Opens a tab: shows its grid, keeps the address, and loads it (reloading with `force` when its data is older than the refresh interval). */
  function openTab(id, { focus = false } = {}) {
    if (id === activeTab && !focus) return;
    activeTab = id;
    for (const [tid, grid] of grids) grid.hidden = tid !== id;
    for (const b of tabBar.querySelectorAll('[role="tab"]')) { const on = b.dataset.tab === id; b.setAttribute("aria-selected", String(on)); b.tabIndex = on ? 0 : -1; }
    if (focus) tabBar.querySelector(`[data-tab="${id}"]`).focus();
    writeUrl();
    loadAll({ force: tabLoadedAt.has(id) && Date.now() - tabLoadedAt.get(id) > REFRESH_MS });
  }
  if (tabbed) {
    tabBar.addEventListener("click", (e) => { const b = e.target.closest('[role="tab"]'); if (b) openTab(b.dataset.tab); });
    tabBar.addEventListener("keydown", (e) => {
      const to = tabKeyTarget(e.key, tabs.findIndex((tab) => tab.id === activeTab), tabs.length);
      if (to === null || e.ctrlKey || e.metaKey || e.altKey) return;
      e.preventDefault();
      openTab(tabs[to].id, { focus: true });
    });
  }
  /**
   * The designer's way of applying a change without drawing the page again (render/designer.js `commit`): `next` is the new compiled spec. Changes to panels' own fields
   * (a changed title is written into the card, any other change builds that one panel again in the same place and loads it) and to the layout (the cards are put in their
   * new rows and widths) are applied here; everything else (the page's own fields, filters, the tabs themselves, panels added or removed) is left to a reload.
   * Returns true when the change was applied here.
   */
  function patch(next) {
    const rest = (s) => JSON.stringify({ ...s, panels: undefined, members: undefined, cubes: undefined, layout: undefined, tabs: undefined });
    const tabHeads = (s) => JSON.stringify(s.tabs ? s.tabs.map((t) => [t.id, t.title]) : null);
    if (rest(next) !== rest(spec) || tabHeads(next) !== tabHeads(spec) || next.panels.length !== spec.panels.length || next.panels.some((p, i) => p.id !== spec.panels[i].id)) return false;
    const changed = next.panels.map((def, i) => [def, i]).filter(([def, i]) => JSON.stringify(def) !== JSON.stringify(spec.panels[i]));
    const titleOnly = (a, b) => JSON.stringify({ ...a, title: 0 }) === JSON.stringify({ ...b, title: 0 });
    if (changed.some(([def, i]) => def.type === "slicer" && !titleOnly(def, spec.panels[i]))) return false;                    // moving a filter between the bar and a slicer is left to a reload
    spec.members = next.members;
    spec.cubes = next.cubes;
    const rebuilt = [];
    for (const [def, i] of changed) {
      const { title: oldTitle, ...oldRest } = spec.panels[i], { title: newTitle, ...newRest } = def;
      const h2 = panels.get(def.id).root.querySelector(".card-h h2");
      if (JSON.stringify(oldRest) === JSON.stringify(newRest) && h2) { spec.panels[i].title = newTitle; h2.textContent = newTitle || ""; continue; }          // only the title: nothing else is touched
      spec.panels[i] = def;
      const made = createPanel(def, ctx), previous = panels.get(def.id).root;
      made.root.style.gridColumn = previous.style.gridColumn;
      previous.replaceWith(made.root);
      panels.set(def.id, made);
      ctx.attachPaneFilters?.(def.id);
      rebuilt.push(made);
    }
    const moved = JSON.stringify([next.layout, next.tabs]) !== JSON.stringify([spec.layout, spec.tabs]);
    if (moved) {
      if (tabbed) next.tabs.forEach((t, i) => { tabs[i].layout = t.layout; }); else { spec.layout = next.layout; tabs[0].layout = next.layout; }
      for (const k of Object.keys(span)) delete span[k];
      for (const c of tabs.flatMap((tab) => tab.layout.flat())) span[c.panel] = c.span;
      for (const tab of tabs) {
        const roots = tab.layout.flat().map((c) => { const root = panels.get(c.panel).root; root.style.gridColumn = `span ${c.span}`; return root; });
        grids.get(tab.id).replaceChildren(...roots);
      }
    }
    if (moved) loadAll();                                    // cards that came into the open tab are loaded; the others only redraw to their new width (their data is cached)
    else {
      const open = new Set(openPanels());
      const now = rebuilt.filter((p) => open.has(p));
      if (now.length) { const c = new AbortController(); Promise.allSettled(now.map((p) => p.load(c.signal))); }
    }
    window.__render.patchCount = (window.__render.patchCount || 0) + 1;                 // for the tests: a change applied here
    return true;
  }
  /** The values a select or multiselect filter offers (for the designer's default-value picker); [] until its options have loaded. */
  const filterOptions = (id) => { const f = (spec.filters || []).find((x) => x.id === id); return f ? optionsOf(optionRows.get(id) || [], f, "").map((o) => o.value) : []; };
  window.__render = { spec, values, panels, loadAll, tabLoadedAt, openTab, patch, filterOptions, activeTab: () => activeTab, ready: null };

  $("#export-all").hidden = false;
  $("#export-all").addEventListener("click", async () => {
    // Every tab goes in: the ones never opened (or left stale by a filter change) are loaded first; a failed panel just has no sheet.
    const signal = new AbortController().signal;
    await Promise.allSettled([...panels.values()].map((p) => p.load(signal)));
    ctx.exportSheets([...panels.values()].map((p) => p.sheet()), "dashboard");
  });
  $("#refresh").hidden = false;
  $("#refresh").addEventListener("click", () => { loadOptions(new AbortController().signal).catch(() => {}); loadAll({ force: true }); });
  if (draft || savedDash) {
    const api = createBuilderApi({ stack: C, client, t });
    if (api.available) { const host = el("div", { id: "builder-host" }); $("#filters").before(host); if (draft) { mountDraftBar(host, api, t, draft); mountDesigner({ api, t, draft, spec, panels, host }); } else mountSavedBar(host, api, t, savedDash); }
  }
  buildFilters();
  ctx.syncReset?.();
  renderSelection();
  setStatus(esc(t.loading));
  await loadOptions(new AbortController().signal).catch((e) => console.warn("filter options failed:", e?.message || e));
  await loadAll();
  setInterval(() => { if (!document.hidden && Date.now() - lastLoad > REFRESH_MS) loadAll({ force: true }); }, 30_000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - lastLoad > REFRESH_MS) loadAll({ force: true }); });
}

// ------------------------------------------------------------------ start
(async () => {
  initDatasetControl();
  localizeChrome(stringsFor(uiLocale(navigator.language)), uiLocale(navigator.language));      // the words that wait in the HTML, before anything loads
  $("#live-text").textContent = stringsFor(uiLocale(navigator.language)).connecting;
  try {
    await client.token();                               // signs in (redirecting if needed) before the first request
    if (id) await showDashboard(); else await showList();
  } catch (e) {
    const t = stringsFor(uiLocale(navigator.language));
    $("#title").textContent = document.title = t.dashboards;
    setStatus(`<strong>${esc(t.stale)}</strong> · ${esc(t.notLoaded)}`, "stale");
    show(readable(e));
  }
})();
