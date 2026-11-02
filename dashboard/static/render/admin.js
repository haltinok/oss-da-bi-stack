// The admin console (/admin/): people and groups, over the admin service (admin/), which manages them in Keycloak. Only an admin gets in; the service checks that itself.
// Plain JS like the rest of the pages. The state is the lists the service sent; every change asks the service and then reads the lists again.
import { createCubeClient } from "/cube/cube-client.mjs";
import { $, el, esc } from "../lib/dom.js";
import { initTheme, mountThemeMenu } from "../lib/theme.js";
import { langOf, uiLocale } from "./strings.js";
import { mountLangSwitch } from "./lang.js";
import { adminStrings } from "./admin-strings.js";

const C = window.STACK;
const lang = langOf(uiLocale(navigator.language));
const t = adminStrings(lang);
document.documentElement.lang = lang;
initTheme();
mountThemeMenu($("#theme"), { locale: () => lang });
mountLangSwitch({ languageLabel: lang === "tr" ? "Dil" : "Language" }, lang);
document.title = t.title;
$("#title").textContent = t.title;
$("#home-text").textContent = t.home;

const client = createCubeClient({ stack: C, apiUrl: C.cube, redirect: `${location.origin}/admin/` });
const show = (msg) => { const e = $("#error"); e.textContent = msg; e.hidden = !msg; };

/** One call to the admin service with the Keycloak token; a 401 once refreshes the token and tries again. */
async function call(method, path, body, base = C.admin) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const kc = await client.keycloak();
    const res = await fetch(`${base}${path}`, { method, headers: { Authorization: `Bearer ${kc.access}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined });
    if (res.status === 401 && attempt === 0) { client.dropKeycloakToken(); continue; }
    if (res.status === 204) return null;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail;
      const err = new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => `${(x.loc || []).slice(-1)[0]}: ${x.msg}`).join("; ") : `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return data;
  }
  throw new Error("not signed in");
}

const s = { tab: "users", users: [], total: 0, groups: [], roles: [], rules: [], regions: [], datasets: [], cubes: [], grantRoles: [], rulesOff: false, preview: null, me: null, q: "", role: "", group: "", status: "" };
const main = $("#main");
const dlg = $("#dlg");
const nameOf = (u) => [u.firstName, u.lastName].filter(Boolean).join(" ");

// ------------------------------------------------------------------------------------------------------------------ data
async function load() {
  const qs = new URLSearchParams({ max: "200", ...(s.q ? { search: s.q } : {}), ...(s.role ? { role: s.role } : {}), ...(s.group ? { group: s.group } : {}), ...(s.status ? { enabled: s.status === "active" } : {}) });
  const [u, g] = await Promise.all([call("GET", `/users?${qs}`), call("GET", "/groups")]);
  s.users = u.users; s.total = u.total; s.groups = g.groups;
  try { const r = await call("GET", "/rls/rules"); s.rules = r.rules; s.regions = r.regions; s.rulesOff = false; } catch (e) { if (e.status !== 503) throw e; s.rules = []; s.regions = []; s.rulesOff = true; }
  if (!s.rulesOff) { const d = await call("GET", "/datasets"); s.datasets = d.datasets; s.cubes = d.cubes; s.grantRoles = d.roles; } else { s.datasets = []; }
}
async function refresh() { try { await load(); draw(); show(""); } catch (e) { show(`${t.failed} ${e.message}`); } }

// ------------------------------------------------------------------------------------------------------------------ the page
function draw() {
  const typing = document.activeElement?.id === "q" ? { value: document.activeElement.value, at: document.activeElement.selectionStart } : null;      // a list that arrives while you type must not eat what you typed
  const tabs = `<div class="adm-tabs" role="tablist"><button role="tab" data-tab="users" aria-selected="${s.tab === "users"}">${esc(t.users)}</button><button role="tab" data-tab="groups" aria-selected="${s.tab === "groups"}">${esc(t.groups)}</button><button role="tab" data-tab="rules" aria-selected="${s.tab === "rules"}">${esc(t.rules)}</button><button role="tab" data-tab="datasets" aria-selected="${s.tab === "datasets"}">${esc(t.datasets)}</button></div>`;
  main.innerHTML = `<div class="adm-page">${tabs}${s.tab === "users" ? usersHtml() : s.tab === "groups" ? groupsHtml() : s.tab === "rules" ? rulesHtml() : datasetsHtml()}</div>`;
  main.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { s.tab = b.dataset.tab; draw(); }));
  if (s.tab === "users") wireUsers(); else if (s.tab === "groups") wireGroups(); else if (s.tab === "rules") wireRules(); else wireDatasets();
  if (typing && $("#q")) { $("#q").value = typing.value; $("#q").focus(); $("#q").setSelectionRange(typing.at, typing.at); }
}

