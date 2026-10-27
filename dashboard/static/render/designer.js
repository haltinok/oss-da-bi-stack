// Design mode on a draft (/d/draft): click a panel to change its fields in a drawer; with nothing picked the drawer is the page's own view (title, filters, add a panel).
// The designer writes to the dashboard's source spec and nothing else; the builder service's validator, the same one that checks a model's answer, accepts or refuses every
// change, and an accepted change is stored in the draft and the page is drawn again (the picked panel and the scroll position come back from sessionStorage).
// The logic is in lib/designer-model.js (a panel's fields) and lib/designer-structure.js (new panels, removing, filters, the page's fields).
import { $, el, esc } from "../lib/dom.js";
import { anyMemberOptions, dimensionOptions, fieldsFor, getAt, measureOptions, setField, shown } from "../lib/designer-model.js";
import { PANEL_TYPES, addFilter, addPanel, duplicatePanel, humanize, removeFilter, removePanel, setFilter, setPageField, timeDimensions } from "../lib/designer-structure.js";
import { drafts } from "./builder.js";

const KEY = "designer";                                           // { on, panel, scroll }: what design mode was doing when the page last loaded
const read = () => { try { return JSON.parse(sessionStorage.getItem(KEY) || "{}"); } catch { return {}; } };
const write = (s) => { try { sessionStorage.setItem(KEY, JSON.stringify(s)); } catch { /* storage unavailable: design mode just starts closed after a change */ } };

/** A measure or dimension written as a formula (sum, ratio) cannot be picked from a list: it is shown in words and left to the YAML. */
const formula = (m) => (m?.sum ? m.sum.join(" + ") : m?.ratio ? `(${m.ratio.num.join(" + ")}) ÷ (${m.ratio.den.join(" + ")})` : JSON.stringify(m));

