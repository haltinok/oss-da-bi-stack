"""Filter values and dynamic dates: the Python mirror (dashspec/filters.py) against the renderer's own code (dashboard/static/lib/filters.js).

  PYTHONPATH=dashboards uv run --with pytest python -m pytest dashboards/tests/test_filters.py -q
"""
import itertools
import json
import pathlib
import shutil
import subprocess
from datetime import date

import pytest

from dashspec import filters as F

REPO = pathlib.Path(__file__).resolve().parents[2]
MEMBER = "a.dim"


def env(today, week=1, fiscal=7):
    return {"today": today, "weekStart": week, "fiscalStart": fiscal}


# ---- the values themselves
@pytest.mark.parametrize("text,expected", [
    ("in:a,b", {"op": "in", "args": ["a", "b"]}),
    ("in:Smith%2C%20John,Lee", {"op": "in", "args": ["Smith, John", "Lee"]}),
    ("not:x", {"op": "not", "args": ["x"]}),
    ("between:10..20", {"op": "between", "args": ["10", "20"]}),
    ("between:2024-01-01..2024-03-31", {"op": "between", "args": ["2024-01-01", "2024-03-31"]}),
    ("contains:bike", {"op": "contains", "args": ["bike"]}),
    ("rel:last_30_days", {"op": "rel", "args": ["last_30_days"]}),
    ("set:", {"op": "set", "args": []}),
    ("unset:", {"op": "unset", "args": []}),
])
def test_values_parse(text, expected):
    assert F.parse_value(text) == expected


@pytest.mark.parametrize("text", ["Bikes", "", None, "bogus:1", "in:", "between:5", "set:x", "gte:", "rel:"])
def test_text_that_is_not_a_value_parses_to_nothing(text):
    assert F.parse_value(text) is None


def test_format_is_the_inverse_of_parse():
    for text in ["in:a,b", "in:Smith%2C%20John", "not:x%3Ay", "between:10..20", "gte:5", "unset:", "rel:last_7_days", "contains:a%2Fb"]:
        v = F.parse_value(text)
        assert F.format_value(v["op"], v["args"]) == text, text


# ---- dynamic dates, by hand
@pytest.mark.parametrize("name,today,week,fiscal,expected", [
    ("today", date(2024, 3, 15), 1, 7, ("2024-03-15", "2024-03-15")),
    ("yesterday", date(2024, 3, 1), 1, 7, ("2024-02-29", "2024-02-29")),                  # a leap day
    ("this_week", date(2024, 3, 15), 1, 7, ("2024-03-11", "2024-03-17")),                  # Monday start
    ("this_week", date(2024, 3, 15), 0, 7, ("2024-03-10", "2024-03-16")),                  # Sunday start
    ("last_week", date(2024, 3, 11), 1, 7, ("2024-03-04", "2024-03-10")),
    ("last_month", date(2024, 3, 31), 1, 7, ("2024-02-01", "2024-02-29")),
    ("last_month", date(2024, 1, 5), 1, 7, ("2023-12-01", "2023-12-31")),                  # across a year
    ("next_month", date(2024, 12, 31), 1, 7, ("2025-01-01", "2025-01-31")),
    ("this_quarter", date(2024, 5, 20), 1, 7, ("2024-04-01", "2024-06-30")),
    ("last_quarter", date(2024, 1, 2), 1, 7, ("2023-10-01", "2023-12-31")),
    ("year_to_date", date(2024, 3, 15), 1, 7, ("2024-01-01", "2024-03-15")),
    ("last_year", date(2024, 3, 15), 1, 7, ("2023-01-01", "2023-12-31")),
    ("this_fiscal_year", date(2024, 3, 15), 1, 7, ("2023-07-01", "2024-06-30")),
    ("this_fiscal_year", date(2024, 8, 1), 1, 7, ("2024-07-01", "2025-06-30")),
    ("last_fiscal_year", date(2024, 3, 15), 1, 7, ("2022-07-01", "2023-06-30")),
    ("this_fiscal_year", date(2024, 3, 15), 1, 1, ("2024-01-01", "2024-12-31")),            # a fiscal year that starts in January is the calendar year
    ("fiscal_year_to_date", date(2024, 3, 15), 1, 7, ("2023-07-01", "2024-03-15")),
    ("this_fiscal_quarter", date(2024, 3, 15), 1, 7, ("2024-01-01", "2024-03-31")),
    ("last_fiscal_quarter", date(2024, 3, 15), 1, 7, ("2023-10-01", "2023-12-31")),
    ("last_30_days", date(2024, 3, 15), 1, 7, ("2024-02-14", "2024-03-14")),                # complete days before today
    ("past_7_days", date(2024, 3, 15), 1, 7, ("2024-03-09", "2024-03-15")),                 # ending today
    ("next_2_weeks", date(2024, 3, 15), 1, 7, ("2024-03-18", "2024-03-31")),
    ("last_3_months", date(2024, 3, 15), 1, 7, ("2023-12-01", "2024-02-29")),
    ("past_2_months", date(2024, 3, 15), 1, 7, ("2024-02-01", "2024-03-15")),
    ("last_2_years", date(2024, 3, 15), 1, 7, ("2022-01-01", "2023-12-31")),
])
def test_dynamic_dates(name, today, week, fiscal, expected):
    r = F.resolve_preset(name, env(today, week, fiscal))
    assert (r["from"], r["to"]) == expected


def test_all_time_and_bad_names():
    e = env(date(2024, 3, 15))
    assert F.resolve_preset("all_time", e) == {"all": True}
    for bad in ["last_0_days", "last_1000_days", "last_5_hours", "bogus", "", "this_decade", "last_-1_days"]:
        assert F.resolve_preset(bad, e) is None, bad


