"""Key figures compared with the previous period: the Python mirror (dashspec/compare.py) against the renderer's own code (dashboard/static/lib/compare.js),
and the comparison queries in the KPI panel's query list.

  PYTHONPATH=dashboards uv run --with pytest python -m pytest dashboards/tests/test_compare.py -q
"""
import json
import pathlib
import shutil
import subprocess

import pytest

from dashspec import compare as C
from dashspec.queries import panel_queries

REPO = pathlib.Path(__file__).resolve().parents[2]


# ---- date ranges
@pytest.mark.parametrize("rng,kind,expected", [
    (["2021-03-01", "2021-03-31"], "previous_year", ["2020-03-01", "2020-03-31"]),
    (["2024-02-01", "2024-02-29"], "previous_year", ["2023-02-01", "2023-02-28"]),          # a leap February: the last day stays the last day
    (["2025-02-01", "2025-02-28"], "previous_year", ["2024-02-01", "2024-02-29"]),
    (["2024-02-29", "2024-03-10"], "previous_year", ["2023-02-28", "2023-03-10"]),
    (["2021-03-01", "2021-03-31"], "previous_period", ["2021-02-01", "2021-02-28"]),        # a whole month: the month before
    (["2021-01-01", "2021-03-31"], "previous_period", ["2020-10-01", "2020-12-31"]),        # a quarter: the quarter before
    (["2020-07-01", "2021-06-30"], "previous_period", ["2019-07-01", "2020-06-30"]),        # a fiscal year
    (["2021-03-31", "2021-03-31"], "previous_period", ["2021-03-30", "2021-03-30"]),        # one day: the day before
    (["2021-03-10", "2021-03-16"], "previous_period", ["2021-03-03", "2021-03-09"]),        # a week
    (["2021-03-01", "2021-03-15"], "previous_period", ["2021-02-14", "2021-02-28"]),        # half a month: by days
    (["2021-03-31", "2021-03-01"], "previous_year", None),                                  # backwards
    (["2021-03-01T00:00:00", "2021-03-31"], "previous_year", None),
    (["2021-03-01"], "previous_year", None),
])
def test_ranges_move_back(rng, kind, expected):
    assert C.shift_range(rng, kind) == expected


@pytest.mark.parametrize("values,kind,expected", [
    (["2021"], "previous_year", ["2020"]),
    ([2021], "previous_year", ["2020"]),
    (["2021", "2022"], "previous_year", ["2020", "2021"]),
    (["2021"], "previous_period", ["2020"]),
    (["2021", "2022"], "previous_period", ["2019", "2020"]),
    (["2022", "2021", "2023"], "previous_period", ["2019", "2018", "2020"]),
    (["2021", "2023"], "previous_period", None),                                            # not consecutive
    (["2021", "2021"], "previous_period", None),
    (["FY21"], "previous_year", None),
    ([], "previous_year", None),
])
def test_years_move_back(values, kind, expected):
    assert C.shift_years(values, kind) == expected


# ---- a whole query
FY = {"member": "dates.fiscal_year", "operator": "equals", "values": ["2021"]}
REGION = {"member": "territories.region", "operator": "equals", "values": ["Canada"]}


def test_a_fiscal_year_select_moves_one_year_and_names_it():
    s = C.shift_query({"measures": ["a.revenue"], "filters": [FY, REGION]}, "previous_year")
    assert s["query"] == {"measures": ["a.revenue"], "filters": [{**FY, "values": ["2020"]}, REGION]}
    assert C.compare_label(s["moved"], "previous_year") == {"year": "2020", "fiscal": True}


def test_the_drill_period_and_a_date_filter_both_move():
    q = {"measures": ["a.revenue"], "filters": [{"member": "a.ship_date", "operator": "inDateRange", "values": ["2021-01-01", "2021-12-31"]}],
         "timeDimensions": [{"dimension": "dates.full_date", "dateRange": ["2021-03-01", "2021-03-31"]}]}
    s = C.shift_query(q, "previous_period")
    assert s["query"]["filters"][0]["values"] == ["2020-01-01", "2020-12-31"]
    assert s["query"]["timeDimensions"][0]["dateRange"] == ["2021-02-01", "2021-02-28"]
    assert C.compare_label(s["moved"], "previous_period") == {"kind": "previous_period"}