// The dashboard's own fields and a filter's, in the same shape as a panel's (see fieldsFor in lib/designer-model.js).
const PAGE_FIELDS = [
  { path: "title", kind: "text", key: "title" }, { path: "description", kind: "text", key: "description", optional: true },
  { path: "locale", kind: "choice", key: "locale", options: ["en-US", "tr-TR"], optional: true }, { path: "currency", kind: "choice", key: "currency", options: ["USD", "TRY"], optional: true },
  { path: "time.dimension", kind: "timedim", key: "timeDimension" },
];
const FILTER_FIELDS = [
  { path: "label", kind: "text", key: "label", optional: true }, { path: "dimension", kind: "anydim", key: "dimension" }, { path: "parent", kind: "anydim", key: "parent", optional: true },
];

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
  const closeBtn = `<button type="button" class="dz-close" aria-label="${esc(dz.close)}">✕</button>`;

  // ---------------------------------------------------------------------------------------------------------------- the drawer
  function draw() {
    const panel = panelDef();
    if (panel) drawPanel(panel); else drawPage();
  }

  function drawPage() {
    drawer.innerHTML = `<div class="dz-head"><h2>${esc(dz.page)}</h2>${closeBtn}</div><div id="dz-msg" class="bmsg" role="alert" hidden></div>
      <p class="hint">${esc(dz.pick)}</p>
      <form class="dz-form" id="dz-page" onsubmit="return false"></form>
      <h3 class="dz-section">${esc(dz.filters)}</h3><div id="dz-filters" class="dz-filters"></div>
      <div class="dz-add-filter"><select id="dz-newfilter" aria-label="${esc(dz.addFilter)}"></select><button type="button" id="dz-addfilter">${esc(dz.addFilter)}</button></div>
      <h3 class="dz-section">${esc(dz.addPanel)}</h3>
      <div class="dz-gallery" id="dz-gallery">${PANEL_TYPES.map((ty) => `<button type="button" class="dz-type" data-add="${ty}"><strong>${esc(typeName(ty))}</strong><span>${esc(dz.typeHint[ty])}</span></button>`).join("")}</div>`;
    const form = drawer.querySelector("#dz-page");
    for (const fd of PAGE_FIELDS) form.append(field(fd, source, (v) => commit(setPageField(source, fd.path, v), { message: dz.pageChanged, panel: null })));
    const list = drawer.querySelector("#dz-filters");
    if (!(source.filters || []).length) list.innerHTML = `<p class="hint">${esc(dz.noFilters)}</p>`;
    for (const f of source.filters || []) {
      const card = el("div", { class: "dz-filter" });
      card.append(el("h4", {}, esc(f.id)));
      for (const fd of FILTER_FIELDS) card.append(field(fd, f, (v) => commit(setFilter(source, catalog, f.id, fd.path, v), { message: dz.filterChanged, panel: null })));
      const rm = el("button", { type: "button", class: "dz-danger", "data-rm-filter": f.id }, esc(dz.removeFilter));
      card.append(rm);
      list.append(card);
    }
    const pick = drawer.querySelector("#dz-newfilter");
    for (const o of dimensionList()) pick.append(el("option", { value: o.value }, esc(o.label)));
  }

  function drawPanel(panel) {
    const fields = fieldsFor(panel);
    let lastGroup = null;
    const rows = fields.map((fd) => {
      const heading = fd.group && fd.group.of > 1 && fd.group.n !== lastGroup ? `<h3 class="dz-item">${esc(dz.item(fd.group.n, fd.group.of))}</h3>` : "";
      lastGroup = fd.group ? fd.group.n : null;
      return `${heading}<label class="dz-field"><span>${esc(dz.f[fd.key] || fd.key)}</span><span class="dz-input" data-slot="${esc(fd.path)}"></span></label>`;
    }).join("");
    drawer.innerHTML = `<div class="dz-head"><div><h2>${esc(panel.title || panel.id)}</h2><span class="badge">${esc(typeName(panel.type))}</span></div>${closeBtn}</div>
      <div id="dz-msg" class="bmsg" role="alert" hidden></div><form class="dz-form" onsubmit="return false">${rows}</form>
      <div class="dz-actions"><button type="button" id="dz-back">${esc(dz.back)}</button><button type="button" id="dz-dup">${esc(dz.duplicate)}</button><button type="button" id="dz-del" class="dz-danger">${esc(dz.remove)}</button></div>
      <p class="hint">${esc(dz.footer)}</p>`;
    for (const slot of drawer.querySelectorAll(".dz-input")) {
      const fd = fields.find((x) => x.path === slot.dataset.slot);
      slot.append(control(fd, panel, (v) => {
        const edit = setField(source, selected, fd.path, v, { optional: fd.optional });
        return commit(edit, { message: dz.changed(edit.source.panels.find((p) => p.id === selected)?.title || selected) });          // named as it will be after the change
      }));
    }
  }

  /** The dimensions a filter may be on: any the role may read. */
  const dimensionList = () => catalog.flatMap((c) => c.dimensions.map((d) => ({ value: d.member, label: d.member, cube: c.cube, description: d.description })));

  /** A label and its control, for a field of `holder` (the dashboard, a filter). */
  function field(fd, holder, onSet) {
    const wrap = el("label", { class: "dz-field" }, `<span>${esc(dz.f[fd.key] || fd.key)}</span>`);
    const slot = el("span", { class: "dz-input" });
    slot.append(control(fd, holder, onSet));
    wrap.append(slot);
    return wrap;
  }

  const options = (fd, holder) => (fd.kind === "measure" ? measureOptions(catalog) : fd.kind === "dimension" ? dimensionOptions(catalog, holder, getAt(holder, fd.path))
    : fd.kind === "timedim" ? timeDimensions(catalog) : fd.kind === "anydim" ? dimensionList() : anyMemberOptions(catalog));

  /** The input for one field: it reads its value from `holder` and calls `onSet(value)` when the person changes it. */
  function control(fd, holder, onSet) {
    const value = shown(holder, fd.path);
    let input;
    if (fd.kind === "readonly") return el("code", { class: "dz-formula" }, esc(formula(getAt(holder, fd.path))));
    if (fd.kind === "textarea") { input = el("textarea", { rows: 8, spellcheck: "false" }); input.value = value; }
    else if (fd.kind === "text" || fd.kind === "color") {
      input = el("input", { type: "text", maxlength: 200, ...(fd.kind === "color" ? { list: "dz-colors", placeholder: "internet · reseller · #rrggbb" } : {}) });
      input.value = value;
    } else if (fd.kind === "number") { input = el("input", { type: "number", min: fd.min, max: fd.max, step: 1 }); input.value = value; }
    else {
      input = el("select");
      const list = fd.kind === "choice" ? fd.options.map((v) => ({ value: v, label: dz.v[v] || v })) : options(fd, holder);
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
    input.addEventListener("change", () => onSet(fd.kind === "number" ? (input.value === "" ? "" : Number(input.value)) : input.value));
    return input;
  }

  function problems(lines, kind = "failed", title = dz.refused) {
    const box = drawer.querySelector("#dz-msg");
    if (!box) return;
    box.className = `bmsg ${kind}`;
    box.innerHTML = `<strong>${esc(title)}</strong><ul>${lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`;
    box.hidden = false;
  }

  // ---------------------------------------------------------------------------------------------------------------- applying a change
  /**
   * Checks a changed source with the validator and, if it is accepted, stores it in the draft and draws the page again with `panel` picked. `edit` is what a function of
   * lib/designer-model.js or lib/designer-structure.js returned: { source, notes, id? } or { problem }. Returns false when nothing was applied.
   */
  async function commit(edit, { message, panel = selected } = {}) {
    if (busy) return false;
    if (edit.problem) { problems([dz.cannot[edit.problem] || edit.problem], "failed", dz.cannotTitle); return false; }
    busy = true;
    drawer.classList.add("busy");
    try {
      const r = await api.validate(JSON.stringify(edit.source));
      if (!r.ok) { draw(); problems(r.problems); return false; }                     // the controls go back to what the draft holds
      drafts.setCurrent({ ...draft, yaml: r.yaml, spec: r.spec, message, notes: (edit.notes || []).map((n) => dz.notes[n] || n) });
      write({ on: true, panel: edit.id ?? panel, scroll: window.scrollY });
      location.reload();
      return true;
    } catch (e) {
      problems([e.message]);
      return false;
    } finally {
      busy = false;
      drawer.classList.remove("busy");
    }
  }

  const activeTab = () => window.__render?.activeTab?.() ?? null;
  const titleOf = (ty, m, d) => dz.defaultTitle(ty, humanize(m), d && humanize(d));

  drawer.addEventListener("click", (e) => {
    const add = e.target.closest("[data-add]");
    if (add) { commit(addPanel(source, add.dataset.add, catalog, { tab: activeTab(), title: titleOf }), { message: dz.added(typeName(add.dataset.add)) }); return; }
    const rm = e.target.closest("[data-rm-filter]");
    if (rm) { if (confirm(dz.confirmFilter)) commit(removeFilter(source, rm.dataset.rmFilter), { message: dz.filterRemoved, panel: null }); return; }
    if (e.target.closest("#dz-addfilter")) { const dim = drawer.querySelector("#dz-newfilter").value; if (dim) commit(addFilter(source, catalog, dim), { message: dz.filterAdded, panel: null }); return; }
    if (e.target.closest("#dz-back")) { select(null); return; }
    if (e.target.closest("#dz-dup")) { commit(duplicatePanel(source, selected, { suffix: dz.copySuffix }), { message: dz.duplicated }); return; }
    if (e.target.closest("#dz-del")) {
      const title = panelDef()?.title || selected;
      if (confirm(dz.confirmRemove(title))) commit(removePanel(source, selected), { message: dz.removed(title), panel: null });
      return;
    }
    if (e.target.closest(".dz-close")) { select(null); setMode(false); }
  });

  // ---------------------------------------------------------------------------------------------------------------- picking a panel, the mode
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
    document.body.append(el("datalist", { id: "dz-colors" }, '<option value="internet"><option value="reseller">'));
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
