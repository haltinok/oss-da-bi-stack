// The SQL lab (/lab/): an editor with tabs, a schema browser of what this person may query, a sortable result grid, and a history. The statement runs in the lab service
// (lab/), which runs it on Cube's SQL API as this person, so it is limited exactly like a dashboard. Plain JS; tabs and history are kept in this browser only.
import { createCubeClient } from "/cube/cube-client.mjs";
import { $, esc } from "../lib/dom.js";
import { cleanTabs, formatCell, insertAt, pushHistory, sortRows, toTsv } from "../lib/lab-grid.js";
import { initTheme, mountThemeMenu } from "../lib/theme.js";
import { langOf, uiLocale } from "./strings.js";
import { mountLangSwitch } from "./lang.js";
import { labStrings } from "./lab-strings.js";

const C = window.STACK;
const lang = langOf(uiLocale(navigator.language));
const w = labStrings(lang);
const main = $("#main");
document.documentElement.lang = lang;
initTheme();
mountThemeMenu($("#theme"), { locale: () => lang });
mountLangSwitch({ languageLabel: lang === "tr" ? "Dil" : "Language" }, lang);
document.title = w.title;
$("#title").textContent = w.title;
$("#home-text").textContent = w.home;
$("#brand-sub").textContent = w.sub;
const show = (msg) => { const e = $("#error"); e.textContent = msg; e.hidden = !msg; };

const client = createCubeClient({ stack: C, apiUrl: C.cube, redirect: `${location.origin}/lab/` });
const store = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable: the lab still works, it just forgets */ } },
};

