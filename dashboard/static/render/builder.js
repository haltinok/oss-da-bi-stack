// The builder's page: a prompt box (on /d/), a draft bar (on /d/draft: change it, edit the YAML, download, save) and a browser for the semantic layer.
// It talks to the builder service (builder/): a prompt becomes a validated dashboard spec for the signed-in role. Everything the service or the model
// returns is shown as text (escaped); a draft lives in this browser (localStorage) until it is saved to the repository as a reviewed YAML file.
import { el, esc } from "../lib/dom.js";

// ------------------------------------------------------------------------------------------------------------------ drafts (this browser only)
const KEY = { current: "builder.draft", list: "builder.drafts" };
const read = (k, fallback) => { try { return JSON.parse(localStorage.getItem(k)) ?? fallback; } catch { return fallback; } };
const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch { return false; } };

export const drafts = {
  current: () => read(KEY.current, null),
  setCurrent: (d) => write(KEY.current, d),
  list: () => read(KEY.list, []),
  /** Keep a copy of the current draft in the saved list (newest first, at most 10). */
  save(d) {
    const entry = { id: String(Date.now()), title: d.spec?.title || "Draft", at: new Date().toISOString(), draft: d };
    return write(KEY.list, [entry, ...drafts.list()].slice(0, 10)) ? entry : null;
  },
  remove: (id) => write(KEY.list, drafts.list().filter((e) => e.id !== id)),
  open(id) { const e = drafts.list().find((x) => x.id === id); return e ? drafts.setCurrent(e.draft) : false; },
};

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
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : Array.isArray(data.detail) ? t.badRequest : `HTTP ${res.status}`);
      return data;
    }
    throw new Error("not signed in");
  }
  let catalog;
  return {
    available: !!base,
    info: () => call("GET", "/info"),
    catalog: () => (catalog ||= call("GET", "/catalog")),
    build: (prompt, currentYaml) => call("POST", "/build", { prompt, ...(currentYaml ? { current_yaml: currentYaml } : {}) }),
    validate: (yaml) => call("POST", "/validate", { yaml }),
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

const modeNote = (info, t) => (info.mode === "llm" ? t.modeLlm : t.modeStandin);

// ------------------------------------------------------------------------------------------------------------------ the prompt box (/d/)
export function mountPromptBox(host, api, t) {
  host.innerHTML = `<section class="card builder-box" aria-labelledby="bb-h">
    <h2 id="bb-h">${esc(t.describe)}</h2><p class="hint">${esc(t.describeHint)}</p>
    <textarea id="bb-prompt" rows="3" maxlength="2000" placeholder="${esc(t.placeholder)}" aria-label="${esc(t.describe)}"></textarea>
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

/** The saved drafts of this browser (list page). */
export function mountDrafts(host, t) {
  const list = drafts.list();
  host.hidden = !list.length;
  if (!list.length) return;
  host.innerHTML = `<h2>${esc(t.yourDrafts)}</h2><ul class="drafts">${list.map((e) => `<li data-id="${esc(e.id)}"><span>${esc(e.title)} <small>${esc(new Date(e.at).toLocaleString())}</small></span>
    <button type="button" data-act="open">${esc(t.open)}</button><button type="button" data-act="remove">${esc(t.remove)}</button></li>`).join("")}</ul>`;
  host.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-act]");
    if (!b) return;
    const id = b.closest("li").dataset.id;
    if (b.dataset.act === "open" && drafts.open(id)) location.assign("/d/draft");
    if (b.dataset.act === "remove") { drafts.remove(id); mountDrafts(host, t); }
  }, { once: true });
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
      <button type="button" id="bd-download">${esc(t.download)}</button><button type="button" id="bd-save">${esc(t.saveDraft)}</button>
      <a class="btn" href="/d/">${esc(t.newOne)}</a></div>
    <div id="bd-msg" class="bmsg" hidden></div>
    <div class="bb-row"><input type="text" id="bd-change" maxlength="2000" placeholder="${esc(t.changePlaceholder)}" aria-label="${esc(t.change)}"><button type="button" id="bd-go" class="primary">${esc(t.change)}</button></div>
    <div class="bb-tab" id="tab-yaml" hidden><p class="hint">${esc(t.yamlHint)}</p><textarea id="bd-yaml" rows="22" spellcheck="false" aria-label="${esc(t.yaml)}"></textarea>
      <div class="bb-row"><button type="button" id="bd-apply" class="primary">${esc(t.apply)}</button></div><div id="bd-problems" class="bmsg" hidden></div></div>
    <div class="bb-tab" id="tab-semantic" hidden></div></section>`;
  const $ = (s) => host.querySelector(s), msg = $("#bd-msg"), yamlBox = $("#bd-yaml");
  yamlBox.value = draft.yaml;
  api.info().then((i) => { $("#bd-mode").textContent = `${t.builtBy}: ${draft.mode === "llm" ? draft.model || "model" : i.mode === "llm" && draft.mode !== "standin" ? "model" : "rule-based stand-in"} · ${modeNote({ mode: draft.mode }, t)}`; }).catch(() => {});
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
  async function change() {
    const text = $("#bd-change").value.trim();
    if (text.length < 3) return;
    $("#bd-go").disabled = true;
    $("#bd-go").textContent = t.building;
    try {
      const result = await api.build(text, draft.yaml);
      if (result.status === "ok") {
        drafts.setCurrent({ ...draft, yaml: result.yaml, spec: result.spec, prompt: text, message: result.message, notes: result.notes, mode: result.mode, model: result.model });
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
      if (r.ok) { drafts.setCurrent({ ...draft, yaml: r.yaml, spec: r.spec, message: t.yamlApplied, notes: r.notes }); location.reload(); return; }
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
  $("#bd-save").addEventListener("click", () => show(msg, { kind: "ok", title: "", lines: [drafts.save(draft) ? t.saved : "The browser would not store it"] }));
}
