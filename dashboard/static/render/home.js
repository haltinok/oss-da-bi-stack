// The start page (/home/): what a person can open and do, gathered from what the dashboards list already knows (the built samples their role may open, their saved dashboards and
// folders, what is shared with them) plus the dashboards they opened lately (this browser only). Plain JS; nothing here decides access: every list comes from a service that does.
import { createCubeClient } from "/cube/cube-client.mjs";
import { $, esc } from "../lib/dom.js";
import { filterItems } from "../lib/search.js";
import { readRecent } from "../lib/recent.js";
import { initTheme, mountThemeMenu } from "../lib/theme.js";
import { langOf, stringsFor, uiLocale } from "./strings.js";
import { mountLangSwitch } from "./lang.js";
import { createBuilderApi } from "./builder.js";
import { homeStrings } from "./home-strings.js";

const C = window.STACK;
const lang = langOf(uiLocale(navigator.language));
const w = homeStrings(lang);
const main = $("#main");
document.documentElement.lang = lang;
initTheme();
mountThemeMenu($("#theme"), { locale: () => lang });
mountLangSwitch({ languageLabel: lang === "tr" ? "Dil" : "Language" }, lang);
document.title = w.title;
$("#title").textContent = w.title;
const show = (msg) => { const e = $("#error"); e.textContent = msg; e.hidden = !msg; };

const client = createCubeClient({
  stack: C, apiUrl: C.cube, redirect: `${location.origin}/home/`,
  onSession(s) {
    if ($("#who")) return;
    const admin = s.role === "admin" ? `<a href="/admin/" id="admin-link">${esc(w.admin)}</a> · ` : "";
    const who = document.createElement("div");
    who.id = "who"; who.className = "who";
    who.innerHTML = `${admin}${esc(s.user)} · <a href="#" id="signout">${esc(w.signOut)}</a>`;
    $("#tools").append(who);
    $("#signout").addEventListener("click", (e) => { e.preventDefault(); client.signOut(); });
  },
});

const link = (d) => (d.kind === "saved" ? `/d/s/${encodeURIComponent(d.id)}` : `/d/${encodeURIComponent(d.id)}`);
const card = (d, hint = "") => `<a class="home-card" href="${esc(link(d))}"><strong>${esc(d.title)}</strong><span class="hint">${esc(hint || d.description || "")}</span></a>`;
const when = (iso) => { try { return new Date(iso).toLocaleDateString(lang === "tr" ? "tr-TR" : "en-US"); } catch { return ""; } };

async function start() {
  await client.token();                                                  // signs in (or back in) and tells us the role
  const session = client.session();
  const t = stringsFor(uiLocale(navigator.language));
  const api = createBuilderApi({ stack: C, client, t });
  $("#brand-sub").textContent = w.sub;
  const problems = [];
  const [index, saved, folders] = await Promise.all([
    fetch("/dashboards/index.json", { cache: "no-store" }).then((r) => r.json()).catch(() => { problems.push("dashboards"); return []; }),
    api.available ? api.listSaved().catch(() => []) : [],
    api.available ? api.listFolders().catch(() => []) : [],
  ]);
  if (problems.length) show(`${w.failed} ${problems.join(", ")}`);
  const readable = api.available ? await api.samples().then((r) => new Set(r.filter((x) => x.readable).map((x) => x.id))).catch(() => null) : null;           // what datasets leave this person
  const built = index.filter((d) => !readable || readable.has(d.id)).map((d) => ({ ...d, kind: "built" }));
  const savedItems = saved.filter((d) => d.readable).map((d) => ({ ...d, kind: "saved" }));
  const mine = savedItems.filter((d) => d.mine), shared = savedItems.filter((d) => !d.mine);
  const known = new Map([...built, ...savedItems].map((d) => [`${d.kind}:${d.id}`, d]));
  const recent = readRecent().map((r) => known.get(`${r.kind}:${r.id}`)).filter(Boolean).slice(0, 6);        // a dashboard that is gone or no longer readable is left out
  const folderCounts = folders.filter((f) => f.mine).map((f) => ({ ...f, n: saved.filter((d) => d.folder_id === f.id).length }));

  const sec = (title, body, more) => `<section class="home-sec"><h2>${esc(title)}${more ? ` <a href="${esc(more)}">${esc(w.more)} →</a>` : ""}</h2>${body}</section>`;
  const grid = (items, fn, none) => (items.length ? `<div class="home-grid">${items.map(fn).join("")}</div>` : `<p class="home-empty">${esc(none)}</p>`);
  const starters = [
    ...(session.role === "viewer" ? [] : [{ href: "/d/", title: w.describe, hint: w.describeHint }]),
    { href: "/", title: w.sales, hint: w.salesHint },
    { href: "/d/", title: w.allDashboards, hint: w.allDashboardsHint },
    ...(session.lab ? [{ href: "/lab/", title: w.lab, hint: w.labHint }] : []),
    ...(session.role === "admin" ? [{ href: "/admin/", title: w.console, hint: w.consoleHint }] : []),
  ];

  const draw = (query = "") => {
    const q = query.trim();
    if (q) {
      const hits = filterItems([...mine, ...shared, ...built], q, ["title", "description", "owner"]);
      $("#results").innerHTML = sec(w.searchResults, hits.length ? `<div class="home-grid">${hits.map((d) => card(d, d.kind === "saved" && !d.mine ? `${w.by} ${d.owner}` : "")).join("")}</div>` : `<p class="home-empty">${esc(w.searchNone(q))}</p>`);
      $("#sections").hidden = true;
      return;
    }
    $("#results").innerHTML = "";
    $("#sections").hidden = false;
  };

  main.innerHTML = `<input class="home-search" id="home-q" type="search" placeholder="${esc(w.search)}" aria-label="${esc(w.search)}" autocomplete="off"><div id="results" role="status" aria-live="polite"></div>
    <div id="sections">
    ${sec(w.start, `<div class="home-grid">${starters.map((s) => `<a class="home-card start" href="${esc(s.href)}"><strong>${esc(s.title)}</strong><span class="hint">${esc(s.hint)}</span></a>`).join("")}</div>`)}
    ${sec(w.recent, grid(recent, (d) => card(d), w.recentNone))}
    ${sec(w.shared, grid(shared.slice(0, 6), (d) => card(d, `${w.by} ${d.owner} · ${w.updated} ${when(d.updated_at)}`), w.sharedNone), shared.length > 6 ? "/d/" : "")}
    ${sec(w.mine, grid(mine.slice(0, 6), (d) => card(d, `${d.folder_name ? w.inFolder(d.folder_name) + " · " : ""}${w.updated} ${when(d.updated_at)}`), w.mineNone), mine.length > 6 ? "/d/" : "")}
    ${folderCounts.length ? sec(w.folders, `<div class="home-folders">${folderCounts.map((f) => `<a href="/d/">📁 ${esc(f.name)} (${f.n})</a>`).join("")}</div>`) : ""}
    ${sec(w.samples, grid(built.slice(0, 6), (d) => card(d), ""), built.length > 6 ? "/d/" : "")}
    </div>`;
  const q = $("#home-q");
  q.addEventListener("input", () => draw(q.value));
}

start().catch((e) => show(`${w.failed} ${e.message}`));
