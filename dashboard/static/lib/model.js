// Which model a page is in (PLAN-models.md). A stack serves one or more models (window.STACK.models, from models.yml: id, label, the model's own Cube); every page is in exactly
// one of them: the address' ?model=, else a hint the page has (a draft says its model), else the last one used in this browser, else the first (the default). Two models share
// nothing but sign-in and the people: different dashboards, builder catalog, lab schema, row rules and Cube, so the header's switch changes the whole page, it does not filter it.
// A stack with one model (or an older one with no `models`) behaves as it always did: no switch, no parameters.

const keep = {
  get: () => { try { return localStorage.getItem("model"); } catch { return null; } },
  set: (v) => { try { localStorage.setItem("model", v); } catch { /* ignore */ } },
};

/** The stack's models (an older stack with none has one, nameless, on its own Cube). */
export const modelsOf = (stack) => (stack.models?.length ? stack.models : [{ id: "default", label: "", cube: stack.cube }]);

/** { models, model, multiple, isDefault }: the model this page is in (and remembered for the next page). `hint`: a model the page already knows (the draft's). */
export function pickModel(stack, { hint = null, search = location.search } = {}) {
  const models = modelsOf(stack);
  const wanted = new URLSearchParams(search).get("model") || hint || keep.get();
  const model = models.find((m) => m.id === wanted) || models[0];
  if (models.length > 1) keep.set(model.id);
  return { models, model, multiple: models.length > 1, isDefault: model === models[0] };
}

/** What the builder and the lab are told: the model's id, or nothing on a one-model stack (their default is the same). */
export const modelParam = (pick) => (pick.multiple ? pick.model.id : undefined);

/** Where a model's compiled dashboards are: /dashboards/<model>/ (a one-model stack keeps /dashboards/). */
export const dashboardsBase = (pick) => (pick.multiple ? `/dashboards/${pick.model.id}/` : "/dashboards/");

/** The address of the same page in another model: a dashboard of the old model does not exist in the new one, so a dashboard page goes to the list. */
export function addressIn(id, { pathname = location.pathname, search = location.search } = {}) {
  const q = new URLSearchParams(search);
  q.set("model", id);
  q.delete("dataset");                                            // a dataset is a choice inside a model
  const here = /^\/d\/.+/.test(pathname) ? "/d/" : pathname;
  if (here !== pathname) { q.delete("tab"); q.delete("q"); q.delete("tag"); }
  return `${here}?${q.toString()}`;
}

/** The header's model select (`#model-field` holds `#f-model`, hidden until there is a choice); changing it opens the page in the other model. */
export function mountModelSwitch(pick, { label = "Model", doc = document, go = (url) => location.assign(url) } = {}) {
  const field = doc.getElementById("model-field"), sel = doc.getElementById("f-model");
  if (!field || !sel || !pick.multiple) return;
  doc.getElementById("model-label")?.replaceChildren(label);
  sel.setAttribute("aria-label", label);
  sel.replaceChildren(...pick.models.map((m) => { const o = doc.createElement("option"); o.value = m.id; o.textContent = m.label || m.id; return o; }));
  sel.value = pick.model.id;
  field.hidden = false;
  sel.addEventListener("change", () => { keep.set(sel.value); go(addressIn(sel.value)); });
}