async function call(method, path, body) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const kc = await client.keycloak();
    const res = await fetch(`${C.lab}${path}`, { method, headers: { Authorization: `Bearer ${kc.access}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined });
    if (res.status === 401 && attempt === 0) { client.dropKeycloakToken(); continue; }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail;
      const err = new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg).join("; ") : `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return data;
  }
  throw new Error("not signed in");
}

const SAMPLES = [
  ["Revenue by category", "select category, measure(revenue) as revenue\nfrom internet_sales cross join products\ngroup by 1\norder by 2 desc"],
  ["Orders by year", "select calendar_year, count(distinct order_number) as orders\nfrom internet_sales cross join dates\ngroup by 1\norder by 1"],
  ["Latest order lines", "select order_number, order_date, product_name\nfrom internet_sales cross join products\norder by order_date desc\nlimit 50"],
];

let tabs = cleanTabs(store.get("labTabs", null));
let current = tabs.some((t) => t.id === store.get("labTab", 0)) ? store.get("labTab", 0) : tabs[0].id;
let history = store.get("labHistory", []);
let last = null;                                                       // { columns, rows, sort: {index, dir} } of the tab on screen
let cubes = [], limits = { row_limit: 10000, timeout_seconds: 60 };
const MAX_SHOWN = 1000;

const tabOf = () => tabs.find((t) => t.id === current);
const save = () => { store.set("labTabs", tabs); store.set("labTab", current); };

function drawSchema(filter = "") {
  const q = filter.trim().toLowerCase();
  const field = (c, f, kind) => `<button type="button" class="lab-field ${kind}" data-insert="${esc(kind === "measure" ? `MEASURE(${f.name})` : f.name)}" title="${esc(f.description || "")}">${esc(f.name)}<span class="k">${esc(kind === "measure" ? w.measure : w.dimension)}</span></button>`;
  $("#schema").innerHTML = cubes.map((c) => {
    const hit = !q || c.name.toLowerCase().includes(q);
    const dims = c.dimensions.filter((f) => hit || f.name.toLowerCase().includes(q)), meas = c.measures.filter((f) => hit || f.name.toLowerCase().includes(q));
    if (!dims.length && !meas.length) return "";
    return `<details${q ? " open" : ""}><summary title="${esc(c.description)}">${esc(c.name)}</summary>${meas.map((f) => field(c, f, "measure")).join("")}${dims.map((f) => field(c, f, "dimension")).join("")}</details>`;
  }).join("") || `<p class="hint">…</p>`;
}

function drawTabs() {
  $("#tabs").innerHTML = tabs.map((t, i) => `<button type="button" role="tab" data-tab="${t.id}" aria-selected="${t.id === current}">${esc(w.tab(i + 1))}</button>${tabs.length > 1 && t.id === current ? `<button type="button" class="x" data-close="${t.id}" aria-label="${esc(w.closeTab)}">✕</button>` : ""}`).join("")
    + `<button type="button" data-newtab="1" aria-label="${esc(w.newTab)}" title="${esc(w.newTab)}">＋</button>`;
}

function drawHistory() {
  $("#history").innerHTML = history.length ? `<ul>${history.map((h, i) => `<li><button type="button" data-hist="${i}" title="${esc(h.sql)}">${esc(h.sql.replace(/\s+/g, " "))}</button></li>`).join("")}</ul>` : `<p class="hint">${esc(w.historyNone)}</p>`;
}

function drawResult() {
  const box = $("#result");
  if (!last) { box.innerHTML = ""; return; }
  const { columns, sort } = last;
  const rows = sort ? sortRows(last.rows, sort.index, sort.dir, columns[sort.index]?.type) : last.rows;
  const shown = rows.slice(0, MAX_SHOWN);
  const head = columns.map((c, i) => `<th data-sort="${i}" aria-sort="${sort?.index === i ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}" title="${esc(w.sort)}">${esc(c.name)}</th>`).join("");
  const body = shown.map((r) => `<tr>${r.map((v, i) => { const c = columns[i]; const empty = v === null || v === undefined; return `<td class="${c.type === "number" ? "n" : ""}${empty ? " null" : ""}">${esc(formatCell(v, c.type))}</td>`; }).join("")}</tr>`).join("");
  box.innerHTML = rows.length ? `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>` : `<p class="hint" style="padding:12px">${esc(w.nothing)}</p>`;
  $("#status").textContent = `${w.rows(last.row_count)} · ${w.took(last.ms)}${last.truncated ? ` · ${w.cut(last.row_count)}` : rows.length > MAX_SHOWN ? ` · ${w.shown(MAX_SHOWN, rows.length)}` : ""}`;
  for (const id of ["copy", "export-csv", "export-xlsx"]) $(`#${id}`).hidden = !rows.length;
}

async function run() {
  const t = tabOf(), sql = t.sql.trim();
  if (!sql) return;
  const btn = $("#run");
  btn.disabled = true; btn.textContent = w.running;
  $("#err").hidden = true;
  try {
    const out = await call("POST", "/query", { sql });
    last = { ...out, sort: null };
    history = pushHistory(history, sql);
    store.set("labHistory", history);
    drawHistory();
    drawResult();
  } catch (e) {
    last = null; drawResult(); $("#status").textContent = "";
    $("#err").textContent = `${w.failed} ${e.message}`; $("#err").hidden = false;
  } finally { btn.disabled = false; btn.textContent = w.run; }
}

function mountLab() {
  main.innerHTML = `<div class="lab-grid"><aside class="lab-side" aria-label="${esc(w.schema)}"><input type="search" id="schema-q" placeholder="${esc(w.schemaSearch)}" aria-label="${esc(w.schemaSearch)}"><p class="hint">${esc(w.schemaHint)}</p><div id="schema"></div></aside>
    <section class="lab-main"><div class="lab-tabs" id="tabs" role="tablist"></div>
      <textarea id="sql" spellcheck="false" aria-label="SQL" placeholder="${esc(w.placeholder)}"></textarea>
      <div class="lab-bar"><button type="button" class="lab-btn primary" id="run">${esc(w.run)}</button><button type="button" class="lab-btn" id="clear">${esc(w.clear)}</button>
        <select id="samples" aria-label="${esc(w.samples)}"><option value="">${esc(w.samples)}</option>${SAMPLES.map(([n], i) => `<option value="${i}">${esc(n)}</option>`).join("")}</select>
        <span class="spacer"></span><span class="hint">${esc(w.limits(limits.row_limit, limits.timeout_seconds))} Ctrl/⌘ + Enter</span><button type="button" class="lab-btn" id="copy" hidden>${esc(w.copy)}</button><button type="button" class="lab-btn" id="export-csv" hidden>${esc(w.exportCsv)}</button><button type="button" class="lab-btn" id="export-xlsx" hidden>${esc(w.exportXlsx)}</button></div>
      <p class="hint">${esc(w.help)}</p>
      <div class="lab-err" id="err" role="alert" hidden></div><div class="lab-status" id="status" role="status" aria-live="polite"></div><div class="lab-result" id="result"></div>
      <details class="lab-history"><summary>${esc(w.history)}</summary><div id="history"></div></details></section></div>`;
  const ed = $("#sql");
  const load = () => { ed.value = tabOf().sql; };
  load(); drawTabs(); drawSchema(); drawHistory();
  ed.addEventListener("input", () => { tabOf().sql = ed.value; save(); });
  ed.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); run(); } });
  $("#run").addEventListener("click", run);
  $("#clear").addEventListener("click", () => { ed.value = ""; tabOf().sql = ""; save(); last = null; drawResult(); $("#status").textContent = ""; $("#err").hidden = true; ed.focus(); });
  $("#samples").addEventListener("change", (e) => { if (e.target.value !== "") { ed.value = SAMPLES[Number(e.target.value)][1]; tabOf().sql = ed.value; save(); e.target.value = ""; ed.focus(); } });
  $("#schema-q").addEventListener("input", (e) => drawSchema(e.target.value));
  $("#schema").addEventListener("click", (e) => {
    const b = e.target.closest("[data-insert]");
    if (!b) return;
    const r = insertAt(ed.value, ed.selectionStart, ed.selectionEnd, b.dataset.insert);
    ed.value = r.text; tabOf().sql = r.text; save(); ed.focus(); ed.setSelectionRange(r.cursor, r.cursor);
  });
  $("#tabs").addEventListener("click", (e) => {
    const go = e.target.closest("[data-tab]"), close = e.target.closest("[data-close]"), add = e.target.closest("[data-newtab]");
    if (go) current = Number(go.dataset.tab);
    else if (close) { tabs = tabs.filter((t) => t.id !== Number(close.dataset.close)); current = tabs[0].id; }
    else if (add) { const id = Math.max(...tabs.map((t) => t.id)) + 1; if (tabs.length < 12) { tabs.push({ id, sql: "" }); current = id; } }
    else return;
    save(); last = null; drawTabs(); load(); drawResult(); $("#status").textContent = ""; $("#err").hidden = true;
  });
  $("#history").addEventListener("click", (e) => { const b = e.target.closest("[data-hist]"); if (b) { ed.value = history[Number(b.dataset.hist)].sql; tabOf().sql = ed.value; save(); ed.focus(); } });
  $("#result").addEventListener("click", (e) => {
    const th = e.target.closest("th[data-sort]");
    if (!th || !last) return;
    const index = Number(th.dataset.sort);
    last.sort = last.sort?.index === index ? { index, dir: last.sort.dir === "asc" ? "desc" : "asc" } : { index, dir: "asc" };
    drawResult();
  });
  $("#export-csv").addEventListener("click", () => exportAs("csv"));
  $("#export-xlsx").addEventListener("click", () => exportAs("xlsx"));
  $("#copy").addEventListener("click", async () => {
    if (!last) return;
    const rows = last.sort ? sortRows(last.rows, last.sort.index, last.sort.dir, last.columns[last.sort.index]?.type) : last.rows;
    try { await navigator.clipboard.writeText(toTsv(last.columns, rows)); $("#copy").textContent = w.copied; setTimeout(() => { $("#copy").textContent = w.copy; }, 1200); } catch { show("clipboard"); }
  });
}

