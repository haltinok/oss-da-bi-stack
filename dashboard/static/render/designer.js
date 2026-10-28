// Design mode on a draft (/d/draft): click a panel to change its fields in a drawer; with nothing picked the drawer is the page's own view (title, filters, add a panel).
// The designer writes to the dashboard's source spec and nothing else; the builder service's validator, the same one that checks a model's answer, accepts or refuses every
// change, and an accepted change is stored in the draft and the page is drawn again (the picked panel and the scroll position come back from sessionStorage).
// The logic is in lib/designer-model.js (a panel's fields) and lib/designer-structure.js (new panels, removing, filters, the page's fields).
import { $, el, esc } from "../lib/dom.js";
import { anyMemberOptions, dimensionOptions, fieldsFor, getAt, measureOptions, setField, shown } from "../lib/designer-model.js";
import { PANEL_TYPES, addFilter, addPanel, duplicatePanel, humanize, removeFilter, removePanel, setFilter, setPageField, timeDimensions } from "../lib/designer-structure.js";
import { LISTS, addItem, addRule, addPart, canRemovePart, changeKind, describe, firstMember, kindOf, listRule, removeItem, removePart, setPart } from "../lib/designer-items.js";
import { MAX_TABS, addTab, dropPanel, layoutToTabs, moveCommand, moveTab, moveToTab, removeTab, renameTab, rowOf, tabsOf, tabsToLayout } from "../lib/designer-layout.js";
import { ACCEPTED, ENCODINGS, fits, sizesToTry } from "../lib/designer-logo.js";
import { mountDnd } from "./designer-dnd.js";
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
const LAYOUT_COMMANDS = ["up", "down", "left", "right", "narrower", "wider", "join-up", "join-down", "own-row"];
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
  const closeBtn = () => {
    const h = drafts.history();
    const hist = (kind, glyph, n, label) => `<button type="button" class="dz-histbtn" data-hist="${kind}" aria-label="${esc(dz[kind])}" title="${esc(n ? `${dz[kind]}: ${label || ""}`.replace(/: $/, "") : dz[kind])}" ${n ? "" : "disabled"}>${glyph}</button>`;
    return `<div class="dz-tools">${hist("undo", "↶", h.undo, h.undoLabel)}${hist("redo", "↷", h.redo, h.redoLabel)}<button type="button" class="dz-close" aria-label="${esc(dz.close)}">✕</button></div>`;
  };

  // ---------------------------------------------------------------------------------------------------------------- the drawer
  function draw() {
    const panel = panelDef();
    if (panel) drawPanel(panel); else drawPage();
  }

  function drawPage() {
    drawer.innerHTML = `<div class="dz-head"><h2>${esc(dz.page)}</h2>${closeBtn()}</div><div id="dz-msg" class="bmsg" role="alert" hidden></div>
      <p class="hint">${esc(dz.pick)}</p>
      <form class="dz-form" id="dz-page" onsubmit="return false"></form>
      <h3 class="dz-section">${esc(dz.look)}</h3><div id="dz-look" class="dz-look"></div>
      <h3 class="dz-section">${esc(dz.tabs)}</h3>
      ${tabsOf(source).length ? `<div id="dz-tabs" class="dz-tabs"></div>
        <div class="dz-add-filter"><input type="text" id="dz-newtab" maxlength="40" placeholder="${esc(dz.newTabName)}" aria-label="${esc(dz.addTab)}"><button type="button" id="dz-addtab" ${tabsOf(source).length >= MAX_TABS ? "disabled" : ""}>${esc(dz.addTab)}</button></div>
        <div class="dz-actions"><button type="button" id="dz-onepage">${esc(dz.onePage)}</button></div>`
        : `<p class="hint">${esc(dz.noTabs)}</p><div class="dz-actions"><button type="button" id="dz-totabs" ${(source.layout || []).length < 2 ? "disabled" : ""}>${esc(dz.makeTabs)}</button></div>`}
      <h3 class="dz-section">${esc(dz.filters)}</h3><div id="dz-filters" class="dz-filters"></div>
      <div class="dz-add-filter"><select id="dz-newfilter" aria-label="${esc(dz.addFilter)}"></select><button type="button" id="dz-addfilter">${esc(dz.addFilter)}</button></div>
      <h3 class="dz-section">${esc(dz.addPanel)}</h3>
      <div class="dz-gallery" id="dz-gallery">${PANEL_TYPES.map((ty) => `<button type="button" class="dz-type" data-add="${ty}"><strong>${esc(typeName(ty))}</strong><span>${esc(dz.typeHint[ty])}</span></button>`).join("")}</div>`;
    const form = drawer.querySelector("#dz-page");
    for (const fd of PAGE_FIELDS) form.append(field(fd, source, (v) => commit(setPageField(source, fd.path, v), { message: dz.pageChanged, panel: null })));
    drawLook(drawer.querySelector("#dz-look"));
    const tabList = drawer.querySelector("#dz-tabs");
    tabsOf(source).forEach((tab, i, all) => {
      const row = el("div", { class: "dz-tab" });
      const input = el("input", { type: "text", maxlength: 60, "aria-label": dz.tabName, "data-tab-title": tab.id });
      input.value = tab.title;
      input.addEventListener("change", () => commit(renameTab(source, tab.id, input.value), { message: dz.tabRenamed, panel: null }));
      row.append(input,
        el("button", { type: "button", "data-tab-move": `${tab.id}:-1`, "aria-label": `${dz.tabEarlier}: ${tab.title}`, ...(i === 0 ? { disabled: "" } : {}) }, "↑"),
        el("button", { type: "button", "data-tab-move": `${tab.id}:1`, "aria-label": `${dz.tabLater}: ${tab.title}`, ...(i === all.length - 1 ? { disabled: "" } : {}) }, "↓"),
        el("button", { type: "button", class: "dz-danger", "data-tab-remove": tab.id, "aria-label": `${dz.tabRemove}: ${tab.title}` }, "✕"));
      tabList.append(row);
    });
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
    const fields = fieldsFor(panel, { isMeasure: (m) => catalog.some((c) => c.measures.some((x) => x.member === m)) });
    let lastGroup = null;
    const rows = fields.map((fd) => {
      const heading = fd.group && fd.group.of > 1 && fd.group.n !== lastGroup ? `<h3 class="dz-item">${esc(dz.item(fd.group.n, fd.group.of))}</h3>` : "";
      lastGroup = fd.group ? fd.group.n : null;
      if (fd.kind === "addrule") return `<div class="dz-field"><span></span><span class="dz-input" data-slot="${esc(fd.path)}"></span></div>`;
      return `${heading}<label class="dz-field"><span>${esc(dz.f[fd.key] || fd.key)}</span><span class="dz-input" data-slot="${esc(fd.path)}"></span></label>`;
    }).join("");
    drawer.innerHTML = `<div class="dz-head"><div><h2>${esc(panel.title || panel.id)}</h2><span class="badge">${esc(typeName(panel.type))}</span></div>${closeBtn()}</div>
      <div id="dz-msg" class="bmsg" role="alert" hidden></div><form class="dz-form" onsubmit="return false">${rows}</form>
      <h3 class="dz-section">${esc(dz.layout)}</h3>
      <div class="dz-layout" role="group" aria-label="${esc(dz.layout)}">${LAYOUT_COMMANDS.map((cmd) => `<button type="button" data-cmd="${cmd}" ${moveCommand(source, panel.id, cmd).problem ? "disabled" : ""}>${esc(dz.cmd[cmd])}</button>`).join("")}</div>
      <p class="hint">${esc(dz.width(rowOf(source, panel.id).find((c) => c.id === panel.id)?.span ?? 12))}</p>
      ${tabsOf(source).length > 1 ? `<label class="dz-field"><span>${esc(dz.toTab)}</span><span class="dz-input"><select id="dz-totab"><option value="">—</option>${tabsOf(source).filter((tab) => !tab.panels.includes(panel.id)).map((tab) => `<option value="${esc(tab.id)}">${esc(tab.title)}</option>`).join("")}</select></span></label>` : ""}
      <div class="dz-actions"><button type="button" id="dz-back">${esc(dz.back)}</button><button type="button" id="dz-dup">${esc(dz.duplicate)}</button><button type="button" id="dz-del" class="dz-danger">${esc(dz.remove)}</button></div>
      <p class="hint">${esc(dz.footer)}</p>`;
    for (const slot of drawer.querySelectorAll(".dz-input")) {
      const fd = fields.find((x) => x.path === slot.dataset.slot);
      if (fd.kind === "addrule") { slot.append(el("button", { type: "button", class: "dz-mini", "data-addrule": fd.base }, esc(dz.f.addRule))); continue; }
      if (fd.kind === "value") slot.append(valueControl(fd, panel));
      else slot.append(control(fd, panel, (v) => {
        const edit = setField(source, selected, fd.path, v, { optional: fd.optional });
        return commit(edit, { message: dz.changed(edit.source.panels.find((p) => p.id === selected)?.title || selected) });          // named as it will be after the change
      }));
      if (fd.rm) slot.append(el("button", { type: "button", class: "dz-mini", "data-rmrule": fd.rm }, esc(dz.f.removeRule)));
      if (fd.list && fd.count > listRule(panel, fd.list).min) slot.append(el("button", { type: "button", class: "dz-mini", "data-rmitem": `${fd.list}:${fd.index}` }, esc(dz.removeItem)));
    }
    const lists = Object.keys(LISTS).filter((k) => k.startsWith(`${panel.type}.`)).map((k) => k.split(".")[1]);
    const form = drawer.querySelector(".dz-form");
    for (const name of lists) if (Array.isArray(panel[name]) && panel[name].length < listRule(panel, name).max) form.append(el("button", { type: "button", class: "dz-mini", "data-additem": name }, esc(name === "series" ? dz.addSeries : dz.addMeasure)));
  }

  /** A measure no part of `item` uses yet (what "add a measure" and a change to a sum or ratio start with); undefined when the role may read no other. */
  const spareFor = (item) => {
    const used = new Set(membersOfItem(item));
    return measureOptions(catalog).find((o) => !used.has(o.value))?.value;
  };
  const membersOfItem = (item) => (typeof item === "string" ? [item] : item?.member ? [item.member] : item?.sum || [...(item?.ratio?.num || []), ...(item?.ratio?.den || [])]);

  /** The control for a measure, a sum or a ratio (a KPI's measure, a time chart's series): which of the three, then its members, and the formula in words. */
  function valueControl(fd, panel) {
    const item = getAt(panel, fd.path), kind = kindOf(item);
    const wrap = el("div", { class: "dz-value" });
    const kinds = el("select", { "data-path": `${fd.path}.kind`, "aria-label": dz.f.formula });
    for (const k of ["member", "sum", "ratio"]) kinds.append(el("option", { value: k }, esc(dz.kind[k])));
    kinds.value = kind;
    kinds.addEventListener("change", () => commit(changeKind(source, selected, fd.path, kinds.value, spareFor(item)), { message: dz.changed(panel.title || selected) }));
    wrap.append(kinds);
    const named = () => dz.changed(panel.title || selected);
    const members = (part, list, canRm) => {
      const box = el("div", { class: "dz-parts" });
      if (part !== "sum" && part !== "member") box.append(el("span", { class: "hint" }, esc(dz.part[part])));
      list.forEach((m, i) => {
        const row = el("div", { class: "dz-part" });
        row.append(control({ path: `${fd.path}.${part === "sum" ? "sum" : `ratio.${part}`}.${i}`, kind: "measure" }, panel, (v) => commit(setPart(source, selected, fd.path, part, i, v), { message: named() })));
        if (canRm) row.append(el("button", { type: "button", class: "dz-mini", "aria-label": dz.removePart }, "−"));
        row.querySelector("button")?.addEventListener("click", () => commit(removePart(source, selected, fd.path, part, i), { message: named() }));
        box.append(row);
      });
      const add = el("button", { type: "button", class: "dz-mini" }, esc(dz.addPart));
      add.addEventListener("click", () => commit(spareFor(item) ? addPart(source, selected, fd.path, part, spareFor(item)) : { problem: "spare" }, { message: named() }));
      box.append(add);
      return box;
    };
    if (kind === "member") wrap.append(control({ path: `${fd.path}.member`, kind: "measure" }, panel, (v) => {
      const edit = setField(source, selected, `${fd.path}.member`, v);
      return commit(edit, { message: named() });
    }));
    else if (kind === "sum") wrap.append(members("sum", item.sum, canRemovePart(item, "sum")));
    else wrap.append(members("num", item.ratio.num, canRemovePart(item, "num")), members("den", item.ratio.den, canRemovePart(item, "den")));
    if (kind !== "member") wrap.append(el("p", { class: "hint dz-preview" }, esc(dz.formulaIs(describe(item)))));
    return wrap;
  }

  /** The dashboard's look: the organisation's name and its logo (kept inside the file as a small data URI, `theme.logo`). */
  function drawLook(host) {
    const setTheme = (path, v) => commit(setPageField(source, path, v), { message: dz.pageChanged, panel: null });
    host.append(field({ path: "theme.name", kind: "text", key: "orgName", optional: true }, source, (v) => setTheme("theme.name", v)));
    const logo = source.theme?.logo;
    const row = el("div", { class: "dz-field dz-logo" }, `<span>${esc(dz.f.logo)}</span>`);
    const slot = el("span", { class: "dz-input" });
    if (logo) slot.append(el("img", { src: logo, alt: "", class: "dz-logo-preview", id: "dz-logo-img" }));
    const file = el("input", { type: "file", id: "dz-logo-file", accept: ACCEPTED.join(","), "aria-label": dz.logoPick });
    file.addEventListener("change", () => { if (file.files[0]) pickLogo(file.files[0], setTheme); });
    slot.append(file);
    if (logo) {
      const rm = el("button", { type: "button", class: "dz-mini", id: "dz-logo-rm" }, esc(dz.logoRemove));
      rm.addEventListener("click", () => setTheme("theme.logo", ""));
      slot.append(rm);
    }
    slot.append(el("p", { class: "hint" }, esc(dz.logoHint)));
    row.append(slot);
    host.append(row);
  }

  /** Shrinks the picked picture until it fits in the file: sizes from large to small, and at each size PNG, then WebP, then JPEG. */
  async function pickLogo(file, setTheme) {
    if (!ACCEPTED.includes(file.type)) { problems([dz.logoType]); return; }
    let bitmap;
    try { bitmap = await createImageBitmap(file); } catch { problems([dz.logoRead]); return; }
    for (const { w, h } of sizesToTry(bitmap.width, bitmap.height)) {
      const canvas = el("canvas", { width: w, height: h }), c2d = canvas.getContext("2d");
      for (const enc of ENCODINGS) {
        c2d.clearRect(0, 0, w, h);
        if (enc.onWhite) { c2d.fillStyle = "#fff"; c2d.fillRect(0, 0, w, h); }
        c2d.drawImage(bitmap, 0, 0, w, h);
        const uri = canvas.toDataURL(enc.type, enc.quality);
        if (uri.startsWith(`data:${enc.type}`) && fits(uri)) { setTheme("theme.logo", uri); return; }
      }
    }
    problems([dz.logoBig]);
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
    } else if (fd.kind === "number") { input = el("input", { type: "number", min: fd.min, max: fd.max, step: fd.step || 1 }); input.value = value; }
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
      drafts.edit({ ...draft, yaml: r.yaml, spec: r.spec, message, notes: (edit.notes || []).map((n) => dz.notes[n] || n) });
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

  /** Undo or redo one step of the draft's history: the draft in this browser is replaced and the page drawn again (the picked panel and the scroll position stay). */
  function step(kind) {
    if (busy || !drafts[kind]((label) => (kind === "undo" ? dz.undone : dz.redone)(label))) return;
    write({ on: true, panel: selected, scroll: window.scrollY });
    location.reload();
  }

  const activeTab = () => window.__render?.activeTab?.() ?? null;
  const titleOf = (ty, m, d) => dz.defaultTitle(ty, humanize(m), d && humanize(d));

  drawer.addEventListener("click", (e) => {
    const hb = e.target.closest("[data-hist]");
    if (hb) { step(hb.dataset.hist); return; }
    const cmd = e.target.closest("[data-cmd]");
    if (cmd) { commit(moveCommand(source, selected, cmd.dataset.cmd), { message: dz.moved }); return; }
    const tabRm = e.target.closest("[data-tab-remove]");
    if (tabRm) {
      const tab = tabsOf(source).find((x) => x.id === tabRm.dataset.tabRemove);
      if (tab && confirm(dz.confirmTab(tab.title, tab.panels.length))) commit(removeTab(source, tab.id), { message: dz.tabRemoved(tab.title), panel: null });
      return;
    }
    if (e.target.id === "dz-addtab") { commit(addTab(source, drawer.querySelector("#dz-newtab").value.trim() || dz.newTabName, dz.newTabNote), { message: dz.tabAdded, panel: null }); return; }
    if (e.target.id === "dz-totabs") { commit(layoutToTabs(source, [dz.tabOverview, dz.tabDetails]), { message: dz.tabsMade, panel: null }); return; }
    if (e.target.id === "dz-onepage") { if (confirm(dz.confirmOnePage)) commit(tabsToLayout(source), { message: dz.tabsUnmade, panel: null }); return; }
    const tabMove = e.target.closest("[data-tab-move]");
    if (tabMove) { const [id, dir] = tabMove.dataset.tabMove.split(":"); commit(moveTab(source, id, Number(dir)), { message: dz.tabMoved, panel: null }); return; }
    const rmRule = e.target.closest("[data-rmrule]");
    if (rmRule) { commit(setField(source, selected, rmRule.dataset.rmrule, "", { optional: true }), { message: dz.changed(panelDef()?.title || selected) }); return; }
    const addRuleBtn = e.target.closest("[data-addrule]");
    if (addRuleBtn) { commit(addRule(source, selected, addRuleBtn.dataset.addrule), { message: dz.changed(panelDef()?.title || selected) }); return; }
    const rmItem = e.target.closest("[data-rmitem]");
    if (rmItem) { const [name, i] = rmItem.dataset.rmitem.split(":"); commit(removeItem(source, selected, name, Number(i)), { message: dz.changed(panelDef()?.title || selected) }); return; }
    const addItemBtn = e.target.closest("[data-additem]");
    if (addItemBtn) {
      const name = addItemBtn.dataset.additem, list = panelDef()?.[name] || [];
      const used = new Set(list.flatMap(membersOfItem));
      const spare = measureOptions(catalog).find((o) => !used.has(o.value))?.value || measureOptions(catalog)[0]?.value;       // one already on the panel is fine when the role reads no other
      commit(addItem(source, selected, name, spare), { message: dz.changed(panelDef()?.title || selected) });
      return;
    }
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

  drawer.addEventListener("change", (e) => {
    if (e.target.id === "dz-totab" && e.target.value) commit(moveToTab(source, selected, e.target.value), { message: dz.moved });
  });

  // ---------------------------------------------------------------------------------------------------------------- picking a panel, the mode
  const announce = () => document.dispatchEvent(new CustomEvent("designer:pick", { detail: { panel: on ? selected : null } }));      // the Change box aims at it (render/builder.js)
  function select(id) {
    selected = id;
    for (const [pid, p] of panels) p.root.classList.toggle("dz-selected", pid === id);
    draw();
    write({ ...read(), on: true, panel: id });
    announce();
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
    if ((e.ctrlKey || e.metaKey) && !e.altKey && ["z", "y"].includes(e.key.toLowerCase()) && !dnd.active()) {
      if (/^(INPUT|TEXTAREA)$/.test(e.target.tagName) || e.target.isContentEditable) return;           // a text field has its own undo
      e.preventDefault();
      step(e.key.toLowerCase() === "y" || e.shiftKey ? "redo" : "undo");
      return;
    }
    if (e.key === "Escape" && selected && !dnd.active()) { select(null); return; }                // while a drag is held, Escape cancels the drag instead
    if ((e.key === "Enter" || e.key === " ") && hit(e) && !drawer.contains(e.target)) pick(e);
  }, true);

  const dnd = mountDnd({ panels, getSource: () => source, getActiveTab: activeTab, commit: (edit, o) => commit(edit, o), dz });

  function setMode(next) {
    on = next;
    if (on) dnd.enable(); else dnd.disable();
    button.setAttribute("aria-pressed", String(on));
    document.body.classList.toggle("designing", on);
    drawer.hidden = !on;
    for (const [, p] of panels) { if (on) p.root.setAttribute("tabindex", "0"); else { p.root.removeAttribute("tabindex"); p.root.classList.remove("dz-selected"); } }
    write({ ...read(), on, panel: on ? selected : null });
    announce();
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
