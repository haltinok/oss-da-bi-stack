"""prior() and rolling() in calculations: the formula, the validator's rules, and the queries they add, the Python mirror (dashspec/timecalc.py, the fixed shifts of
dashspec/compare.py) against the renderer's own code (dashboard/static/lib/timecalc.js, lib/compare.js).

  PYTHONPATH=dashboards uv run --with pytest python -m pytest dashboards/tests/test_timecalc.py -q
"""
import copy
import json
import pathlib
import shutil
import subprocess

import pytest
import yaml

from dashspec import calculations as calc
from dashspec import catalog as cat
from dashspec import compare as C
from dashspec import timecalc as T
from dashspec.compile import compile_spec
from dashspec.queries import panel_queries
from dashspec.validate import validate

REPO = pathlib.Path(__file__).resolve().parents[2]
YEAR = {"fiscal": ["dates.fiscal_year", "ship_dates.fiscal_year"], "calendar": ["dates.calendar_year", "ship_dates.calendar_year"]}
GOOD = yaml.safe_load((REPO / "dashboards" / "sales-overview.yml").read_text())
CATALOG = cat.from_model(REPO / "cube" / "model")
FY = {"member": "dates.fiscal_year", "operator": "equals", "values": ["2021"]}
REGION = {"member": "territories.region", "operator": "equals", "values": ["Canada"]}
MARCH = ["2021-03-01", "2021-03-31"]


# ---- the formula
def test_prior_and_rolling_read_into_the_tree_and_name_their_measures():
    tree = calc.parse("(a.revenue - prior(a.revenue, year)) / prior(a.revenue, year) + rolling(b.units, 12) / 12")
    assert calc.members_of(tree) == ["a.revenue", "b.units"]
    assert calc.time_calls([tree]) == {"prior": {"year": ["a.revenue"]}, "rolling": {"b.units": [12]}}
    row = {"a.revenue": 110, calc.prior_key("year", "a.revenue"): 100, calc.rolling_key(12, "b.units"): 24}
    assert calc.evaluate(tree, row.get) == pytest.approx(2.1)
    assert calc.evaluate(calc.parse("a.x / prior(a.x, month) - 1"), {"a.x": 5}.get) is None, "no earlier value: no value"
    assert calc.evaluate(calc.parse("rolling(a.x, 3) / rolling(a.y, 3)"), {"rolling:3:a.x": 6, "rolling:3:a.y": 3}.get) == 2


@pytest.mark.parametrize("bad,says", [
    ("prior(a.x, decade)", "prior(...) moves by year, quarter, month, week, day, not 'decade'"),
    ("prior(a.x, 2)", "prior(...) moves by"),
    ("prior(a.x)", "expected ','"),
    ("prior(a.x + a.y, year)", "expected ','"),
    ("prior(revenue, year)", "reads one measure of the model"),
    ("prior(calc.tax, year)", "reads one measure of the model"),
    ("prior(prior(a.x, year), year)", "reads one measure of the model"),
    ("rolling(a.x, 1)", "2 to 36, not '1'"),
    ("rolling(a.x, 37)", "2 to 36"),
    ("rolling(a.x, 2.5)", "2 to 36"),
    ("rolling(a.x, month)", "2 to 36"),
    ("rolling(a.x, 3", "expected ')'"),
])
def test_a_wrong_prior_or_rolling_says_how_to_write_it(bad, says):
    with pytest.raises(calc.FormulaError) as e:
        calc.parse(bad)
    assert says in str(e.value)


# ---- shifting and widening
@pytest.mark.parametrize("rng,shift,expected", [
    (MARCH, {"months": 1}, ["2021-02-01", "2021-02-28"]),
    (MARCH, {"months": 3}, ["2020-12-01", "2020-12-31"]),
    (["2024-02-01", "2024-02-29"], {"months": 12, "years": 1}, ["2023-02-01", "2023-02-28"]),
    (["2021-03-15", "2021-03-21"], {"days": 364}, ["2020-03-16", "2020-03-22"]),          # 52 weeks: a Monday stays a Monday
    (["2021-03-15", "2021-03-21"], {"days": 7}, ["2021-03-08", "2021-03-14"]),
])
def test_a_fixed_shift_moves_a_range(rng, shift, expected):
    assert C.shift_range(rng, shift) == expected


def test_a_fixed_shift_moves_a_year_value_only_by_whole_years():
    assert C.shift_years(["2021", "2022"], {"months": 12, "years": 1}) == ["2020", "2021"]
    assert C.shift_years(["2021"], {"months": 1}) is None
    assert C.shift_query({"measures": ["a.x"], "filters": [FY, REGION]}, {"months": 12, "years": 1}, YEAR)["query"]["filters"] == [{**FY, "values": ["2020"]}, REGION]
    assert C.shift_query({"measures": ["a.x"], "filters": [FY]}, {"months": 1}, YEAR) is None, "a month back from a fiscal year select cannot be written as a year select"


