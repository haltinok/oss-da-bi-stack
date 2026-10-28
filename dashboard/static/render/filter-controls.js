// The filter bar's controls for the filter types other than `select` (the select is drawn by main.js). Each control owns a piece of DOM and speaks in the filter's
// value string (see lib/filters.js): `show(value)` puts a value into it, and `onChange(value)` is called when the reader changes it ("" = no filter).
import { el, esc } from "../lib/dom.js";
import { FIXED_PRESETS, COUNTED_UNITS, MAX_COUNT, formatValue, parseValue } from "../lib/filters.js";
import { fold } from "../lib/search.js";

const MAX_SHOWN = 300;                                               // options drawn at once; more than that and the search narrows them

/**
 * A slicer's control for a select or multiselect filter: the options shown in the layout as a `list` (radio buttons or ticks) or as `chips` (buttons). Same contract as createControl:
 * `show(value)`, `setOptions(list)`, `onChange(value)`. A chosen value stays chosen (and shown) when the options no longer hold it, so other filters never undo a choice.
 */
export function createSlicer(f, t, display = "list") {
  const fc = t.fc, multi = f.type === "multiselect", label = f.label || f.id;
  const control = { onChange: () => {} };
  const root = el("div", { class: `slicer slicer-${display}`, role: "group", "aria-label": label });
  const search = el("input", { type: "search", class: "fc-search", placeholder: fc.search, "aria-label": `${label}: ${fc.search}`, hidden: "" });
  const list = el("div", { class: "slicer-list" });
  const except = el("input", { type: "checkbox" });
  const exceptRow = el("label", { class: "fc-ex", hidden: "" }, "");
  exceptRow.append(except, document.createTextNode(` ${fc.exclude}`));
  const clear = el("button", { type: "button", class: "fc-mini", hidden: "" }, esc(fc.clear));
  root.append(search, list, el("div", { class: "fc-actions" }), exceptRow);
  root.querySelector(".fc-actions").append(clear);
  let options = [], chosen = new Set(), exclude = false;
  const value = () => (!chosen.size ? "" : multi ? formatValue({ op: exclude ? "not" : "in", args: [...chosen] }) : [...chosen][0]);
  const emit = () => { control.onChange(value()); draw(); };
  function draw() {
    const q = fold(search.value);
    const known = options.map((o) => o.value);
    const all = [...known, ...[...chosen].filter((v) => !known.includes(v))];                 // a chosen value the options no longer hold stays, after them (the list does not jump when you pick)
    search.hidden = all.length <= 12;
    const hits = all.filter((v) => !q || fold(v).includes(q)).slice(0, MAX_SHOWN);
    list.replaceChildren(...hits.map((v) => {
      const on = chosen.has(v);
      if (display === "chips") {
        const b = el("button", { type: "button", class: "slicer-chip", "aria-pressed": String(on) }, esc(v));
        b.addEventListener("click", () => toggle(v));
        return b;
      }
      const box = el("input", { type: multi ? "checkbox" : "radio", name: `sl-${f.id}` });
      box.checked = on;
      box.addEventListener("click", () => toggle(v));                              // a click on the chosen radio clears it
      const lab = el("label", { class: "slicer-item" }, "");
      lab.append(box, document.createTextNode(` ${v}`));
      return lab;
    }));
    exceptRow.hidden = !multi || !chosen.size;
    except.checked = exclude;
    clear.hidden = !chosen.size;
  }
  function toggle(v) {
    if (multi) { if (chosen.has(v)) chosen.delete(v); else chosen.add(v); } else chosen = chosen.has(v) ? new Set() : new Set([v]);
    emit();
  }
  search.addEventListener("input", draw);
  except.addEventListener("change", () => { exclude = except.checked; emit(); });
  clear.addEventListener("click", () => { chosen.clear(); emit(); });
  return Object.assign(control, {
    el: root,
    setOptions(list_) { options = list_; draw(); },
    show(v) {
      const p = parseValue(v);
      if (multi) { chosen = new Set(p && (p.op === "in" || p.op === "not") ? p.args : []); exclude = !!p && p.op === "not"; } else chosen = new Set(v ? [String(v)] : []);
      draw();
    },
  });
}

