// The builder's page: a prompt box (on /d/), a draft bar (on /d/draft: change it, edit the YAML, download, save) and a browser for the semantic layer.
// It talks to the builder service (builder/): a prompt becomes a validated dashboard spec for the signed-in role. Everything the service or the model
// returns is shown as text (escaped); a draft lives in this browser (localStorage) until it is saved to the repository as a reviewed YAML file.
import { el, esc } from "../lib/dom.js";
import { filterItems } from "../lib/search.js";
import { chipsHtml, groupByFirstTag, tagsOf, withTags } from "../lib/tags.js";

// ------------------------------------------------------------------------------------------------------------------ drafts (this browser only)
const KEY = { current: "builder.draft", history: "builder.draft.history" };
const MAX_HISTORY = 20;                                          // steps that can be undone (each keeps a compiled spec, so a handful of KB)
const read = (k, fallback) => { try { return JSON.parse(localStorage.getItem(k)) ?? fallback; } catch { return fallback; } };
const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch { return false; } };

const noHistory = () => ({ undo: [], redo: [] });
const shot = (d) => ({ yaml: d.yaml, spec: d.spec, message: d.message || "" });       // what a step keeps: the file, its compiled page, and what produced it

/**
 * The draft being worked on, in this browser, with an undo history. `setCurrent` is for a draft that is new (just built, opened for editing, copied): its history starts empty.
 * `edit` is for a change to the draft in hand (the designer, the Change box, the YAML tab): the draft as it was is kept so `undo` can bring it back and `redo` can go forward again.
 */
export const drafts = {
  current: () => read(KEY.current, null),
  setCurrent(d) { write(KEY.history, noHistory()); return write(KEY.current, d); },
  edit(d) {
    const cur = read(KEY.current, null), h = read(KEY.history, noHistory());
    if (cur?.yaml && cur.yaml !== d.yaml) { h.undo = [...h.undo, shot(cur)].slice(-MAX_HISTORY); h.redo = []; write(KEY.history, h); }
    return write(KEY.current, d);
  },
  /** { undo, redo } step counts and the words of what each would undo / redo (the change that produced the draft now, and the one a redo would bring back). */
  history() {
    const h = read(KEY.history, noHistory()), cur = read(KEY.current, null);
    return { undo: h.undo.length, redo: h.redo.length, undoLabel: cur?.message || "", redoLabel: h.redo.at(-1)?.message || "" };
  },
  /** Steps back; `wording(label)` is the message the draft bar shows. False when there is nothing to undo. */
  undo(wording = (label) => label) {
    const cur = read(KEY.current, null), h = read(KEY.history, noHistory());
    if (!cur || !h.undo.length) return false;
    const prev = h.undo.pop();
    h.redo = [...h.redo, shot(cur)];
    write(KEY.history, h);
    return write(KEY.current, { ...cur, yaml: prev.yaml, spec: prev.spec, message: wording(cur.message || ""), notes: [] });
  },
  /** Steps forward again. */
  redo(wording = (label) => label) {
    const cur = read(KEY.current, null), h = read(KEY.history, noHistory());
    if (!cur || !h.redo.length) return false;
    const next = h.redo.pop();
    h.undo = [...h.undo, shot(cur)].slice(-MAX_HISTORY);
    write(KEY.history, h);
    return write(KEY.current, { ...cur, yaml: next.yaml, spec: next.spec, message: wording(next.message || ""), notes: [] });
  },
};

const ROLES = ["admin", "manager", "rep", "purchasing", "marketing"];

