// The dashboard renderer: /d/ lists the dashboards a role may open, /d/<id> draws one compiled spec (dashboards/build/<id>.json).
// Every number comes from Cube (the same sign-in, token and row-level security as the sales dashboard); this page builds queries from
// member names and never writes SQL. Panels load independently and in parallel; changing a filter cancels the queries still running.
import { createCubeClient } from "/cube/cube-client.mjs";
import { $, el, esc } from "../lib/dom.js";
import { createFormat } from "../lib/format.js";
import { describeValue } from "../lib/filters.js";
import { setMemberLabels } from "../lib/labels.js";
import { createTooltip } from "../lib/tooltip.js";
import { downloadXlsx, slugify } from "../lib/table.js";
import { createPanel, readable } from "./panels.js";
import { formatPeriod, humanize, normalizeTabs, optionMeasures, optionsOf, parsePeriod, sortKeyOf, withSortKeys, PERIOD, isSelected, pick, pickTab, queriesPerCube, runAll, periodDims, periodKey, slicerQueries, tabKeyTarget, tabPanelIds } from "./plan.js";
import { langOf, stringsFor, uiLocale } from "./strings.js";
import { initTheme, mountThemeMenu } from "../lib/theme.js";
import { mountLangSwitch } from "./lang.js";
import { createControl, createSlicer } from "./filter-controls.js";
import { createBuilderApi, drafts, mountDraftBar, mountSavedBar } from "./builder.js";
import { mountDesigner } from "./designer.js";
import { mountList } from "./list.js";
import { noteRecent } from "../lib/recent.js";
import { life, onGo, onRedraw, renew } from "../lib/life.js";

const REFRESH_MS = 5 * 60_000;
const C = window.STACK;
const show = (msg) => { const e = $("#error"); e.textContent = msg; e.hidden = !msg; };
// One tooltip and one panel context for the life of the page, not of one drawing of the dashboard: a remount refills `pageCtx`, and the panels it keeps
// (their definition did not change) read the new spec, filters and functions through it, and their tooltips stay registered.
const tooltip = createTooltip($("#tip"));
const pageCtx = {};

initTheme();
mountThemeMenu($("#theme"), { locale: () => document.documentElement.lang || "en" });

// ------------------------------------------------------------------ dataset (the same choice and storage as the sales dashboard)
const DATASETS = C.datasets || [{ id: "live", label: "Live (simulator)", mart: "mart", cube: C.cube }];
const keep = { get: () => { try { return localStorage.getItem("dataset"); } catch { return null; } }, set: (v) => { try { localStorage.setItem("dataset", v); } catch { /* ignore */ } } };
const wanted = new URLSearchParams(location.search).get("dataset") || keep.get();
const dataset = DATASETS.find((d) => d.id === wanted) || DATASETS[0];
keep.set(dataset.id);