const opts = (items, current, first) => `${first ? `<option value="">${esc(first)}</option>` : ""}${items.map(([v, label]) => `<option value="${esc(v)}"${v === current ? " selected" : ""}>${esc(label)}</option>`).join("")}`;

function usersHtml() {
  const rows = s.users.map((u) => `<tr class="${u.enabled ? "" : "off"}" data-id="${esc(u.id)}">
      <td><strong>${esc(u.username)}</strong>${u.username === s.me ? ` <span class="hint">(${esc(t.you)})</span>` : ""}</td>
      <td class="hide-s">${esc(nameOf(u))}</td><td class="hide-s">${esc(u.email)}</td>
      <td><span class="adm-badge ${u.role === "admin" ? "admin" : ""}" title="${esc(t.rolesHint[u.role] || "")}">${esc(u.role || "-")}</span></td>
      <td class="hide-s">${u.groups.map((g) => `<span class="adm-chip">${esc(g.name)}</span>`).join("") || `<span class="hint">${esc(t.none)}</span>`}</td>
      <td><span class="adm-badge ${u.enabled ? "" : "off"}">${esc(u.enabled ? t.active : t.inactive)}</span></td>
      <td class="adm-act"><button class="adm-btn mini" data-act="edit">${esc(t.edit)}</button><button class="adm-btn mini" data-act="password">${esc(t.password)}</button>
        <button class="adm-btn mini" data-act="${u.enabled ? "deactivate" : "activate"}">${esc(u.enabled ? t.deactivate : t.activate)}</button><button class="adm-btn mini danger" data-act="delete">${esc(t.delete)}</button></td></tr>`).join("");
  return `<div class="adm-bar"><input type="search" id="q" value="${esc(s.q)}" placeholder="${esc(t.search)}" aria-label="${esc(t.search)}">
      <select id="f-role" aria-label="${esc(t.role)}">${opts(s.roles.map((r) => [r, r]), s.role, t.allRoles)}</select>
      <select id="f-group" aria-label="${esc(t.groupsLabel)}">${opts(s.groups.map((g) => [g.id, g.name]), s.group, t.allGroups)}</select>
      <select id="f-status" aria-label="${esc(t.status)}">${opts([["active", t.active], ["inactive", t.inactive]], s.status, t.allStatus)}</select>
      <span class="spacer"></span><button class="adm-btn primary" id="new-user">${esc(t.newUser)}</button></div>
    ${s.users.length ? `<table class="adm-table"><thead><tr><th>${esc(t.username)}</th><th class="hide-s">${esc(t.name)}</th><th class="hide-s">${esc(t.email)}</th><th>${esc(t.role)}</th><th class="hide-s">${esc(t.groupsLabel)}</th><th>${esc(t.status)}</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
      : `<p class="adm-empty">${esc(t.noUsers)}</p>`}<p class="adm-count" role="status">${esc(t.total(s.total))}</p>`;
}

let timer = 0;
function wireUsers() {
  const q = $("#q");
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(async () => { s.q = q.value.trim(); await refresh(); $("#q").focus(); $("#q").setSelectionRange(99, 99); }, 250); });
  for (const [id, key] of [["f-role", "role"], ["f-group", "group"], ["f-status", "status"]]) $(`#${id}`).addEventListener("change", (e) => { s[key] = e.target.value; refresh(); });
  $("#new-user").addEventListener("click", () => userDialog());
  main.querySelectorAll("tr[data-id] [data-act]").forEach((b) => b.addEventListener("click", () => {
    const u = s.users.find((x) => x.id === b.closest("tr").dataset.id);
    ({ edit: () => userDialog(u), password: () => passwordDialog(u), deactivate: () => deactivateDialog(u), activate: () => act(() => call("POST", `/users/${u.id}/enable`)), delete: () => deleteDialog(u) })[b.dataset.act]();
  }));
}