def test_every_fixed_name_resolves_and_every_range_is_in_order():
    for today, week, fiscal in itertools.product([date(2024, 2, 29), date(2023, 12, 31), date(2024, 1, 1), date(2025, 6, 30)], [0, 1], [1, 4, 7, 10]):
        for name in [*F.FIXED_PRESETS, *(f"{p}_{n}_{u}" for p in ("last", "next", "past") for n in (1, 7, 30, 999) for u in F.COUNTED_UNITS)]:
            r = F.resolve_preset(name, env(today, week, fiscal))
            assert r is not None, name
            assert r.get("all") or r["from"] <= r["to"], (name, today, r)


# ---- Cube filters, by hand
def test_select_keeps_sending_one_equals_exactly_as_before():
    assert F.to_cube({"dimension": MEMBER}, "Bikes", env(date(2024, 1, 1))) == [{"member": MEMBER, "operator": "equals", "values": ["Bikes"]}]
    assert F.to_cube({"dimension": MEMBER, "type": "select"}, "in:A", env(date(2024, 1, 1))) == [{"member": MEMBER, "operator": "equals", "values": ["in:A"]}], "a select never reads a prefix"


@pytest.mark.parametrize("typ,text,expected", [
    ("multiselect", "in:A,B", [("equals", ["A", "B"])]),
    ("multiselect", "not:A", [("notEquals", ["A"])]),
    ("multiselect", "contains:A", []),                                       # an operator this type does not have
    ("text", "contains:bike", [("contains", ["bike"])]),
    ("text", "starts:Mo", [("startsWith", ["Mo"])]),
    ("text", "unset:", [("notSet", None)]),
    ("number", "gte:100", [("gte", ["100"])]),
    ("number", "eq:3.50", [("equals", ["3.5"])]),
    ("number", "between:10..20", [("gte", ["10"]), ("lte", ["20"])]),
    ("number", "between:20..10", []),                                        # backwards: narrows nothing rather than everything
    ("number", "gt:abc", []),
    ("date", "after:2024-01-01", [("afterDate", ["2024-01-01"])]),
    ("date", "on:2024-02-29", [("inDateRange", ["2024-02-29", "2024-02-29"])]),
    ("date", "between:2024-01-01..2024-03-31", [("inDateRange", ["2024-01-01", "2024-03-31"])]),
    ("date", "between:2024-03-31..2024-01-01", []),
    ("date", "after:yesterday", []),
    ("date", "rel:last_month", [("inDateRange", ["2024-02-01", "2024-02-29"])]),
    ("date", "rel:all_time", []),
    ("date", "rel:bogus", []),
    ("number", "after:2024-01-01", []),
])
def test_values_become_cube_filters(typ, text, expected):
    out = F.to_cube({"dimension": MEMBER, "type": typ}, text, env(date(2024, 3, 15)))
    assert out == [{"member": MEMBER, "operator": op, **({"values": v} if v is not None else {})} for op, v in expected]


def test_empty_and_unreadable_values_narrow_nothing():
    for typ in ("select", "multiselect", "text", "number", "date"):
        for text in (None, "", "garbage"):
            if typ == "select" and text == "garbage":
                continue
            assert F.to_cube({"dimension": MEMBER, "type": typ}, text, env(date(2024, 3, 15))) == [], (typ, text)


# ---- the browser's code gives the same answers
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_python_mirror_equals_the_renderers_code():
    cases = []
    texts = {"multiselect": ["in:A,B", "not:Smith%2C%20J"], "text": ["contains:x", "not_contains:x", "starts:x", "ends:x", "set:", "unset:"],
             "number": ["eq:1", "ne:-2.5", "gt:3", "gte:3", "lt:3", "lte:3", "between:1..9", "between:9..1", "gt:x", "eq:1e3"],
             "date": ["between:2024-01-01..2024-02-01", "on:2024-02-29", "after:2024-01-01", "on_or_after:2024-01-01", "before:2024-01-01", "on_or_before:2024-01-01", "set:", "unset:", "after:nope"],
             "select": ["Bikes", "in:A"]}
    presets = [*F.FIXED_PRESETS, *(f"{p}_{n}_{u}" for p in ("last", "next", "past") for n in (1, 2, 30, 365) for u in F.COUNTED_UNITS), "last_0_days", "bogus", "last_1000_days"]
    texts["date"] += [f"rel:{p}" for p in presets]
    for today, week, fiscal in [(date(2024, 2, 29), 1, 7), (date(2023, 12, 31), 0, 1), (date(2025, 1, 1), 1, 4), (date(2024, 7, 1), 0, 7), (date(2024, 12, 31), 1, 10)]:
        for typ, ts in texts.items():
            for t in ts:
                cases.append({"filter": {"dimension": MEMBER, "type": typ}, "text": t, "env": {"today": today.isoformat(), "weekStart": week, "fiscalStart": fiscal}})
    out = subprocess.run(["node", str(REPO / "dashboards" / "tests" / "dump_filters.mjs")], input=json.dumps(cases), capture_output=True, text=True, check=True).stdout
    js = json.loads(out)
    assert len(js) == len(cases) > 500
    for case, got in zip(cases, js, strict=True):
        e = {**case["env"], "today": date.fromisoformat(case["env"]["today"])}
        assert got["cube"] == F.to_cube(case["filter"], case["text"], e), case
        if got["preset"] is not None or case["text"].startswith("rel:"):
            assert got["preset"] == F.resolve_preset(F.parse_value(case["text"])["args"][0], e), case