const idOf = (path) => decodeURIComponent(path.replace(/^\/d\/?/, "").replace(/\/$/, ""));
let id = idOf(location.pathname);                                  // the dashboard shown; go() and Back / Forward change it without loading the page
const client = createCubeClient({
  stack: C, apiUrl: dataset.cube, redirect: `${location.origin}${location.pathname}`,
  onSession(s) {
    if ($("#who")) return;
    const t = stringsFor(uiLocale(navigator.language));
    const adminLink = s.role === "admin" ? `<a href="/admin/" id="admin-link">${langOf(uiLocale(navigator.language)) === "tr" ? "Yönetim" : "Admin"}</a> · ` : "";
    const who = el("div", { id: "who", class: "who", title: t.signedInAs(s.user, s.role) }, `${adminLink}${esc(s.user)} · <a href="#" id="signout">${esc(t.signOut)}</a>`);
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
  if ($("#home-start")) { $("#home-start").title = t.home; $("#home-start").setAttribute("aria-label", t.home); }
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

/** A dashboard's own look: a name and logo in the header, and colours for the theme tokens (a series `color: series1` follows them; `internet` and `reseller` are the old names of series1 and series2). */
const TOKEN_ALIASES = { internet: "series1", reseller: "series2" };
function applyTheme(theme = {}) {
  if (theme.name) { $("#brand-name").textContent = theme.name; $("#brand-name").hidden = false; }
  if (theme.logo) { $("#logo").src = theme.logo; $("#logo").hidden = false; }
  for (const [token, hex] of Object.entries(theme.colors || {})) {
    document.documentElement.style.setProperty(`--${token}`, hex);
    if (TOKEN_ALIASES[token]) document.documentElement.style.setProperty(`--${TOKEN_ALIASES[token]}`, hex);          // the old name recolours the new one, so the default cycle follows
  }
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
  const locale = uiLocale(navigator.language);
  const t = stringsFor(locale);
  const api = createBuilderApi({ stack: C, client, t });
  let readable = null;                                                          // the samples this person can open (what datasets leave them); all of them when the builder cannot say
  if (api.available) { try { readable = new Set((await api.samples()).filter((x) => x.readable).map((x) => x.id)); } catch { readable = null; } }
  const mine = index.filter((d) => !readable || readable.has(d.id));
  setHomeLink(t, true);
  localizeChrome(t, locale);
  document.title = t.dashboards;
  $("#title").textContent = t.dashboards;
  $("#export-label").textContent = t.exportAll;
  setStatus(`<strong>${esc(t.signedIn)}</strong>`);
  mountList({ main: $("#main"), mine, api, t, viewer: role === "viewer" });
}

// ------------------------------------------------------------------ one dashboard
/**
 * Draws the dashboard of this address. It can run again in the same page (`remount`): what it adds outside its own elements is tied to the signal of
 * lib/life.js, which a remount ends first. `again`: drawn again from what this page already checked (the draft is not compiled once more).
 */
async function showDashboard({ again = false, counts = {}, carry = null } = {}) {
  const pageSignal = life();                                     // the page's life (lib/life.js); `signal` below is one load's
  const locale0 = uiLocale(navigator.language);
  const t0 = stringsFor(locale0);
  localizeChrome(t0, locale0);
  setHomeLink(t0);                                              // visible from the start, so an error page (no such dashboard, wrong role) still leads back
  let draft = id === "draft" ? drafts.current() : null;       // a draft lives in this browser (see builder.js); a saved dashboard (s/<id>) comes from the builder service; every other id is a built file
  let spec, savedDash = null;
  if (id.startsWith("s/")) {
    const api = createBuilderApi({ stack: C, client, t: t0 });
    try { savedDash = await api.openSaved(id.slice(2)); } catch (e) { throw new Error(e.problems?.length ? `${e.message} ${e.problems[0]}` : e.message); }
    spec = savedDash.spec;
  } else if (id === "draft") {
    if (!draft?.spec) throw new Error(t0.noDraft);
    const api = createBuilderApi({ stack: C, client, t: t0 });
    if (api.available && draft.yaml && !again) {                // the stored page may predate the compiler (cross-filtering, say): compile the file again
      try { const r = await api.validate(draft.yaml); if (r?.ok && r.spec) draft = drafts.recompiled(r.spec) || draft; } catch { /* keep the stored page */ }
    }
    spec = draft.spec;
  } else {
    const res = await fetch(`/dashboards/${encodeURIComponent(id)}.json`, { cache: "no-store" });
    if (!res.ok) throw new Error(res.status === 404 ? t0.noSuchDashboard(id) : t0.loadFailed(res.status));
    spec = await res.json();
  }
  if (pageSignal.aborted) return;                                // drawn again (or another dashboard) while this one was being fetched: that one draws the page
  const role = client.session().role;
  if (id !== "draft") noteRecent({ kind: id.startsWith("s/") ? "saved" : "built", id: id.startsWith("s/") ? id.slice(2) : id, title: spec.title });        // for the start page's "pick up where you left off"
  const locale = uiLocale(spec.locale || "en-US");              // the person's choice (EN | TR), else the dashboard's own locale
  const t = stringsFor(locale);
  setHomeLink(t);
  localizeChrome(t, locale);
  $("#filters").setAttribute("aria-label", t.filters);
  applyTheme(spec.theme);
  $("#export-label").textContent = t.exportAll;
  $("#refresh").title = $("#refresh").ariaLabel = t.refresh;
  if ($("#signout")) $("#signout").textContent = t.signOut;

  document.title = `${draft ? `${t.draft}: ` : ""}${spec.title} · ${dataset.label}`;
  $("#title").textContent = spec.title;
  $("#brand-sub").textContent = spec.description || "";
  const fmt = createFormat({ locale, currency: spec.currency || "USD" });
  const dateFmt = new Intl.DateTimeFormat(fmt.locale, { dateStyle: "medium", timeZone: "UTC" });
  const dateTimeFmt = new Intl.DateTimeFormat(fmt.locale, { dateStyle: "medium", timeStyle: "short" });
  const asDate = (b) => new Date(`${String(b).slice(0, 19)}Z`);

  setMemberLabels(Object.fromEntries(Object.entries(spec.members || {}).filter(([, m]) => m.label).map(([k, m]) => [k, m.label])));          // "Ship month name" for the fields of a role-playing cube
  const qs = new URLSearchParams(location.search);
  // A filter opens at its `default` unless the address says otherwise (an address with `?id=` and nothing after it means "cleared", see writeUrl).
  // A hidden filter always holds its default, whatever the address says.
  const values = Object.fromEntries((spec.filters || []).map((f) => [f.id, f.visible !== false && qs.has(f.id) ? qs.get(f.id) : f.default || ""]));
  const visibleFilters = () => (spec.filters || []).filter((f) => f.visible !== false);
  // The date range a drill-down sets (the other panels on the same date field follow it): `period` for the dashboard's own date, `period_<field>` for another date role.
  const periodParam = (dim) => (dim === spec.time.dimension ? "period" : `period_${dim}`);
  for (const dim of periodDims(spec)) values[periodKey(spec, dim)] = parsePeriod(qs.get(periodParam(dim))) ? qs.get(periodParam(dim)) : "";
  const anyPeriod = () => periodDims(spec).some((dim) => values[periodKey(spec, dim)]);
  const drills = Object.fromEntries(spec.panels.filter((p) => p.drill).map((p) => [p.id, (qs.get(`drill_${p.id}`) || "").split(",").filter((b) => /^\d{4}-\d{2}-\d{2}/.test(b))]));
  const clearedHooks = [];
  const tabs = normalizeTabs(spec);
  const tabbed = !!spec.tabs?.length;                    // a plain `layout` is one untitled tab and has no tab bar
  let activeTab = pickTab(tabs, qs.get("tab"));
  const span = Object.fromEntries(tabs.flatMap((tab) => tab.layout.flat()).map((c) => [c.panel, c.span]));

  const ctx = pageCtx;
  for (const k of Object.keys(ctx)) delete ctx[k];                // what the last drawing added (syncReset, attachPaneFilters) must not outlive it
  Object.assign(ctx, {
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
    period: (dim = spec.time.dimension) => parsePeriod(values[periodKey(spec, dim)]),
    setPeriod(range, dim = spec.time.dimension) { values[periodKey(spec, dim)] = range ? formatPeriod(range[0], range[1]) : ""; if (!range) clearedHooks.filter((h) => h.dim === dim).forEach((h) => h.fn()); renderPeriod(); writeUrl(); loadAll(); },
    drillPath: (id) => drills[id] || [],
    setDrill(id, path) { drills[id] = path; },
    onPeriodCleared: (fn, dim = spec.time.dimension) => clearedHooks.push({ fn, dim }),
    bodyWidth: (id) => panels.get(id)?.root.querySelector(".panel-body")?.clientWidth || 640,
    // A click on a panel sets filters (see plan.js `pick`): the page applies them like a change in the filter bar.
    pick: (ids, vals) => {
      const was = isSelected(values, ids, vals), patch = pick(values, ids, vals, saved);
      values._clicked = was ? (values._clicked || []).filter((i) => !ids.includes(i)) : [...new Set([...(values._clicked || []), ...ids])];          // which filters hold a choice made by a click (see clickedIds)
      apply(patch);
    },
  });
  const saved = {};                                     // what the filters held before a click, so that clicking again can undo it

  const panels = new Map(spec.panels.map((p) => [p.id, kept(carry, spec, p) || createPanel(p, ctx)]));
  const periodBar = el("div", { id: "period-bar", class: "period-bar", hidden: "" });
  function renderPeriod() {
    const show = (d) => dateFmt.format(new Date(`${d}T00:00:00Z`));
    const chips = periodDims(spec).flatMap((dim) => {
      const range = parsePeriod(values[periodKey(spec, dim)]);
      if (!range) return [];
      const label = dim === spec.time.dimension ? t.periodLabel : `${t.periodLabel} (${humanize(dim)})`;          // another date role names its field
      const chip = el("span", { class: "chip on" }, `${esc(label)}: ${esc(range[0] === range[1] ? show(range[0]) : `${show(range[0])} – ${show(range[1])}`)}`);
      const x = el("button", { type: "button", class: "chip-x", "aria-label": `${t.clearPeriod}: ${label}`, title: t.clearPeriod }, "✕");
      x.addEventListener("click", () => ctx.setPeriod(null, dim));
      return [chip, x];
    });
    periodBar.hidden = !chips.length;
    periodBar.replaceChildren(...chips);
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
      const raw = values[f.id], isTime = spec.members?.[f.dimension]?.type === "time" && !Number.isNaN(Date.parse(raw));          // a time value reads as a date and time, not as the database writes it
      const text = `${f.label || f.id}: ${isTime ? dateTimeFmt.format(new Date(raw)) : raw}`;
      const chip = el("span", { class: "chip on" }, esc(text));
      const x = el("button", { type: "button", class: "chip-x", "aria-label": t.removeSelection(text), title: t.removeSelection(text) }, "✕");
      x.addEventListener("click", () => changeFilter(f, ""));
      return [chip, x];
    }));
    renderIgnored();
  }
  // Under a panel's title: the filters now chosen that this panel does not apply (its data cannot be filtered by them), so a chip above is never taken for more than it does.
  function renderIgnored() {
    for (const def of spec.panels) {
      const root = panels.get(def.id)?.root;
      if (!root) continue;
      const skipped = (def.ignore_filters || []).map((id) => (spec.filters || []).find((f) => f.id === id)).filter((f) => f && values[f.id] && (!f.tab || f.tab === activeTab));
      let note = root.querySelector(":scope > .ignored-note");
      const head = root.querySelector(".card-h");                // a panel with no title has no head to put it under
      if (!skipped.length || !head) { note?.remove(); continue; }
      if (!note) { note = el("div", { class: "hint ignored-note" }, ""); head.after(note); }
      note.textContent = t.ignoredFilters(skipped.map((f) => f.label || f.id).join(", "));
    }
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
    const opts = optionsOf(optionRows.get(f.id) || [], f, pf ? values[pf.id] : "", sortKeyOf(spec, f.dimension)).filter((o) => !f.allowed?.length || f.allowed.includes(o.value));          // the designer's list limits what is offered
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
      const dims = withSortKeys(spec, [...(f.parent ? [f.parent] : []), f.dimension]);
      optionRows.set(f.id, measures.length ? await runAll(ctx.run, queriesPerCube(spec, measures, { dimensions: dims }), signal) : []);
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
    values._clicked = (values._clicked || []).filter((i) => i !== f.id);                 // chosen in the header now: it narrows every panel
    for (const g of spec.filters) if (parentFilter(g)?.id === f.id) fillOptions(g);       // a child's options follow its parent's value
    for (const g of spec.filters) { const sel = selects.get(g.id); if (sel) sel.classList.toggle("set", !!values[g.id]); }
    writeUrl();
    loadAll();
  }
  /** A filter the designer limited (`allowed`) says so under its control, so a reader is not left wondering why a panel shows fewer values than the data has. */
  function syncLimitNote(f) {
    const node = filterEls.get(f.id);
    if (!node) return;
    node.querySelector(":scope > .limit-note")?.remove();
    if (f.allowed?.length) node.append(el("small", { class: "limit-note", title: f.allowed.join(", ") }, esc(t.fc.limited(f.allowed.length))));
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
      values._clicked = [];
      for (const f of visibleFilters()) values[f.id] = f.default || "";                     // Reset goes back to where the page opened (a hidden filter never moved)
      for (const dim of periodDims(spec)) values[periodKey(spec, dim)] = "";
      clearedHooks.forEach((h) => h.fn());
      renderPeriod();
      for (const f of visibleFilters()) { fillOptions(f); showValue(f); }
      writeUrl();
      loadAll();
    });
    bar.append(reset);
    for (const f of visibleFilters()) syncLimitNote(f);
    const dashboardBar = visibleFilters().some((f) => (!f.scope || f.scope === "dashboard") && !slicerOf.has(f.id) && !f.implicit);
    bar.hidden = !dashboardBar;                                                              // with only page and pane filters the header bar shows when Reset is needed
    ctx.syncReset = () => {
      const needed = visibleFilters().some((f) => (values[f.id] || "") !== (f.default || "")) || anyPeriod();
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
  pageSignal.addEventListener("abort", () => { ctrl?.abort(); slicerCtrl?.abort(); clearTimeout(slicerTimer); });     // drawn again: what this page still asks Cube for is dropped
  function writeUrl() {
    const q = new URLSearchParams(location.search);
    // Only what differs from the default is written; a filter cleared while it has a default is written as `?id=` (so a reload does not bring the default back).
    for (const f of spec.filters || []) { const v = values[f.id] || ""; if (f.visible === false || v === (f.default || "")) q.delete(f.id); else q.set(f.id, v); }
    for (const dim of periodDims(spec)) { const v = values[periodKey(spec, dim)]; if (v) q.set(periodParam(dim), v); else q.delete(periodParam(dim)); }
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
    if (mine !== seq || pageSignal.aborted) return;           // a newer load took over, or the page was drawn again
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
    const rest = (s) => JSON.stringify({ ...s, filters: s.filters?.map(({ default: _d, allowed: _a, visible: _v, ...f }) => f), panels: undefined, members: undefined, cubes: undefined, layout: undefined, tabs: undefined });   // a filter's default and allowed values are applied below
    const tabHeads = (s) => JSON.stringify(s.tabs ? s.tabs.map((t) => [t.id, t.title]) : null);
    if (rest(next) !== rest(spec) || tabHeads(next) !== tabHeads(spec) || next.panels.length !== spec.panels.length || next.panels.some((p, i) => p.id !== spec.panels[i].id)) return false;
    const changed = next.panels.map((def, i) => [def, i]).filter(([def, i]) => JSON.stringify(def) !== JSON.stringify(spec.panels[i]));
    const titleOnly = (a, b) => JSON.stringify({ ...a, title: 0 }) === JSON.stringify({ ...b, title: 0 });
    if (changed.some(([def, i]) => def.type === "slicer" && !titleOnly(def, spec.panels[i]))) return false;                    // moving a filter between the bar and a slicer is left to a reload
    spec.members = next.members;
    spec.cubes = next.cubes;
    const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
    const shown = (f) => f.visible !== false;
    if ((next.filters || []).some((f, i) => shown(f) && !shown(spec.filters[i]))) return false;                     // a hidden filter shown again needs its control built: left to a reload
    const hiddenNow = (next.filters || []).filter((f, i) => !shown(f) && shown(spec.filters[i]));              // a filter that became a pre-filter: its control just goes
    const defaultsMoved = (next.filters || []).filter((f, i) => !same(f.default, spec.filters[i].default));
    const allowedMoved = (next.filters || []).filter((f, i) => !same(f.allowed, spec.filters[i].allowed));
    for (const f of [...defaultsMoved, ...allowedMoved, ...hiddenNow]) {
      const mine = spec.filters.find((x) => x.id === f.id);
      for (const k of ["default", "allowed"]) { if (f[k]) mine[k] = f[k]; else delete mine[k]; }
      if (f.visible === false) mine.visible = false;
    }
    for (const f of hiddenNow) { filterEls.get(f.id)?.remove(); filterEls.delete(f.id); selects.delete(f.id); controls.delete(f.id); document.querySelector(".pane-filters:empty")?.remove(); }
    for (const f of defaultsMoved) values[f.id] = f.default || "";       // a new default is where the filter stands now (the reader's own picks are what the designer is replacing)
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
    const filtersMoved = defaultsMoved.length + allowedMoved.length + hiddenNow.length > 0;
    if (filtersMoved) {
      for (const f of allowedMoved) { const mine = spec.filters.find((x) => x.id === f.id); fillOptions(mine); syncLimitNote(mine); }
      for (const f of visibleFilters()) showValue(f);
      writeUrl();
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
    if (moved || filtersMoved) loadAll();            // cards that came into the open tab are loaded; the others only redraw to their new width (their data is cached)
    else {
      const open = new Set(openPanels());
      const now = rebuilt.filter((p) => open.has(p));
      if (now.length) { const c = new AbortController(); Promise.allSettled(now.map((p) => p.load(c.signal))); }
    }
    window.__render.patchCount = (window.__render.patchCount || 0) + 1;                 // for the tests: a change applied here
    return true;
  }
  /** The values a select or multiselect filter offers (for the designer's default-value picker); [] until its options have loaded. */
  const filterOptions = (id) => { const f = (spec.filters || []).find((x) => x.id === id); return f ? optionsOf(optionRows.get(id) || [], f, "", sortKeyOf(spec, f.dimension)).map((o) => o.value) : []; };
  /** Loads the values of any select filter, hidden or not (the designer's picker needs them for a pre-filter, which has no control on the page). Says so with `filters:options` once. */
  async function ensureOptions(id) {
    const f = (spec.filters || []).find((x) => x.id === id);
    if (!f || optionRows.has(id) || (f.type && f.type !== "select" && f.type !== "multiselect")) return;
    const measures = optionMeasures(spec, f);
    optionRows.set(id, []);                                                              // a second ask while this one runs (or when there is nothing to load) does nothing
    try { optionRows.set(id, measures.length ? await runAll(ctx.run, queriesPerCube(spec, measures, { dimensions: withSortKeys(spec, [...(f.parent ? [f.parent] : []), f.dimension]) }), new AbortController().signal) : []); } catch (e) { console.warn(`options of ${id} failed:`, e?.message || e); }
    document.dispatchEvent(new CustomEvent("filters:options"));
  }
  // patchCount and mountCount (for the tests: a change applied in place, the page drawn again in place) carry over a remount
  window.__render = { spec, values, panels, loadAll, tabLoadedAt, openTab, patch, filterOptions, ensureOptions, activeTab: () => activeTab, ready: null, remount, patchCount: counts.patchCount || 0, mountCount: counts.mountCount || 0,
    keptCount: [...panels.values()].filter((p) => carry?.panels.get(p.root.dataset.panel) === p).length };          // for the tests: panels the last remount took over

  $("#export-all").hidden = false;
  $("#export-all").addEventListener("click", async () => {
    // Every tab goes in: the ones never opened (or left stale by a filter change) are loaded first; a failed panel just has no sheet.
    const signal = new AbortController().signal;
    await Promise.allSettled([...panels.values()].map((p) => p.load(signal)));
    ctx.exportSheets([...panels.values()].map((p) => p.sheet()), "dashboard");
  }, { signal: pageSignal });
  $("#refresh").hidden = false;
  $("#refresh").addEventListener("click", () => { loadOptions(new AbortController().signal).catch(() => {}); loadAll({ force: true }); }, { signal: pageSignal });
  if (role === "viewer" && draft) throw new Error(t0.noDraft);                       // a viewer builds nothing: no drafts
  if ((draft || savedDash) && role !== "viewer") {                                    // ... and has no builder bar or designer on a dashboard
    const api = createBuilderApi({ stack: C, client, t });
    if (api.available) { const host = el("div", { id: "builder-host" }); $("#filters").before(host); if (draft) { mountDraftBar(host, api, t, draft); mountDesigner({ api, t, draft, spec, panels, host }); } else mountSavedBar(host, api, t, savedDash); }
  }
  buildFilters();
  ctx.syncReset?.();
  renderSelection();
  setStatus(esc(t.loading));
  await loadOptions(pageSignal).catch((e) => { if (e?.name !== "AbortError") console.warn("filter options failed:", e?.message || e); });
  if (pageSignal.aborted) return;
  document.dispatchEvent(new CustomEvent("filters:options"));                           // the designer's default-value pickers can now list the real values
  await loadAll();
  const stale = () => { if (!document.hidden && Date.now() - lastLoad > REFRESH_MS) loadAll({ force: true }); };
  if (pageSignal.aborted) return;
  const timer = setInterval(stale, 30_000);
  pageSignal.addEventListener("abort", () => clearInterval(timer));
  document.addEventListener("visibilitychange", stale, { signal: pageSignal });
}

/**
 * A panel of the last drawing that a remount can take over as it is, with its element and its loaded data: its compiled definition did not change, nor did
 * what every panel formats with (language, currency, time field, theme). Its load then only redraws unless what it depends on changed (a filter that now
 * applies to it, say: plan.js activeFilters is in its cache key). A drill-down chart is always made again (it registers with the page's period hooks).
 * What the last drawing put into the card (a slicer's or pane's filter controls, the note on ignored filters, the designer's marks) is taken out.
 */
function kept(carry, spec, def) {
  if (!carry || def.drill) return null;
  const frame = (s) => JSON.stringify([s.locale, s.currency, s.time, s.theme]);
  const before = carry.spec.panels.find((p) => p.id === def.id), panel = carry.panels.get(def.id);
  if (!before || !panel || frame(carry.spec) !== frame(spec) || JSON.stringify(before) !== JSON.stringify(def)) return null;
  const root = panel.root;
  root.querySelectorAll(":scope .pane-filters, :scope > .ignored-note").forEach((n) => n.remove());
  root.querySelector(".slicer-body")?.replaceChildren();
  root.classList.remove("dz-selected");
  root.removeAttribute("tabindex");
  return panel;
}

/**
 * Draws the dashboard of this address again, in the page and without loading it (lib/life.js `redraw`: the designer's changes that `patch` cannot apply, undo and
 * redo, the Change box, Apply YAML). The old dashboard's listeners, timers and queries end with its life; the page keeps its height while the new one is made, so
 * the scroll position does not jump, and the designer comes back where it was (render/designer.js keeps that in sessionStorage, as for a reload).
 */
async function remount() {
  const main = $("#main");
  main.style.minHeight = `${main.offsetHeight}px`;
  const counts = { patchCount: window.__render?.patchCount || 0, mountCount: (window.__render?.mountCount || 0) + 1 };
  const carry = window.__render?.panels ? { spec: window.__render.spec, panels: window.__render.panels } : null;          // the panels the new drawing may keep
  const signal = renew();
  for (const q of ["#builder-host", "#designer", "#dz-colors"]) $(q)?.remove();          // what the draft bar and the designer put in the page; they are mounted again
  document.body.classList.remove("designing", "dz-dragging");
  const bar = $("#filters");
  bar.replaceChildren();
  bar.hidden = true;
  show("");
  setStatus(esc(stringsFor(uiLocale(navigator.language)).loading));                  // until the new dashboard has loaded (a saved one is fetched first): not "Updated" from the old one
  try {
    await showDashboard({ again: true, counts, carry });
  } catch (e) {
    if (signal.aborted) return;
    setStatus(`<strong>${esc(stringsFor(uiLocale(navigator.language)).stale)}</strong>`, "stale");
    show(readable(e));
  } finally {
    if (!signal.aborted) main.style.minHeight = "";
  }
}
onRedraw(remount);

/** Moves to the dashboard at `path` in this page (lib/life.js `go`): Design and Edit on a saved dashboard, Save, a copy, an older version. The list is a page of its own. */
function goTo(path, { replace = false, keepQuery = true } = {}) {
  const url = new URL(path, location.origin);
  if (keepQuery && !url.search) url.search = location.search;
  if (!idOf(url.pathname) || !id) { location[replace ? "replace" : "assign"](url); return; }
  history[replace ? "replaceState" : "pushState"](null, "", url);
  id = idOf(url.pathname);
  remount();
}
onGo(goTo);
// Back and Forward between dashboards shown with go(): the one in the address is drawn in place (the list, or coming from it, loads the page).
window.addEventListener("popstate", () => {
  const next = idOf(location.pathname);
  if (!next || !id) { location.reload(); return; }
  id = next;
  remount();
});

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