@pytest.mark.parametrize("s,gran,expected", [
    ("2021-03-17", "day", "2021-03-17"), ("2021-03-17", "week", "2021-03-15"), ("2021-03-15", "week", "2021-03-15"), ("2021-01-03", "week", "2020-12-28"),
    ("2021-03-17", "month", "2021-03-01"), ("2021-08-17", "quarter", "2021-07-01"), ("2021-03-17", "year", "2021-01-01"),
])
def test_a_date_falls_in_a_bucket(s, gran, expected):
    assert T.bucket_start(s, gran) == expected


def _axis(gran, rng=None):
    return [{"dimension": "dates.full_date", "granularity": gran, **({"dateRange": rng} if rng else {})}]


@pytest.mark.parametrize("query,n,expected", [
    ({"measures": ["a.x"], "timeDimensions": _axis("month", MARCH)}, 3, ["2021-01-01", "2021-03-31"]),
    ({"measures": ["a.x"], "timeDimensions": _axis("month", ["2021-03-15", "2021-04-10"])}, 3, ["2021-01-01", "2021-04-10"]),
    ({"measures": ["a.x"], "timeDimensions": _axis("quarter", ["2021-04-01", "2021-06-30"])}, 4, ["2020-07-01", "2021-06-30"]),
    ({"measures": ["a.x"], "timeDimensions": _axis("week", ["2021-03-17", "2021-03-31"])}, 2, ["2021-03-08", "2021-03-31"]),
    ({"measures": ["a.x"], "timeDimensions": _axis("day", MARCH)}, 7, ["2021-02-23", "2021-03-31"]),
])
def test_rolling_widens_the_range_of_the_time_axis(query, n, expected):
    w = T.widen_query(query, n, YEAR)
    assert w["query"]["timeDimensions"][0]["dateRange"] == expected
    assert w["widened"] == [{"member": "dates.full_date", "from": query["timeDimensions"][0]["dateRange"], "to": expected}]


@pytest.mark.parametrize("n,years", [(12, ["2020", "2021"]), (13, ["2020", "2021"]), (25, ["2019", "2020", "2021"]), (2, ["2020", "2021"])])
def test_rolling_takes_in_the_years_a_window_reaches(n, years):
    w = T.widen_query({"measures": ["a.x"], "timeDimensions": _axis("month"), "filters": [FY, REGION]}, n, YEAR)
    assert w["query"]["filters"] == [{**FY, "values": years}, REGION]


@pytest.mark.parametrize("query", [
    {"measures": ["a.x"], "timeDimensions": _axis("month")},                                            # all time: nothing to widen
    {"measures": ["a.x"], "filters": [FY]},                                                              # no time axis
    {"measures": ["a.x"], "timeDimensions": _axis("hour", MARCH)},
    {"measures": ["a.x"], "timeDimensions": _axis("month"), "filters": [{"member": "dates.full_date", "operator": "afterDate", "values": ["2021-01-01"]}]},
])
def test_rolling_widens_nothing_without_a_bounded_time_axis(query):
    assert T.widen_query(query, 3, YEAR) is None


def _post(**formulas):
    return {"calcs": {f"calc.{k}": calc.parse(v) for k, v in formulas.items()}}


def test_a_panels_queries_gain_the_widened_and_the_moved_ones():
    q = {"cube": "a", "query": {"measures": ["a.x", "a.y"], "timeDimensions": _axis("month", MARCH), "filters": [REGION]}, "post": _post(yoy="a.x / prior(a.x, year) - 1", r="rolling(a.y, 3)")}
    out = T.with_time_calcs([q], YEAR)
    assert [x.get("prior") for x in out] == [None, "year"]
    assert out[0]["query"]["timeDimensions"][0]["dateRange"] == ["2021-01-01", "2021-03-31"] and out[0]["widened"][0]["from"] == MARCH
    assert out[1]["query"] == {"measures": ["a.x"], "timeDimensions": _axis("month", ["2020-03-01", "2020-03-31"]), "filters": [REGION]}, "only what prior() reads, moved from the asked range"
    other = {"cube": "b", "query": {"measures": ["b.z"], "timeDimensions": _axis("month", MARCH)}, "post": q["post"]}
    assert T.with_time_calcs([other], YEAR) == [other], "a cube whose measures prior() and rolling() do not read is left alone"
    plain = {"cube": "a", "query": {"measures": ["a.x"]}}
    assert T.with_time_calcs([plain], YEAR) == [plain]


