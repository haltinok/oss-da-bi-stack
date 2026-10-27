// Design mode on a draft (/d/draft): click a panel, change its fields in a drawer. The designer writes to the dashboard's source spec and nothing else; the builder
// service's validator, the same one that checks a model's answer, accepts or refuses every change, and an accepted change is stored in the draft and the page is
// drawn again (the selected panel and the scroll position come back from sessionStorage). The logic is in lib/designer-model.js.
import { $, el, esc } from "../lib/dom.js";
import { anyMemberOptions, dimensionOptions, fieldsFor, getAt, measureOptions, setField, shown } from "../lib/designer-model.js";
import { drafts } from "./builder.js";

const KEY = "designer";                                           // { on, panel, scroll }: what design mode was doing when the page last loaded
const read = () => { try { return JSON.parse(sessionStorage.getItem(KEY) || "{}"); } catch { return {}; } };
const write = (s) => { try { sessionStorage.setItem(KEY, JSON.stringify(s)); } catch { /* storage unavailable: design mode just starts closed after a change */ } };

/** A measure or dimension written as a formula (sum, ratio) cannot be picked from a list: it is shown in words and left to the YAML. */
const formula = (m) => (m?.sum ? m.sum.join(" + ") : m?.ratio ? `(${m.ratio.num.join(" + ")}) ÷ (${m.ratio.den.join(" + ")})` : JSON.stringify(m));