// ------------------------------------------------------------------------------------------------------------------ the service
export function createBuilderApi({ stack, client, t }) {
  const base = stack.builder;
  async function call(method, path, body) {
    for (let attempt = 0; attempt < 2; attempt++) {
      const kc = await client.keycloak();
      const res = await fetch(`${base}${path}`, {
        method, headers: { Authorization: `Bearer ${kc.access}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined,
      });
      if (res.status === 401 && attempt === 0) { client.dropKeycloakToken(); continue; }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const d = data.detail;
        const err = new Error(typeof d === "string" ? d : d?.message ? d.message : Array.isArray(d) ? t.badRequest : `HTTP ${res.status}`);
        err.status = res.status;
        err.problems = d?.problems || [];                                  // the validator's messages, when a refusal has some
        throw err;
      }
      return data;
    }
    throw new Error("not signed in");
  }
  let catalog;
  return {
    available: !!base,
    info: () => call("GET", `/info?lang=${t.dateLocale.startsWith("tr") ? "tr" : "en"}`),             // the examples come in the page's language
    catalog: () => (catalog ||= call("GET", "/catalog")),
    build: (prompt, currentYaml, focus) => call("POST", "/build", { prompt, ...(currentYaml ? { current_yaml: currentYaml } : {}), ...(currentYaml && focus ? { focus } : {}) }),
    validate: (yaml) => call("POST", "/validate", { yaml }),
    listSaved: () => call("GET", "/saved"),
    save: (body) => call("POST", "/saved", body),
    openSaved: (id, version) => call("GET", `/saved/${encodeURIComponent(id)}${version ? `?version=${version}` : ""}`),
    updateSaved: (id, body) => call("PUT", `/saved/${encodeURIComponent(id)}`, body),
    deleteSaved: (id) => call("DELETE", `/saved/${encodeURIComponent(id)}`),
    savedVersions: (id) => call("GET", `/saved/${encodeURIComponent(id)}/versions`),
    restoreSaved: (id, version) => call("POST", `/saved/${encodeURIComponent(id)}/restore`, { version }),
  };
}

/** What a build returned, as lines for the reader: why nothing was built, or the notes on what was. All text is escaped by the caller. */
export function outcome(result, t) {
  if (result.status === "ok") return { kind: "ok", title: "", lines: [result.message, ...(result.notes || [])].filter(Boolean) };
  if (result.status === "cannot") return { kind: "cannot", title: t.cannotTitle, lines: [result.message] };
  return { kind: "failed", title: t.failedTitle, lines: [result.message, ...(result.problems || [])].filter(Boolean) };
}

const show = (host, o) => {
  host.hidden = !o || !o.lines.length;
  if (host.hidden) return;
  host.className = `bmsg ${o.kind}`;
  host.setAttribute("role", o.kind === "ok" ? "status" : "alert");
  host.innerHTML = `${o.title ? `<strong>${esc(o.title)}</strong>` : ""}<ul>${o.lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`;
};

const modeNote = (info, t) => (info.mode === "llm" ? `${t.modeLlm}${info.provider ? ` (${info.provider}${info.model ? `, ${info.model}` : ""})` : ""}` : t.modeStandin);

// ------------------------------------------------------------------------------------------------------------------ the prompt box (/d/)
export function mountPromptBox(host, api, t) {
  host.innerHTML = `<section class="card builder-box lsec lsec-create" aria-labelledby="bb-h">
    <h2 id="bb-h">${esc(t.describe)}</h2><p class="hint">${esc(t.describeHint)}</p>
    <textarea id="bb-prompt" rows="6" maxlength="2000" placeholder="${esc(t.placeholder)}" aria-label="${esc(t.describe)}"></textarea>
    <div class="bb-row"><button type="button" id="bb-go" class="primary">${esc(t.build)}</button><span class="hint" id="bb-mode"></span></div>
    <div class="bb-examples" id="bb-ex" hidden><span class="hint">${esc(t.examples)}:</span></div>
    <div id="bb-out" class="bmsg" hidden></div></section>`;
  const prompt = host.querySelector("#bb-prompt"), go = host.querySelector("#bb-go"), out = host.querySelector("#bb-out");
  api.info().then((info) => {
    host.querySelector("#bb-mode").textContent = `${modeNote(info, t)}${info.builds_left !== undefined ? ` ${t.buildsLeft(info.builds_left, info.rate_limit_per_hour)}` : ""}`;
    const ex = host.querySelector("#bb-ex");
    for (const text of info.examples || []) {
      const b = el("button", { type: "button", class: "chip" }, esc(text));
      b.addEventListener("click", () => { prompt.value = text; prompt.focus(); });
      ex.append(b);
    }
    ex.hidden = !(info.examples || []).length;
  }).catch((e) => show(out, { kind: "failed", title: "", lines: [e.message] }));
  async function build() {
    const text = prompt.value.trim();
    if (text.length < 3) return;
    go.disabled = true;
    go.textContent = t.building;
    show(out, null);
    try {
      const result = await api.build(text);
      if (result.status === "ok") {
        drafts.setCurrent({ yaml: result.yaml, spec: result.spec, prompt: text, mode: result.mode, model: result.model, message: result.message, notes: result.notes });
        location.assign("/d/draft");
        return;
      }
      show(out, outcome(result, t));
    } catch (e) {
      show(out, { kind: "failed", title: "", lines: [e.message] });
    }
    go.disabled = false;
    go.textContent = t.build;
  }
  go.addEventListener("click", build);
  prompt.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) build(); });
}

const visBadge = (d, t) => (d.visibility === "private" ? t.badgePrivate : d.visibility === "everyone" ? t.badgeEveryone : `${t.badgeRoles}: ${d.shared_roles.join(", ")}`);

/**
 * The saved dashboards on /d/: yours, and those shared with you (greyed, with the reason, when your role cannot open one).
 * The list view's state comes in as functions: `query()` (matched on title, description and owner), `tags()` (the selected tags: an item must carry
 * all of them) and `group()` (draw each section by first tag). `onTag(tag)` is called when a tag chip is clicked; `onCount({ shown, total })` says how
 * many are left. The handle's `render()` draws the lists again from what it already has (no request), `items()` gives them all (for the tag bar).
 * Resolves to null when the server keeps no dashboards.
 */
export async function mountSavedList(host, api, t, { query = () => "", tags = () => [], group = () => false, onCount = () => {}, onTag = () => {} } = {}) {
  let list = [];
  const load = async () => { list = await api.listSaved(); };
  try { await load(); } catch { host.hidden = true; onCount({ shown: 0, total: 0 }); return null; }
  host.hidden = false;
  const label = (tag) => t.tagFilterAria(tag);
  const card = (d) => `<li class="saved ${d.readable ? "" : "unreadable"}" data-id="${esc(d.id)}">
      <div class="saved-main">${d.readable ? `<a href="/d/s/${encodeURIComponent(d.id)}">${esc(d.title)}</a>` : `<span>${esc(d.title)}</span>`} <span class="badge">${esc(visBadge(d, t))}</span>
        <div class="hint">${esc(d.description || "")}${d.description ? " · " : ""}${d.mine ? "" : `${esc(t.by)} ${esc(d.owner)} · `}${esc(t.updated)} ${esc(new Date(d.updated_at).toLocaleString(t.dateLocale))}</div>
        ${tagsOf(d).length ? `<div class="tagrow">${chipsHtml(tagsOf(d), tags(), label)}</div>` : ""}
        ${d.readable ? "" : `<div class="hint warn">${esc(t.cannotOpen)}: ${esc(d.problems[0] || "")}</div>`}</div>
      ${!d.mine && d.readable ? `<button type="button" data-act="copy">${esc(t.copy)}</button>` : ""}${d.can_manage ? `<button type="button" data-act="delete">${esc(t.deleteBtn)}</button>` : ""}</li>`;
  const render = () => {
    const q = query().trim(), selected = tags();
    const filtering = !!q || selected.length > 0;
    const keep = (d) => (!q || filterItems([d], q, ["title", "description", "owner"]).length > 0) && withTags([d], selected).length > 0;
    const mine = list.filter((d) => d.mine), others = list.filter((d) => !d.mine);
    const mineShown = mine.filter(keep), othersShown = others.filter(keep);
    const heading = (text, hint, shown, all) => `<h2>${esc(text)}${filtering ? ` <span class="hint">(${esc(t.searchCount(shown.length, all.length))})</span>` : ""}</h2><p class="hint lsec-hint">${esc(hint)}</p>`;
    const body = (shown) => (group()
      ? groupByFirstTag(shown).map((g) => `<h3 class="tg-h">${esc(g.tag ?? t.untagged)} <span class="hint">(${g.items.length})</span></h3><ul class="drafts">${g.items.map(card).join("")}</ul>`).join("")
      : `<ul class="drafts">${shown.map(card).join("")}</ul>`);
    const section = (kind, text, hint, shown, all, none) => `<section class="lsec lsec-${kind}">${heading(text, hint, shown, all)}${shown.length ? body(shown) : `<p class="hint">${esc(none)}</p>`}</section>`;
    host.innerHTML = section("mine", t.yourSaved, t.yourSavedHint, mineShown, mine, mine.length ? t.searchNoSaved : t.noSaved)
      + (others.length && (othersShown.length || !filtering) ? section("shared", t.sharedWithYou, t.sharedHint, othersShown, others, t.searchNoSaved) : "");
    onCount({ shown: mineShown.length + othersShown.length, total: list.length });
  };
  render();
  host.onclick = async (ev) => {
    const chip = ev.target.closest("button[data-tag]");
    if (chip) { onTag(chip.dataset.tag); return; }
    const cp = ev.target.closest('button[data-act="copy"]');
    if (cp) {                                           // someone else's dashboard: a copy of its latest version, saved as yours, then opened
      cp.disabled = true;
      try {
        const src = await api.openSaved(cp.closest("li").dataset.id);
        const out = await api.save({ yaml: src.yaml, title: src.meta.title });
        location.assign(`/d/s/${encodeURIComponent(out.id)}`);
      } catch (e) { cp.disabled = false; alert([e.message, ...(e.problems || [])].join("\n")); }
      return;
    }
    const b = ev.target.closest('button[data-act="delete"]');
    if (!b || !confirm(t.confirmDelete)) return;
    try { await api.deleteSaved(b.closest("li").dataset.id); } catch (e) { alert(e.message); }
    try { await load(); } catch { /* keep what is shown */ }
    render();                                           // the search and tags are kept: the list is drawn again from the new answer
  };
  return { render, items: () => list };
}

// ------------------------------------------------------------------------------------------------------------------ the semantic layer
export function mountSemantic(host, api, t, { insert = () => {} } = {}) {
  host.innerHTML = `<p class="hint">${esc(t.semanticHint)}</p><input type="search" class="sem-search" placeholder="${esc(t.search)}" aria-label="${esc(t.search)}"><div class="sem"></div>`;
  const box = host.querySelector(".sem"), search = host.querySelector(".sem-search");
  api.catalog().then((cubes) => {
    box.innerHTML = cubes.map((c) => `<details class="sem-cube" data-cube="${esc(c.cube)}"><summary><code>${esc(c.cube)}</code>${c.fact ? ` <span class="badge">${esc(t.factCube)}</span>` : ""}
      <span class="sem-desc">${esc(c.description)}</span></summary>
      ${c.joins.length ? `<p class="hint">${esc(t.joins)}: ${c.joins.map((j) => `<code>${esc(j)}</code>`).join(", ")}</p>` : ""}
      <table class="sem-members"><tbody>${[...c.measures.map((m) => ({ ...m, kind: "measure" })), ...c.dimensions.map((m) => ({ ...m, kind: "dimension" }))].map((m) => `<tr data-text="${esc(`${m.member} ${m.description}`.toLowerCase())}">
        <td><button type="button" class="member" data-member="${esc(m.member)}" title="${m.hidden_from.length ? esc(`not for: ${m.hidden_from.join(", ")}`) : ""}">${esc(m.name)}</button></td>
        <td class="k">${esc(m.kind)} · ${esc(m.type)}</td><td>${esc(m.description)}</td></tr>`).join("")}</tbody></table></details>`).join("");
  }).catch((e) => { box.textContent = e.message; });
  box.addEventListener("click", async (ev) => {
    const b = ev.target.closest("button.member");
    if (!b) return;
    insert(b.dataset.member);
    try { await navigator.clipboard.writeText(b.dataset.member); } catch { /* the clipboard needs a secure page */ }
    b.classList.add("copied");
    b.title = t.copied;
    setTimeout(() => b.classList.remove("copied"), 1200);
  });
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    let any = false;
    for (const d of box.querySelectorAll(".sem-cube")) {
      let hits = 0;
      for (const r of d.querySelectorAll("tr")) { const on = !q || r.dataset.text.includes(q) || d.dataset.cube.includes(q); r.hidden = !on; hits += on; }
      d.hidden = !hits;
      d.open = !!q && hits > 0;
      any ||= hits > 0;
    }
    box.querySelector(".sem-none")?.remove();
    if (!any) box.append(el("p", { class: "hint sem-none" }, esc(t.noMatch)));
  });
}

// ------------------------------------------------------------------------------------------------------------------ the draft bar (/d/draft)
export function mountDraftBar(host, api, t, draft) {
  host.innerHTML = `<section class="card builder-bar" aria-label="${esc(t.draft)}">
    <div class="bb-head"><span class="badge">${esc(t.draft)}</span><span class="hint" id="bd-mode"></span><span class="spacer"></span>
      <button type="button" data-tab="yaml">${esc(t.yaml)}</button><button type="button" data-tab="semantic">${esc(t.semantic)}</button>
      <button type="button" id="bd-download">${esc(t.download)}</button><button type="button" data-tab="save" id="bd-save-tab" hidden>${esc(t.saveBtn)}</button>
      <a class="btn" href="/d/">${esc(t.newOne)}</a></div>
    <div id="bd-msg" class="bmsg" hidden></div>
    <p class="hint" id="bd-focus" hidden></p>
    <div class="bb-row"><input type="text" id="bd-change" maxlength="2000" placeholder="${esc(t.changePlaceholder)}" aria-label="${esc(t.change)}"><button type="button" id="bd-go" class="primary">${esc(t.change)}</button></div>
    <div class="bb-tab" id="tab-yaml" hidden><p class="hint">${esc(t.yamlHint)}</p><textarea id="bd-yaml" rows="22" spellcheck="false" aria-label="${esc(t.yaml)}"></textarea>
      <div class="bb-row"><button type="button" id="bd-apply" class="primary">${esc(t.apply)}</button></div><div id="bd-problems" class="bmsg" hidden></div></div>
    <div class="bb-tab" id="tab-save" hidden></div>
    <div class="bb-tab" id="tab-semantic" hidden></div></section>`;
  const $ = (s) => host.querySelector(s), msg = $("#bd-msg"), yamlBox = $("#bd-yaml");
  yamlBox.value = draft.yaml;
  mountSavePane($("#tab-save"), api, t, draft, () => yamlBox.value);
  api.info().then((i) => {
    if (i.saving) $("#bd-save-tab").hidden = false;
    else show($("#bd-msg"), { kind: "ok", title: "", lines: [t.savingOff] }); $("#bd-mode").textContent = `${t.builtBy}: ${draft.mode === "llm" ? draft.model || "model" : i.mode === "llm" && draft.mode !== "standin" ? "model" : "rule-based stand-in"} · ${modeNote({ mode: draft.mode }, t)}`; }).catch(() => {});
  show(msg, outcome({ status: "ok", message: draft.message, notes: draft.notes }, t));
  let semanticMounted = false;
  for (const b of host.querySelectorAll("[data-tab]")) {
    b.addEventListener("click", () => {
      const pane = $(`#tab-${b.dataset.tab}`);
      pane.hidden = !pane.hidden;                    // independent: with both open, a member clicked in the semantic layer goes into the YAML
      if (b.dataset.tab === "semantic" && !semanticMounted && !pane.hidden) {
        semanticMounted = true;
        mountSemantic(pane, api, t, { insert: (member) => {
          if ($("#tab-yaml").hidden) return;
          const at = yamlBox.selectionStart ?? yamlBox.value.length;
          yamlBox.setRangeText(member, at, yamlBox.selectionEnd ?? at, "end");
          yamlBox.focus();
        } });
      }
    });
  }
  // With the designer on and a panel picked, the Change box is about that panel (render/designer.js announces the pick on `document`).
  let focus = null;
  const aim = (id) => {
    const panel = id ? draft.spec?.panels?.find((p) => p.id === id) : null;
    focus = panel ? panel.id : null;
    $("#bd-focus").hidden = !panel;
    $("#bd-focus").textContent = panel ? t.focusOn(panel.title || panel.id) : "";
    $("#bd-change").placeholder = panel ? t.focusPlaceholder : t.changePlaceholder;
  };
  document.addEventListener("designer:pick", (e) => aim(e.detail?.panel));
  try { const s = JSON.parse(sessionStorage.getItem("designer") || "{}"); if (s.on) aim(s.panel); } catch { /* no designer state: the whole dashboard */ }
  async function change() {
    const text = $("#bd-change").value.trim();
    if (text.length < 3) return;
    $("#bd-go").disabled = true;
    $("#bd-go").textContent = t.building;
    try {
      const result = await api.build(text, draft.yaml, focus);
      if (result.status === "ok") {
        drafts.edit({ ...draft, yaml: result.yaml, spec: result.spec, prompt: text, message: result.message, notes: result.notes, mode: result.mode, model: result.model });
        location.reload();
        return;
      }
      show(msg, outcome(result, t));
    } catch (e) {
      show(msg, { kind: "failed", title: "", lines: [e.message] });
    }
    $("#bd-go").disabled = false;
    $("#bd-go").textContent = t.change;
  }
  $("#bd-go").addEventListener("click", change);
  $("#bd-change").addEventListener("keydown", (e) => { if (e.key === "Enter") change(); });
  $("#bd-apply").addEventListener("click", async () => {
    const problems = $("#bd-problems");
    try {
      const r = await api.validate(yamlBox.value);
      if (r.ok) { drafts.edit({ ...draft, yaml: r.yaml, spec: r.spec, message: t.yamlApplied, notes: r.notes }); location.reload(); return; }
      show(problems, { kind: "failed", title: t.problems, lines: r.problems });
    } catch (e) {
      show(problems, { kind: "failed", title: "", lines: [e.message] });
    }
  });
  $("#bd-download").addEventListener("click", () => {
    const a = el("a", { href: URL.createObjectURL(new Blob([draft.yaml], { type: "text/yaml" })), download: `${(draft.spec?.title || "dashboard").toLowerCase().replace(/[^a-z0-9]+/g, "-")}.yml` });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
  });
}

// ------------------------------------------------------------------------------------------------------------------ the Tags field
const MAX_TAGS = 5;                                             // what a dashboard may carry (the validator says the rest: case, characters, length)

/**
 * A Tags field: the tags as chips with a remove button, and a box where Enter or a comma adds one (a pasted "a, b" adds both, a half-typed tag is kept
 * when you leave the box or press Save, Backspace in an empty box removes the last). It does not judge a tag: the server's validator does, with its usual
 * messages, so there is one set of rules. `read()` gives the tags, or null while the person has not changed anything, so an untouched field never
 * overrides the tags in the YAML.
 */
function tagEditor(t, initial = []) {
  let tags = [...initial], dirty = false;
  const box = el("div", { class: "tag-editor" });
  box.innerHTML = `<div class="te-chips"></div><input type="text" class="te-input" maxlength="24" autocomplete="off" spellcheck="false" aria-label="${esc(t.tagInputLabel)}" placeholder="${esc(t.tagInputPlaceholder)}"><p class="hint">${esc(t.tagsHint)}</p>`;
  const chips = box.querySelector(".te-chips"), input = box.querySelector(".te-input");
  const draw = () => {
    chips.innerHTML = tags.map((tag) => `<span class="te-chip">${esc(tag)}<button type="button" data-rm="${esc(tag)}" aria-label="${esc(t.tagRemove(tag))}">✕</button></span>`).join("");
    // At the limit the box stays focusable (a disabled one cannot be, and gets no keys, so Backspace could not remove a tag): it just takes no more text.
    const full = tags.length >= MAX_TAGS;
    input.readOnly = full;
    input.placeholder = full ? t.tagsMax : t.tagInputPlaceholder;
  };
  function add(text) {
    for (const part of text.split(",")) {
      const tag = part.trim();
      if (tag && !tags.includes(tag) && tags.length < MAX_TAGS) { tags.push(tag); dirty = true; }
    }
    draw();
  }
  const commit = () => { if (input.value.trim()) add(input.value); input.value = ""; };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); }
    else if (e.key === "Backspace" && !input.value && tags.length) { tags.pop(); dirty = true; draw(); }
  });
  input.addEventListener("input", () => { if (input.value.includes(",")) { const last = input.value.split(",").pop(); add(input.value.slice(0, input.value.length - last.length)); input.value = last.trimStart(); } });
  input.addEventListener("blur", commit);
  chips.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-rm]");
    if (!b) return;
    tags = tags.filter((x) => x !== b.dataset.rm);
    dirty = true;
    draw();
    input.focus();
  });
  draw();
  return { el: box, read: () => { commit(); return dirty ? [...tags] : null; } };
}

