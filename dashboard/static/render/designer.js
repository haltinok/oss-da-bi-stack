// Design mode on a draft (/d/draft): click a panel to change its fields in a drawer; with nothing picked the drawer is the page's own view (title, filters, add a panel).
// The designer writes to the dashboard's source spec and nothing else; the builder service's validator, the same one that checks a model's answer, accepts or refuses every
// change, and an accepted change is stored in the draft and the page is drawn again (the picked panel and the scroll position come back from sessionStorage).
// The logic is in lib/designer-model.js (a panel's fields) and lib/designer-structure.js (new panels, removing, filters, the page's fields).
import { $, el, esc } from "../lib/dom.js";
import { anyMemberOptions, dimensionOptions, fieldsFor, getAt, measureOptions, setField, shown } from "../lib/designer-model.js";
import { createControl, createSlicer } from "./filter-controls.js";
import { describeValue, formatValue, parseValue } from "../lib/filters.js";
import { PANEL_TYPES, addFilter, addPanel, duplicatePanel, humanize, removeFilter, removePanel, setCrossFilter, crossModeOf, setFilter, setFilterScope, setFilterSlicer, setFilterType, setFilterVisible, slicerOf, setPageField, timeDimensions, typesFor, dimensionTypeOf } from "../lib/designer-structure.js";
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
      const typ = f.type || "select";
      const edit = (path, v) => commit(setFilter(source, catalog, f.id, path, v), { message: dz.filterChanged, panel: null });
      for (const fd of FILTER_FIELDS.filter((x) => x.path !== "parent")) card.append(field(fd, f, (v) => edit(fd.path, v)));
      card.append(field({ path: "type", kind: "choice", key: "filterType", options: typesFor(dimensionTypeOf(catalog, f.dimension)) }, { ...f, type: typ },
        (v) => commit(setFilterType(source, catalog, f.id, v), { message: dz.filterChanged, panel: null })));
      if (typ === "select" || typ === "multiselect") card.append(field(FILTER_FIELDS.find((x) => x.path === "parent"), f, (v) => edit("parent", v)));
      card.append(defaultRow(f, typ, (v) => edit("default", v)));
      // Where it applies and whether the reader sees it.
      const scope = f.scope || "dashboard", hasTabs = tabsOf(source).length > 0;
      const scopes = ["dashboard", ...(hasTabs || scope === "page" ? ["page"] : []), "panel"];
      card.append(field({ path: "scope", kind: "choice", key: "filterScope", options: scopes }, { ...f, scope },
        (v) => commit(setFilterScope(source, catalog, f.id, v), { message: dz.filterChanged, panel: null })));
      if (scope === "page") card.append(field({ path: "tab", kind: "choice", key: "filterTab", options: tabsOf(source).map((x) => x.id), labels: Object.fromEntries(tabsOf(source).map((x) => [x.id, x.title])) }, f, (v) => edit("tab", v)));
      if (scope === "panel") card.append(field({ path: "panel", kind: "choice", key: "filterPanel", options: source.panels.filter((p) => p.type !== "text").map((p) => p.id), labels: Object.fromEntries(source.panels.map((p) => [p.id, p.title || p.id])) }, f, (v) => edit("panel", v)));
      const eye = el("input", { type: "checkbox", "data-path": "visible", "aria-label": dz.f.filterVisible });
      eye.checked = f.visible !== false;
      eye.addEventListener("change", async () => { if (!(await commit(setFilterVisible(source, f.id, eye.checked), { message: dz.filterChanged, panel: null }))) eye.checked = !eye.checked; });         // a refused change puts the box back
      const eyeRow = el("label", { class: "dz-field dz-eye" }, `<span>${esc(dz.f.filterVisible)}</span>`);
      eyeRow.append(el("span", { class: "dz-input" }, "")); eyeRow.lastChild.append(eye);
      card.append(eyeRow);
      const slicer = el("input", { type: "checkbox", "data-path": "slicer", "aria-label": dz.f.filterSlicer });
      slicer.checked = !!slicerOf(source, f.id);
      slicer.addEventListener("change", async () => { if (!(await commit(setFilterSlicer(source, f.id, slicer.checked, { tab: activeTab() }), { message: dz.filterChanged, panel: null }))) slicer.checked = !slicer.checked; });
      const slicerRow = el("label", { class: "dz-field dz-eye" }, `<span>${esc(dz.f.filterSlicer)}</span>`);
      slicerRow.append(el("span", { class: "dz-input" }, "")); slicerRow.lastChild.append(slicer);
      card.append(slicerRow);
      if (f.visible === false) card.querySelector("h4").insertAdjacentHTML("beforeend", ` <span class="badge" title="${esc(dz.hiddenHint)}">${esc(dz.hidden)}</span>`);
      const rm = el("button", { type: "button", class: "dz-danger", "data-rm-filter": f.id }, esc(dz.removeFilter));
      card.append(rm);
      list.append(card);
    }
    const pick = drawer.querySelector("#dz-newfilter");
    for (const o of dimensionList()) pick.append(el("option", { value: o.value }, esc(o.label)));
  }

  function drawPanel(panel) {
    const fields = fieldsFor(panel, { isMeasure: (m) => catalog.some((c) => c.measures.some((x) => x.member === m)), filters: (source.filters || []).filter((x) => x.visible !== false) });
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
      if (!fd) continue;                                                                     // "Move to tab" has a slot of its own that is not a field
      if (fd.kind === "addrule") { slot.append(el("button", { type: "button", class: "dz-mini", "data-addrule": fd.base }, esc(dz.f.addRule))); continue; }
      if (fd.kind === "crossfilter") { slot.append(crossControl(panel)); continue; }
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

  /** "Clicking it filters the other panels": off, the whole dashboard, or this panel's tab. A click rule written by hand in the YAML shows as off, with a hint; choosing a mode replaces it. */
  function crossControl(panel) {
    const wrap = el("div", { class: "dz-cross" });
    const pick = el("select", { "data-path": "cross_filter", "aria-label": dz.f.crossFilter });
    const modes = ["", "all", ...(tabsOf(source).length ? ["page"] : [])];
    for (const m of modes) pick.append(el("option", { value: m }, esc(dz.v[m ? `cross_${m}` : "cross_off"])));
    pick.value = crossModeOf(panel);
    pick.addEventListener("change", () => commit(setCrossFilter(source, selected, pick.value), { message: dz.changed(panel.title || selected) }));
    wrap.append(pick);
    if (panel.on_click && !panel.cross_filter) wrap.append(el("p", { class: "hint" }, esc(dz.crossByHand)));
    return wrap;
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

  /** The row for a filter's default value: the filter's own control for the types that have one, and plain boxes for a select (a value) and a multiselect (values; the options come from data the designer does not read). */
  function defaultRow(f, typ, set) {
    const known = (typ === "select" || typ === "multiselect") ? window.__render?.filterOptions?.(f.id) || [] : [];
    if (known.length) {                                        // the real values, picked from a list (one for a select, several for a multiselect)
      const picker = createSlicer({ ...f, label: dz.f.filterDefault }, t, "list");
      picker.setOptions(known.map((value) => ({ value })));
      picker.show(f.default || "");
      picker.onChange = set;
      picker.el.classList.add("dz-default");
      const wrap = el("div", { class: "dz-field dz-default" }, `<span>${esc(dz.f.filterDefault)}</span>`);
      const slot = el("span", { class: "dz-input" });
      slot.append(picker.el);
      wrap.append(slot);
      return wrap;
    }
    if (typ === "select") return field({ path: "default", kind: "text", key: "filterDefault", optional: true }, f, set);
    const wrap = el("div", { class: "dz-field dz-default" }, `<span>${esc(dz.f.filterDefault)}</span>`);
    const slot = el("span", { class: "dz-input" });
    wrap.append(slot);
    if (typ === "multiselect") {
      const cur = parseValue(f.default), box = el("input", { type: "text", maxlength: 200, "aria-label": dz.f.filterDefault, placeholder: dz.multiHint, "data-path": "default" });
      box.value = cur ? cur.args.join(", ") : "";
      const not = el("input", { type: "checkbox", "aria-label": dz.exceptSelected });
      not.checked = cur?.op === "not";
      const push = () => { const args = box.value.split(",").map((x) => x.trim()).filter(Boolean); set(args.length ? formatValue({ op: not.checked ? "not" : "in", args }) : ""); };
      box.addEventListener("change", push);
      not.addEventListener("change", () => { if (box.value.trim()) push(); });
      const label = el("label", { class: "dz-except" }, "");
      label.append(not, document.createTextNode(` ${dz.exceptSelected}`));
      slot.append(box, label);
      return wrap;
    }
    const control = createControl({ ...f, label: dz.f.filterDefault }, t);
    control.show(f.default || "");
    control.onChange = set;
    control.el.classList.add("dz-default");
    if (f.default) control.el.append(el("p", { class: "hint" }, esc(describeValue(f, f.default))));
    return control.el;
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
      const list = fd.kind === "choice" ? fd.options.map((v) => ({ value: v, label: fd.labels?.[v] || dz.v[v] || v })) : options(fd, holder);
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
      Object.assign(draft, drafts.current());                                         // the page's draft object is the one the draft bar and the Change box read from
      // A change to a panel's own fields is applied to that panel alone (the page patches it in place); anything else (layout, tabs, filters, a new or removed panel) draws the page again.
      if (!edit.id && panel === selected && window.__render?.patch?.(r.spec)) {
        source = edit.source;
        const focused = drawer.contains(document.activeElement) ? document.activeElement.dataset?.path : null;
        resync();
        draw();
        if (focused) drawer.querySelector(`[data-path="${CSS.escape(focused)}"]`)?.focus({ preventScroll: true });
        document.dispatchEvent(new CustomEvent("draft:changed"));
        return true;
      }
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

  /** After the page replaced a panel's DOM: the new one is picked, can be reached by keyboard, and has its grip again. */
  function resync() {
    dnd.disable();
    dnd.enable();
    for (const [pid, p] of panels) {
      p.root.setAttribute("tabindex", "0");
      p.root.classList.toggle("dz-selected", pid === selected);
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
  // The filters' options arrive after the page is drawn (and the designer may already be open): the page view is drawn again so a default value can be picked from them.
  document.addEventListener("filters:options", () => { if (on && !selected && !busy && source) draw(); });

  // The data the drawer needs: the source of this draft and the members the role may read.
  button.disabled = true;
  try {
    const [r, cat] = await Promise.all([api.validate(draft.yaml), api.catalog()]);
    if (!r.ok) throw new Error(r.problems?.[0] || "the draft does not validate");
    if (!r.source) throw new Error(dz.oldBuilder);                              // a builder service built before the designer existed does not send the source back
    source = r.source;
    catalog = cat;
    button.disabled = false;
    document.body.append(el("datalist", { id: "dz-colors" }, '<option value="internet"><option value="reseller">'));
  } catch (e) {
    button.title = e.message;
    button.after(el("span", { class: "hint", id: "bd-design-note", role: "status" }, esc(e.message)));
    write({ ...read(), on: false, panel: null });                                // the designer is not usable: do not reopen it empty on the next load
    return;
  }
  if (state.on) {
    setMode(true);
    if (state.panel && panels.has(state.panel)) select(state.panel);
    if (Number.isFinite(state.scroll)) requestAnimationFrame(() => window.scrollTo(0, state.scroll));
  }
}