export async function mountDesigner({ api, t, draft, spec, panels, host }) {
  const head = host.querySelector(".bb-head");
  if (!head) return;
  const dz = t.designer;
  const button = el("button", { type: "button", id: "bd-design", "aria-pressed": "false" }, esc(dz.button));
  head.querySelector("[data-tab]")?.before(button);
  let source = null, catalog = null, selected = null, on = false, busy = false;
  const state = read();

  const drawer = el("aside", { id: "designer", class: "designer", role: "complementary", "aria-label": dz.title, hidden: "" });
  document.body.append(drawer);

  const panelDef = () => source?.panels.find((p) => p.id === selected);
  const typeName = (type) => dz.types[type] || type;

  function draw() {
    const panel = panelDef();
    if (!panel) {
      drawer.innerHTML = `<div class="dz-head"><h2>${esc(dz.title)}</h2><button type="button" class="dz-close" aria-label="${esc(dz.close)}">✕</button></div><p class="hint">${esc(dz.pick)}</p>`;
      return;
    }
    const fields = fieldsFor(panel);
    let lastGroup = null;
    const rows = fields.map((fd) => {
      const heading = fd.group && fd.group.of > 1 && fd.group.n !== lastGroup ? `<h3 class="dz-item">${esc(dz.item(fd.group.n, fd.group.of))}</h3>` : "";
      lastGroup = fd.group ? fd.group.n : null;
      return `${heading}<label class="dz-field"><span>${esc(dz.f[fd.key] || fd.key)}</span><span class="dz-input" data-slot="${esc(fd.path)}"></span></label>`;
    }).join("");
    drawer.innerHTML = `<div class="dz-head"><div><h2>${esc(panel.title || panel.id)}</h2><span class="badge">${esc(typeName(panel.type))}</span></div>
      <button type="button" class="dz-close" aria-label="${esc(dz.close)}">✕</button></div>
      <div id="dz-msg" class="bmsg" role="alert" hidden></div><form class="dz-form" onsubmit="return false">${rows}</form><p class="hint">${esc(dz.footer)}</p>`;
    for (const slot of drawer.querySelectorAll(".dz-input")) {
      const fd = fields.find((x) => x.path === slot.dataset.slot);
      slot.append(control(fd, panel));
    }
  }

  const options = (fd, panel) => (fd.kind === "measure" ? measureOptions(catalog) : fd.kind === "dimension" ? dimensionOptions(catalog, panel, getAt(panel, fd.path)) : anyMemberOptions(catalog));

  function control(fd, panel) {
    const value = shown(panel, fd.path);
    let input;
    if (fd.kind === "readonly") return el("code", { class: "dz-formula" }, esc(formula(getAt(panel, fd.path))));
    if (fd.kind === "textarea") { input = el("textarea", { rows: 8, spellcheck: "false" }); input.value = value; }
    else if (fd.kind === "text" || fd.kind === "color") {
      input = el("input", { type: "text", maxlength: 200, ...(fd.kind === "color" ? { list: "dz-colors", placeholder: "internet · reseller · #rrggbb" } : {}) });
      input.value = value;
    } else if (fd.kind === "number") { input = el("input", { type: "number", min: fd.min, max: fd.max, step: 1 }); input.value = value; }
    else {
      input = el("select");
      const list = fd.kind === "choice" ? fd.options.map((v) => ({ value: v, label: dz.v[v] || v })) : options(fd, panel);
      if (fd.optional) input.append(el("option", { value: "" }, esc(dz.none)));
      if (value && !list.some((o) => o.value === value)) list.push({ value, label: value });
      if (fd.kind === "choice") for (const o of list) input.append(el("option", { value: o.value }, esc(o.label)));
      else {
        const byCube = new Map();
        for (const o of list) byCube.set(o.cube || "", [...(byCube.get(o.cube || "") || []), o]);
        for (const [cube, items] of byCube) {
          const group = cube ? el("optgroup", { label: cube }) : input;
          for (const o of items) group.append(el("option", { value: o.value, title: o.description || "" }, esc(o.label)));
          if (cube) input.append(group);
        }
      }
      input.value = value;
    }
    input.dataset.path = fd.path;
    input.addEventListener("change", () => apply(fd, fd.kind === "number" ? (input.value === "" ? "" : Number(input.value)) : input.value));
    return input;
  }

  function problems(lines) {
    const box = drawer.querySelector("#dz-msg");
    if (!box) return;
    box.className = "bmsg failed";
    box.innerHTML = `<strong>${esc(dz.refused)}</strong><ul>${lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`;
    box.hidden = false;
  }

  async function apply(fd, value) {
    if (busy) return;
    busy = true;
    drawer.classList.add("busy");
    try {
      const { source: next, notes } = setField(source, selected, fd.path, value, { optional: fd.optional });
      const r = await api.validate(JSON.stringify(next));
      if (!r.ok) { draw(); problems(r.problems); return; }                     // the controls go back to what the draft holds
      const title = next.panels.find((p) => p.id === selected)?.title || selected;
      drafts.setCurrent({ ...draft, yaml: r.yaml, spec: r.spec, message: dz.changed(title), notes: notes.map((n) => dz.notes[n] || n) });
      write({ on: true, panel: selected, scroll: window.scrollY });
      location.reload();
    } catch (e) {
      problems([e.message]);
    } finally {
      busy = false;
      drawer.classList.remove("busy");
    }
  }

  const rootOf = (id) => panels.get(id)?.root;
  function select(id) {
    selected = id;
    for (const [pid, p] of panels) p.root.classList.toggle("dz-selected", pid === id);
    draw();
    write({ ...read(), on: true, panel: id });
    if (id) drawer.querySelector("select, input, textarea")?.focus({ preventScroll: true });
  }

  const hit = (e) => (on ? e.target.closest?.("[data-panel]") : null);
  const pick = (e) => {
    const node = hit(e);
    if (!node || !panels.has(node.dataset.panel)) return;
    e.preventDefault();
    e.stopPropagation();
    select(node.dataset.panel);
  };
  document.addEventListener("click", pick, true);                                 // before the panel's own click (which would filter the page)
  document.addEventListener("keydown", (e) => {
    if (!on) return;
    if (e.key === "Escape" && selected && drawer.contains(document.activeElement)) { select(null); return; }
    if ((e.key === "Enter" || e.key === " ") && hit(e) && !drawer.contains(e.target)) pick(e);
  }, true);
  drawer.addEventListener("click", (e) => { if (e.target.closest(".dz-close")) { select(null); setMode(false); } });

  function setMode(next) {
    on = next;
    button.setAttribute("aria-pressed", String(on));
    document.body.classList.toggle("designing", on);
    drawer.hidden = !on;
    for (const [, p] of panels) { if (on) p.root.setAttribute("tabindex", "0"); else { p.root.removeAttribute("tabindex"); p.root.classList.remove("dz-selected"); } }
    write({ ...read(), on, panel: on ? selected : null });
    if (on) draw();
  }
  button.addEventListener("click", () => setMode(!on));

  // The data the drawer needs: the source of this draft and the members the role may read.
  button.disabled = true;
  try {
    const [r, cat] = await Promise.all([api.validate(draft.yaml), api.catalog()]);
    if (!r.ok) throw new Error(r.problems?.[0] || "the draft does not validate");
    source = r.source;
    catalog = cat;
    button.disabled = false;
    const list = el("datalist", { id: "dz-colors" }, '<option value="internet"><option value="reseller">');
    document.body.append(list);
  } catch (e) {
    button.title = e.message;
    return;
  }
  if (state.on) {
    setMode(true);
    if (state.panel && panels.has(state.panel)) select(state.panel);
    if (Number.isFinite(state.scroll)) requestAnimationFrame(() => window.scrollTo(0, state.scroll));
  }
}