/** { el, show(value), setOptions(list), onChange } for a filter of type multiselect, text, number or date. `t.fc` holds the words. */
export function createControl(f, t) {
  const control = { onChange: () => {}, setOptions: () => {} };
  const notify = (v) => control.onChange(v);                       // looked up when it happens: the page sets `onChange` after the control is made
  const label = f.label || f.id;
  const field = el("div", { class: "field fc", role: "group", "aria-label": label }, `<span class="fc-label">${esc(label)}</span>`);       // not a <label>: a click inside the popover must not click its first button
  if (f.type === "multiselect") Object.assign(control, multi(f, t, label, field, notify));
  else Object.assign(control, comparison(f, t, label, field, notify));
  control.el = field;
  return control;
}

// ------------------------------------------------------------------------------------------------------------------ multiselect
function multi(f, t, label, field, notify) {
  const fc = t.fc;
  let options = [], chosen = new Set(), exclude = false, timer = null;
  const api = {};
  const button = el("button", { type: "button", class: "fc-btn", "aria-haspopup": "dialog", "aria-expanded": "false" });
  const pop = el("div", { class: "fc-pop", role: "dialog", "aria-label": label, hidden: "" });
  const search = el("input", { type: "search", class: "fc-search", placeholder: fc.search, "aria-label": fc.search });
  const exBox = el("input", { type: "checkbox" });
  const list = el("ul", { class: "fc-list" });
  const more = el("p", { class: "hint fc-more", hidden: "" });
  const all = el("button", { type: "button", class: "fc-mini" }, esc(fc.selectAll));
  const none = el("button", { type: "button", class: "fc-mini" }, esc(fc.clear));
  pop.append(search, el("label", { class: "fc-ex" }, ""), el("div", { class: "fc-actions" }), list, more);
  pop.querySelector(".fc-ex").append(exBox, document.createTextNode(` ${fc.exclude}`));
  pop.querySelector(".fc-actions").append(all, none);
  field.append(button, pop);

  const value = () => (chosen.size ? formatValue({ op: exclude ? "not" : "in", args: [...chosen] }) : "");
  const summary = () => {
    button.textContent = !chosen.size ? t.all : exclude ? fc.nExcept(chosen.size) : chosen.size === 1 ? [...chosen][0] : fc.nSelected(chosen.size);
    button.classList.toggle("set", chosen.size > 0);
  };
  const emit = () => { summary(); clearTimeout(timer); timer = setTimeout(() => notify(value()), 300); };       // a run of ticks is one change
  function drawList() {
    const q = fold(search.value);
    const all_ = [...new Set([...chosen, ...options.map((o) => o.value)])];       // a chosen value the options no longer hold stays visible, so it can be unticked
    const hits = all_.filter((v) => !q || fold(v).includes(q));
    list.replaceChildren(...hits.slice(0, MAX_SHOWN).map((v) => {
      const box = el("input", { type: "checkbox" });
      box.checked = chosen.has(v);
      box.addEventListener("change", () => { if (box.checked) chosen.add(v); else chosen.delete(v); emit(); });
      const li = el("li", {}, "");
      const lab = el("label", {}, "");
      lab.append(box, document.createTextNode(` ${v}`));
      li.append(lab);
      return li;
    }));
    more.hidden = hits.length <= MAX_SHOWN;
    more.textContent = fc.more(hits.length - MAX_SHOWN);
    api.shown = hits.slice(0, MAX_SHOWN);
  }
  const setOpen = (open) => {
    pop.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
    if (open) { search.value = ""; drawList(); search.focus(); }
  };
  button.addEventListener("click", (e) => { e.preventDefault(); setOpen(pop.hidden); });
  search.addEventListener("input", drawList);
  exBox.addEventListener("change", () => { exclude = exBox.checked; emit(); });
  all.addEventListener("click", () => { for (const v of api.shown || []) chosen.add(v); drawList(); emit(); });
  none.addEventListener("click", () => { chosen.clear(); drawList(); emit(); });
  document.addEventListener("click", (e) => { if (!pop.hidden && !field.contains(e.target)) setOpen(false); });
  field.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) { setOpen(false); button.focus(); } });
  summary();
  return Object.assign(api, {
    setOptions(list_) { options = list_; if (!pop.hidden) drawList(); },
    show(v) {
      const p = parseValue(v);
      chosen = new Set(p && (p.op === "in" || p.op === "not") ? p.args : []);
      exclude = !!p && p.op === "not";
      exBox.checked = exclude;
      summary();
      if (!pop.hidden) drawList();
    },
  });
}