function groupsHtml() {
  const rows = s.groups.map((g) => `<tr data-id="${esc(g.id)}"><td><strong>${esc(g.name)}</strong></td><td>${g.members}</td>
      <td class="adm-act"><button class="adm-btn mini" data-act="members">${esc(t.members)}</button><button class="adm-btn mini" data-act="rename">${esc(t.rename)}</button><button class="adm-btn mini danger" data-act="delete">${esc(t.delete)}</button></td></tr>`).join("");
  return `<div class="adm-bar"><span class="spacer"></span><button class="adm-btn primary" id="new-group">${esc(t.newGroup)}</button></div>
    ${s.groups.length ? `<table class="adm-table"><thead><tr><th>${esc(t.groupName)}</th><th>${esc(t.members)}</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : `<p class="adm-empty">${esc(t.noGroups)}</p>`}`;
}

function wireGroups() {
  $("#new-group").addEventListener("click", () => nameDialog(t.newGroup, "", t.create, (name) => call("POST", "/groups", { name })));
  main.querySelectorAll("tr[data-id] [data-act]").forEach((b) => b.addEventListener("click", () => {
    const g = s.groups.find((x) => x.id === b.closest("tr").dataset.id);
    ({ members: () => membersDialog(g), rename: () => nameDialog(t.rename, g.name, t.saveUser, (name) => call("PUT", `/groups/${g.id}`, { name })),
      delete: () => confirmDialog(t.deleteGroup, `${t.deleteGroupWhy} (${g.name})`, t.delete, () => call("DELETE", `/groups/${g.id}`)) })[b.dataset.act]();
  }));
}

// ------------------------------------------------------------------------------------------------------------------ row rules
function rulesHtml() {
  if (s.rulesOff) return `<p class="adm-empty" role="status">${esc(t.rulesOff)}</p>`;
  const rows = s.rules.map((r) => `<tr data-type="${esc(r.type)}" data-principal="${esc(r.principal)}"><td><span class="adm-badge">${esc(r.type === "user" ? t.ruleUser : t.ruleGroup)}</span> <strong>${esc(r.principal)}</strong></td>
      <td>${r.values.map((v) => `<span class="adm-chip">${esc(v)}</span>`).join("")}</td><td class="hide-s hint">${esc(r.updated_by)}</td>
      <td class="adm-act"><button class="adm-btn mini" data-act="edit">${esc(t.edit)}</button><button class="adm-btn mini danger" data-act="delete">${esc(t.delete)}</button></td></tr>`).join("");
  return `<p class="hint">${esc(t.rulesHint)}</p><div class="adm-bar"><span class="spacer"></span><button class="adm-btn primary" id="new-rule">${esc(t.newRule)}</button></div>
    ${s.rules.length ? `<table class="adm-table"><thead><tr><th>${esc(t.ruleWho)}</th><th>${esc(t.ruleTerritories)}</th><th class="hide-s">${esc(t.ruleUpdated)}</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : `<p class="adm-empty">${esc(t.noRules)}</p>`}
    <section class="adm-preview" aria-labelledby="pv-h"><h3 id="pv-h">${esc(t.preview)}</h3>
      <div class="adm-bar"><select id="pv-user" aria-label="${esc(t.previewPick)}"><option value="">${esc(t.previewPick)}</option></select><button class="adm-btn" id="pv-go">${esc(t.previewGo)}</button></div>
      <div id="pv-out" role="status" aria-live="polite">${s.preview ? previewHtml(s.preview) : ""}</div></section>`;
}