@pytest.mark.parametrize("filters", [
    [REGION],                                                                                 # no period: all time
    [],
    [FY, {"member": "dates.full_date", "operator": "beforeDate", "values": ["2021-01-01"]}],   # an open range
    [{**FY, "operator": "notEquals"}],
    [{**FY, "operator": "gte"}],
    [{**FY, "values": ["x"]}],
])
def test_no_comparison_without_a_period_that_can_move(filters):
    assert C.shift_query({"measures": ["a.revenue"], "filters": filters}, "previous_year") is None


def test_set_on_a_year_field_is_not_a_period():
    assert C.shift_query({"measures": ["a.x"], "filters": [{"member": "dates.calendar_year", "operator": "set"}]}, "previous_year") is None


def test_an_unknown_kind_compares_nothing():
    assert C.shift_query({"measures": ["a.x"], "filters": [FY]}, "previous_week") is None
    assert C.previous_queries([{"cube": "a", "query": {"filters": [FY]}}], None) is None


def test_queries_of_several_cubes_name_what_moved_once():
    qs = [{"cube": c, "query": {"measures": [f"{c}.revenue"], "filters": [FY]}} for c in ("a", "b")]
    p = C.previous_queries(qs, "previous_year")
    assert [q["query"]["filters"][0]["values"] for q in p["queries"]] == [["2020"], ["2020"]]
    assert p["moved"] == [{"member": "dates.fiscal_year", "from": ["2021"], "to": ["2020"]}]


# ---- the panel's queries
def _spec(compare="previous_year"):
    return {"time": {"dimension": "dates.full_date"}, "members": {}, "filters": [{"id": "fy", "dimension": "dates.fiscal_year"}],
            "panels": [], "_panel": {"id": "k", "type": "kpi", "measures": [{"member": "a.revenue"}], **({"compare": compare} if compare else {})}}


def test_a_compared_kpi_sends_the_previous_period_too_and_only_when_there_is_one():
    spec = _spec()
    panel = spec["_panel"]
    assert len(panel_queries(spec, panel, {})) == 1
    qs = panel_queries(spec, panel, {"fy": "2021"})
    assert [q["query"]["filters"][0]["values"] for q in qs] == [["2021"], ["2020"]]
    plain = _spec(None)
    assert len(panel_queries(plain, plain["_panel"], {"fy": "2021"})) == 1


# ---- the browser's code gives the same answers
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_python_mirror_equals_the_renderers_code():
    ranges = [["2021-03-01", "2021-03-31"], ["2024-02-01", "2024-02-29"], ["2025-02-28", "2025-03-01"], ["2021-01-01", "2021-03-31"], ["2020-07-01", "2021-06-30"],
              ["2021-03-10", "2021-03-16"], ["2024-02-29", "2024-02-29"], ["2021-12-31", "2022-01-01"], ["2000-01-31", "2000-02-29"], ["2021-03-31", "2021-03-01"], ["bad", "2021-01-01"]]
    years = [["2021"], ["2021", "2022"], ["2023", "2021", "2022"], ["2021", "2023"], ["x"], ["2021", "2021"]]
    filters = [[], [REGION], [FY, REGION]]
    filters += [[{"member": "dates.fiscal_year", "operator": op, "values": ys}] for ys in years for op in ("equals", "notEquals")]
    filters += [[{"member": "dates.full_date", "operator": op, "values": r}] for r in ranges for op in ("inDateRange", "beforeDate")]
    filters += [[{"member": "ship_dates.calendar_year", "operator": "equals", "values": ["2021"]}, {"member": "dates.calendar_year", "operator": "set"}]]
    cases = []
    for kind in ("previous_year", "previous_period", "nope"):
        for f in filters:
            cases.append({"query": {"measures": ["a.x"], "filters": f}, "kind": kind})
            for r in ranges[:4]:
                cases.append({"query": {"measures": ["a.x"], "filters": f, "timeDimensions": [{"dimension": "dates.full_date", "dateRange": r}]}, "kind": kind})
        cases.append({"query": {"measures": ["a.x"], "timeDimensions": [{"dimension": "dates.full_date", "granularity": "month"}]}, "kind": kind})
    out = subprocess.run(["node", str(REPO / "dashboards" / "tests" / "dump_compare.mjs")], input=json.dumps(cases), capture_output=True, text=True, check=True).stdout
    js = json.loads(out)
    assert len(js) == len(cases) > 300
    for case, got in zip(cases, js, strict=True):
        s = C.shift_query(case["query"], case["kind"])
        assert got == (s and {**s, "label": C.compare_label(s["moved"], case["kind"])}), case
