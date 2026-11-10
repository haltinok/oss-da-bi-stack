// The SQL lab (/lab/): an editor with tabs, a schema browser of what this person may query, a sortable result grid, and a history. The statement runs in the lab service
// (lab/), which runs it on Cube's SQL API as this person, so it is limited exactly like a dashboard. Plain JS; tabs and history are kept in this browser only.
import { createCubeClient } from "/cube/cube-client.mjs";
import { $, esc } from "../lib/dom.js";
import { cleanTabs, formatCell, insertAt, pushHistory, sortRows, toTsv } from "../lib/lab-grid.js";
import { initTheme, mountThemeMenu } from "../lib/theme.js";
import { langOf, uiLocale } from "./strings.js";
import { mountLangSwitch } from "./lang.js";
import { labStrings } from "./lab-strings.js";
import { nameDialog, shareDialog, words as sharingWords } from "./sharing.js";

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

let SAMPLES = [];                                                      // [[title, sql]] from the model (lab.examples in model.config.yml), or made from the cubes this person may read
const flat = (sql) => sql.replace(/\s+/g, " ").trim();

let tabs = cleanTabs(store.get("labTabs", null));
let current = tabs.some((t) => t.id === store.get("labTab", 0)) ? store.get("labTab", 0) : tabs[0].id;
let history = store.get("labHistory", []);
let last = null;                                                       // { columns, rows, sort: {index, dir} } of the tab on screen
let cubes = [], limits = { row_limit: 10000, timeout_seconds: 60 }, saving = false, saved = [], folders = [];
const MAX_SHOWN = 1000;

const tabOf = () => tabs.find((t) => t.id === current);
const savedOf = () => saved.find((q) => q.id === tabOf().queryId);                // the saved query the open tab is linked to, if it is still there
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
    const q = savedOf();
    const keep = q && q.sql.trim() === sql;                                          // the tab is a saved query, unchanged: run it as a saved query, which keeps the result as your snapshot
    const out = keep ? await call("POST", `/queries/${encodeURIComponent(q.id)}/run`) : await call("POST", "/query", { sql });
    last = { ...out, sort: null };
    if (keep && out.snapshot) $("#note").textContent = w.snapshotNote(new Date().toLocaleString(lang === "tr" ? "tr-TR" : "en-US"), new Date(out.snapshot.expires_at).toLocaleString(lang === "tr" ? "tr-TR" : "en-US"));
    history = pushHistory(history, sql);
    store.set("labHistory", history);
    drawHistory();
    drawResult();
  } catch (e) {
    last = null; drawResult(); $("#status").textContent = "";
    $("#err").textContent = `${w.failed} ${e.message}`; $("#err").hidden = false;
  } finally { btn.disabled = false; btn.textContent = w.run; }
}

// ------------------------------------------------------------------------------------------------------------------ saved queries
const when = (iso) => new Date(iso).toLocaleString(lang === "tr" ? "tr-TR" : "en-US");
const sw = () => sharingWords({ dateLocale: lang === "tr" ? "tr-TR" : "en-US" });

async function loadSaved() {
  if (!saving) return;
  [saved, folders] = await Promise.all([call("GET", "/queries").catch(() => []), call("GET", "/query-folders").catch(() => [])]);
}

function drawSaved() {
  const box = $("#saved-box");
  if (!saving) { box.innerHTML = `<p class="hint">${esc(w.savedOff)}</p>`; return; }
  const item = (q) => `<li><button type="button" class="lab-q" data-open="${esc(q.id)}" title="${esc(q.sql)}">${esc(q.title)}</button><span class="hint">${q.folder_name ? esc(w.folderOf(q.folder_name)) + " · " : ""}${q.mine ? "" : esc(q.owner)}</span></li>`;
  const mine = saved.filter((q) => q.mine), others = saved.filter((q) => !q.mine);
  box.innerHTML = `<details open><summary>${esc(w.saved)} (${saved.length})</summary><p class="hint">${esc(w.savedHint)}</p>
    ${mine.length ? `<p class="hint"><strong>${esc(w.savedMine)}</strong></p><ul>${mine.map(item).join("")}</ul>` : ""}${others.length ? `<p class="hint"><strong>${esc(w.savedShared)}</strong></p><ul>${others.map(item).join("")}</ul>` : ""}${saved.length ? "" : `<p class="hint">${esc(w.savedNone)}</p>`}</details>`;
}

function drawLinked() {
  const q = savedOf(), tab = tabOf();
  if (tab.queryId && !q) { delete tab.queryId; save(); }                              // the saved query is gone (deleted, or no longer shared with you)
  $("#linked").hidden = !q;
  if (q) $("#linked").textContent = `${w.linked(q.title, q.owner, q.mine)}${q.folder_name ? ` · ${w.folderOf(q.folder_name)}` : ""}`;
  $("#save").hidden = !saving || (!!q && !q.can_edit);
  $("#save-new").hidden = !saving || !q;
  $("#share").hidden = !q || !q.can_manage;
  $("#delete-q").hidden = !q || !q.can_manage;
}

async function openSaved(id) {
  const q = saved.find((x) => x.id === id);
  if (!q) return;
  const tab = tabOf();
  tab.sql = q.sql; tab.queryId = q.id; save();
  $("#sql").value = q.sql; last = null; drawResult(); drawLinked();
  $("#status").textContent = ""; $("#err").hidden = true; $("#note").textContent = "";
  try {                                                                               // your own last result of it, if it has not expired
    const snap = await call("GET", `/queries/${encodeURIComponent(id)}/snapshot`);
    last = { ...snap, sort: null }; drawResult();
    $("#note").textContent = w.snapshotNote(when(snap.created_at), when(snap.expires_at));
  } catch (e) { if (e.status === 404) $("#note").textContent = w.snapshotNone; }
}

