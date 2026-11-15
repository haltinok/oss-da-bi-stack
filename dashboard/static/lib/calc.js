// A calculation's formula (a tree made by dashboards/dashspec/calculations.py, kept in the compiled spec's `members["calc.<id>"].calc.ast`) worked out on numbers.
// `+`, `-` and `sum` skip a part with no value (unless only numbers are left); `*` and `/` give no value when a side has none, and `/` by zero gives none. Mirror of calculations.evaluate in Python.
// `prior` and `rolling` nodes read values that come from other rows (see lib/timecalc.js), kept on the row under priorKey / rollingKey.
export const priorKey = (unit, member) => `prior:${unit}:${member}`;
export const rollingKey = (n, member) => `rolling:${n}:${member}`;

// Each part is [value, has data]: a sum left with only numbers in place of a missing part has no value (x / prior(x, year) - 1 with no year before is not -100%).
const add = (parts) => {
  const have = parts.filter(([v]) => v != null && Number.isFinite(v));
  if (!have.length || (have.length < parts.length && !have.some(([, d]) => d))) return [null, false];
  return [have.reduce((a, [v]) => a + v, 0), have.some(([, d]) => d)];
};

/** The formula's value from `valueOf(member) -> number | null`; null when it has none. */
export function evaluateCalc(node, valueOf) {
  const go = (n) => {
    if ("n" in n) return [n.n, false];
    if ("m" in n || "prior" in n || "rolling" in n) {
      const v = valueOf("m" in n ? n.m : "prior" in n ? priorKey(n.by, n.prior) : rollingKey(n.over, n.rolling));
      return v == null || !Number.isFinite(v) ? [null, false] : [v, true];
    }
    if ("neg" in n) { const [v, d] = go(n.neg); return [v == null ? null : -v, d]; }
    if ("sum" in n) return add(n.sum.map(go));
    const [a, da] = go(n.a), [b, db] = go(n.b);
    if (n.op === "+") return add([[a, da], [b, db]]);
    if (n.op === "-") return add([[a, da], [b == null ? null : -b, db]]);
    if (a == null || b == null) return [null, false];
    if (n.op === "*") return [a * b, da || db];
    return b === 0 ? [null, false] : [a / b, da || db];
  };
  return go(node)[0];
}

/** The measures a list of measures comes to once each calculation is replaced by the ones it reads (each once). */
export function realMembers(members, measures) {
  return [...new Set(measures.flatMap((m) => (m.startsWith("calc.") && members[m]?.calc ? members[m].calc.members : [m])))];
}

/** What formulas read from other rows: { prior: { unit: [members] }, rolling: { member: [n, ...] } }, in order of appearance (mirror of calculations.time_calls). */
export function timeCalls(trees) {
  const out = { prior: {}, rolling: {} };
  const walk = (n) => {
    if ("prior" in n) { const ms = (out.prior[n.by] ||= []); if (!ms.includes(n.prior)) ms.push(n.prior); }
    else if ("rolling" in n) { const ns = (out.rolling[n.rolling] ||= []); if (!ns.includes(n.over)) ns.push(n.over); }
    else if ("sum" in n) n.sum.forEach(walk);
    else if ("neg" in n) walk(n.neg);
    else if ("op" in n) { walk(n.a); walk(n.b); }
  };
  trees.forEach(walk);
  return out;
}