function previewHtml(p) {
  if (!p.applies) return `<p class="hint">${esc(t.previewNa)}</p><p class="hint">${esc(t.blockedCubes)}: ${(p.blocked_cubes || []).map((c) => `<span class="adm-chip">${esc(c)}</span>`).join("") || esc(t.noneBlocked)}</p>`;
  const chips = p.territories.map((v) => `<span class="adm-chip">${esc(v)}</span>`).join("") || `<span class="hint">${esc(t.none)}</span>`;
  const via = p.rules.length ? `<p class="hint">${esc(t.previewVia)}: ${p.rules.map((r) => `${esc(r.principal)} (${esc(r.type === "user" ? t.ruleUser : t.ruleGroup)})`).join(", ")}</p>` : "";
  const labLine = `<p class="hint">${esc(p.lab ? t.labOn : t.labOff)}</p>`;
  const blocked = `<p class="hint">${esc(t.blockedCubes)}: ${(p.blocked_cubes || []).map((c) => `<span class="adm-chip">${esc(c)}</span>`).join("") || esc(t.noneBlocked)}</p>`;
  return `<p><strong>${esc(p.username)}</strong>: ${chips}</p><p class="hint">${esc(t.previewSource[p.source] || p.source)}</p>${via}${blocked}${labLine}`;
}

function wireRules() {
  if (s.rulesOff) return;
  $("#new-rule").addEventListener("click", () => ruleDialog());
  main.querySelectorAll("tr[data-type] [data-act]").forEach((b) => b.addEventListener("click", () => {
    const tr = b.closest("tr"), r = s.rules.find((x) => x.type === tr.dataset.type && x.principal === tr.dataset.principal);
    if (b.dataset.act === "edit") ruleDialog(r);
    else confirmDialog(t.ruleDelete, t.ruleDeleteWhy(r.principal), t.delete, () => call("DELETE", `/rls/rules/${r.type}/${encodeURIComponent(r.principal)}`));
  }));
  call("GET", "/users?max=200").then((r) => {
    const sel = $("#pv-user");
    if (!sel) return;
    sel.innerHTML = `<option value="">${esc(t.previewPick)}</option>${opts(r.users.map((u) => [u.username, u.username]), s.preview?.username || "")}`;
  });
  $("#pv-go").addEventListener("click", async () => {
    const who = $("#pv-user").value;
    if (!who) return;
    try { s.preview = await call("GET", `/rls/preview/${encodeURIComponent(who)}`); $("#pv-out").innerHTML = previewHtml(s.preview); show(""); } catch (e) { show(`${t.failed} ${e.message}`); }
  });
}

async function ruleDialog(rule) {
  const all = (await call("GET", "/users?max=200")).users;
  const type = rule?.type || "user";
  const picked = new Set(rule?.values || []);
  const regionBoxes = s.regions.length
    ? `<div class="groups-pick" role="group" aria-label="${esc(t.ruleTerritories)}">${s.regions.map((r) => `<label><input type="checkbox" name="r" value="${esc(r)}"${picked.has(r) ? " checked" : ""}> ${esc(r)}</label>`).join("")}</div>`
    : `<input name="regions" value="${esc([...picked].join(", "))}"><p class="hint">${esc(t.regionsHint)}</p>`;
  const principals = (ty) => (ty === "user" ? all.map((u) => [u.username, u.username]) : s.groups.map((g) => [g.name, g.name]));
  const form = openForm(`<h2>${esc(rule ? `${t.edit}: ${rule.principal}` : t.newRule)}</h2>
    <label>${esc(t.ruleFor)}<select name="type"${rule ? " disabled" : ""}>${opts([["user", t.ruleUser], ["group", t.ruleGroup]], type)}</select></label>
    <label>${esc(t.ruleWho)}<select name="principal"${rule ? " disabled" : ""}>${opts(principals(type), rule?.principal || "")}</select></label>
    <label>${esc(t.ruleTerritories)}${regionBoxes}</label>${foot(t.ruleSave)}`, async (f) => {
    const v = Object.fromEntries(new FormData(f));
    const type_ = rule?.type || v.type, principal = rule?.principal || v.principal;
    const values = s.regions.length ? [...f.querySelectorAll("[name=r]:checked")].map((c) => c.value) : (v.regions || "").split(",").map((x) => x.trim()).filter(Boolean);
    if (!values.length) throw new Error(t.pickOne);
    await call("PUT", `/rls/rules/${type_}/${encodeURIComponent(principal)}`, { values });
  });
  form.querySelector("[name=type]").addEventListener("change", (e) => { form.querySelector("[name=principal]").innerHTML = opts(principals(e.target.value), ""); });
}

