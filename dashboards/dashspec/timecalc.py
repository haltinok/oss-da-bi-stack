"""The queries behind a calculation's prior() and rolling(): a Python mirror of dashboard/static/lib/timecalc.js (the renderer's source of truth), so `dashspec lint`
sees them. dashboards/tests/test_timecalc.py runs both on a table of cases."""
import math
import re
from datetime import date

from .calculations import time_calls
from .compare import add_days, add_months, is_range, is_year_field, shift_query

PRIOR_UNITS = ("year", "quarter", "month", "week", "day")
ROLLING_GRANULARITIES = ("year", "quarter", "month", "week", "day")
_INT = re.compile(r"^-?\d+$")


def prior_shift(unit, granularity):
    """How far prior(., unit) moves on a panel grouped by `granularity` (None: no time axis); a year on a weekly axis is 52 weeks."""
    if unit == "year":
        return {"days": 364} if granularity == "week" else {"months": 12, "years": 1}
    return {"quarter": {"months": 3}, "month": {"months": 1}, "week": {"days": 7}, "day": {"days": 1}}[unit]


def bucket_start(s, granularity):
    y, m, _ = map(int, s.split("-"))
    if granularity == "week":
        return add_days(s, -date.fromisoformat(s).weekday())
    if granularity == "month":
        return f"{s[:7]}-01"
    if granularity == "quarter":
        return f"{y:04d}-{(m - 1) // 3 * 3 + 1:02d}-01"
    if granularity == "year":
        return f"{s[:4]}-01-01"
    return s


def buckets_back(s, k, granularity):
    if granularity == "week":
        return add_days(s, -7 * k)
    if granularity == "month":
        return add_months(s, -k)
    if granularity == "quarter":
        return add_months(s, -3 * k)
    if granularity == "year":
        return add_months(s, -12 * k)
    return add_days(s, -k)


def years_back(k, granularity):
    if granularity == "month":
        return math.ceil(k / 12)
    if granularity == "quarter":
        return math.ceil(k / 4)
    if granularity == "year":
        return k
    return (7 * k if granularity == "week" else k) // 365 + 1


def widen_query(query, n, year_fields=None):
    """{ query, widened } or None (see widenQuery in timecalc.js)."""
    axis = next((t for t in query.get("timeDimensions", []) if t.get("granularity")), None)
    if axis is None or axis["granularity"] not in ROLLING_GRANULARITIES or n < 2:
        return None
    gran, k, widened = axis["granularity"], n - 1, []

    def widen(member, rng):
        to = [buckets_back(bucket_start(rng[0], gran), k, gran), rng[1]]
        widened.append({"member": member, "from": list(rng), "to": to})
        return to

    tds = [{**t, "dateRange": widen(t["dimension"], t["dateRange"])} if t["dimension"] == axis["dimension"] and is_range(t.get("dateRange")) else t
           for t in query["timeDimensions"]]
    filters = []
    for f in query.get("filters", []):
        if f.get("operator") == "inDateRange" and f.get("member") == axis["dimension"] and is_range(f.get("values")):
            f = {**f, "values": widen(f["member"], f["values"])}
        elif f.get("operator") == "equals" and is_year_field(f.get("member"), year_fields) and f.get("values") and all(_INT.match(str(v)) for v in f["values"]):
            back = years_back(k, gran)
            to = [str(y) for y in sorted({int(v) - j for v in f["values"] for j in range(back + 1)})]
            widened.append({"member": f["member"], "from": [str(v) for v in f["values"]], "to": to})
            f = {**f, "values": to}
        filters.append(f)
    if not widened:
        return None
    out = {**query, "timeDimensions": tds}
    if "filters" in query:
        out["filters"] = filters
    return {"query": out, "widened": widened}


def with_time_calcs(queries, year_fields=None):
    """A panel's queries with what prior() and rolling() need (see withTimeCalcs in timecalc.js)."""
    out = []
    for q in queries:
        calcs = (q.get("post") or {}).get("calcs")
        calls = time_calls(list(calcs.values())) if calcs else None
        if not calls or (not calls["prior"] and not calls["rolling"]):
            out.append(q)
            continue
        measures = q["query"].get("measures", [])
        gran = next((t["granularity"] for t in q["query"].get("timeDimensions", []) if t.get("granularity")), None)
        ns = [n for m in measures for n in calls["rolling"].get(m, [])]
        w = widen_query(q["query"], max(ns), year_fields) if ns and gran else None
        out.append({**q, "query": w["query"], "widened": w["widened"]} if w else q)
        for unit in PRIOR_UNITS:
            read = [m for m in measures if m in calls["prior"].get(unit, [])]
            if not read:
                continue
            s = shift_query({**q["query"], "measures": read}, prior_shift(unit, gran), year_fields)
            if s:
                out.append({**q, "query": s["query"], "prior": unit})
    return out