// ------------------------------------------------------------------------------------------------------------------ saving a draft
/** The visibility choice shared by the save and share forms: who may open it. Returns { read() -> { visibility, shared_roles }, el }. */
function visibilityForm(t, initial = { visibility: "private", shared_roles: [] }, readableBy = null) {
  const box = el("div", { class: "vis" });
  const opts = [["private", t.visPrivate], ["roles", t.visRoles], ["everyone", t.visEveryone]];
  box.innerHTML = `${opts.map(([v, label]) => `<label class="radio"><input type="radio" name="vis" value="${v}" ${v === initial.visibility ? "checked" : ""}> ${esc(label)}</label>`).join("")}
    <div class="roles" ${initial.visibility === "roles" ? "" : "hidden"}>${ROLES.map((r) => `<label class="check"><input type="checkbox" value="${r}" ${initial.shared_roles.includes(r) ? "checked" : ""}> ${esc(r)}${
      readableBy ? (readableBy.includes(r) ? ' <span class="ok" title="can open it">✓</span>' : ' <span class="no" title="cannot read one of its members">✗</span>') : ""}</label>`).join("")}</div>
    ${readableBy ? `<p class="hint">${esc(t.canOpen)}: ${esc(readableBy.join(", ") || "—")}.${ROLES.some((r) => !readableBy.includes(r)) ? ` ${esc(t.cannotOpenRoles)}: ${esc(ROLES.filter((r) => !readableBy.includes(r)).join(", "))}.` : ""}</p>` : ""}`;
  const sync = () => { box.querySelector(".roles").hidden = box.querySelector("input[name=vis]:checked").value !== "roles"; };
  box.addEventListener("change", sync);
  return {
    el: box,
    read: () => ({ visibility: box.querySelector("input[name=vis]:checked").value, shared_roles: [...box.querySelectorAll(".roles input:checked")].map((i) => i.value) }),
  };
}