/** Run the statement of the open tab again as an export and hand the file to the browser. The file may hold more rows than the grid (the export limit). */
async function exportAs(format) {
  const sql = tabOf().sql.trim();
  if (!sql) return;
  const buttons = ["export-csv", "export-xlsx"].map((id) => $(`#${id}`));
  const labels = buttons.map((b) => b.textContent);
  buttons.forEach((b) => { b.disabled = true; b.textContent = w.exporting; });
  $("#err").hidden = true;
  try {
    const kc = await client.keycloak();
    const res = await fetch(`${C.lab}/export`, { method: "POST", headers: { Authorization: `Bearer ${kc.access}`, "Content-Type": "application/json" }, body: JSON.stringify({ sql, format }) });
    if (!res.ok) { const d = (await res.json().catch(() => ({}))).detail; throw new Error(typeof d === "string" ? d : `HTTP ${res.status}`); }
    const blob = await res.blob();
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || `lab.${format}`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    const n = Number(res.headers.get("X-Lab-Rows") || 0);
    $("#status").textContent = res.headers.get("X-Lab-Truncated") === "true" ? w.exportCut(n) : w.exportAll(n);
  } catch (e) {
    $("#err").textContent = `${w.failed} ${e.message}`; $("#err").hidden = false;
  } finally { buttons.forEach((b, i) => { b.disabled = false; b.textContent = labels[i]; }); }
}

(async () => {
  try {
    const info = await call("GET", "/info");
    limits = info.limits || limits;
    if (!info.lab) { main.innerHTML = `<div class="home-sec"><h2>${esc(w.noLab)}</h2><p class="hint">${esc(w.noLabWhy)}</p></div>`; return; }
    cubes = (await call("GET", "/schema")).cubes;
    mountLab();
  } catch (e) { show(`${w.failed} ${e.message}`); }
})();
