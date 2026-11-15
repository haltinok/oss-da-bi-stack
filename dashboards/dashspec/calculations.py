"""`calculations`: named formulas over Cube measures (Average price = sum(a.revenue, b.revenue) / sum(a.units, b.units); Tax = a.revenue * 0.2), used like a measure (`calc.<id>`) anywhere
a panel takes one. The formula is read here, once, into a small tree the renderer evaluates on the numbers Cube returns (renderer: lib/calc.js): a total is the formula over the totals
of its parts (a ratio of sums, not an average of ratios).

    expr   := term (("+" | "-") term)*
    term   := factor (("*" | "/") factor)*
    factor := NUMBER | MEMBER | "sum" "(" expr ("," expr)* ")" | "prior" "(" MEMBER "," UNIT ")" | "rolling" "(" MEMBER "," N ")" | "(" expr ")" | "-" factor

`prior(m, unit)` is the measure one unit (year, quarter, month, week, day) earlier for the same row; `rolling(m, N)` is its sum over this time bucket and the N-1 before it.
Their values come from other rows (dashspec/timecalc.py makes the queries that bring them); the tree reads them under `prior_key` / `rolling_key`.

`+`, `-` and `sum` skip a part that has no value (a month one cube has no row for), unless only numbers are left (`x / prior(x, year) - 1` with no year before has none); `*` and `/` give no value when a side has none, and `/` by zero gives none."""
import re

PREFIX = "calc."
UNITS = ("year", "quarter", "month", "week", "day")          # what prior() moves by
ROLLING_MAX = 36


def prior_key(unit, member):
    """Where a row keeps a measure's value one `unit` earlier (mirror of priorKey in lib/calc.js)."""
    return f"prior:{unit}:{member}"


def rolling_key(n, member):
    """Where a row keeps a measure's sum over its last `n` time buckets (mirror of rollingKey in lib/calc.js)."""
    return f"rolling:{n}:{member}"
ID = re.compile(r"[a-z][a-z0-9_]*$")
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)|(.))")


class FormulaError(ValueError):
    pass


def _tokens(text):
    out, pos = [], 0
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        num, name, other = m.groups()
        out.append(("num", float(num) if "." in num else int(num)) if num else ("name", name) if name else ("op", other))
        pos = m.end()
    return out


def parse(text):
    """The formula as a tree: {"n": 2} | {"m": "cube.name"} | {"op": "+-*/", "a", "b"} | {"sum": [..]} | {"neg": ..}. Raises FormulaError saying what is wrong."""
    toks = _tokens(text or "")
    if not toks:
        raise FormulaError("the formula is empty")
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else (None, None)

    def take():
        nonlocal pos
        pos += 1
        return toks[pos - 1]

    def expect(op):
        if peek() != ("op", op):
            raise FormulaError(f"expected '{op}'" + (f" but found '{peek()[1]}'" if peek()[0] else " at the end"))
        take()

    def expr():
        node = term()
        while peek() in (("op", "+"), ("op", "-")):
            node = {"op": take()[1], "a": node, "b": term()}
        return node

    def term():
        node = factor()
        while peek() in (("op", "*"), ("op", "/")):
            node = {"op": take()[1], "a": node, "b": factor()}
        return node

    def factor():
        kind, val = peek()
        if kind is None:
            raise FormulaError("the formula ends where a number, a measure or '(' is needed")
        if kind == "num":
            take()
            return {"n": val}
        if kind == "name":
            take()
            if val == "sum" and peek() == ("op", "("):
                take()
                args = [expr()]
                while peek() == ("op", ","):
                    take()
                    args.append(expr())
                expect(")")
                return {"sum": args}
            if val in ("prior", "rolling") and peek() == ("op", "("):
                return time_call(val)
            if "." not in val:
                raise FormulaError(f"'{val}' is not a measure: write it as cube.measure (or use sum(...))")
            return {"m": val}
        if (kind, val) == ("op", "("):
            take()
            node = expr()
            expect(")")
            return node
        if (kind, val) == ("op", "-"):
            take()
            return {"neg": factor()}
        raise FormulaError(f"unexpected '{val}'")

    def time_call(fn):
        take()
        usage = "prior(cube.measure, year)" if fn == "prior" else "rolling(cube.measure, 12)"
        kind, member = peek()
        if kind != "name" or "." not in member or member.startswith(PREFIX):
            raise FormulaError(f"{fn}(...) reads one measure of the model, written cube.measure: {usage}")
        take()
        expect(",")
        kind, arg = take() if pos < len(toks) else (None, None)
        if fn == "prior":
            if kind != "name" or arg not in UNITS:
                raise FormulaError(f"prior(...) moves by {', '.join(UNITS)}" + (f", not '{arg}'" if arg is not None else "") + f": {usage}")
            expect(")")
            return {"prior": member, "by": arg}
        if kind != "num" or not isinstance(arg, int) or not 2 <= arg <= ROLLING_MAX:
            raise FormulaError(f"rolling(...) sums a whole number of time buckets, 2 to {ROLLING_MAX}" + (f", not '{arg}'" if arg is not None else "") + f": {usage}")
        expect(")")
        return {"rolling": member, "over": arg}          # not "n": that key is a number's

    tree = expr()
    if pos < len(toks):
        raise FormulaError(f"unexpected '{toks[pos][1]}'")
    return tree


