// The dashboards a person opened lately (the start page's "Pick up where you left off"). Kept in this browser only: a per-viewer convenience, never a record.
// Pure functions plus a guarded storage wrapper, so a browser that blocks storage just shows nothing.
export const RECENT_KEY = "dashRecent";
export const MAX_RECENT = 8;

/** `list` with `item` ({ kind: "built" | "saved", id, title }) first and stamped `at`; an earlier visit to the same dashboard is replaced, the rest cut to MAX_RECENT. */
export const pushRecent = (list, item, at = Date.now()) => [{ kind: item.kind, id: item.id, title: String(item.title || "").slice(0, 120), at },
  ...list.filter((x) => !(x.kind === item.kind && x.id === item.id))].slice(0, MAX_RECENT);

/** A list as it came out of storage, made safe: only well-formed entries, newest first, at most MAX_RECENT. */
export const cleanRecent = (raw) => (Array.isArray(raw) ? raw : [])
  .filter((x) => x && (x.kind === "built" || x.kind === "saved") && typeof x.id === "string" && x.id && typeof x.at === "number")
  .sort((a, b) => b.at - a.at).slice(0, MAX_RECENT);

/** The recent list from a Storage (localStorage). */
export function readRecent(storage = globalThis.localStorage) {
  try { return cleanRecent(JSON.parse(storage.getItem(RECENT_KEY) || "[]")); } catch { return []; }
}

/** Note that `item` was opened. */
export function noteRecent(item, storage = globalThis.localStorage, at = Date.now()) {
  try { storage.setItem(RECENT_KEY, JSON.stringify(pushRecent(readRecent(storage), item, at))); return true; } catch { return false; }
}