async function saveQuery(asNew) {
  const tab = tabOf(), q = savedOf(), sql = tab.sql.trim();
  if (!sql) return;
  const done = async (out) => { tab.queryId = out.id; save(); await loadSaved(); drawSaved(); drawLinked(); $("#status").textContent = w.saved1; };
  if (q && !asNew) { try { await done(await call("PUT", `/queries/${encodeURIComponent(q.id)}`, { sql })); } catch (e) { $("#err").textContent = `${w.failed} ${e.message}`; $("#err").hidden = false; } return; }
  nameDialog({ ...sw(), folderName: w.queryTitle }, w.saveTitle, q && asNew ? q.title : "", w.save, async (title) => { await done(await call("POST", "/queries", { title, sql })); });
}

function shareQuery() {
  const q = savedOf();
  if (!q) return;
  shareDialog({ w: sw(), kind: "dashboard", item: { ...q, title: q.title }, folders, save: async (body) => { await call("PUT", `/queries/${encodeURIComponent(q.id)}`, body); await loadSaved(); drawSaved(); drawLinked(); } });
}

async function deleteQuery() {
  const q = savedOf();
  if (!q || !confirm(w.deleteConfirm)) return;
  try { await call("DELETE", `/queries/${encodeURIComponent(q.id)}`); } catch (e) { $("#err").textContent = `${w.failed} ${e.message}`; $("#err").hidden = false; return; }
  await loadSaved(); drawSaved(); drawLinked();
}

function mountLab() {
  main.innerHTML = `<div class="lab-grid"><aside class="lab-side" aria-label="${esc(w.schema)}"><div id="saved-box" class="lab-saved"></div><input type="search" id="schema-q" placeholder="${esc(w.schemaSearch)}" aria-label="${esc(w.schemaSearch)}"><p class="hint">${esc(w.schemaHint)}</p><div id="schema"></div></aside>
    <section class="lab-main"><div class="lab-tabs" id="tabs" role="tablist"></div><div class="lab-linked" id="linked" hidden></div>
      <textarea id="sql" spellcheck="false" aria-label="SQL" placeholder="${esc(SAMPLES[0] ? flat(SAMPLES[0][1]) : w.placeholder)}"></textarea>
      <div class="lab-bar"><button type="button" class="lab-btn primary" id="run">${esc(w.run)}</button><button type="button" class="lab-btn" id="clear">${esc(w.clear)}</button><button type="button" class="lab-btn" id="save" hidden>${esc(w.save)}</button><button type="button" class="lab-btn" id="save-new" hidden>${esc(w.saveNew)}</button><button type="button" class="lab-btn" id="share" hidden>${esc(w.shareBtn)}</button><button type="button" class="lab-btn" id="delete-q" hidden>${esc(w.deleteBtn)}</button>
        <select id="samples" aria-label="${esc(w.samples)}"><option value="">${esc(w.samples)}</option>${SAMPLES.map(([n], i) => `<option value="${i}">${esc(n)}</option>`).join("")}</select>
        <span class="spacer"></span><span class="hint">${esc(w.limits(limits.row_limit, limits.timeout_seconds))} Ctrl/⌘ + Enter</span><button type="button" class="lab-btn" id="copy" hidden>${esc(w.copy)}</button><button type="button" class="lab-btn" id="export-csv" hidden>${esc(w.exportCsv)}</button><button type="button" class="lab-btn" id="export-xlsx" hidden>${esc(w.exportXlsx)}</button></div>
      <p class="hint">${esc(w.help)}</p>
      <div class="lab-err" id="err" role="alert" hidden></div><div class="lab-status" id="status" role="status" aria-live="polite"></div><div class="lab-status" id="note"></div><div class="lab-result" id="result"></div>
      <details class="lab-history"><summary>${esc(w.history)}</summary><div id="history"></div></details></section></div>`;
  const ed = $("#sql");
  const load = () => { ed.value = tabOf().sql; };
  load(); drawTabs(); drawSchema(); drawHistory(); drawSaved(); drawLinked();
  ed.addEventListener("input", () => { tabOf().sql = ed.value; save(); });
  ed.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); run(); } });
  $("#run").addEventListener("click", run);
  $("#save").addEventListener("click", () => saveQuery(false));
  $("#save-new").addEventListener("click", () => saveQuery(true));
  $("#share").addEventListener("click", shareQuery);
  $("#delete-q").addEventListener("click", deleteQuery);
  $("#saved-box").addEventListener("click", (e) => { const b = e.target.closest("[data-open]"); if (b) openSaved(b.dataset.open); });
  $("#clear").addEventListener("click", () => { ed.value = ""; tabOf().sql = ""; save(); last = null; drawResult(); $("#status").textContent = ""; $("#err").hidden = true; $("#note").textContent = ""; ed.focus(); });
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
    save(); last = null; drawTabs(); load(); drawResult(); drawLinked(); $("#status").textContent = ""; $("#err").hidden = true; $("#note").textContent = "";
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
    saving = !!info.saving;
    if (!info.lab) { main.innerHTML = `<div class="home-sec"><h2>${esc(w.noLab)}</h2><p class="hint">${esc(w.noLabWhy)}</p></div>`; return; }
    const schema = await call("GET", "/schema");
    cubes = schema.cubes;
    SAMPLES = (schema.examples || []).map((e) => [e.title[lang] || e.title.en, e.sql]);
    await loadSaved();
    mountLab();
  } catch (e) { show(`${w.failed} ${e.message}`); }
})();