def members_of(tree):
    """The measures a formula reads, each once, in order of appearance."""
    out = []

    def walk(n):
        if "m" in n:
            out.append(n["m"])
        elif "prior" in n:
            out.append(n["prior"])
        elif "rolling" in n:
            out.append(n["rolling"])
        elif "sum" in n:
            for a in n["sum"]:
                walk(a)
        elif "neg" in n:
            walk(n["neg"])
        elif "op" in n:
            walk(n["a"])
            walk(n["b"])

    walk(tree)
    return list(dict.fromkeys(out))


def evaluate(tree, value_of):
    """The formula over `value_of(member) -> number | None` (a Python mirror of lib/calc.js; the tests compare the two)."""
    def go(n):
        """-> (value, whether a measure's value is in it): a sum left with only numbers has no value (x / prior(x, year) - 1 with no year before is not -100%)."""
        if "n" in n:
            return n["n"], False
        if "m" in n or "prior" in n or "rolling" in n:
            v = value_of(n["m"] if "m" in n else prior_key(n["by"], n["prior"]) if "prior" in n else rolling_key(n["over"], n["rolling"]))
            return v, v is not None
        if "neg" in n:
            v, d = go(n["neg"])
            return (None if v is None else -v), d
        if "sum" in n:
            return _add([go(a) for a in n["sum"]])
        (a, da), (b, db) = go(n["a"]), go(n["b"])
        if n["op"] == "+":
            return _add([(a, da), (b, db)])
        if n["op"] == "-":
            return _add([(a, da), (None if b is None else -b, db)])
        if a is None or b is None:
            return None, False
        if n["op"] == "*":
            return a * b, da or db
        return (None, False) if b == 0 else (a / b, da or db)

    return go(tree)[0]


def time_calls(trees):
    """What the formulas read from other rows: { "prior": { unit: [members] }, "rolling": { member: [n, ...] } }, each list in order of appearance (mirror of timeCalls in lib/calc.js)."""
    out = {"prior": {}, "rolling": {}}

    def walk(n):
        if "prior" in n:
            ms = out["prior"].setdefault(n["by"], [])
            if n["prior"] not in ms:
                ms.append(n["prior"])
        elif "rolling" in n:
            ns = out["rolling"].setdefault(n["rolling"], [])
            if n["over"] not in ns:
                ns.append(n["over"])
        elif "sum" in n:
            for a in n["sum"]:
                walk(a)
        elif "neg" in n:
            walk(n["neg"])
        elif "op" in n:
            walk(n["a"])
            walk(n["b"])

    for t in trees:
        walk(t)
    return out


def _add(parts):
    """(value, has data) parts added, skipping those with no value; none left, or only numbers left in place of a missing part: no value."""
    have = [(v, d) for v, d in parts if v is not None]
    if not have or (len(have) < len(parts) and not any(d for _, d in have)):
        return None, False
    return sum(v for v, _ in have), any(d for _, d in have)


def entry(calc, tree):
    """What `members` holds for `calc.<id>` in the compiled spec: a measure, with the tree and the measures it reads."""
    out = {"kind": "measure", "type": "number", "label": calc["label"], "calc": {"ast": tree, "members": members_of(tree)}}
    if "format" in calc:
        out["format"] = calc["format"]
    return out


def real_members(members, measures):
    """`measures` with each calculation replaced by the measures it reads (each once): what Cube is asked for, and what decides which cubes a panel reaches."""
    out = []
    for m in measures:
        out.extend(members.get(m, {}).get("calc", {}).get("members", [m]) if m.startswith(PREFIX) else [m])
    return list(dict.fromkeys(out))


def of_spec(spec):
    """{ "calc.<id>": entry } for the calculations a (validated) spec lists; a formula that does not read is left out (the validator says so)."""
    out = {}
    for c in spec.get("calculations", []):
        try:
            out[PREFIX + c["id"]] = entry(c, parse(c["formula"]))
        except FormulaError:
            pass
    return out


class WithCalculations:
    """A catalog that also knows the calculations of one spec: `calc.<id>` is a number measure that reaches whatever all the measures it reads can reach."""

    def __init__(self, base, calcs):
        self._base, self.calcs = base, calcs

    def __getattr__(self, name):
        return getattr(self._base, name)

    def lookup(self, member):
        if member.startswith(PREFIX):
            return ("measure", "number") if member in self.calcs else None
        return self._base.lookup(member)

    def extra(self, member):
        return self.calcs.get(member, {}) if member.startswith(PREFIX) else {}

    def suggest(self, member):
        if member.startswith(PREFIX):
            return "calculations: " + (", ".join(sorted(self.calcs)) or "none are defined")
        return self._base.suggest(member)

    def reachable(self, src, dst):
        return self._base.reachable(src, dst)


def with_calculations(catalog, spec):
    """`catalog`, taught the calculations of `spec` (the catalog itself when it has none)."""
    if not spec.get("calculations") or isinstance(catalog, WithCalculations):
        return catalog
    return WithCalculations(catalog, of_spec(spec))
