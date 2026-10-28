// Reads a JSON list of { filter, text, env: { today: "YYYY-MM-DD", weekStart, fiscalStart } } on stdin and prints what dashboard/static/lib/filters.js makes of each
// ({ cube: [...], preset: {...} | null }), for test_filters.py to compare with the Python mirror.
import { day, resolvePreset, toCube } from "../../dashboard/static/lib/filters.js";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const out = JSON.parse(input).map(({ filter, text, env }) => {
  const [y, m, d] = env.today.split("-").map(Number);
  const e = { ...env, today: day(y, m, d) };
  return { cube: toCube(filter, text, e), preset: filter.type === "date" && text?.startsWith("rel:") ? resolvePreset(decodeURIComponent(text.slice(4)), e) : null };
});
console.log(JSON.stringify(out));