// ------------------------------------------------------------------------------------------------------------------ text, number and date
// An operator choice, then the boxes that operator needs. Nothing is sent until every box is filled in; choosing "Any" removes the filter.
const KINDS = {
  text: { contains: ["text"], not_contains: ["text"], starts: ["text"], ends: ["text"], set: [], unset: [] },
  number: { eq: ["number"], ne: ["number"], gt: ["number"], gte: ["number"], lt: ["number"], lte: ["number"], between: ["number", "number"], set: [], unset: [] },
  date: { between: ["date", "date"], on: ["date"], after: ["date"], on_or_after: ["date"], before: ["date"], on_or_before: ["date"], rel: ["rel"], set: [], unset: [] },
};

function comparison(f, t, label, field, notify) {
  const fc = t.fc, kinds = KINDS[f.type];
  const api = {};
  const row = el("span", { class: "fc-row" });
  const opSel = el("select", { "aria-label": label });
  opSel.append(el("option", { value: "" }, esc(fc.any)), ...Object.keys(kinds).map((op) => el("option", { value: op }, esc(fc.ops[op]))));
  const boxes = el("span", { class: "fc-boxes" });
  row.append(opSel, boxes);
  field.append(row);
  let inputs = [], rel = null;

  function drawBoxes(op, args = []) {
    boxes.replaceChildren();
    inputs = [];
    rel = null;
    const want = kinds[op] || [];
    want.forEach((kind, i) => {
      if (kind === "rel") { rel = relBoxes(args[0]); boxes.append(...rel.nodes); return; }
      const input = el("input", { type: kind === "text" ? "text" : kind, "aria-label": `${label}: ${fc.ops[op]}`, ...(kind === "number" ? { step: "any" } : {}), ...(kind === "text" ? { maxlength: 200 } : {}) });
      input.value = args[i] ?? "";
      input.addEventListener("change", push);
      if (kind === "text") input.addEventListener("keydown", (e) => { if (e.key === "Enter") push(); });
      inputs.push(input);
      boxes.append(i === 1 ? document.createTextNode(` ${fc.and} `) : "", input);
    });
  }
  /** The dynamic-date boxes: a named period, or last / next / past N units. */
  function relBoxes(current = "") {
    const counted = /^(last|next|past)_(\d+)_(\w+)$/.exec(current);
    const pick = el("select", { "aria-label": `${label}: ${fc.ops.rel}` });
    pick.append(...FIXED_PRESETS.map((p) => el("option", { value: p }, esc(fc.presets[p] || p))), ...["last", "next", "past"].map((d) => el("option", { value: `~${d}` }, esc(fc.counted[d]))));
    const n = el("input", { type: "number", min: 1, max: MAX_COUNT, step: 1, value: counted ? counted[2] : "7", "aria-label": fc.count, class: "fc-n" });
    const unit = el("select", { "aria-label": fc.unit });
    unit.append(...COUNTED_UNITS.map((u) => el("option", { value: u }, esc(fc.units[u]))));
    pick.value = counted ? `~${counted[1]}` : FIXED_PRESETS.includes(current) ? current : "last_month";
    if (counted) unit.value = counted[3];
    const sync = () => { const c = pick.value.startsWith("~"); n.hidden = unit.hidden = !c; };
    for (const x of [pick, n, unit]) x.addEventListener("change", () => { sync(); push(); });
    sync();
    return { nodes: [pick, n, unit], value: () => (pick.value.startsWith("~") ? `${pick.value.slice(1)}_${Math.min(MAX_COUNT, Math.max(1, Number(n.value) || 1))}_${unit.value}` : pick.value) };
  }
  function push() {
    const op = opSel.value;
    field.classList.toggle("set", !!op);
    if (!op) { notify(""); return; }
    if (op === "rel") { notify(formatValue({ op, args: [rel.value()] })); return; }
    const args = inputs.map((i) => i.value.trim());
    if (args.some((a) => a === "")) return;                                      // half filled in: wait
    if (op === "between" && f.type === "number" && Number(args[0]) > Number(args[1])) args.reverse();
    if (op === "between" && f.type === "date" && args[0] > args[1]) args.reverse();
    notify(formatValue({ op, args }));
  }
  opSel.addEventListener("change", () => { drawBoxes(opSel.value); push(); });
  return Object.assign(api, {
    show(v) {
      const p = parseValue(v);
      const ok = p && kinds[p.op];
      opSel.value = ok ? p.op : "";
      drawBoxes(ok ? p.op : "", ok ? p.args : []);
      field.classList.toggle("set", !!ok);
    },
  });
}
