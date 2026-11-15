// Reads a JSON list of cases on stdin and prints what dashboard/static/lib/timecalc.js (and the fixed shifts of lib/compare.js) make of each, for test_timecalc.py to
// compare with the Python mirror. A case is { fn, args }.
import { shiftQuery, shiftRange, shiftYears } from "../../dashboard/static/lib/compare.js";
import { bucketStart, priorShift, widenQuery, withTimeCalcs } from "../../dashboard/static/lib/timecalc.js";

const fns = { shiftRange, shiftYears, shiftQuery, bucketStart, priorShift, widenQuery, withTimeCalcs };
let input = "";
for await (const chunk of process.stdin) input += chunk;
console.log(JSON.stringify(JSON.parse(input).map(({ fn, args }) => fns[fn](...args) ?? null)));
