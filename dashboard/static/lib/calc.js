// A calculation's formula (a tree made by dashboards/dashspec/calculations.py, kept in the compiled spec's `members["calc.<id>"].calc.ast`) worked out on numbers.
// `+`, `-` and `sum` skip a part with no value; `*` and `/` give no value when a side has none, and `/` by zero gives none. Mirror of calculations.evaluate in Python.
const add = (vs) => { const some = vs.filter((v) => v != null && Number.isFinite(v)); return some.length ? some.reduce((a, b) => a + b, 0) : null; };

/** The formula's value from `valueOf(member) -> number | null`; null when it has none. */
export function evaluateCalc(node, valueOf) {
  const go = (n) => {
    if ("n" in n) return n.n;
    if ("m" in n) { const v = valueOf(n.m); return v == null || !Number.isFinite(v) ? null : v; }
    if ("neg" in n) { const v = go(n.neg); return v == null ? null : -v; }
    if ("sum" in n) return add(n.sum.map(go));
    const a = go(n.a), b = go(n.b);
    if (n.op === "+") return add([a, b]);
    if (n.op === "-") return add([a, b == null ? null : -b]);
    if (a == null || b == null) return null;
    if (n.op === "*") return a * b;
    return b === 0 ? null : a / b;
  };
  return go(node);
}

/** The measures a list of measures comes to once each calculation is replaced by the ones it reads (each once). */
export function realMembers(members, measures) {
  return [...new Set(measures.flatMap((m) => (m.startsWith("calc.") && members[m]?.calc ? members[m].calc.members : [m])))];
}
