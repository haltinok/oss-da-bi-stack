"""Filter values and what they mean to Cube: the Python mirror of dashboard/static/lib/filters.js (that file explains the value forms).
`dashspec lint` asks Cube for the queries a page sends, so a filter has to turn into the same Cube filters here as in the browser;
dashboards/tests/test_filters.py runs both on one table of cases and compares."""
import re
from datetime import date, timedelta
from urllib.parse import quote, unquote

OPS = {
    "select": ["equals"],
    "multiselect": ["in", "not"],
    "text": ["contains", "not_contains", "starts", "ends", "set", "unset"],
    "number": ["eq", "ne", "gt", "gte", "lt", "lte", "between", "set", "unset"],
    "date": ["between", "on", "after", "on_or_after", "before", "on_or_before", "rel", "set", "unset"],
}
LIST_OPS, NO_ARG = {"in", "not"}, {"set", "unset"}
ALL_OPS = {op for ops in OPS.values() for op in ops}
FIXED_PRESETS = [
    "today", "yesterday", "tomorrow",
    "this_week", "last_week", "next_week", "this_month", "last_month", "next_month", "this_quarter", "last_quarter", "next_quarter", "this_year", "last_year", "next_year",
    "week_to_date", "month_to_date", "quarter_to_date", "year_to_date",
    "this_fiscal_quarter", "last_fiscal_quarter", "this_fiscal_year", "last_fiscal_year", "fiscal_year_to_date", "all_time",
]
COUNTED_UNITS = ["days", "weeks", "months", "quarters", "years"]
MAX_COUNT = 999


def parse_value(text):
    """'in:a,b' -> {'op': 'in', 'args': ['a', 'b']}; None when the text is not one of the forms."""
    m = re.match(r"^([a-z_]+):(.*)$", str(text if text is not None else ""), re.S)
    if not m or m.group(1) not in ALL_OPS:
        return None
    op, rest = m.groups()
    if op in NO_ARG:
        return {"op": op, "args": []} if rest == "" else None
    if op == "between":
        p = re.match(r"^(.*)\.\.(.*)$", rest, re.S)
        return {"op": op, "args": [unquote(p.group(1)), unquote(p.group(2))]} if p else None
    if op in LIST_OPS:
        return {"op": op, "args": [unquote(x) for x in rest.split(",")]} if rest else None
    return {"op": op, "args": [unquote(rest)]} if rest else None


def format_value(op, args=()):
    enc = lambda s: quote(str(s), safe="-_.!~*'()")        # what encodeURIComponent leaves alone
    if op in NO_ARG:
        return f"{op}:"
    if op == "between":
        return f"between:{enc(args[0])}..{enc(args[1])}"
    return f"{op}:{','.join(enc(a) for a in args)}"


