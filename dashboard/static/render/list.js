// The list page (/d/): the prompt box, the search, the tag bar, the built dashboards, the saved dashboards and the semantic layer.
// Search, selected tags and the "group by tag" switch live here; the built list is drawn from them, the saved lists draw themselves from the
// same state (builder.js mountSavedList). Everything is filtered in the browser, nothing is asked of the server while you type or pick a tag.
import { $, esc } from "../lib/dom.js";
import { filterItems } from "../lib/search.js";
import { chipsHtml, groupByFirstTag, listSearch, MAX_SELECTED, parseListUrl, tagCounts, tagsOf, withTags } from "../lib/tags.js";
import { mountPromptBox, mountSavedList, mountSemantic } from "./builder.js";

const GROUP_KEY = "dashGroupByTag";                              // a per-viewer preference, kept in this browser only
const readGroup = () => { try { return localStorage.getItem(GROUP_KEY) === "1"; } catch { return false; } };
const writeGroup = (on) => { try { localStorage.setItem(GROUP_KEY, on ? "1" : "0"); } catch { /* storage unavailable: the switch still works for this visit */ } };

export function mountList({ main, mine, api, t }) {
  const start = parseListUrl(location.search);
  let query = start.q, selected = start.tags, group = readGroup(), saved = null;
  const counts = { built: { shown: mine.length, total: mine.length }, saved: { shown: 0, total: 0 } };
  const label = (tag) => t.tagFilterAria(tag);

  main.innerHTML = (api.available ? `<div id="builder-host"></div>` : "")
    + `<div class="list-search" role="search"><label for="list-q" class="sr-only">${esc(t.searchLabel)}</label>
        <input id="list-q" type="search" autocomplete="off" spellcheck="false" placeholder="${esc(t.searchPlaceholder)}">
        <button type="button" id="list-q-clear" class="icon-btn" aria-label="${esc(t.searchClear)}" title="${esc(t.searchClear)}" hidden>✕</button>
        <span id="list-q-status" class="hint" role="status" aria-live="polite"></span></div>
      <div class="tag-bar" id="tag-bar" hidden><span class="tag-bar-label" id="tag-bar-label">${esc(t.tagsLabel)}</span>
        <span class="tag-chips" id="tag-chips" data-scope="bar" role="group" aria-labelledby="tag-bar-label"></span>
        <button type="button" id="group-switch" class="tag-switch" aria-pressed="false">${esc(t.groupByTag)}</button></div>
      <div id="list-q-none" class="empty" hidden></div>`
    + (api.available ? `<div id="drafts-host" class="drafts-host" data-scope="saved" hidden></div>` : "")
    + `<div id="built-host" data-scope="built"></div>`
    + (api.available ? `<details class="card sem-wrap" id="sem-wrap"><summary>${esc(t.semantic)}</summary><div id="sem-host"></div></details>` : "");
  const box = $("#list-q"), clear = $("#list-q-clear"), status = $("#list-q-status"), none = $("#list-q-none"), bar = $("#tag-bar"), chips = $("#tag-chips"), sw = $("#group-switch");
  box.value = query;

  const card = (d) => `<div class="card dcard" data-id="${esc(d.id)}"><h2><a class="stretch" href="/d/${encodeURIComponent(d.id)}">${esc(d.title)}</a></h2><p>${esc(d.description)}</p>${
    tagsOf(d).length ? `<div class="tagrow">${chipsHtml(tagsOf(d), selected, label)}</div>` : ""}</div>`;
  const textMatch = (items, fields) => filterItems(items, query, fields);

  function drawBuilt(shown) {
    const host = $("#built-host");
    if (!mine.length) { host.innerHTML = `<div class="empty">${esc(t.noDashboards)}</div>`; return; }
    host.innerHTML = group
      ? groupByFirstTag(shown).map((g) => `<section class="tgroup"><h3 class="tg-h">${esc(g.tag ?? t.untagged)} <span class="hint">(${g.items.length})</span></h3><div class="dlist">${g.items.map(card).join("")}</div></section>`).join("")
      : `<div class="dlist">${shown.map(card).join("")}</div>`;
  }

  function drawBar() {
    // counts follow the search words (not the tag choice): "if I also pick this tag, how many are there?"
    const everyone = [...textMatch(mine, ["title", "description"]), ...textMatch(saved?.items() ?? [], ["title", "description", "owner"])];
    const list = tagCounts(everyone, selected);
    bar.hidden = !list.length;
    chips.innerHTML = list.map(({ tag, count }) => `<button type="button" class="tag-chip" data-tag="${esc(tag)}" aria-pressed="${selected.includes(tag)}" aria-label="${esc(`${label(tag)} (${count})`)}">${esc(tag)} <span class="tag-n">${count}</span></button>`).join("");
    sw.setAttribute("aria-pressed", String(group));
  }

  function showStatus() {
    const q = query.trim(), filtering = !!q || selected.length > 0;
    const shown = counts.built.shown + counts.saved.shown, total = counts.built.total + counts.saved.total;
    status.textContent = filtering ? t.searchCount(shown, total) : "";
    none.hidden = !(filtering && shown === 0 && total > 0);
    if (!none.hidden) none.textContent = q && selected.length ? t.searchNoneTagged(q, selected.join(", ")) : q ? t.searchNone(q) : t.tagNone(selected.join(", "));
    clear.hidden = !filtering;
  }

  function writeUrl() {
    try { history.replaceState(null, "", location.pathname + listSearch(query, selected)); } catch { /* an unusual page: the state just is not in the URL */ }
  }

  function apply() {
    const active = document.activeElement;                       // a chip is redrawn when it is clicked: put the focus back on its new self
    const spot = active?.dataset?.tag ? { scope: active.closest("[data-scope]")?.dataset.scope, tag: active.dataset.tag } : null;
    const shown = withTags(textMatch(mine, ["title", "description"]), selected);
    counts.built = { shown: shown.length, total: mine.length };
    drawBuilt(shown);
    saved?.render();                                              // the saved lists draw themselves again for this state (and report their count)
    drawBar();
    showStatus();
    writeUrl();
    if (spot) document.querySelector(`[data-scope="${spot.scope}"] button[data-tag="${CSS.escape(spot.tag)}"]`)?.focus();
  }

  function setState(q, tags) { query = q; selected = tags; box.value = q; apply(); }
  function toggleTag(tag) {
    if (selected.includes(tag)) selected = selected.filter((x) => x !== tag);
    else if (selected.length < MAX_SELECTED) selected = [...selected, tag];
    apply();
  }

  box.addEventListener("input", () => { query = box.value; apply(); });
  box.addEventListener("keydown", (e) => { if (e.key === "Escape" && (box.value || selected.length)) { e.preventDefault(); setState("", []); } });
  clear.addEventListener("click", () => { setState("", []); box.focus(); });
  sw.addEventListener("click", () => { group = !group; writeGroup(group); apply(); });
  main.addEventListener("click", (e) => {
    const chip = e.target.closest("#built-host button[data-tag], #tag-chips button[data-tag]");     // the saved lists handle their own chips (onTag)
    if (chip) toggleTag(chip.dataset.tag);
  });
  document.addEventListener("keydown", (e) => {                  // "/" jumps to the search, unless you are typing somewhere
    const on = document.activeElement;
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(on?.tagName) || on?.isContentEditable) return;
    e.preventDefault();
    box.focus();
  });
  apply();
  if (!api.available) return;
  mountPromptBox($("#builder-host"), api, t);
  mountSavedList($("#drafts-host"), api, t, {
    query: () => query, tags: () => selected, group: () => group, onTag: toggleTag,
    onCount: (c) => { counts.saved = c; showStatus(); },
  }).then((h) => { saved = h; apply(); });
  $("#sem-wrap").addEventListener("toggle", () => { if ($("#sem-wrap").open && !$("#sem-host").dataset.ready) { $("#sem-host").dataset.ready = "1"; mountSemantic($("#sem-host"), api, t); } });
}