def test_nothing_to_move_sends_no_moved_query():
    all_time = {"cube": "a", "query": {"measures": ["a.x"], "timeDimensions": _axis("month")}, "post": _post(mom="a.x / prior(a.x, month)")}
    assert T.with_time_calcs([all_time], YEAR) == [all_time], "all time: the earlier buckets are among the panel's own rows"
    week = {"cube": "a", "query": {"measures": ["a.x"], "timeDimensions": _axis("week", ["2021-03-15", "2021-03-21"])}, "post": _post(yoy="prior(a.x, year)")}
    assert T.with_time_calcs([week], YEAR)[1]["query"]["timeDimensions"][0]["dateRange"] == ["2020-03-16", "2020-03-22"]


# ---- the browser's code gives the same answers
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_python_mirror_equals_the_renderers_code():
    py = {"shiftRange": C.shift_range, "shiftYears": C.shift_years, "shiftQuery": C.shift_query, "bucketStart": T.bucket_start, "priorShift": T.prior_shift,
          "widenQuery": T.widen_query, "withTimeCalcs": T.with_time_calcs}
    shifts = [{"months": 1}, {"months": 3}, {"months": 12, "years": 1}, {"days": 7}, {"days": 1}, {"days": 364}]
    ranges = [MARCH, ["2024-02-01", "2024-02-29"], ["2024-02-29", "2024-03-10"], ["2021-12-31", "2022-01-01"], ["2000-01-31", "2000-02-29"], ["2021-03-31", "2021-03-01"]]
    dates = ["2021-03-17", "2021-01-03", "2020-12-31", "2024-02-29", "2021-01-01", "1999-11-30"]
    grans = ["day", "week", "month", "quarter", "year", "hour"]
    filters = [[], [REGION], [FY, REGION], [{**FY, "values": ["2021", "2022"]}], [{**FY, "operator": "notEquals"}], [{**FY, "values": ["x"]}],
               [{"member": "dates.full_date", "operator": "inDateRange", "values": MARCH}], [{"member": "ship_dates.full_date", "operator": "inDateRange", "values": MARCH}],
               [{"member": "dates.full_date", "operator": "beforeDate", "values": ["2021-01-01"]}]]
    cases = [{"fn": "shiftRange", "args": [r, s]} for r in ranges for s in shifts]
    cases += [{"fn": "shiftYears", "args": [ys, s]} for ys in (["2021"], ["2021", "2022"], ["x"]) for s in shifts]
    cases += [{"fn": "bucketStart", "args": [d, g]} for d in dates for g in grans[:5]]
    cases += [{"fn": "priorShift", "args": [u, g]} for u in T.PRIOR_UNITS for g in [*grans, None]]
    queries = [{"measures": ["a.x"], "filters": f, **({"timeDimensions": td} if td else {})} for f in filters
               for td in [None, _axis("month"), *(_axis(g, r) for g in grans for r in ranges[:4])]]
    cases += [{"fn": "shiftQuery", "args": [q, s, YEAR]} for q in queries for s in shifts]
    cases += [{"fn": "widenQuery", "args": [q, n, YEAR]} for q in queries for n in (2, 3, 12, 13, 25)]
    posts = [_post(yoy="a.x / prior(a.x, year) - 1"), _post(r="rolling(a.x, 3) / rolling(a.y, 12)"), _post(m="prior(a.x, month) + prior(a.y, week) + rolling(a.y, 4)"), _post(p="a.x * 2")]
    cases += [{"fn": "withTimeCalcs", "args": [[{"cube": "a", "query": {**q, "measures": ["a.x", "a.y"]}, "post": p}, {"cube": "b", "query": {**q, "measures": ["b.z"]}, "post": p}], YEAR]}
              for q in queries for p in posts]
    out = subprocess.run(["node", str(REPO / "dashboards" / "tests" / "dump_timecalc.mjs")], input=json.dumps(cases), capture_output=True, text=True, check=True).stdout
    js = json.loads(out)
    assert len(js) == len(cases) > 3000
    for case, got in zip(cases, js, strict=True):
        assert got == py[case["fn"]](*case["args"]), case


# ---- the validator
def with_time_calcs(*panels):
    spec = copy.deepcopy(GOOD)
    spec["calculations"] = [
        {"id": "yoy", "label": "Revenue vs last year", "formula": "internet_sales.revenue / prior(internet_sales.revenue, year) - 1", "format": "pct"},
        {"id": "mom", "label": "Revenue vs last month", "formula": "internet_sales.revenue / prior(internet_sales.revenue, month) - 1", "format": "pct"},
        {"id": "r12", "label": "Revenue, last 12 months", "formula": "rolling(internet_sales.revenue, 12) + rolling(reseller_sales.revenue, 12)", "format": "money"},
    ]
    if "calc.orders_r3" in json.dumps(panels):
        spec["calculations"].append({"id": "orders_r3", "label": "Orders, 3 months", "formula": "rolling(internet_sales.orders, 3)"})
    spec["panels"] += list(panels)
    spec["layout"] += [[{p["id"]: 12}] for p in panels]
    return spec


