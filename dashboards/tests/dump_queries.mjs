// Prints the queries the renderer would send for every panel of a compiled dashboard under several filter states, for test_queries_match.
//   node dump_queries.mjs dashboards/build/sales-overview.json
import { readFileSync } from "node:fs";
import { panelQueries, periodDims, periodKey } from "../../dashboard/static/render/plan.js";

const spec = JSON.parse(readFileSync(process.argv[2], "utf8"));
const ids = (spec.filters || []).map((f) => f.id);
const states = [{}, ...ids.map((i) => ({ [i]: "x" })), Object.fromEntries(ids.map((i) => [i, "y"])), { _period: "2021-03-01..2021-03-31" }, { _period: "2020-01-01..2020-12-31", ...Object.fromEntries(ids.map((i) => [i, "z"])) },
  ...periodDims(spec).filter((d) => periodKey(spec, d) !== "_period").map((d) => ({ [periodKey(spec, d)]: "2021-03-01..2021-03-31" }))];                 // a period on another date role
console.log(JSON.stringify(states.map((values) => ({ values, panels: Object.fromEntries(spec.panels.map((p) => [p.id, panelQueries(spec, p, values)])) }))));
