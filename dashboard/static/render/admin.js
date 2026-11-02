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
async function call(method, path, body) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const kc = await client.keycloak();
    const res = await fetch(`${C.admin}${path}`, { method, headers: { Authorization: `Bearer ${kc.access}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined });
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

const s = { tab: "users", users: [], total: 0, groups: [], roles: [], me: null, q: "", role: "", group: "", status: "" };
const main = $("#main");
const dlg = $("#dlg");
const nameOf = (u) => [u.firstName, u.lastName].filter(Boolean).join(" ");

// ------------------------------------------------------------------------------------------------------------------ data
async function load() {
  const qs = new URLSearchParams({ max: "200", ...(s.q ? { search: s.q } : {}), ...(s.role ? { role: s.role } : {}), ...(s.group ? { group: s.group } : {}), ...(s.status ? { enabled: s.status === "active" } : {}) });
  const [u, g] = await Promise.all([call("GET", `/users?${qs}`), call("GET", "/groups")]);
  s.users = u.users; s.total = u.total; s.groups = g.groups;
}
async function refresh() { try { await load(); draw(); show(""); } catch (e) { show(`${t.failed} ${e.message}`); } }

// ------------------------------------------------------------------------------------------------------------------ the page
function draw() {
  const tabs = `<div class="adm-tabs" role="tablist"><button role="tab" data-tab="users" aria-selected="${s.tab === "users"}">${esc(t.users)}</button><button role="tab" data-tab="groups" aria-selected="${s.tab === "groups"}">${esc(t.groups)}</button></div>`;
  main.innerHTML = `<div class="adm-page">${tabs}${s.tab === "users" ? usersHtml() : groupsHtml()}</div>`;
  main.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { s.tab = b.dataset.tab; draw(); }));
  if (s.tab === "users") wireUsers(); else wireGroups();
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
    <label>${esc(t.deleteType)}: <strong>${esc(u.username)}</strong><input name="confirm" autocomplete="off"></label>${foot(t.deleteIt, "danger")}`,
  (f) => call("DELETE", `/users/${u.id}?confirm=${encodeURIComponent(new FormData(f).get("confirm").trim())}`));
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
