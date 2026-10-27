// Searching a list of dashboards by what a person types. Pure functions, no DOM.
// The search is forgiving: case and accents do not matter, with Turkish rules ("satis" finds "Satış", "ISI" finds "ısı" and "isi"),
// every word must be found (in any order), and the query is plain text, never a pattern.
// A word also finds what it means (synonyms.js, Turkish and English: "gelir" finds "revenue"), what it is the ending of ("gelirleri" finds
// "gelir"), and a word one slip away from it ("revenu" and "revnue" find "revenue"). The word as typed is still looked for as plain text first.
import { SYNONYM_GROUPS } from "./synonyms.js";

/** Lower-case with Turkish rules, accents removed, dotless ı as i: both the text and the query go through it, so they meet in the middle. */
export const fold = (text) => String(text ?? "").toLocaleLowerCase("tr").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ı/g, "i");

/** The words of a query, folded; none when it is empty or only spaces. */
export const words = (query) => fold(query).split(/\s+/).filter(Boolean);

// Endings, longest first: the Turkish plural, case and possessive endings that stick to a business word, and the English plural / -ing / -ed.
const ENDINGS = ["lerinin", "larinin", "lerden", "lardan", "lerde", "larda", "lerin", "larin", "leri", "lari", "ler", "lar", "nin", "ye", "ya", "den", "dan", "ten", "tan", "de", "da", "te", "ta", "si", "in", "ing", "ed", "es", "s"];
const MIN_STEM = 3, MIN_FUZZY = 5, MIN_PREFIX = 4;

/** The word without one or two endings, as far as three letters are left: "gelirleri" gives "gelirler" and "gelir". */
export const stems = (word) => {
  const out = [];
  let level = [word];
  for (let pass = 0; pass < 2; pass++) {
    const next = [];
    for (const w of level) for (const e of ENDINGS) if (w.length - e.length >= MIN_STEM && w.endsWith(e)) next.push(w.slice(0, -e.length));
    out.push(...next);
    level = next;
  }
  return [...new Set(out)];
};

// word -> the words of every group it is in, folded once when the module loads
const RELATED = new Map();
for (const line of SYNONYM_GROUPS) {
  const group = [...new Set(line.split(/\s+/).filter(Boolean).map(fold))];
  for (const w of group) RELATED.set(w, new Set([...(RELATED.get(w) ?? []), ...group.filter((x) => x !== w)]));
}

/** The words that mean the same as `word`, or as the word it is a form of; none for a word the dictionary does not know. */
export const related = (word) => {
  const w = fold(word), out = new Set(RELATED.get(w));
  for (const stem of stems(w)) for (const r of RELATED.get(stem) ?? []) out.add(r);
  out.delete(w);
  return [...out];
};

/** Is `a` one insertion, deletion, substitution or swap of neighbours away from `b`? (Not equal: that is a plain match.) */
export const oneSlip = (a, b) => {
  if (a === b || Math.abs(a.length - b.length) > 1) return false;
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i++;
  if (i === a.length || i === b.length) return true;                                  // one extra letter at the end of the longer one
  const [x, y] = [a.slice(i + 1), b.slice(i + 1)];
  if (a.length === b.length) return x === y || (a[i] === b[i + 1] && a[i + 1] === b[i] && a.slice(i + 2) === b.slice(i + 2));
  return a.length > b.length ? x === b.slice(i) : y === a.slice(i);
};

/** Does the folded `text` hold `word` or a word with the same meaning? */
const found = (text, tokens, word) => {
  if (text.includes(word)) return true;                                                // as typed: any part of any word, as ever
  for (const stem of stems(word)) if (stem.length > MIN_STEM && text.includes(stem)) return true;
  for (const r of related(word)) if (tokens.some((t) => t === r || (r.length >= MIN_PREFIX && t.startsWith(r)))) return true;   // a meaning matches whole words (plus their endings), never a piece of one
  return word.length >= MIN_FUZZY && tokens.some((t) => t.length >= MIN_FUZZY - 1 && oneSlip(word, t));
};

/** Is every word of `query` (or something that means the same) somewhere in `haystack`? An empty query matches everything. */
export const matches = (haystack, query) => {
  const wanted = words(query);
  if (!wanted.length) return true;
  const text = fold(haystack), tokens = text.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  return wanted.every((w) => found(text, tokens, w));
};

/** The items whose fields (names of properties, or functions of the item) match the query; the same items, in the same order. */
export const filterItems = (items, query, fields) =>
  items.filter((item) => matches(fields.map((f) => (typeof f === "function" ? f(item) : item[f])).join(" "), query));