function mountSavePane(pane, api, t, draft, currentYaml) {
  const editing = !!draft.savedId;
  const form = visibilityForm(t, draft.savedMeta ? { visibility: draft.savedMeta.visibility, shared_roles: draft.savedMeta.shared_roles } : undefined);
  pane.innerHTML = `${editing ? `<p class="hint">${esc(t.editing)}: <strong>${esc(draft.savedMeta?.title || "")}</strong></p>` : ""}
    <label class="field-l">${esc(t.saveName)} <input type="text" id="sv-name" maxlength="120" value="${esc(draft.savedMeta?.title || draft.spec?.title || "")}"></label>
    <div class="field-l" role="group" aria-labelledby="sv-tags-l"><span id="sv-tags-l">${esc(t.tagsLabel)}</span><div id="sv-tags"></div></div>
    <div id="sv-vis"></div>
    <div class="bb-row"><button type="button" id="sv-go" class="primary">${esc(editing ? t.saveNewVersion : t.saveGo)}</button>${editing ? `<button type="button" id="sv-new">${esc(t.saveAsNew)}</button>` : ""}</div>
    <div id="sv-msg" class="bmsg" hidden></div>`;
  pane.querySelector("#sv-vis").append(form.el);
  const tagsField = tagEditor(t, draft.spec?.tags || []);
  pane.querySelector("#sv-tags").append(tagsField.el);
  const msg = pane.querySelector("#sv-msg");
  async function go(asNew) {
    const tags = tagsField.read();                      // null: left alone, so the YAML's own tags stand
    const body = { yaml: currentYaml(), title: pane.querySelector("#sv-name").value.trim() || undefined, ...form.read(), ...(tags ? { tags } : {}) };
    for (const b of pane.querySelectorAll("button")) b.disabled = true;
    try {
      const out = asNew || !editing ? await api.save(body) : await api.updateSaved(draft.savedId, body);
      location.assign(`/d/s/${encodeURIComponent(out.id)}`);
    } catch (e) {
      show(msg, { kind: "failed", title: "", lines: [e.message, ...(e.problems || [])] });
      for (const b of pane.querySelectorAll("button")) b.disabled = false;
    }
  }
  pane.querySelector("#sv-go").addEventListener("click", () => go(false));
  pane.querySelector("#sv-new")?.addEventListener("click", () => go(true));
}

