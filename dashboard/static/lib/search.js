// Searching a list of dashboards by what a person types. Pure functions, no DOM.
// The search is forgiving: case and accents do not matter, with Turkish rules ("satis" finds "Satış", "ISI" finds "ısı" and "isi"),
// every word must be found (in any order), and the query is plain text, never a pattern.

/** Lower-case with Turkish rules, accents removed, dotless ı as i: both the text and the query go through it, so they meet in the middle. */
export const fold = (text) => String(text ?? "").toLocaleLowerCase("tr").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ı/g, "i");

/** The words of a query, folded; none when it is empty or only spaces. */
export const words = (query) => fold(query).split(/\s+/).filter(Boolean);

/** Is every word of `query` somewhere in `haystack`? An empty query matches everything. */
export const matches = (haystack, query) => {
  const wanted = words(query);
  if (!wanted.length) return true;
  const text = fold(haystack);
  return wanted.every((w) => text.includes(w));
};

/** The items whose fields (names of properties, or functions of the item) match the query; the same items, in the same order. */
export const filterItems = (items, query, fields) =>
  items.filter((item) => matches(fields.map((f) => (typeof f === "function" ? f(item) : item[f])).join(" "), query));