# ---- dates (the arithmetic is on calendar days; no clock is involved)
def _add_months(d, n):
    t = d.year * 12 + d.month - 1 + n
    return date(t // 12, t % 12 + 1, 1)


def _month_start(d):
    return date(d.year, d.month, 1)


def _week_start(d, first):
    return d - timedelta(days=(d.isoweekday() % 7 - first + 7) % 7)        # isoweekday()%7: Sunday 0 .. Saturday 6, like JavaScript's getUTCDay


def _quarter_start(d):
    return date(d.year, (d.month - 1) // 3 * 3 + 1, 1)


def _fiscal_year_start(d, f):
    return date(d.year if d.month >= f else d.year - 1, f, 1)


def _fiscal_quarter_start(d, f):
    s = _fiscal_year_start(d, f)
    months = (d.year - s.year) * 12 + d.month - s.month
    return _add_months(s, months // 3 * 3)


def _units(env):
    first, f = env["weekStart"], env["fiscalStart"]
    q_end = lambda s: _add_months(s, 3) - timedelta(days=1)
    y_end = lambda s: _add_months(s, 12) - timedelta(days=1)
    return {
        "days": (lambda d: d, lambda s, n: s + timedelta(days=n), lambda s: s),
        "weeks": (lambda d: _week_start(d, first), lambda s, n: s + timedelta(days=7 * n), lambda s: s + timedelta(days=6)),
        "months": (_month_start, _add_months, lambda s: _add_months(s, 1) - timedelta(days=1)),
        "quarters": (_quarter_start, lambda s, n: _add_months(s, 3 * n), q_end),
        "years": (lambda d: date(d.year, 1, 1), lambda s, n: _add_months(s, 12 * n), y_end),
        "fiscal_quarters": (lambda d: _fiscal_quarter_start(d, f), lambda s, n: _add_months(s, 3 * n), q_end),
        "fiscal_years": (lambda d: _fiscal_year_start(d, f), lambda s, n: _add_months(s, 12 * n), y_end),
    }


_SINGULAR = {"day": "days", "week": "weeks", "month": "months", "quarter": "quarters", "year": "years", "fiscal_quarter": "fiscal_quarters", "fiscal_year": "fiscal_years"}


def resolve_preset(name, env):
    """{'from', 'to'} (ISO dates, both included), {'all': True} for all_time, None for a name that is not a dynamic date. env: today (a date), weekStart (0 Sunday), fiscalStart (1-12)."""
    today, u = env["today"], _units(env)
    rng = lambda a, b: {"from": a.isoformat(), "to": b.isoformat()}
    if name == "all_time":
        return {"all": True}
    if name in ("today", "yesterday", "tomorrow"):
        d = today + timedelta(days={"today": 0, "yesterday": -1, "tomorrow": 1}[name])
        return rng(d, d)
    m = re.match(r"^(this|last|next)_((?:fiscal_)?(?:week|month|quarter|year))$", name)
    if m:
        start_of, shift, end_of = u[_SINGULAR[m.group(2)]]
        s = shift(start_of(today), {"this": 0, "last": -1, "next": 1}[m.group(1)])
        return rng(s, end_of(s))
    m = re.match(r"^((?:fiscal_)?(?:week|month|quarter|year))_to_date$", name)
    if m:
        return rng(u[_SINGULAR[m.group(1)]][0](today), today)
    m = re.match(r"^(last|next|past)_(\d{1,3})_(days|weeks|months|quarters|years)$", name)
    if m:
        n = int(m.group(2))
        if n < 1 or n > MAX_COUNT:
            return None
        start_of, shift, end_of = u[m.group(3)]
        here = start_of(today)
        if m.group(1) == "last":
            return rng(shift(here, -n), end_of(shift(here, -1)))
        if m.group(1) == "next":
            return rng(shift(here, 1), end_of(shift(here, n)))
        return rng(shift(here, -(n - 1)), today)
    return None


# ---- Cube filters
_NUMBER, _DATE = re.compile(r"^-?\d+(\.\d+)?$"), re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _flt(member, operator, values=None):
    return {"member": member, "operator": operator} if values is None else {"member": member, "operator": operator, "values": values}


def _num(s):
    n = float(s)
    return str(int(n)) if n == int(n) else repr(n)             # JavaScript's String(Number(s))


def to_cube(flt, text, env):
    """The Cube filters a filter's value stands for ([] when it narrows nothing, or the value is empty or not understood)."""
    member, typ = flt["dimension"], flt.get("type", "select")
    if text is None or text == "":
        return []
    if typ == "select":
        return [_flt(member, "equals", [str(text)])]
    v = parse_value(text)
    if v is None or v["op"] not in OPS.get(typ, []):
        return []
    op, args = v["op"], v["args"]
    a = args[0] if args else None
    simple = {"in": ("equals", args), "not": ("notEquals", args), "contains": ("contains", [a]), "not_contains": ("notContains", [a]),
              "starts": ("startsWith", [a]), "ends": ("endsWith", [a])}
    if op in simple:
        return [_flt(member, simple[op][0], simple[op][1])]
    if op == "set":
        return [_flt(member, "set")]
    if op == "unset":
        return [_flt(member, "notSet")]
    if typ == "number":
        if not all(_NUMBER.match(x) for x in args):
            return []
        one = {"eq": "equals", "ne": "notEquals", "gt": "gt", "gte": "gte", "lt": "lt", "lte": "lte"}.get(op)
        if one:
            return [_flt(member, one, [_num(a)])]
        return [_flt(member, "gte", [_num(a)]), _flt(member, "lte", [_num(args[1])])] if float(a) <= float(args[1]) else []
    if typ == "date":
        if op == "rel":
            r = resolve_preset(a, env)
            return [] if r is None or r.get("all") else [_flt(member, "inDateRange", [r["from"], r["to"]])]
        if not all(_DATE.match(x) for x in args):
            return []
        if op == "between":
            return [_flt(member, "inDateRange", [a, args[1]])] if a <= args[1] else []
        one = {"on": "inDateRange", "after": "afterDate", "on_or_after": "afterOrOnDate", "before": "beforeDate", "on_or_before": "beforeOrOnDate"}[op]
        return [_flt(member, one, [a, a] if op == "on" else [a])]
    return []


_SUNDAY_FIRST = {"US", "CA", "MX", "BR", "IN", "JP"}


def default_env(spec, today=None):
    """The calendar a page's dynamic dates use. The browser asks its locale data for the first day of the week; this table is its fallback and what the lint uses."""
    region = (spec.get("locale") or "en-US").partition("-")[2]
    return {"today": today or date.today(), "weekStart": 0 if region in _SUNDAY_FIRST else 1, "fiscalStart": spec.get("time", {}).get("fiscal_year_start", 1)}