/** What a version changed, as a short list of lines in the page's language (the server sends facts, not text: builder/changes.py). At most four lines, then "and N more". */
export function changeList(changes = [], t, show = 4) {
  const typeName = (type) => t.designer?.types?.[type] || type;
  const words = changes.map((c) => { const w = t.versionChanges[c.kind] ?? t.versionChanges.unknown; return typeof w === "function" ? w(c, typeName(c.type)) : w; });
  if (!words.length) return "";
  const lines = words.slice(0, show).map((w) => `<li>${esc(w)}</li>`);
  if (words.length > show) lines.push(`<li>${esc(t.versionChanges.more(words.length - show))}</li>`);
  return `<ul class="vc">${lines.join("")}</ul>`;
}

// ------------------------------------------------------------------------------------------------------------------ a saved dashboard (/d/s/<id>)
export function mountSavedBar(host, api, t, opened) {
  const m = opened.meta;
  const owner = m.can_edit, manage = m.can_manage;
  host.innerHTML = `<section class="card builder-bar" aria-label="${esc(m.title)}">
    <div class="bb-head"><span class="badge">${esc(visBadge(m, t))}</span>
      <span class="hint">${esc(owner ? t.yours : `${t.sharedBy} ${m.owner}`)} · ${esc(t.versionNo)} ${m.version} · ${esc(t.updated)} ${esc(new Date(m.updated_at).toLocaleString(t.dateLocale))}</span><span class="spacer"></span>
      <button type="button" data-tab="yaml">${esc(t.yaml)}</button><button type="button" id="sb-download">${esc(t.download)}</button>
      ${owner ? `<button type="button" id="sb-edit" class="primary">${esc(t.edit)}</button><button type="button" id="sb-design">${esc(t.designer.button)}</button>` : `<button type="button" id="sb-copy">${esc(t.copy)}</button><button type="button" id="sb-editcopy">${esc(t.editCopy)}</button><button type="button" id="sb-designcopy">${esc(t.designer.designCopy)}</button>`}
      ${manage ? `<button type="button" data-tab="share">${esc(t.sharing)}</button>` : ""}${owner ? `<button type="button" data-tab="tags">${esc(t.tagsLabel)}</button><button type="button" data-tab="versions">${esc(t.versions)}</button>` : ""}
      ${manage ? `<button type="button" id="sb-delete">${esc(t.deleteBtn)}</button>` : ""}<a class="btn" href="/d/">${esc(t.dashboards)}</a></div>
    <div id="sb-msg" class="bmsg" hidden></div>
    <div class="bb-tab" id="tab-yaml" hidden><textarea id="sb-yaml" rows="20" spellcheck="false" readonly aria-label="${esc(t.yaml)}"></textarea></div>
    <div class="bb-tab" id="tab-share" hidden></div><div class="bb-tab" id="tab-tags" hidden></div><div class="bb-tab" id="tab-versions" hidden></div></section>`;
  const $ = (q) => host.querySelector(q), msg = $("#sb-msg");
  $("#sb-yaml").value = opened.yaml;
  for (const b of host.querySelectorAll("[data-tab]")) b.addEventListener("click", () => { const pane = $(`#tab-${b.dataset.tab}`); pane.hidden = !pane.hidden; });
  const asDraft = (extra) => { drafts.setCurrent({ yaml: opened.yaml, spec: opened.spec, prompt: "", message: "", notes: [], mode: "saved", model: "", ...extra }); location.assign("/d/draft"); };
  $("#sb-edit")?.addEventListener("click", () => asDraft({ savedId: m.id, savedMeta: { title: m.title, visibility: m.visibility, shared_roles: m.shared_roles } }));
  $("#sb-editcopy")?.addEventListener("click", () => asDraft({}));
  // Design: the same draft as Edit (or Edit a copy), opened with the designer already on (render/designer.js keeps its mode under this key in sessionStorage).
  const designing = (extra) => { try { sessionStorage.setItem("designer", JSON.stringify({ on: true, panel: null })); } catch { /* the designer then starts closed: one more click */ } asDraft(extra); };
  $("#sb-design")?.addEventListener("click", () => designing({ savedId: m.id, savedMeta: { title: m.title, visibility: m.visibility, shared_roles: m.shared_roles } }));
  $("#sb-designcopy")?.addEventListener("click", () => designing({}));
  $("#sb-copy")?.addEventListener("click", async () => {
    try { const out = await api.save({ yaml: opened.yaml, title: m.title }); location.assign(`/d/s/${encodeURIComponent(out.id)}`); }
    catch (e) { show(msg, { kind: "failed", title: "", lines: [e.message, ...(e.problems || [])] }); }
  });
  $("#sb-download")?.addEventListener("click", () => {
    const a = el("a", { href: URL.createObjectURL(new Blob([opened.yaml], { type: "text/yaml" })), download: `${m.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.yml` });
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
  });
  $("#sb-delete")?.addEventListener("click", async () => {
    if (!confirm(t.confirmDelete)) return;
    try { await api.deleteSaved(m.id); location.assign("/d/"); } catch (e) { show(msg, { kind: "failed", title: "", lines: [e.message] }); }
  });
  if (manage) {
    const form = visibilityForm(t, { visibility: m.visibility, shared_roles: m.shared_roles }, opened.readable_by || null);
    const pane = $("#tab-share");
    pane.append(form.el, el("div", { class: "bb-row" }, `<button type="button" id="sb-share-go" class="primary">${esc(t.saveGo)}</button>`));
    pane.querySelector("#sb-share-go").addEventListener("click", async () => {
      try { await api.updateSaved(m.id, form.read()); location.reload(); } catch (e) { show(msg, { kind: "failed", title: "", lines: [e.message, ...(e.problems || [])] }); }
    });
  }
  if (owner) {
    const pane = $("#tab-tags");                         // changing the tags changes the YAML: the owner's alone, and a new version
    const field = tagEditor(t, m.tags || opened.spec?.tags || []);
    pane.append(field.el, el("div", { class: "bb-row" }, `<button type="button" id="sb-tags-go" class="primary">${esc(t.saveGo)}</button>`));
    pane.querySelector("#sb-tags-go").addEventListener("click", async () => {
      const tags = field.read();
      if (!tags) return;                                 // nothing changed
      try { await api.updateSaved(m.id, { tags }); location.reload(); } catch (e) { show(msg, { kind: "failed", title: "", lines: [e.message, ...(e.problems || [])] }); }
    });
  }
  if (owner) {
    const pane = $("#tab-versions");
    let loaded = false;
    $('[data-tab="versions"]').addEventListener("click", async () => {
      if (loaded || pane.hidden) return;
      loaded = true;
      try {
        const vs = await api.savedVersions(m.id);
        pane.innerHTML = vs.length > 1 ? `<ul class="drafts">${vs.map((v) => `<li data-v="${v.version}"><div class="vmain"><span>${esc(t.versionNo)} ${v.version} <small>${esc(v.title)} · ${esc(v.saved_by)} · ${esc(new Date(v.saved_at).toLocaleString(t.dateLocale))}</small></span>${changeList(v.changes, t)}</div>
          ${v.version === m.version ? "" : `<button type="button" data-act="view">${esc(t.viewVersion)}</button><button type="button" data-act="restore">${esc(t.restore)}</button>`}</li>`).join("")}</ul>` : `<p class="hint">${esc(t.noVersions)}</p>`;
      } catch (e) { pane.textContent = e.message; }
    });
    pane.addEventListener("click", async (ev) => {
      const b = ev.target.closest("button[data-act]");
      if (!b) return;
      const v = Number(b.closest("li").dataset.v);
      try {
        if (b.dataset.act === "restore") { await api.restoreSaved(m.id, v); location.reload(); return; }
        const old = await api.openSaved(m.id, v);
        drafts.setCurrent({ yaml: old.yaml, spec: old.spec, prompt: "", message: "", notes: [], mode: "saved", model: "", savedId: m.id, savedMeta: { title: old.meta.title, visibility: m.visibility, shared_roles: m.shared_roles } });
        location.assign("/d/draft");
      } catch (e) { show(msg, { kind: "failed", title: "", lines: [e.message, ...(e.problems || [])] }); }
    });
  }
}
