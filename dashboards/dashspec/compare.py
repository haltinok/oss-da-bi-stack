"""A key figure's comparison with the previous period: a Python mirror of dashboard/static/lib/compare.js (the renderer's source of truth).
`panel_queries` uses it so `dashspec lint` sees the comparison queries; dashboards/tests/test_compare.py runs both on a table of cases."""
import json
import re
from calendar import monthrange
from datetime import date, timedelta

COMPARE_KINDS = ("previous_year", "previous_period")
YEAR_FIELDS = ("fiscal_year", "calendar_year")
OPEN = ("beforeDate", "afterDate", "beforeOrOnDate", "afterOrOnDate", "notInDateRange")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INT = re.compile(r"^-?\d+$")


def _days_in(y, m):
    return monthrange(y, m)[1]


def add_months(s, n, keep_end=False):
    y, m, d = map(int, s.split("-"))
    k = y * 12 + (m - 1) + n
    ty, tm = k // 12, k % 12 + 1
    last = _days_in(ty, tm)
    return f"{ty:04d}-{tm:02d}-{last if keep_end and d == _days_in(y, m) else min(d, last):02d}"


def shift_range(rng, kind):
    if not isinstance(rng, list) or len(rng) != 2 or not all(isinstance(s, str) and _ISO.match(s) for s in rng):
        return None
    a, b = rng
    if a > b:
        return None
    if kind == "previous_year":
        return [add_months(a, -12), add_months(b, -12, True)]
    ay, am, ad = map(int, a.split("-"))
    by, bm, bd = map(int, b.split("-"))
    if ad == 1 and bd == _days_in(by, bm):
        n = (by * 12 + bm) - (ay * 12 + am) + 1
        return [add_months(a, -n), add_months(b, -n, True)]
    da, db = date.fromisoformat(a), date.fromisoformat(b)
    length = (db - da).days + 1
    return [(da - timedelta(days=length)).isoformat(), (da - timedelta(days=1)).isoformat()]


def shift_years(values, kind):
    if not values or not all(_INT.match(str(v)) for v in values):
        return None
    ys = [int(v) for v in values]
    by = 1
    if kind == "previous_period" and len(ys) > 1:
        s = sorted(set(ys))
        if len(s) != len(ys) or any(s[i] != s[i - 1] + 1 for i in range(1, len(s))):
            return None
        by = len(s)
    return [str(y - by) for y in ys]


def is_year_field(member):
    return str(member).partition(".")[2] in YEAR_FIELDS


def shift_query(query, kind):
    """{ query, moved } or None (see shiftQuery in compare.js)."""
    if kind not in COMPARE_KINDS:
        return None
    moved, ok = [], True
    filters = []
    for f in query.get("filters", []):
        op = f.get("operator")
        if op in OPEN:
            ok = False
        elif op == "inDateRange":
            to = shift_range(f.get("values"), kind)
            if to is None:
                ok = False
            else:
                moved.append({"member": f["member"], "from": list(f["values"]), "to": to})
                f = {**f, "values": to}
        elif is_year_field(f.get("member")) and op not in ("set", "notSet"):
            to = shift_years(f.get("values"), kind) if op == "equals" else None
            if to is None:
                ok = False
            else:
                moved.append({"member": f["member"], "from": [str(v) for v in f["values"]], "to": to})
                f = {**f, "values": to}
        filters.append(f)
    tds = []
    for t in query.get("timeDimensions", []):
        if t.get("dateRange") is not None:
            to = shift_range(t["dateRange"], kind)
            if to is None:
                ok = False
            else:
                moved.append({"member": t["dimension"], "from": list(t["dateRange"]), "to": to})
                t = {**t, "dateRange": to}
        tds.append(t)
    if not ok or not moved:
        return None
    out = dict(query)
    if "filters" in query:
        out["filters"] = filters
    if "timeDimensions" in query:
        out["timeDimensions"] = tds
    return {"query": out, "moved": moved}


def previous_queries(queries, kind):
    """{ queries, moved } or None (see previousQueries in compare.js)."""
    if not kind or not queries:
        return None
    out, moved, seen = [], [], set()
    for q in queries:
        s = shift_query(q["query"], kind)
        if s is None:
            return None
        out.append({**q, "query": s["query"]})
        for m in s["moved"]:
            key = json.dumps([m["member"], m["from"], m["to"]])
            if key not in seen:
                seen.add(key)
                moved.append(m)
    return {"queries": out, "moved": moved}


def compare_label(moved, kind):
    if len(moved) == 1 and is_year_field(moved[0]["member"]) and len(moved[0]["to"]) == 1:
        return {"year": moved[0]["to"][0], "fiscal": moved[0]["member"].endswith(".fiscal_year")}
    return {"kind": kind}
