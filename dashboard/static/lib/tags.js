// Tags on the dashboard list: which items carry which tags, counting them, filtering by them, grouping by the first one, and keeping the
// list's search and tag filters in the URL. Pure functions (the chip markup is a string), no DOM.
import { esc } from "./dom.js";

const collator = new Intl.Collator("tr");                       // Turkish order: ç after c, ş after s, ı before i
export const MAX_SELECTED = 5;                                  // a dashboard has at most 5 tags, so more cannot match anything

/** The tags of a list item (built dashboards and saved ones both carry `tags`; anything else is none). */
export const tagsOf = (item) => (Array.isArray(item?.tags) ? item.tags.filter((t) => typeof t === "string") : []);

/** The items that carry every selected tag; no selection keeps them all. */
export const withTags = (items, selected) => (selected.length ? items.filter((it) => selected.every((t) => tagsOf(it).includes(t))) : items);

/** [{ tag, count }] over `items`, the most used first and then by name (Turkish order). Selected tags are always listed, even with no item, so they can be unselected. */
export function tagCounts(items, selected = []) {
  const counts = new Map(selected.map((t) => [t, 0]));
  for (const it of items) for (const t of new Set(tagsOf(it))) counts.set(t, (counts.get(t) || 0) + 1);
  return [...counts].map(([tag, count]) => ({ tag, count })).sort((a, b) => b.count - a.count || collator.compare(a.tag, b.tag));
}

/** [{ tag, items }] by each item's FIRST tag, the tags in Turkish order and the untagged last (tag null); every item appears once, in its own order. */
export function groupByFirstTag(items) {
  const groups = new Map();
  for (const it of items) {
    const key = tagsOf(it)[0] ?? null;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(it);
  }
  const named = [...groups].filter(([k]) => k !== null).sort((a, b) => collator.compare(a[0], b[0]));
  return [...named, ...(groups.has(null) ? [[null, groups.get(null)]] : [])].map(([tag, list]) => ({ tag, items: list }));
}

/** The search and the selected tags from a URL's query string: ?q=sales&tag=a&tag=b. Unknown or odd values are cleaned, never an error. */
export function parseListUrl(search) {
  const params = new URLSearchParams(search || "");
  const tags = [];
  for (const raw of params.getAll("tag")) {
    const tag = raw.trim().toLocaleLowerCase("tr");
    if (tag && tag.length <= 24 && !tags.includes(tag) && tags.length < MAX_SELECTED) tags.push(tag);
  }
  return { q: (params.get("q") || "").slice(0, 200), tags };
}

/** The query string (with its "?", or "" when there is nothing) that restores a search and tags. */
export function listSearch(q, tags) {
  const params = new URLSearchParams();
  if (q.trim()) params.set("q", q.trim());
  for (const t of tags) params.append("tag", t);
  const text = params.toString();
  return text ? `?${text}` : "";
}

/**
 * Tag chips for a card, as buttons: `selected` ones are pressed. `label(tag)` is the accessible name ("Filter by tag sales"). Escaped.
 * Each carries data-tag so one click handler on the list can read it.
 */
export const chipsHtml = (tags, selected, label) => tags.map((t) =>
  `<button type="button" class="tag-chip" data-tag="${esc(t)}" aria-pressed="${selected.includes(t)}" aria-label="${esc(label(t))}">${esc(t)}</button>`).join("");
