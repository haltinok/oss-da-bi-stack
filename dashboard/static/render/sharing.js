// Folders, sharing, moving, handing over and the trash on the dashboards list (/d/). The list itself is drawn by builder.js (mountSavedList); these are its dialogs.
import { esc } from "../lib/dom.js";
import { sharingStrings } from "./sharing-strings.js";

export const words = (t) => sharingStrings(t.dateLocale || "en");

const dlg = () => {
  let d = document.querySelector("#share-dlg");
  if (!d) { d = document.createElement("dialog"); d.id = "share-dlg"; d.className = "share-dialog"; document.body.append(d); }
  return d;
};

/** A one-field dialog (a folder's name). `done(value)` returns a promise; a refusal is shown in the dialog. */
export function nameDialog(w, title, value, goLabel, done) {
  const d = dlg();
  d.innerHTML = `<form method="dialog" novalidate><h2>${esc(title)}</h2><label>${esc(w.folderName)}<input name="name" value="${esc(value)}" maxlength="80" required></label>
    <p class="err" role="alert" hidden></p><div class="foot"><button type="button" data-close>${esc(w.cancel)}</button><button type="submit" class="primary" data-go>${esc(goLabel)}</button></div></form>`;
  wire(d, async (f) => { await done(new FormData(f).get("name").trim()); });
  open(d);
}

/**
 * The sharing dialog of a dashboard (`kind` "dashboard") or a folder: who it is shared with (a person or a group, view or edit), and for a dashboard also its folder and its owner.
 * `item` is the list's entry (id, title / name, shares, folder_id, owner), `folders` the folders you may put it in. `save(body)` sends the change.
 */
export function shareDialog({ w, kind, item, folders = [], save }) {
  const shares = (item.shares || []).map((s) => ({ ...s }));
  const d = dlg();
  const folderRow = kind === "dashboard"
    ? `<label>${esc(w.moveTo)}<select name="folder"><option value="">${esc(w.noFolder)}</option>${folders.filter((f) => f.can_edit).map((f) => `<option value="${esc(f.id)}"${f.id === item.folder_id ? " selected" : ""}>${esc(f.name)}</option>`).join("")}</select></label>
       <label>${esc(w.ownerChange)}<input name="owner" value="" placeholder="${esc(item.owner)}" autocomplete="off"><span class="hint">${esc(w.ownerHint)}</span></label>` : `<p class="hint">${esc(w.folderShared)}</p>`;
  d.innerHTML = `<form method="dialog" novalidate><h2>${esc(w.shareTitle(item.title || item.name))}</h2>
    <div><span class="hint">${esc(w.shareWith)}</span><div id="sh-list" class="share-list"></div>
      <div class="row"><select id="sh-type" aria-label="${esc(w.shareWith)}"><option value="user">${esc(w.sharePerson)}</option><option value="group">${esc(w.shareGroup)}</option></select>
        <input id="sh-name" placeholder="${esc(w.shareName)}" autocomplete="off" aria-label="${esc(w.shareName)}">
        <select id="sh-perm" aria-label="permission"><option value="view">${esc(w.shareView)}</option><option value="edit">${esc(w.shareEdit)}</option></select>
        <button type="button" id="sh-add">${esc(w.shareAdd)}</button></div><p class="hint">${esc(w.shareHint)}</p></div>
    ${folderRow}<p class="err" role="alert" hidden></p><div class="foot"><button type="button" data-close>${esc(w.cancel)}</button><button type="submit" class="primary" data-go>${esc(w.save)}</button></div></form>`;
  const list = d.querySelector("#sh-list");
  const draw = () => {
    list.innerHTML = shares.map((s, i) => `<span class="chip">${esc(s.type === "group" ? `${w.shareGroup}: ${s.principal}` : s.principal)} · ${esc(s.permission === "edit" ? w.shareEdit : w.shareView)}
      <button type="button" class="x" data-rm="${i}" aria-label="${esc(w.remove)} ${esc(s.principal)}">✕</button></span>`).join("") || `<span class="hint">${esc(w.shareNobody)}</span>`;
    list.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => { shares.splice(Number(b.dataset.rm), 1); draw(); }));
  };
  draw();
  d.querySelector("#sh-add").addEventListener("click", () => {
    const name = d.querySelector("#sh-name").value.trim();
    if (!name) return;
    const type = d.querySelector("#sh-type").value, permission = d.querySelector("#sh-perm").value;
    const at = shares.findIndex((s) => s.type === type && s.principal === name);
    if (at >= 0) shares[at].permission = permission; else shares.push({ type, principal: name, permission });
    d.querySelector("#sh-name").value = "";
    draw();
  });
  wire(d, async (f) => {
    const v = Object.fromEntries(new FormData(f));
    const body = { shares };
    if (kind === "dashboard") {
      if ((v.folder || null) !== (item.folder_id || null)) body.folder_id = v.folder || null;
      if (v.owner && v.owner.trim() && v.owner.trim() !== item.owner) body.owner = v.owner.trim();
    }
    await save(body);
  });
  open(d);
}

function wire(d, onSubmit) {
  const form = d.querySelector("form"), err = form.querySelector(".err");
  form.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", (e) => { e.preventDefault(); d.close(); }));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const go = form.querySelector("[data-go]");
    go.disabled = true;
    try { await onSubmit(form); d.close(); } catch (x) { err.textContent = x.message; err.hidden = false; go.disabled = false; }
  });
}

function open(d) { if (!d.open) d.showModal(); d.querySelector("input:not([type=hidden]), select")?.focus(); }