// ------------------------------------------------------------------------------------------------------------------ datasets
function datasetsHtml() {
  if (s.rulesOff) return `<p class="adm-empty" role="status">${esc(t.rulesOff)}</p>`;
  const who = (g) => `<span class="adm-chip" title="${esc(t.grantType[g.type])}">${esc((g.type === "role" ? `role: ${g.principal}` : g.type === "group" ? `group: ${g.principal}` : g.principal) + (g.permission === "lab" ? ` · ${t.grantLabShort}` : ""))}</span>`;
  const rows = s.datasets.map((d) => `<tr data-id="${esc(d.id)}"><td><strong>${esc(d.name)}</strong><br><span class="hint">${esc(d.description)}</span></td>
      <td>${d.cubes.map((c) => `<span class="adm-chip">${esc(c)}</span>`).join("")}</td>
      <td>${d.grants.map(who).join("") || `<span class="hint">${esc(t.nobodyYet)}</span>`}</td>
      <td class="adm-act"><button class="adm-btn mini" data-act="edit">${esc(t.edit)}</button><button class="adm-btn mini danger" data-act="delete">${esc(t.delete)}</button></td></tr>`).join("");
  return `<p class="hint">${esc(t.datasetsHint)}</p><div class="adm-bar"><span class="spacer"></span><button class="adm-btn primary" id="new-dataset">${esc(t.newDataset)}</button></div>
    ${s.datasets.length ? `<table class="adm-table"><thead><tr><th>${esc(t.datasetName)}</th><th>${esc(t.datasetCubes)}</th><th>${esc(t.datasetAccess)}</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : `<p class="adm-empty">${esc(t.noDatasets)}</p>`}`;
}

function wireDatasets() {
  if (s.rulesOff) return;
  $("#new-dataset").addEventListener("click", () => datasetDialog());
  main.querySelectorAll("tr[data-id] [data-act]").forEach((b) => b.addEventListener("click", () => {
    const d = s.datasets.find((x) => x.id === b.closest("tr").dataset.id);
    if (b.dataset.act === "edit") datasetDialog(d);
    else confirmDialog(t.datasetDelete, t.datasetDeleteWhy(d.name), t.delete, () => call("DELETE", `/datasets/${encodeURIComponent(d.id)}`));
  }));
}

const slug = (name) => name.toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "dataset";

async function datasetDialog(d) {
  const all = (await call("GET", "/users?max=200")).users;
  const grants = (d?.grants || []).map((g) => ({ ...g }));
  const picked = new Set(d?.cubes || []);
  const choices = (type) => (type === "user" ? all.map((u) => u.username) : type === "group" ? s.groups.map((g) => g.name) : s.grantRoles);
  const form = openForm(`<h2>${esc(d ? `${t.edit}: ${d.name}` : t.newDataset)}</h2>
    <label>${esc(t.datasetName)}<input name="name" value="${esc(d?.name || "")}" maxlength="80" required></label>
    <label>${esc(t.datasetDesc)}<input name="description" value="${esc(d?.description || "")}" maxlength="400"></label>
    <label>${esc(t.datasetCubes)}<div class="groups-pick" role="group" aria-label="${esc(t.datasetCubes)}">${s.cubes.map((c) => `<label title="${esc(c.description)}"><input type="checkbox" name="c" value="${esc(c.name)}"${picked.has(c.name) ? " checked" : ""}> ${esc(c.name)} <span class="hint">(${c.measures + c.dimensions})</span></label>`).join("")}</div></label>
    <div><span class="hint">${esc(t.datasetAccess)}</span><div id="grant-list" class="adm-grants"></div>
      <div class="row"><select id="g-type" aria-label="${esc(t.ruleFor)}">${opts([["user", t.grantType.user], ["group", t.grantType.group], ["role", t.grantType.role]], "role")}</select>
      <select id="g-who" aria-label="${esc(t.ruleWho)}"></select></div>
      <label class="inline"><input type="checkbox" id="g-lab"> ${esc(t.grantLab)}</label><span class="hint">${esc(t.grantLabHint)}</span><br><button type="button" class="adm-btn mini" id="g-add">${esc(t.grantAdd)}</button></div>
    ${foot(t.datasetSave)}`, async (f) => {
    const v = Object.fromEntries(new FormData(f));
    const cubes = [...f.querySelectorAll("[name=c]:checked")].map((c) => c.value);
    if (!cubes.length) throw new Error(t.pickCube);
    await call("PUT", `/datasets/${encodeURIComponent(d?.id || slug(v.name))}`, { name: v.name.trim(), description: (v.description || "").trim(), cubes, grants });
  });
  const list = form.querySelector("#grant-list"), type = form.querySelector("#g-type"), who = form.querySelector("#g-who");
  const drawGrants = () => {
    list.innerHTML = grants.map((g, i) => `<span class="adm-chip">${esc(`${t.grantType[g.type]}: ${g.principal}${g.permission === "lab" ? ` · ${t.grantLabShort}` : ""}`)} <button type="button" class="adm-x" data-rm="${i}" aria-label="${esc(t.remove)} ${esc(g.principal)}">✕</button></span>`).join("") || `<span class="hint">${esc(t.nobodyYet)}</span>`;
    list.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => { grants.splice(Number(b.dataset.rm), 1); drawGrants(); }));
  };
  const drawWho = () => { who.innerHTML = opts(choices(type.value).map((x) => [x, x]), "", t.grantPick); };
  type.addEventListener("change", drawWho);
  form.querySelector("#g-add").addEventListener("click", () => {
    if (!who.value) return;
    const permission = form.querySelector("#g-lab").checked ? "lab" : "view";
    const at = grants.findIndex((g) => g.type === type.value && g.principal === who.value);
    if (at >= 0) grants[at].permission = permission; else grants.push({ type: type.value, principal: who.value, permission });
    drawGrants();
  });
  drawGrants(); drawWho();
}

// ------------------------------------------------------------------------------------------------------------------ dialogs
/** Open the one dialog with a form; `onSubmit(form)` returns a promise: a refusal is shown in the dialog, success closes it and reads the lists again. */
function openForm(html, onSubmit, { wide } = {}) {
  dlg.innerHTML = `<form method="dialog" novalidate>${html}<p class="err" role="alert" hidden></p></form>`;
  const form = dlg.querySelector("form"), err = form.querySelector(".err");
  form.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", (e) => { e.preventDefault(); dlg.close(); }));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const go = form.querySelector("[data-go]");
    if (go) go.disabled = true;
    try { const keep = await onSubmit(form); if (keep !== "stay") { dlg.close(); await refresh(); } } catch (x) { err.textContent = x.message; err.hidden = false; if (go) go.disabled = false; }
  });
  if (!dlg.open) dlg.showModal();
  form.querySelector("input:not([type=checkbox]), select")?.focus();
  return form;
}
const foot = (go, goClass = "primary") => `<div class="foot"><button type="button" class="adm-btn" data-close>${esc(t.cancel)}</button><button type="submit" class="adm-btn ${goClass}" data-go>${esc(go)}</button></div>`;
const act = async (fn) => { try { await fn(); await refresh(); } catch (e) { show(`${t.failed} ${e.message}`); } };

function userDialog(u) {
  const edit = !!u;
  const groupsPick = `<div class="groups-pick" role="group" aria-label="${esc(t.groupsLabel)}">${s.groups.map((g) => `<label><input type="checkbox" name="g" value="${esc(g.id)}"${u?.groups.some((x) => x.id === g.id) ? " checked" : ""}> ${esc(g.name)}</label>`).join("") || `<span class="hint">${esc(t.noGroups)}</span>`}</div>`;
  openForm(`<h2>${esc(edit ? `${t.edit}: ${u.username}` : t.newUser)}</h2>
    ${edit ? "" : `<label>${esc(t.username)}<input name="username" required autocomplete="off" maxlength="60"></label>`}
    <div class="row"><label>${esc(t.firstName)}<input name="firstName" value="${esc(u?.firstName || "")}"></label><label>${esc(t.lastName)}<input name="lastName" value="${esc(u?.lastName || "")}"></label></div>
    <label>${esc(t.email)}<input name="email" type="email" value="${esc(u?.email || "")}"></label>
    <label>${esc(t.role)}<select name="role">${opts(s.roles.map((r) => [r, `${r}: ${t.rolesHint[r] || ""}`]), u?.role || "rep")}</select></label>
    <label>${esc(t.groupsLabel)}${groupsPick}</label>
    ${edit ? "" : `<label>${esc(t.tempPassword)}<input name="password" type="text" required autocomplete="new-password" minlength="10"></label><p class="hint">${esc(t.tempNote)}</p>`}
    ${foot(edit ? t.saveUser : t.createUser)}`, async (f) => {
    const v = Object.fromEntries(new FormData(f));
    const groups = [...f.querySelectorAll("[name=g]:checked")].map((c) => c.value);
    if (edit) await call("PUT", `/users/${u.id}`, { firstName: v.firstName, lastName: v.lastName, email: v.email, role: v.role, groups });
    else if ((v.password || "").length < 10) throw new Error(t.shortPassword);
    else await call("POST", "/users", { username: v.username.trim(), firstName: v.firstName, lastName: v.lastName, email: v.email, role: v.role, groups, password: v.password, temporary: true });
  });
}

function passwordDialog(u) {
  openForm(`<h2>${esc(`${t.password}: ${u.username}`)}</h2>
    <label>${esc(t.newPassword)}<input name="password" type="text" autocomplete="new-password" minlength="10"></label>
    <label class="inline"><input type="checkbox" name="temporary" checked> ${esc(t.keep)}</label>
    <div class="foot"><button type="button" class="adm-btn" data-close>${esc(t.cancel)}</button><button type="button" class="adm-btn" id="reset">${esc(t.reset)}</button><button type="submit" class="adm-btn primary" data-go>${esc(t.setIt)}</button></div>`,
  async (f) => { const v = Object.fromEntries(new FormData(f)); if ((v.password || "").length < 10) throw new Error(t.shortPassword); await call("POST", `/users/${u.id}/password`, { password: v.password, temporary: !!v.temporary }); });
  $("#reset").addEventListener("click", (e) => { e.preventDefault(); resetDialog(u); });
}

function resetDialog(u) {
  openForm(`<h2>${esc(`${t.resetTitle}: ${u.username}`)}</h2><p class="hint">${esc(t.resetBy)}</p>
    <label class="inline"><input type="radio" name="how" value="temp" checked> ${esc(t.resetTemp)}</label>
    <label class="inline"><input type="radio" name="how" value="email"${u.email ? "" : " disabled"}> ${esc(t.resetEmail)}</label>${foot(t.reset)}`, async (f) => {
    const how = new FormData(f).get("how");
    const r = await call("POST", `/users/${u.id}/reset-password`, { email: how === "email" });
    if (r.emailed) { showResult(`${t.emailed}`); return "stay"; }
    showResult(`${t.resetDone} ${u.username}`, r.temporary_password, t.resetShown);
    return "stay";
  });
}

function showResult(title, secret, note) {
  dlg.innerHTML = `<form method="dialog"><h2>${esc(title)}</h2>${secret ? `<div class="temp" id="temp">${esc(secret)}</div>` : ""}${note ? `<p class="hint">${esc(note)}</p>` : ""}<div class="foot"><button class="adm-btn primary" value="ok">${esc(t.close)}</button></div></form>`;
  dlg.addEventListener("close", () => refresh(), { once: true });
}

function deactivateDialog(u) { confirmDialog(t.deactivateTitle, `${t.deactivateWhy} (${u.username})`, t.deactivate, () => call("POST", `/users/${u.id}/disable`)); }

function confirmDialog(title, why, go, fn) {
  openForm(`<h2>${esc(title)}</h2><p class="hint">${esc(why)}</p>${foot(go, "danger")}`, () => fn());
}

function deleteDialog(u) {
  openForm(`<h2>${esc(t.deleteTitle)}</h2><p class="hint">${esc(t.deleteWhy)}</p>
    <label class="inline"><input type="checkbox" name="handover" checked> ${esc(t.handOver(s.me || "you"))}</label>
    <label>${esc(t.deleteType)}: <strong>${esc(u.username)}</strong><input name="confirm" autocomplete="off"></label>${foot(t.deleteIt, "danger")}`,
  async (f) => {
    const v = new FormData(f);
    const confirm = v.get("confirm").trim();
    if (confirm !== u.username) throw new Error(t.deleteType);
    if (v.get("handover") && s.me && C.builder) {                       // their saved dashboards go to the admin first, so deleting the person deletes no work
      try { await call("POST", "/transfer", { from_user: u.username, to_user: s.me }, C.builder); } catch (e) { if (e.status !== 503) throw e; }       // 503: this install does not keep saved dashboards
    }
    await call("DELETE", `/users/${u.id}?confirm=${encodeURIComponent(confirm)}`);
  });
}

function nameDialog(title, value, go, fn) {
  openForm(`<h2>${esc(title)}</h2><label>${esc(t.groupName)}<input name="name" value="${esc(value)}" maxlength="80" required></label>${foot(go)}`, (f) => fn(new FormData(f).get("name").trim()));
}

function membersDialog(g) {
  const draw = async () => {
    const all = (await call("GET", "/users?max=200")).users;                       // everyone, whatever the list behind the dialog is filtered by
    const members = all.filter((u) => u.groups.some((x) => x.id === g.id));
    const rest = all.filter((u) => !members.includes(u));
    dlg.innerHTML = `<form method="dialog"><h2>${esc(t.membersOf(g.name))}</h2>
      <div class="adm-members">${members.map((u) => `<div class="m"><span>${esc(u.username)} <span class="hint">${esc(nameOf(u))}</span></span><button type="button" class="adm-btn mini" data-rm="${esc(u.id)}">${esc(t.remove)}</button></div>`).join("") || `<p class="adm-empty">${esc(t.noMembers)}</p>`}</div>
      <div class="row"><select id="add-user" aria-label="${esc(t.addMember)}">${opts(rest.map((u) => [u.id, u.username]), "", t.addMember)}</select><button type="button" class="adm-btn" id="add-btn">${esc(t.add)}</button></div>
      <p class="err" role="alert" hidden></p><div class="foot"><button class="adm-btn primary" value="ok">${esc(t.close)}</button></div></form>`;
    const err = dlg.querySelector(".err");
    const run = async (fn) => { try { await fn(); await draw(); } catch (x) { err.textContent = x.message; err.hidden = false; } };
    dlg.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => run(() => call("DELETE", `/groups/${g.id}/members/${b.dataset.rm}`))));
    $("#add-btn").addEventListener("click", () => { const v = $("#add-user").value; if (v) run(() => call("PUT", `/groups/${g.id}/members/${v}`)); });
  };
  draw().then(() => { if (!dlg.open) dlg.showModal(); dlg.addEventListener("close", () => refresh(), { once: true }); });
}

// ------------------------------------------------------------------------------------------------------------------ start
/** The username in the Keycloak token (to mark "you" in the list); the service, not this, decides who is an admin. */
function usernameOf(access) {
  try { return JSON.parse(atob(access.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))).preferred_username || null; } catch { return null; }
}

(async () => {
  try {
    s.me = usernameOf((await client.keycloak()).access);
    try { s.roles = (await call("GET", "/roles")).roles; } catch (e) { if (e.status === 403) { main.innerHTML = `<p class="adm-empty">${esc(t.notAdmin)}</p>`; return; } throw e; }
    await load();
    draw();
  } catch (e) { show(`${t.failed} ${e.message}`); }
})();
