// Reads a JSON list of { query, kind } on stdin and prints what dashboard/static/lib/compare.js makes of each ({ shifted, label } or null),
// for test_compare.py to compare with the Python mirror.
import { compareLabel, shiftQuery } from "../../dashboard/static/lib/compare.js";

let input = "";
for await (const chunk of process.stdin) input += chunk;
console.log(JSON.stringify(JSON.parse(input).map(({ query, kind, yearFields }) => {
  const s = shiftQuery(query, kind, yearFields);
  return s && { ...s, label: compareLabel(s.moved, kind, yearFields) };
})));