TREND = {"id": "trend_tc", "type": "timeseries", "series": [{"member": "calc.yoy"}, {"member": "calc.mom"}, {"member": "calc.r12"}], "granularity": "month"}
USES = [TREND, {"id": "kpi_tc", "type": "kpi", "measures": [{"member": "calc.yoy"}]},
        {"id": "bar_tc", "type": "bar", "measure": "calc.yoy", "by": "products.category"},
        {"id": "piv_tc", "type": "pivot", "rows": ["products.category"], "columns": {"member": "dates.full_date", "granularity": "quarter"}, "measures": ["calc.r12", "calc.yoy"]}]


def test_prior_and_rolling_validate_where_they_fit_and_their_queries_are_the_renderers(tmp_path):
    spec = with_time_calcs(*USES)
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    qs = panel_queries(out, next(p for p in out["panels"] if p["id"] == "trend_tc"), {"fy": "2021"})
    # a fiscal year chosen: rolling takes in the year before, prior(year) moves the year, prior(month) cannot be written as a year select (the chart finds the month before
    # among its own rows), and the other cube only rolls
    assert [(q["cube"], q.get("prior")) for q in qs] == [("internet_sales", None), ("internet_sales", "year"), ("reseller_sales", None)]
    assert qs[0]["widened"] == [{"member": "dates.fiscal_year", "from": ["2021"], "to": ["2020", "2021"]}] and qs[1]["query"]["measures"] == ["internet_sales.revenue"]
    assert [f["values"] for f in qs[1]["query"]["filters"] if f["member"] == "dates.fiscal_year"] == [["2020"]]
    if shutil.which("node") is None:
        return
    path = tmp_path / "tc.json"
    path.write_text(json.dumps(out))
    dumped = json.loads(subprocess.run(["node", str(REPO / "dashboards/tests/dump_queries.mjs"), str(path)], capture_output=True, text=True, check=True).stdout)
    for state in dumped:
        for p in out["panels"]:
            assert panel_queries(out, p, state["values"]) == state["panels"][p["id"]], f"{p['id']} under {state['values']}"


BROKEN = [
    ("rolling a distinct count", [{**TREND, "series": [{"member": "calc.orders_r3"}]}],
     "calculation 'orders_r3': formula: rolling(internet_sales.orders, 3): 'internet_sales.orders' is a count_distinct measure, which does not add up over time buckets"),
    ("rolling on a bar", [{"id": "b", "type": "bar", "measure": "calc.r12", "by": "products.category"}], "panel 'b' (bar): measure: 'calc.r12' uses rolling(), which"),
    ("rolling on a key figure", [{"id": "k", "type": "kpi", "measures": [{"member": "calc.r12"}], "sparkline": {"granularity": "month"}}], "(a key figure has a single value"),
    ("prior by month on a yearly chart", [{**TREND, "series": [{"member": "calc.mom"}], "granularity": "year"}],
     "panel 'trend_tc' (timeseries): series[0].member: 'calc.mom' uses prior(..., month), which does not move a year bucket onto another one (on a year axis: year)"),
    ("prior by month on a drill-down that starts at years", [{**TREND, "series": [{"member": "calc.mom"}], "granularity": "year", "drill": ["year", "month"]}], "does not move a year bucket"),
    ("prior by month on a weekly switch", [{**TREND, "series": [{"member": "calc.mom"}], "granularities": ["month", "week"]}], "does not move a week bucket"),
    ("prior on a weekly sparkline", [{"id": "k", "type": "kpi", "measures": [{"member": "calc.mom"}], "sparkline": {"granularity": "week"}}], "does not move a week bucket"),
]


@pytest.mark.parametrize("name,panels,expected", BROKEN, ids=[b[0] for b in BROKEN])
def test_prior_and_rolling_are_refused_where_they_mean_nothing(name, panels, expected):
    errors, _ = validate(with_time_calcs(*panels), CATALOG)
    assert any(expected in e for e in errors), "\n".join(errors)


def test_the_measures_aggregation_comes_from_cubes_agg_type_in_meta():
    meta = {"cubes": [{"name": "s", "measures": [{"name": "s.rev", "type": "number", "aggType": "sum"}, {"name": "s.n", "type": "number", "aggType": "countDistinct"},
                                                  {"name": "s.old", "type": "number"}], "dimensions": []}]}
    c = cat.from_meta(meta)
    assert (c.agg_type("s.rev"), c.agg_type("s.n"), c.agg_type("s.old")) == ("sum", "count_distinct", None)
    assert CATALOG.agg_type("internet_sales.orders") == "count_distinct" and CATALOG.agg_type("internet_sales.revenue") == "sum"
