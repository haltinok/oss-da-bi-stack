"""dashspec: the good example validates, and each kind of broken file fails with a message naming the panel and the field.

  PYTHONPATH=dashboards uv run --with pytest --with pyyaml --with 'jsonschema>=4.18' python -m pytest dashboards/tests -q
"""
import copy
import json
import pathlib

import pytest
import yaml

from dashspec import catalog as cat
from dashspec.cli import main
from dashspec.compile import compile_spec
from dashspec.validate import validate

REPO = pathlib.Path(__file__).resolve().parents[2]
GOOD = yaml.safe_load((REPO / "dashboards" / "sales-overview.yml").read_text())
CATALOG = cat.from_model(REPO / "cube" / "model")


def panel(spec, pid):
    return next(p for p in spec["panels"] if p["id"] == pid)


def run(mutate):
    spec = copy.deepcopy(GOOD)
    mutate(spec)
    errors, _ = validate(spec, CATALOG)
    return errors


def test_good_example_validates_and_compiles():
    errors, used = validate(copy.deepcopy(GOOD), CATALOG)
    assert errors == []
    out = compile_spec(GOOD, used)
    assert out["layout"][1] == [{"panel": "trend", "span": 8}, {"panel": "lines", "span": 4}]
    assert out["members"]["internet_sales.revenue"] == {"kind": "measure", "type": "sum"}
    assert out["members"]["dates.full_date"] == {"kind": "dimension", "type": "time"}
    json.dumps(out)


def test_every_checked_in_dashboard_validates():
    for path in sorted((REPO / "dashboards").glob("*.yml")):
        errors, _ = validate(yaml.safe_load(path.read_text()), CATALOG)
        assert errors == [], path.name


def _set(pid, key, value):
    def f(spec):
        panel(spec, pid)[key] = value
    return f


def _drop(pid, key):
    def f(spec):
        del panel(spec, pid)[key]
    return f


# (name, mutation, every substring the report must contain)
BROKEN = [
    ("unknown member", lambda s: panel(s, "top").update(by="products.nme"),
     ["panel 'top' (bar)", "by:", "'products.nme' is not in the Cube model", "products has:"]),
    ("unknown cube", lambda s: panel(s, "mix").update(measure="sales.revenue"),
     ["panel 'mix' (treemap)", "measure:", "'sales.revenue' is not in the Cube model", "cubes:"]),
    ("dimension used as a measure", lambda s: panel(s, "mix").update(measure="products.name"),
     ["panel 'mix'", "measure:", "is a dimension, a measure is needed"]),
    ("measure used as a dimension", lambda s: panel(s, "top").update(by="internet_sales.revenue"),
     ["panel 'top'", "by:", "is a measure, a dimension is needed"]),
    ("measure in a series, wrong index named", lambda s: panel(s, "trend")["series"].append({"member": "products.name"}),
     ["panel 'trend' (timeseries)", "series[2].member", "is a dimension"]),
    ("bad granularity", _set("trend", "granularity", "fortnight"),
     ["panel 'trend' (timeseries)", "granularity:", "'fortnight' is not one of"]),
    ("unknown panel type", _set("top", "type", "radar"),
     ["panel 'top' (radar)", "type:", "'radar' is not one of"]),
    ("missing required field", _drop("top", "by"),
     ["panel 'top' (bar)", "'by' is a required property"]),
    ("unknown field", _set("top", "colour", "red"),
     ["panel 'top' (bar)", "colour:", "'colour' is not a field of a bar panel"]),
    ("limit out of range", _set("top", "limit", 0),
     ["panel 'top'", "limit:", "0 is less than the minimum of 1"]),
    ("kpi measure without member or sum", lambda s: panel(s, "kpis")["measures"].append({"label": "x"}),
     ["panel 'kpis' (kpi)", "measures[6]", "needs a 'member'"]),
    ("sum of one measure", lambda s: panel(s, "kpis")["measures"][0].update(sum=["internet_sales.revenue"]),
     ["panel 'kpis'", "measures[0].sum", "is too short"]),
    ("ratio with an unknown member", lambda s: panel(s, "kpis")["measures"][2]["ratio"]["num"].append("internet_sales.nope"),
     ["panel 'kpis'", "measures[2].ratio.num[2]", "'internet_sales.nope' is not in the Cube model"]),
    ("ratio denominator that is a dimension", lambda s: panel(s, "kpis")["measures"][2]["ratio"]["den"].append("products.name"),
     ["panel 'kpis'", "measures[2].ratio.den[2]", "is a dimension"]),
    ("ratio without a label", lambda s: panel(s, "kpis")["measures"][2].pop("label"),
     ["panel 'kpis'", "measures[2]", "needs a 'member'"]),
    ("table column object with an unknown member", lambda s: panel(s, "lines")["columns"].append({"member": "territories.nope", "label": "X"}),
     ["panel 'lines' (table)", "columns[4]", "'territories.nope' is not in the Cube model"]),
    ("table column object with a bad format", lambda s: panel(s, "lines")["columns"][3].update(format="euros"),
     ["panel 'lines'", "columns[3]"]),
    ("sum of a dimension", lambda s: panel(s, "kpis")["measures"][0].update(sum=["internet_sales.revenue", "products.name"]),
     ["panel 'kpis'", "measures[0].sum[1]", "is a dimension"]),
    ("time dimension that is not time", lambda s: s["time"].update(dimension="dates.fiscal_year"),
     ["dashboard", "time.dimension", "a time dimension is needed"]),
    ("filter on a measure", lambda s: s["filters"][0].update(dimension="internet_sales.revenue"),
     ["filter 'fy'", "dimension:", "is a measure"]),
    ("filter parent unknown", lambda s: s["filters"][1].update(parent="territories.nope"),
     ["filter 'region'", "parent:", "'territories.nope' is not in the Cube model"]),
    ("filter its own parent", lambda s: s["filters"][1].update(parent="territories.region"),
     ["filter 'region'", "parent:", "own parent"]),
    ("duplicate filter id", lambda s: s["filters"][1].update(id="fy"),
     ["filters:", "id 'fy' is used by more than one filter"]),
    ("duplicate panel id", lambda s: panel(s, "top").update(id="mix"),
     ["panels:", "id 'mix' is used by more than one panel"]),
    ("on_click names an unknown filter", _set("trend", "on_click", {"set_filter": "year"}),
     ["panel 'trend'", "on_click.set_filter", "no filter with id 'year'"]),
    ("on_click names too many filters", _set("trend", "on_click", {"set_filter": ["fy", "region"]}),
     ["panel 'trend'", "on_click.set_filter", "carries one value"]),
    ("time chart click on a non-year filter", _set("trend", "on_click", {"set_filter": "region"}),
     ["panel 'trend' (timeseries)", "on_click.set_filter", "filter 'region' is on 'territories.region'", "fiscal_year or calendar_year"]),
    ("bar click on a filter for another dimension", _set("top", "on_click", {"set_filter": "category"}),
     ["panel 'top' (bar)", "on_click.set_filter", "filter 'category' is on 'products.category', which this bar does not show"]),
    ("bar click naming two filters", _set("top", "on_click", {"set_filter": ["category", "subcategory"]}),
     ["panel 'top' (bar)", "a click on a bar carries one value"]),
    ("treemap filters in the wrong order", _set("mix", "on_click", {"set_filter": ["subcategory", "category"]}),
     ["panel 'mix' (treemap)", "filter 'subcategory' is on 'products.subcategory' but group[0] is 'products.category'", "in the order of the group"]),
    ("table click on a measure column's dimension that is not shown", _set("lines", "on_click", {"set_filter": "category"}),
     ["panel 'lines' (table)", "filter 'category' is on 'products.category', which this table does not show"]),
    ("granularities without the default", _set("trend", "granularities", ["quarter", "year"]),
     ["panel 'trend' (timeseries)", "granularities:", "must include the default granularity 'month'"]),
    ("granularities with one entry", _set("trend", "granularities", ["month"]),
     ["panel 'trend'", "granularities:", "is too short"]),
    ("a bar with neither measure nor stack", _drop("top", "stack"),
     ["panel 'top' (bar)", "needs exactly one of: measure, stack"]),
    ("a stacked bar that is also split", _set("top", "split", "territories.region"),
     ["panel 'top' (bar)", "split:", "stacked by measures"]),
    ("a stack member that is a dimension", lambda s: panel(s, "top")["stack"].append({"member": "products.name"}),
     ["panel 'top' (bar)", "stack[2].member", "is a dimension"]),
    ("a series ratio with an unknown member", lambda s: panel(s, "margin")["series"][0]["ratio"]["num"].append("internet_sales.nope"),
     ["panel 'margin' (timeseries)", "series[0].ratio.num[2]", "'internet_sales.nope' is not in the Cube model"]),
    ("a series sum without a label", lambda s: panel(s, "trend")["series"].append({"sum": ["internet_sales.revenue", "reseller_sales.revenue"]}),
     ["panel 'trend' (timeseries)", "series[2]", "needs a 'member'"]),
    ("role rep on a dashboard with profit", lambda s: s.update(roles=["admin", "rep"]),
     ["panel 'kpis' (kpi)", "role 'rep' cannot read 'internet_sales.gross_profit'", "profit and margin are hidden from reps"]),
    ("role purchasing on a sales dashboard", lambda s: s.update(roles=["purchasing"]),
     ["role 'purchasing' cannot read", "is not available to purchasing"]),
    ("drill levels out of order", lambda s: panel(s, "trend").update(drill=["month", "year"], granularity="month", granularities=None) or panel(s, "trend").pop("granularities") or panel(s, "trend").pop("on_click"),
     ["panel 'trend' (timeseries)", "drill:", "must go from coarse to fine"]),
    ("drill whose first level is not the granularity", lambda s: panel(s, "trend").update(drill=["year", "month"]),
     ["panel 'trend'", "granularity:", "must be the first drill level 'year'"]),
    ("drill together with granularities", lambda s: panel(s, "trend").update(drill=["month", "day"]),
     ["panel 'trend'", "granularities:", "a drill-down already changes the granularity"]),
    ("drill together with on_click", lambda s: panel(s, "trend").update(drill=["month", "day"]),
     ["panel 'trend'", "on_click:", "also filters the other panels by the period"]),
    ("a week inside a month", lambda s: (panel(s, "trend").update(drill=["month", "week"]), panel(s, "trend").pop("granularities"), panel(s, "trend").pop("on_click")),
     ["panel 'trend'", "a week does not fit inside a month"]),
    ("a drill with one level", lambda s: panel(s, "trend").update(drill=["month"]),
     ["panel 'trend'", "drill:", "is too short"]),
    ("a chart style that does not exist", _set("trend", "style", "radar"),
     ["panel 'trend' (timeseries)", "style:", "'radar' is not one of"]),
    ("a bar orientation that does not exist", _set("top", "orientation", "diagonal"),
     ["panel 'top' (bar)", "orientation:", "'diagonal' is not one of"]),
    ("a pie with a stack", lambda s: s["panels"].append({"id": "p", "type": "pie", "stack": [], "by": "products.category"}) or s["layout"].append([{"p": 12}]),
     ["panel 'p' (pie)", "stack:"]),
    ("a pie click on another dimension", lambda s: (s["panels"].append({"id": "p", "type": "pie", "measure": "internet_sales.revenue", "by": "products.category", "on_click": {"set_filter": "region"}}), s["layout"].append([{"p": 12}])),
     ["panel 'p' (pie)", "filter 'region' is on 'territories.region', which this pie does not show"]),
    ("a pie with one slice", lambda s: (s["panels"].append({"id": "p", "type": "pie", "measure": "internet_sales.revenue", "by": "products.category", "limit": 1}), s["layout"].append([{"p": 12}])),
     ["panel 'p' (pie)", "limit:", "less than the minimum of 2"]),
    ("a pie by an unknown dimension", lambda s: (s["panels"].append({"id": "p", "type": "pie", "measure": "internet_sales.revenue", "by": "products.nope"}), s["layout"].append([{"p": 12}])),
     ["panel 'p' (pie)", "by:", "'products.nope' is not in the Cube model"]),
    ("ignore_filters names an unknown filter", _set("top", "ignore_filters", ["nope"]),
     ["panel 'top'", "ignore_filters:", "no filter with id 'nope'"]),
    ("table order on a column that is not shown", _set("lines", "order", {"internet_sales.units": "desc"}),
     ["panel 'lines' (table)", "order.internet_sales.units", "not one of the table's columns"]),
    ("a table total with no measure column", lambda s: panel(s, "lines").update(columns=["internet_sales.order_number", "territories.country"], order={}, totals="footer"),
     ["panel 'lines' (table)", "totals:", "needs at least one measure column"]),
    ("a table total somewhere else than header or footer", _set("lines", "totals", "side"),
     ["panel 'lines' (table)", "totals:", "'side' is not one of"]),
    ("layout row not 12 wide", lambda s: s["layout"].__setitem__(1, [{"trend": 8}, {"lines": 3}]),
     ["layout:", "row 2", "add up to 11"]),
    ("layout names an unknown panel", lambda s: s["layout"].append([{"ghost": 12}]),
     ["layout:", "no panel with id 'ghost'"]),
    ("panel missing from the layout", lambda s: s["layout"].pop(),
     ["layout:", "panel 'margin' is placed 0 times", "panel 'territories' is placed 0 times"]),
    ("panel placed twice", lambda s: s["layout"].append([{"kpis": 12}]),
     ["layout:", "panel 'kpis' is placed 2 times"]),
    ("a filter on a cube the measure has no join to", lambda s: s["panels"].append(
        {"id": "stock", "type": "kpi", "measures": [{"member": "inventory_health.stockout_items"}]}) or s["layout"].append([{"stock": 12}]),
     ["panel 'stock' (kpi)", "'inventory_health.stockout_items' cannot be combined with 'territories.region'", "filter 'region'",
      "ignore_filters"]),
    ("spec version", lambda s: s.update(spec=2), ["dashboard", "spec:", "was expected"]),
    ("unknown role", lambda s: s.update(roles=["boss"]), ["dashboard", "roles[0]", "'boss' is not one of"]),
    ("bad currency", lambda s: s.update(currency="usd"), ["dashboard", "currency:", "does not match"]),
]


@pytest.mark.parametrize("name,mutate,needles", BROKEN, ids=[b[0] for b in BROKEN])
def test_broken_spec_fails_with_a_message_that_names_the_place(name, mutate, needles):
    errors = run(mutate)
    assert errors, f"{name}: expected a problem"
    text = "\n".join(errors)
    for needle in needles:
        assert needle in text, f"{name}: {needle!r} missing from:\n{text}"


def test_ignore_filters_fixes_the_join_error():
    def add(s):
        s["panels"].append({"id": "stock", "type": "kpi", "measures": [{"member": "inventory_health.stockout_items"}],
                            "ignore_filters": ["fy", "region", "category", "subcategory"]})
        s["layout"].append([{"stock": 12}])
        s["roles"] = ["admin"]          # a manager may not read inventory data (see the role rules)
    assert run(add) == []


def test_a_bad_panel_type_is_reported_once_not_as_noise():
    errors = run(_set("top", "type", "radar"))
    assert len(errors) == 1, errors


def test_cli_validate_and_compile(tmp_path, capsys):
    good = REPO / "dashboards" / "sales-overview.yml"
    assert main(["validate", str(good)]) == 0
    assert "ok" in capsys.readouterr().out
    out = tmp_path / "build" / "x.json"
    assert main(["compile", str(good), "-o", str(out)]) == 0
    assert json.loads(out.read_text())["id"] == "sales-overview"
    bad = tmp_path / "bad.yml"
    spec = copy.deepcopy(GOOD)
    panel(spec, "top")["by"] = "products.nme"
    bad.write_text(yaml.safe_dump(spec))
    assert main(["validate", str(bad)]) == 1
    assert "products.nme" in capsys.readouterr().out
    assert main(["compile", str(bad)]) == 1


def test_cli_rejects_invalid_yaml(tmp_path, capsys):
    bad = tmp_path / "bad.yml"
    bad.write_text("a: [unclosed")
    assert main(["validate", str(bad)]) == 1
    assert "not valid YAML" in capsys.readouterr().out


def test_meta_lists_the_cubes(capsys):
    assert main(["meta"]) == 0
    out = capsys.readouterr().out
    assert "cube internet_sales" in out and "revenue [sum]" in out and "full_date [time]" in out


def test_a_nested_error_does_not_make_every_key_of_the_panel_look_unknown():
    def f(s):
        panel(s, "trend")["granularity"] = "fortnight"
        panel(s, "trend")["colour"] = "red"
    errors = run(f)
    assert len(errors) == 2, errors
    assert any("granularity:" in e and "'fortnight'" in e for e in errors)
    assert any("colour:" in e for e in errors)
    assert not any("Unevaluated" in e for e in errors)


def test_compile_gives_every_table_column_as_an_object():
    errors, used = validate(copy.deepcopy(GOOD), CATALOG)
    assert errors == []
    cols = next(p for p in compile_spec(copy.deepcopy(GOOD), used)["panels"] if p["id"] == "lines")["columns"]
    assert cols[0] == {"member": "internet_sales.order_number", "label": "Order"}
    spec = copy.deepcopy(GOOD)
    panel(spec, "lines")["columns"] = ["internet_sales.order_number", "internet_sales.revenue"]
    assert next(p for p in compile_spec(spec, used)["panels"] if p["id"] == "lines")["columns"] == [{"member": "internet_sales.order_number"}, {"member": "internet_sales.revenue"}]


def test_build_writes_each_dashboard_and_an_index(tmp_path, capsys):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    (src / "sales-overview.yml").write_text((REPO / "dashboards" / "sales-overview.yml").read_text())
    assert main(["build", "--dir", str(src), "--out", str(out)]) == 0
    assert json.loads((out / "sales-overview.json").read_text())["id"] == "sales-overview"
    index = json.loads((out / "index.json").read_text())
    assert index == [{"id": "sales-overview", "title": "Sales overview", "description": GOOD["description"], "roles": ["admin", "manager"], "tags": GOOD["tags"]}]
    (out / "gone.json").write_text("{}")                       # a dashboard that no longer exists is not served
    assert main(["build", "--dir", str(src), "--out", str(out)]) == 0
    assert not (out / "gone.json").exists()


def test_build_fails_on_a_bad_file_and_on_a_name_that_is_not_the_id(tmp_path, capsys):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    spec = copy.deepcopy(GOOD)
    panel(spec, "top")["by"] = "products.nme"
    (src / "sales-overview.yml").write_text(yaml.safe_dump(spec))
    assert main(["build", "--dir", str(src), "--out", str(out)]) == 1
    assert "products.nme" in capsys.readouterr().err
    (src / "sales-overview.yml").write_text((REPO / "dashboards" / "sales-overview.yml").read_text())
    (src / "other-name.yml").write_text((REPO / "dashboards" / "sales-overview.yml").read_text())
    assert main(["build", "--dir", str(src), "--out", str(out)]) == 1
    assert "must be the dashboard id" in capsys.readouterr().err


def test_the_committed_build_is_current(tmp_path):
    """dashboards/build is committed (nginx serves it as is): rebuilding from the YAML must change nothing."""
    out = tmp_path / "out"
    assert main(["build", "--out", str(out)]) == 0
    committed = REPO / "dashboards" / "build"
    for f in sorted(out.iterdir()):
        assert (committed / f.name).read_text() == f.read_text(), f"{f.name} is stale: run scripts/dashspec build"
    assert sorted(p.name for p in committed.iterdir()) == sorted(p.name for p in out.iterdir())


# ---------------------------------------------------------------------------------------------------------------- queries and lint
import shutil  # noqa: E402
import subprocess  # noqa: E402

from dashspec.lint import filter_states, lint  # noqa: E402
from dashspec.queries import panel_queries  # noqa: E402


def built(name):
    return json.loads((REPO / "dashboards" / "build" / f"{name}.json").read_text())


@pytest.mark.skipif(shutil.which("node") is None, reason="node is needed to run the renderer's query builders")
@pytest.mark.parametrize("path", sorted((REPO / "dashboards" / "build").glob("*.json")), ids=lambda p: p.stem)
def test_python_queries_match_the_renderers(path):
    """The queries dashspec lint asks Cube about are the ones the page sends (plan.js is the source of truth)."""
    spec = json.loads(path.read_text())
    if path.name == "index.json":
        pytest.skip("not a dashboard")
    dumped = json.loads(subprocess.run(["node", str(REPO / "dashboards/tests/dump_queries.mjs"), str(path)], capture_output=True, text=True, check=True).stdout)
    for state in dumped:
        for pid, js in state["panels"].items():
            panel = next(p for p in spec["panels"] if p["id"] == pid)
            assert panel_queries(spec, panel, state["values"]) == js, f"{pid} under {state['values']}"


def test_lint_reports_queries_no_rollup_serves_and_those_cube_did_not_describe():
    spec = built("sales-overview")
    calls = []

    def plan(q):
        calls.append(q)
        if "inventory" in json.dumps(q):
            return None
        return [] if "products.name" in q.get("dimensions", []) else ["internet_sales.monthly"]

    found = lint(spec, plan)
    text = "\n".join(m for _, m in found)
    assert any(s == "warning" for s, _ in found)
    assert "panel 'top' (bar): no pre-aggregation serves" in text and "products.name" in text
    assert "panel 'kpis'" not in text, "served queries are not reported"
    assert len(calls) == len({json.dumps(c, sort_keys=True) for c in calls}), "the same query is only asked once"
    assert [label for label, _ in filter_states(spec)][:2] == ["no filter", "filter 'fy'"]
    assert lint(spec, lambda q: ["x"]) == []
    assert all(s == "unknown" for s, _ in lint(spec, lambda q: None))


def test_cli_lint_needs_a_cube(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("CUBE_TOKEN", raising=False)
    with pytest.raises(SystemExit) as e:
        main(["lint", str(REPO / "dashboards" / "sales-overview.yml")])
    assert "CUBE_TOKEN" in str(e.value)


def test_role_rules_for_inventory_dashboards():
    spec = yaml.safe_load((REPO / "dashboards" / "envanter-sagligi.yml").read_text())
    assert validate(copy.deepcopy(spec), CATALOG)[0] == []
    spec["roles"] = ["admin", "purchasing", "marketing"]
    text = "\n".join(validate(spec, CATALOG)[0])
    assert "role 'marketing' cannot read 'inventory_health.suggested_order_value_total'" in text and "supplier and order data" in text
    spec["roles"] = ["manager"]
    assert "role 'manager' cannot read 'inventory_health." in "\n".join(validate(spec, CATALOG)[0])


def test_role_rules_match_cube_js():
    """validate.py mirrors the role rules of cube/cube.js; if one changes, so must the other."""
    import re

    import dashspec.validate as v
    js = (REPO / "cube" / "cube.js").read_text()

    def js_set(name):
        return set(re.findall(r"'([a-z_]+)'", re.search(rf"const {name} = new Set\(\[(.*?)\]\)", js, re.S).group(1)))
    assert js_set("PROFIT_MEMBERS") == v.PROFIT_MEMBERS
    assert js_set("INVENTORY_CUBES") == v.INVENTORY_CUBES
    assert js_set("SUPPLIER_MEMBERS") == v.SUPPLIER_MEMBERS
    for role, cubes in v.ROLE_CUBES.items():
        assert set(re.findall(r"'([a-z_]+)'", re.search(rf"{role}: new Set\(\[(.*?)\]\)", js).group(1))) == cubes


def test_a_rep_dashboard_uses_no_profit_member():
    for path in (REPO / "dashboards").glob("*.yml"):
        spec = yaml.safe_load(path.read_text())
        if "rep" in spec.get("roles", []):
            assert validate(spec, CATALOG)[0] == [], path.name


def test_cli_lint_against_a_stub_cube(capsys, monkeypatch):
    """`dashspec lint` asks GET /cubejs-api/v1/sql for each query and reports the ones whose plan uses no pre-aggregation."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    seen = []

    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            assert self.headers["Authorization"] == "tok"
            q = json.loads(parse_qs(urlparse(self.path).query)["query"][0])
            seen.append(q)
            body = {"sql": {"sql": ["select 1", []], "preAggregations": [] if "products.name" in q.get("dimensions", []) else [{"tableName": "x"}]}}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("CUBE_TOKEN", "tok")
    good = str(REPO / "dashboards" / "sales-overview.yml")
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        assert main(["lint", good, "--cube-url", url]) == 0
        out = capsys.readouterr().out
        assert "warning(s)" in out and "panel 'top' (bar): no pre-aggregation serves" in out and "panel 'kpis'" not in out
        assert main(["lint", good, "--cube-url", url, "--strict"]) == 1
        assert seen, "Cube was asked"
    finally:
        server.shutdown()


@pytest.mark.parametrize("theme,needle", [
    ({"colors": {"internet": "blue"}}, "theme.colors.internet"),
    ({"colors": {"sidebar": "#112233"}}, "theme.colors"),
    ({"logo": "javascript:alert(1)"}, "theme.logo"),
    ({"logo": "http://example.com/x.svg"}, "theme.logo"),
    ({"name": "x" * 61}, "theme.name"),
    ({"title": "x"}, "theme"),
])
def test_theme_is_checked(theme, needle):
    errors = run(lambda s: s.update(theme=theme))
    assert errors and needle in "\n".join(errors), errors


def test_a_good_theme_compiles():
    spec = copy.deepcopy(GOOD)
    spec["theme"] = {"name": "Fairstone", "logo": "/assets/logo.svg", "colors": {"internet": "#112233", "focus": "#3987E5"}}
    errors, used = validate(spec, CATALOG)
    assert errors == []
    assert compile_spec(spec, used)["theme"]["colors"]["internet"] == "#112233"


# ---------------------------------------------------------------------------------------------------------------- documentation
def test_the_spec_reference_is_generated_from_the_schema_and_current():
    from dashspec.docs import generate
    text = generate()          # raises if a schema field has no description, or a description has no field
    assert (REPO / "docs" / "dashboard-spec-reference.md").read_text() == text, "run scripts/dashspec docs"
    for field in ("fiscal_year_start", "granularities", "ignore_filters", "set_filter", "stack", "markdown"):
        assert f"`{field}`" in text


def test_links_and_images_in_the_dashboard_docs_resolve():
    import re
    for name in ("dashboards.md", "dashboard-spec-reference.md", "dashboard-spec-plan.md", "builder.md", "semantic-layer.md"):
        path = REPO / "docs" / name
        for target in re.findall(r"\]\(((?!https?://|#|mailto:)[^)\s]+)\)", path.read_text()):
            assert (path.parent / target.split("#")[0]).resolve().exists(), f"{name}: broken link {target}"
    guide = (REPO / "docs" / "dashboards.md").read_text()
    for anchor in re.findall(r"\]\(#([^)]+)\)", guide):
        heads = [re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-") for h in re.findall(r"^#+ (.+)$", guide, re.M)]
        assert anchor in heads, f"dashboards.md: no heading for #{anchor}"
    for panel_type in ("kpi", "timeseries", "bar", "pie", "treemap", "table", "text"):
        assert f"**`{panel_type}`" in guide, f"the gallery lacks {panel_type}"


# ---------------------------------------------------------------------------------------------------------------- the semantic layer
def test_every_member_of_the_cube_model_has_a_description():
    """The descriptions are what people (and the builder's model) read to choose members; a new member must come with one."""
    missing = [f"{c}.{m}" for c, v in CATALOG.cubes.items() for m in [*v["measures"], *v["dimensions"]] if m not in v["docs"]]
    assert not missing, f"describe these in cube/model/cubes/*.yml: {missing}"
    assert all(v["description"] for v in CATALOG.cubes.values()), "every cube needs a description"


def test_the_semantic_layer_page_is_generated_from_the_model_and_current():
    from dashspec.semantic import generate
    assert (REPO / "docs" / "semantic-layer.md").read_text() == generate(CATALOG), "run scripts/dashspec semantic"


def test_catalog_json_hides_what_a_role_cannot_read():
    from dashspec.semantic import catalog_json
    rep = {c["cube"]: c for c in catalog_json(CATALOG, "rep")}
    assert "inventory_health" not in rep and "customers" not in rep
    assert "gross_profit" not in {m["name"] for m in rep["internet_sales"]["measures"]}
    assert "revenue" in {m["name"] for m in rep["internet_sales"]["measures"]}
    mk = {c["cube"]: c for c in catalog_json(CATALOG, "marketing")}
    assert set(mk) == {"inventory_health", "offer_performance", "products"}
    assert "vendor_name" not in {d["name"] for d in mk["inventory_health"]["dimensions"]}
    admin = {c["cube"]: c for c in catalog_json(CATALOG)}
    gp = next(m for m in admin["internet_sales"]["measures"] if m["name"] == "gross_profit")
    assert gp["hidden_from"] == ["rep", "purchasing", "marketing"] and gp["description"]
    assert admin["internet_sales"]["joins"] == ["customers", "dates", "due_dates", "products", "ship_dates", "territories"] and admin["internet_sales"]["fact"]


def test_a_drill_down_a_pie_and_the_new_styles_are_valid_and_compile_with_cube_joins():
    spec = copy.deepcopy(GOOD)
    trend = panel(spec, "trend")
    trend.pop("granularities")
    trend.pop("on_click")
    trend.update(drill=["year", "month", "day"], granularity="year", style="stacked-area")
    spec["panels"].append({"id": "p", "type": "pie", "measure": "internet_sales.revenue", "by": "products.subcategory", "style": "donut", "limit": 6, "format": "money", "on_click": {"set_filter": "subcategory"}})
    panel(spec, "top")["orientation"] = "vertical"
    panel(spec, "kpis")["ignore_filters"] = ["period"]
    spec["layout"].append([{"p": 12}])
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used, CATALOG)
    assert out["cubes"]["internet_sales"]["joins"] == ["customers", "dates", "due_dates", "products", "ship_dates", "territories"] and out["cubes"]["dates"]["joins"] == []
    assert next(p for p in out["panels"] if p["id"] == "trend")["drill"] == ["year", "month", "day"]


def test_ignore_filters_only_accepts_filters_and_the_period():
    errors = run(_set("top", "ignore_filters", ["period", "nope"]))
    assert errors == ["panel 'top' (bar): ignore_filters: no filter with id 'nope'"]


def test_pie_bar_and_treemap_can_name_their_measure_and_dimensions_in_your_language():
    spec = copy.deepcopy(GOOD)
    spec["panels"].append({"id": "p", "type": "pie", "sum": ["internet_sales.revenue", "reseller_sales.revenue"], "label": "Gelir", "by": "products.subcategory", "by_label": "Alt kategori"})
    panel(spec, "mix").update(label="Gelir", group_labels=["Kategori", "Alt kategori"])
    spec["panels"].append({"id": "b", "type": "bar", "measure": "internet_sales.revenue", "label": "Gelir", "by": "territories.region", "by_label": "Bölge"})
    spec["layout"] += [[{"p": 12}], [{"b": 12}]]
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used, CATALOG)
    assert next(p for p in out["panels"] if p["id"] == "p")["sum"] == ["internet_sales.revenue", "reseller_sales.revenue"]


@pytest.mark.parametrize("pie,needle", [
    ({"sum": ["internet_sales.revenue", "reseller_sales.revenue"]}, "needs exactly one of: measure, sum"),             # a sum needs its label
    ({"measure": "internet_sales.revenue", "sum": ["internet_sales.revenue", "reseller_sales.revenue"], "label": "x"}, "needs exactly one of: measure, sum"),
    ({"sum": ["internet_sales.revenue", "products.name"], "label": "x"}, "sum[1]"),
    ({"sum": ["internet_sales.revenue"], "label": "x"}, "sum:"),
    ({}, "needs exactly one of: measure, sum"),
])
def test_a_pie_has_a_measure_or_a_labelled_sum(pie, needle):
    errors = run(lambda s: (s["panels"].append({"id": "p", "type": "pie", "by": "products.category", **pie}), s["layout"].append([{"p": 12}])))
    assert errors and needle in "\n".join(errors), errors


# ---------------------------------------------------------------------------------------------------------------- table totals
@pytest.mark.parametrize("where", ["header", "footer"])
def test_a_table_total_validates_and_asks_for_the_whole_set_per_cube(where):
    spec = copy.deepcopy(GOOD)
    panel(spec, "lines")["totals"] = where
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used)
    lines = panel(out, "lines")
    assert lines["totals"] == where
    queries = panel_queries(out, lines, {"fy": "2021"})
    rows, total = queries[:-1], queries[-1]
    assert all("limit" in q["query"] for q in rows)
    assert "dimensions" not in total["query"] and "limit" not in total["query"] and "order" not in total["query"]
    assert total["query"]["measures"] == [m for m in total["query"]["measures"] if out["members"][m]["kind"] == "measure"]
    assert total["query"]["filters"] == rows[0]["query"]["filters"], "the total covers the same set as the rows"


def test_a_table_without_an_order_is_read_by_every_dimension_ascending():
    spec = copy.deepcopy(GOOD)
    del panel(spec, "lines")["order"]
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used)
    query = panel_queries(out, panel(out, "lines"), {})[0]["query"]
    assert query["order"] == {"internet_sales.order_number": "asc", "internet_sales.order_date": "asc", "territories.country": "asc"}


# ---------------------------------------------------------------------------------------------------------------- pivot panels
PIVOT = {"id": "xtab", "type": "pivot", "title": "Revenue by category and year", "rows": ["products.category"], "columns": "dates.fiscal_year",
         "measures": ["internet_sales.revenue"], "on_click": {"set_filter": ["category", "fy"]}}


def with_pivot(**changes):
    def f(spec):
        spec["panels"].append({**copy.deepcopy(PIVOT), **changes})
        spec["layout"].append([{"xtab": 12}])
    return f


def test_a_pivot_validates_and_compiles_its_measures_as_objects():
    spec = copy.deepcopy(GOOD)
    with_pivot(rows=["products.category", "products.subcategory"], measures=["internet_sales.revenue", {"member": "internet_sales.margin_pct", "label": "Margin", "format": "pct"}],
               totals="rows", order={"by": "label"}, limit={"rows": 10, "columns": 6})(spec)
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used)
    assert panel(out, "xtab")["measures"] == [{"member": "internet_sales.revenue"}, {"member": "internet_sales.margin_pct", "label": "Margin", "format": "pct"}]
    assert out["members"]["dates.fiscal_year"]["kind"] == "dimension" and out["members"]["internet_sales.revenue"]["kind"] == "measure"


PIVOT_BROKEN = [
    ("the same dimension down the side and across the top", with_pivot(columns="products.category"),
     ["panel 'xtab' (pivot)", "columns:", "also in `rows`"]),
    ("three row dimensions", with_pivot(rows=["products.category", "products.subcategory", "territories.region"]),
     ["panel 'xtab'", "rows:", "is too long"]),
    ("a row that repeats", with_pivot(rows=["products.category", "products.category"]), ["panel 'xtab'", "rows:", "non-unique"]),
    ("an unknown member", with_pivot(columns="dates.nope"), ["panel 'xtab' (pivot)", "columns:", "'dates.nope' is not in the Cube model"]),
    ("a measure where a dimension goes", with_pivot(columns="internet_sales.revenue"), ["panel 'xtab' (pivot)", "columns:", "is a measure, a dimension is needed"]),
    ("a dimension where a measure goes", with_pivot(measures=["products.category"]), ["panel 'xtab' (pivot)", "measures[0]:", "is a dimension, a measure is needed"]),
    ("no measures", with_pivot(measures=[]), ["panel 'xtab'", "measures:", "should be non-empty"]),
    ("four measures", with_pivot(measures=["internet_sales.revenue", "internet_sales.units", "internet_sales.orders", "internet_sales.margin_pct"]), ["panel 'xtab'", "measures:", "is too long"]),
    ("a bad totals value", with_pivot(totals="all"), ["panel 'xtab' (pivot)", "totals:", "'all' is not one of"]),
    ("a bad order", with_pivot(order={"by": "revenue"}), ["panel 'xtab' (pivot)", "order", "'revenue' is not one of"]),
    ("too many rows", with_pivot(limit={"rows": 500}), ["panel 'xtab' (pivot)", "limit", "greater than the maximum of 200"]),
    ("too many columns", with_pivot(limit={"columns": 40}), ["panel 'xtab' (pivot)", "limit", "greater than the maximum of 24"]),
    ("a click on a filter of a dimension the pivot does not show", with_pivot(on_click={"set_filter": ["region"]}),
     ["panel 'xtab' (pivot)", "on_click.set_filter:", "filter 'region' is on 'territories.region', which this pivot does not show"]),
    ("a click that names a bad filter id still gets the filter message", with_pivot(on_click={"set_filter": "Bad id"}), ["panel 'xtab' (pivot)", "on_click", "must be a filter id or a list of one or two filter ids"]),
    ("a column that is neither a member nor an object", with_pivot(columns="nope"), ["panel 'xtab' (pivot)", "columns", "must be a member ('cube.name') or an object { member, granularity }"]),
    ("a row share when the pivot has no row totals", with_pivot(show="share_of_row", totals="columns"),
     ["panel 'xtab' (pivot)", "show:", "'share_of_row' divides by a total for every row", "totals: 'columns'"]),
    ("a column share when the pivot has no column totals", with_pivot(show="share_of_column", totals="rows"),
     ["panel 'xtab' (pivot)", "show:", "'share_of_column' divides by a total for every column"]),
    ("a share of the total with no totals at all", with_pivot(show="share_of_total", totals="none"),
     ["panel 'xtab' (pivot)", "show:", "'share_of_total' divides by a grand total"]),
    ("a share of a ratio", with_pivot(show="share_of_total", measures=["internet_sales.margin_pct"]),
     ["panel 'xtab' (pivot)", "measures[0]:", "does not add up across rows and columns"]),
    ("a show that does not exist", with_pivot(show="percent"), ["panel 'xtab' (pivot)", "show:", "'percent' is not one of"]),
    ("a click on a filter that does not exist", with_pivot(on_click={"set_filter": ["ghost"]}), ["panel 'xtab'", "on_click.set_filter:", "no filter with id 'ghost'"]),
    ("a measure cube with no join to the dimension", with_pivot(measures=["inventory_health.stockout_items"], on_click={"set_filter": ["category"]}),
     ["panel 'xtab' (pivot)", "'inventory_health.stockout_items' cannot be combined with"]),
    ("a profit measure for a rep", lambda s: (with_pivot(measures=["internet_sales.margin_pct"])(s), s.update(roles=["rep"])),
     ["panel 'xtab' (pivot)", "role 'rep' cannot read 'internet_sales.margin_pct'"]),
    ("an unknown field", with_pivot(shade="yes"), ["panel 'xtab'", "'shade' is not a field of a pivot panel"]),
    ("a granularity on a dimension that is not a time dimension", with_pivot(columns={"member": "dates.fiscal_year", "granularity": "month"}),
     ["panel 'xtab' (pivot)", "columns.member:", "is a number dimension, a time dimension is needed"]),
    ("a time column without a granularity", with_pivot(columns={"member": "dates.full_date"}), ["panel 'xtab'", "columns", "'granularity' is a required property"]),
    ("a bad granularity", with_pivot(columns={"member": "dates.full_date", "granularity": "decade"}), ["panel 'xtab'", "columns", "'decade' is not one of"]),
    ("the time column also down the side", with_pivot(rows=["dates.full_date"], columns={"member": "dates.full_date", "granularity": "month"}, on_click={"set_filter": ["fy"]}),
     ["panel 'xtab' (pivot)", "columns:", "also in `rows`"]),
    ("heat on a measure the pivot does not show", with_pivot(heat={"measure": "internet_sales.units"}), ["panel 'xtab' (pivot)", "heat.measure:", "not one of the pivot's measures"]),
    ("heat without a measure", with_pivot(heat={}), ["panel 'xtab'", "heat", "'measure' is a required property"]),
    ("a click on a filter of the time column's year", with_pivot(columns={"member": "dates.full_date", "granularity": "month"}, on_click={"set_filter": ["fy"]}),
     ["panel 'xtab' (pivot)", "on_click.set_filter:", "filter 'fy' is on 'dates.fiscal_year', which this pivot does not show"]),
]


@pytest.mark.parametrize("name,mutate,needles", PIVOT_BROKEN, ids=[b[0] for b in PIVOT_BROKEN])
def test_a_broken_pivot_fails_with_a_message_that_names_the_place(name, mutate, needles):
    errors = run(mutate)
    assert errors, f"{name}: expected a problem"
    text = "\n".join(errors)
    for needle in needles:
        assert needle in text, f"{name}: {needle!r} missing from:\n{text}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is needed to run the renderer's query builders")
@pytest.mark.parametrize("changes", [
    {}, {"rows": ["products.category", "products.subcategory"]}, {"totals": "none"}, {"totals": "rows"}, {"totals": "columns"},
    {"order": {"by": "label"}}, {"order": {"dir": "asc"}, "limit": {"rows": 5, "columns": 3}},
    {"columns": {"member": "dates.full_date", "granularity": "month"}, "on_click": {"set_filter": ["category"]}},
    {"rows": ["products.category", "products.subcategory"], "columns": {"member": "dates.full_date", "granularity": "quarter"}, "totals": "columns", "on_click": {"set_filter": ["category"]}},
    {"heat": {"measure": "internet_sales.revenue"}},
    {"show": "share_of_row", "totals": "rows"},
    {"rows": ["products.category", "products.subcategory"], "measures": ["internet_sales.revenue", "reseller_sales.revenue"], "totals": "both"},
], ids=["plain", "two-levels", "no-totals", "row-totals", "column-totals", "by-label", "limits", "time-months", "time-quarters-two-levels", "heat", "share", "two-cubes"])
def test_python_pivot_queries_match_the_renderers(tmp_path, changes):
    spec = copy.deepcopy(GOOD)
    with_pivot(**changes)(spec)
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used, CATALOG)
    path = tmp_path / "p.json"
    path.write_text(json.dumps(out))
    dumped = json.loads(subprocess.run(["node", str(REPO / "dashboards/tests/dump_queries.mjs"), str(path)], capture_output=True, text=True, check=True).stdout)
    for state in dumped:
        assert panel_queries(out, panel(out, "xtab"), state["values"]) == state["panels"]["xtab"], f"under {state['values']}"


@pytest.mark.parametrize("show,totals", [("share_of_row", "both"), ("share_of_row", "rows"), ("share_of_column", "columns"), ("share_of_total", "rows"), ("share_of_total", "both")])
def test_a_share_validates_when_its_total_is_asked_for(show, totals):
    spec = copy.deepcopy(GOOD)
    with_pivot(show=show, totals=totals, measures=["internet_sales.revenue", "internet_sales.units"])(spec)
    assert validate(spec, CATALOG)[0] == []


# ---------------------------------------------------------------------------------------------------------------- tags
@pytest.mark.parametrize("tags", [["sales"], ["sales", "management"], ["satış", "ürün", "çok güzel"], ["2024-q1", "q1 review"], ["a", "b", "c", "d", "e"], ["x" * 24], []])
def test_good_tags_validate_and_reach_the_compiled_file(tags):
    spec = copy.deepcopy(GOOD)
    spec["tags"] = tags
    errors, used = validate(spec, CATALOG)
    assert errors == []
    assert compile_spec(spec, used)["tags"] == tags


TAG_BROKEN = [
    ("six tags", ["a", "b", "c", "d", "e", "f"], ["dashboard: tags:", "is too long"]),
    ("an empty tag", [""], ["dashboard: tags[0]:", "non-empty"]),
    ("a tag of 25 characters", ["x" * 25], ["dashboard: tags[0]:", "is too long"]),
    ("a tag twice", ["sales", "sales"], ["dashboard: tags:", "non-unique"]),
    ("capitals", ["Sales"], ["dashboard: tags[0]: 'Sales' is not lower case; write 'sales'"]),
    ("a Turkish capital", ["İş"], ["dashboard: tags[0]: 'İş' is not lower case"]),
    ("a space at the end", ["sales "], ["dashboard: tags[0]:", "spaces at its ends"]),
    ("two spaces in a row", ["a  b"], ["dashboard: tags[0]:", "two in a row"]),
    ("a comma", ["sales,hr"], ["dashboard: tags[0]:", "contains ','", "letters, digits, spaces and hyphens"]),
    ("markup", ["<b>"], ["dashboard: tags[0]:", "contains '<' '>'"]),
    ("a quote", ['a"b'], ["dashboard: tags[0]:", "contains '\"'"]),
    ("a new line", ["a\nb"], ["dashboard: tags[0]:", "contains '\\n'"]),
    ("an underscore", ["a_b"], ["dashboard: tags[0]:", "contains '_'"]),
    ("a hyphen first", ["-sales"], ["dashboard: tags[0]:", "must start with a letter or a digit"]),
    ("a number", [5], ["dashboard: tags[0]:", "is not of type 'string'"]),
    ("not a list", "sales", ["dashboard: tags:", "is not of type 'array'"]),
]


@pytest.mark.parametrize("name,tags,needles", TAG_BROKEN, ids=[b[0] for b in TAG_BROKEN])
def test_bad_tags_are_refused_with_a_message_that_says_what_to_write(name, tags, needles):
    spec = copy.deepcopy(GOOD)
    spec["tags"] = tags
    text = "\n".join(validate(spec, CATALOG)[0])
    assert text, name
    for needle in needles:
        assert needle in text, f"{name}: {needle!r} missing from:\n{text}"


def test_every_checked_in_dashboard_has_tags_and_the_index_lists_them():
    index = {d["id"]: d for d in json.loads((REPO / "dashboards" / "build" / "index.json").read_text())}
    for path in sorted((REPO / "dashboards").glob("*.yml")):
        spec = yaml.safe_load(path.read_text())
        assert spec.get("tags"), f"{path.name} has no tags"
        assert index[spec["id"]]["tags"] == spec["tags"]


def test_a_dashboard_without_tags_has_no_tags_key_in_the_index(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    spec = copy.deepcopy(GOOD)
    del spec["tags"]
    (src / "sales-overview.yml").write_text(yaml.safe_dump(spec, allow_unicode=True))
    assert main(["build", "--dir", str(src), "--out", str(out)]) == 0
    assert "tags" not in json.loads((out / "index.json").read_text())[0]


# ---------------------------------------------------------------------------------------------------------------- tabs
def tabbed(split=1, spec=None):
    """The sales-overview dashboard with its layout rows split over two tabs: the first `split` rows on 'overview', the rest on 'details'."""
    s = copy.deepcopy(spec or GOOD)
    rows = s.pop("layout")
    s["tabs"] = [{"id": "overview", "title": "Overview", "layout": rows[:split]}, {"id": "details", "title": "Details", "layout": rows[split:]}]
    return s


@pytest.mark.parametrize("split", [1, 2, 3])
def test_a_tabbed_dashboard_validates_and_compiles_each_tab_to_explicit_cells(split):
    spec = tabbed(split)
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used)
    assert "layout" not in out and [t["id"] for t in out["tabs"]] == ["overview", "details"]
    assert out["tabs"][0]["title"] == "Overview" and out["tabs"][0]["layout"][0] == [{"panel": "kpis", "span": 12}]
    assert sum(len(row) for t in out["tabs"] for row in t["layout"]) == sum(len(r) for r in GOOD["layout"]), "every cell is somewhere"
    json.dumps(out)


def test_a_plain_layout_still_compiles_to_a_layout_and_no_tabs():
    errors, used = validate(copy.deepcopy(GOOD), CATALOG)
    out = compile_spec(GOOD, used)
    assert errors == [] and "tabs" not in out and out["layout"][1] == [{"panel": "trend", "span": 8}, {"panel": "lines", "span": 4}]


def run_tabbed(mutate, split=1):
    spec = tabbed(split)
    mutate(spec)
    return validate(spec, CATALOG)[0]


TAB_BROKEN = [
    ("both layout and tabs", lambda s: s.update(layout=copy.deepcopy(GOOD["layout"])), ["dashboard:", "needs exactly one of: layout, tabs"]),
    ("neither layout nor tabs", lambda s: s.pop("tabs"), ["dashboard:", "needs exactly one of: layout, tabs"]),
    ("a panel on two tabs", lambda s: s["tabs"][1]["layout"].append([{"kpis": 12}]), ["tabs: panel 'kpis' is placed 2 times (tab 'overview' and tab 'details'), it must be placed once"]),
    ("a panel on no tab", lambda s: s["tabs"][1]["layout"].pop(), ["tabs: panel 'margin' is placed 0 times", "panel 'territories' is placed 0 times"]),
    ("a row that is not 12 wide on the second tab", lambda s: s["tabs"][1]["layout"].__setitem__(0, [{"trend": 8}, {"lines": 3}]), ["tab 'details': row 1: the widths add up to 11"]),
    ("a row that is not 12 wide on the first tab", lambda s: s["tabs"][0]["layout"].__setitem__(0, [{"kpis": 13}]), ["tabs[0]", "13 is greater than the maximum of 12"]),
    ("a panel that does not exist", lambda s: s["tabs"][1]["layout"].append([{"ghost": 12}]), ["tab 'details': row 4: no panel with id 'ghost'"]),
    ("two tabs with one id", lambda s: s["tabs"][1].update(id="overview"), ["tabs: id 'overview' is used by more than one tab"]),
    ("only one tab", lambda s: s.update(tabs=s["tabs"][:1]), ["dashboard: tabs:", "a dashboard has 2 to 8 tabs, this one has 1", "use `layout` for a single page"]),
    ("nine tabs", lambda s: s.update(tabs=[{"id": f"t{i}", "title": "T", "layout": [[{"kpis": 12}]]} for i in range(9)]), ["a dashboard has 2 to 8 tabs, this one has 9"]),
    ("a tab with no title", lambda s: s["tabs"][0].update(title=""), ["dashboard: tabs[0].title:", "non-empty"]),
    ("a tab with a title of 41 characters", lambda s: s["tabs"][0].update(title="x" * 41), ["tabs[0].title:", "is too long"]),
    ("a tab without a layout", lambda s: s["tabs"][0].pop("layout"), ["tabs[0]", "'layout' is a required property"]),
    ("a tab with an empty layout", lambda s: s["tabs"][0].update(layout=[]), ["tabs[0].layout", "non-empty"]),
    ("a tab with a field that is not one", lambda s: s["tabs"][0].update(icon="x"), ["tabs[0]", "'icon' was unexpected"]),
    ("a tab id that is not an id", lambda s: s["tabs"][0].update(id="Over View"), ["tabs[0].id:", "does not match"]),
    ("a tab that is not an object", lambda s: s.update(tabs=["a", "b"]), ["tabs[0]", "is not of type 'object'"]),
]


@pytest.mark.parametrize("name,mutate,needles", TAB_BROKEN, ids=[b[0] for b in TAB_BROKEN])
def test_a_broken_tab_setup_fails_with_a_message_that_names_the_place(name, mutate, needles):
    errors = run_tabbed(mutate)
    assert errors, f"{name}: expected a problem"
    text = "\n".join(errors)
    for needle in needles:
        assert needle in text, f"{name}: {needle!r} missing from:\n{text}"


def test_the_panels_are_still_checked_on_a_tab_roles_included():
    spec = tabbed(2)
    spec["roles"] = ["admin", "rep"]                    # a rep may not read profit: the KPI row has it, whichever tab it is on
    text = "\n".join(validate(spec, CATALOG)[0])
    assert "panel 'kpis' (kpi): role 'rep' cannot read" in text
    spec = tabbed(2)
    panel(spec, "top")["by"] = "products.nme"
    assert "panel 'top' (bar): by: 'products.nme' is not in the Cube model" in "\n".join(validate(spec, CATALOG)[0])


def test_every_filter_still_applies_across_tabs_so_a_filter_error_is_reported_once():
    spec = tabbed(2)
    spec["panels"].append({"id": "stock", "type": "kpi", "measures": [{"member": "inventory_health.stockout_items"}]})
    spec["tabs"][1]["layout"].append([{"stock": 12}])
    text = "\n".join(validate(spec, CATALOG)[0])
    assert text.count("panel 'stock' (kpi): 'inventory_health.stockout_items' cannot be combined with 'territories.region'") == 1


def test_lint_and_the_queries_do_not_care_about_tabs():
    errors, used = validate(tabbed(2), CATALOG)
    assert errors == []
    out = compile_spec(tabbed(2), used, CATALOG)
    flat = compile_spec(GOOD, validate(copy.deepcopy(GOOD), CATALOG)[1], CATALOG)
    for p in out["panels"]:
        assert panel_queries(out, p, {"fy": "2021"}) == panel_queries(flat, panel(flat, p["id"]), {"fy": "2021"}), p["id"]


def test_a_checked_in_dashboard_uses_tabs_so_the_real_path_is_exercised_as_well_as_the_plain_one():
    specs = {p.stem: yaml.safe_load(p.read_text()) for p in (REPO / "dashboards").glob("*.yml")}
    tabbed_ones = {k: v for k, v in specs.items() if "tabs" in v}
    assert "pivot-gallery" in tabbed_ones and len(tabbed_ones["pivot-gallery"]["tabs"]) == 3
    assert any("layout" in v for v in specs.values()), "and some dashboards keep a plain layout"
    built = json.loads((REPO / "dashboards" / "build" / "pivot-gallery.json").read_text())
    assert "layout" not in built and [t["id"] for t in built["tabs"]] == ["overview", "groups", "heat"]
    placed = [c["panel"] for t in built["tabs"] for row in t["layout"] for c in row]
    assert sorted(placed) == sorted(p["id"] for p in built["panels"]), "every panel is on one tab"


# ---- colour rules on key figures and table measure columns
RULES = [{"when": "below", "value": 0.2, "tone": "bad"}, {"when": "at_least", "value": 0.3, "tone": "good"}]


def _kpi_rules(rules):
    def f(spec):
        panel(spec, "kpis")["measures"][2]["rules"] = rules
    return f


def _column_rules(member, rules):
    def f(spec):
        cols = panel(spec, "lines")["columns"]
        next(c for c in cols if isinstance(c, dict) and c["member"] == member)["rules"] = rules
    return f


def test_colour_rules_on_a_key_figure_and_a_table_measure_validate_and_reach_the_renderer():
    spec = copy.deepcopy(GOOD)
    _kpi_rules(RULES)(spec)
    _column_rules("internet_sales.revenue", [{"when": "above", "value": 1000, "tone": "good"}])(spec)
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used)
    assert panel(out, "kpis")["measures"][2]["rules"] == RULES
    assert panel(out, "lines")["columns"][3]["rules"] == [{"when": "above", "value": 1000, "tone": "good"}]


@pytest.mark.parametrize("rules,needle", [
    ([], "rules"), ([{"when": "below", "value": 1, "tone": "bad"}] * 5, "rules"),
    ([{"when": "under", "value": 1, "tone": "bad"}], "under"), ([{"when": "below", "value": "x", "tone": "bad"}], "x"),
    ([{"when": "below", "value": 1, "tone": "purple"}], "purple"), ([{"when": "below", "value": 1}], "tone"),
    ([{"when": "below", "value": 1, "tone": "bad", "color": "red"}], "color"),
])
def test_bad_colour_rules_are_refused_naming_the_problem(rules, needle):
    errors = run(_kpi_rules(rules))
    assert errors and any(needle in e for e in errors), errors


def test_rules_belong_on_a_measure_column_not_a_dimension_or_a_pivot():
    dim = run(_column_rules("territories.country", RULES))
    assert any("territories.country" in e and "not a measure" in e for e in dim), dim

    def pivot(spec):
        spec["panels"].append({"id": "pv", "type": "pivot", "rows": ["products.category"], "columns": "dates.fiscal_year",
                               "measures": [{"member": "internet_sales.revenue", "rules": RULES}]})
        spec["layout"].append([{"pv": 12}])
    errors = run(pivot)
    assert any("pv" in e and "heat" in e for e in errors), errors


# ---- an inline logo
import base64 as _b64

PNG = _b64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40).decode()
JPEG = _b64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 40).decode()
WEBP = _b64.b64encode(b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 20).decode()


@pytest.mark.parametrize("uri", [f"data:image/png;base64,{PNG}", f"data:image/jpeg;base64,{JPEG}", f"data:image/webp;base64,{WEBP}"])
def test_an_inline_logo_of_a_real_image_type_is_accepted_and_compiled(uri):
    spec = copy.deepcopy(GOOD)
    spec["theme"] = {"logo": uri}
    errors, used = validate(spec, CATALOG)
    assert errors == []
    assert compile_spec(spec, used)["theme"]["logo"] == uri


@pytest.mark.parametrize("logo,needle", [
    ("data:image/svg+xml;base64," + _b64.b64encode(b"<svg onload=alert(1)/>").decode(), "theme.logo"),
    ("data:text/html;base64," + _b64.b64encode(b"<script>").decode(), "theme.logo"),
    ("data:image/png;base64," + _b64.b64encode(b"<script>alert(1)</script>").decode(), "not really a PNG"),
    ("data:image/jpeg;base64," + PNG, "not really a JPEG"),
    ("data:image/webp;base64," + _b64.b64encode(b"RIFF\x10\x00\x00\x00WAVEfmt ").decode(), "not really a WEBP"),
    ("data:image/png;base64,@@@", "theme.logo"),
    ("data:image/png;base64," + "A" * 20001, "theme.logo"),
])
def test_an_inline_logo_that_is_not_what_it_says_is_refused(logo, needle):
    errors = run(lambda s: s.update(theme={"logo": logo}))
    assert errors and needle in "\n".join(errors), errors


# ---- filter types
def _filters(*fs):
    def f(spec):
        spec["filters"] = [*spec["filters"], *fs]
    return f


@pytest.mark.parametrize("flt", [
    {"id": "m", "dimension": "products.category", "type": "multiselect", "default": "in:Bikes,Clothing"},
    {"id": "m", "dimension": "products.category", "type": "multiselect", "default": "not:Clothing"},
    {"id": "t", "dimension": "products.name", "type": "text", "default": "contains:bike"},
    {"id": "d", "dimension": "dates.full_date", "type": "date", "default": "rel:last_30_days"},
    {"id": "d", "dimension": "dates.full_date", "type": "date", "default": "between:2024-01-01..2024-03-31"},
    {"id": "d", "dimension": "dates.full_date", "type": "date"},
    {"id": "n", "dimension": "dates.fiscal_year", "label": "Year", "type": "select", "default": "2021"},
])
def test_the_filter_types_validate(flt):
    assert run(_filters(flt)) == []


@pytest.mark.parametrize("flt,needle", [
    ({"id": "d", "dimension": "products.category", "type": "date"}, "needs a time dimension"),
    ({"id": "n", "dimension": "products.category", "type": "number"}, "needs a number dimension"),
    ({"id": "t", "dimension": "dates.full_date", "type": "text"}, "needs a string dimension"),
    ({"id": "d", "dimension": "dates.full_date", "type": "date", "default": "rel:last_5_hours"}, "not a value of a date filter"),
    ({"id": "d", "dimension": "dates.full_date", "type": "date", "default": "contains:x"}, "not a value of a date filter"),
    ({"id": "m", "dimension": "products.category", "type": "multiselect", "default": "Bikes"}, "not a value of a multiselect filter"),
    ({"id": "m", "dimension": "products.category", "type": "multiselect", "default": "between:5..1"}, "not a value of a multiselect filter"),
    ({"id": "x", "dimension": "products.category", "type": "slider"}, "type"),
    ({"id": "x", "dimension": "products.category", "default": ""}, "default"),
    ({"id": "t", "dimension": "products.name", "type": "text", "parent": "products.category"}, "only a select or multiselect"),
])
def test_a_filter_that_does_not_fit_its_type_is_refused(flt, needle):
    errors = run(_filters(flt))
    assert errors and any(needle in e for e in errors), errors


def test_a_parent_must_be_a_plain_select_and_a_click_can_only_set_a_select():
    errors = run(_filters({"id": "grp", "dimension": "territories.group_name", "type": "multiselect"}))        # the region filter's parent is this one
    assert any("must be a plain select" in e for e in errors), errors

    def click(spec):
        next(f for f in spec["filters"] if f["id"] == "region")["type"] = "multiselect"          # the territories table's click sets it
    errors = run(click)
    assert any("can only set a select filter" in e for e in errors), errors


# ---- where a filter applies, and hidden filters
def _tabbed(spec):
    """The sales overview split into two tabs: its first two rows on tab a, the rest on tab b."""
    spec["tabs"] = [{"id": "a", "title": "A", "layout": spec["layout"][:2]}, {"id": "b", "title": "B", "layout": spec["layout"][2:]}]
    del spec["layout"]


def _add(*fs, tabbed=False):
    def f(spec):
        if tabbed:
            _tabbed(spec)
        spec["filters"] = [*spec["filters"], *fs]
    return f


@pytest.mark.parametrize("flt,tabbed", [
    ({"id": "pg", "dimension": "products.category", "scope": "page", "tab": "a"}, True),
    ({"id": "pn", "dimension": "products.category", "scope": "panel", "panel": "kpis"}, False),
    ({"id": "hid", "dimension": "territories.region", "visible": False, "default": "France"}, False),
    ({"id": "hidp", "dimension": "products.category", "scope": "panel", "panel": "lines", "visible": False, "default": "Bikes"}, False),
])
def test_filter_scopes_and_hidden_filters_validate(flt, tabbed):
    assert run(_add(flt, tabbed=tabbed)) == []


@pytest.mark.parametrize("flt,tabbed,needle", [
    ({"id": "p", "dimension": "products.category", "scope": "page", "tab": "a"}, False, "has no tabs"),
    ({"id": "p", "dimension": "products.category", "scope": "page"}, True, "must say which tab"),
    ({"id": "p", "dimension": "products.category", "scope": "page", "tab": "zzz"}, True, "no tab with id 'zzz'"),
    ({"id": "p", "dimension": "products.category", "tab": "a"}, True, "only a page filter"),
    ({"id": "p", "dimension": "products.category", "scope": "panel"}, False, "must say which panel"),
    ({"id": "p", "dimension": "products.category", "scope": "panel", "panel": "zzz"}, False, "no panel with id 'zzz'"),
    ({"id": "p", "dimension": "products.category", "panel": "kpis"}, False, "only a pane filter"),
    ({"id": "h", "dimension": "products.category", "visible": False}, False, "needs a `default`"),
    ({"id": "h", "dimension": "products.category", "visible": False, "default": "Bikes", "parent": "products.category"}, False, "no list to narrow"),
    ({"id": "p", "dimension": "products.category", "scope": "everywhere"}, False, "scope"),
])
def test_a_filter_scope_that_does_not_make_sense_is_refused(flt, tabbed, needle):
    errors = run(_add(flt, tabbed=tabbed))
    assert errors and any(needle in e for e in errors), errors


def test_clicks_cannot_set_a_hidden_filter_or_another_panels_pane_filter():
    def hidden(spec):
        next(f for f in spec["filters"] if f["id"] == "region")["visible"] = False
        next(f for f in spec["filters"] if f["id"] == "region")["default"] = "France"
        next(f for f in spec["filters"] if f["id"] == "region").pop("parent", None)
    assert any("is hidden; a click cannot change it" in e for e in run(hidden))

    def pane(spec):
        next(f for f in spec["filters"] if f["id"] == "region").update(scope="panel", panel="kpis")
    assert any("only a click on that panel can set it" in e for e in run(pane))


def test_a_filter_is_only_joined_with_the_panels_it_applies_to():
    """A pane filter on a dimension that panel's measures cannot join to is a mistake; the same filter on another panel is not the panel's business."""
    inv = {"id": "st", "dimension": "inventory_health.status", "scope": "panel", "panel": "kpis"}
    errors = run(_add(inv))
    assert any("kpis" in e and "inventory_health" in e for e in errors), errors
    assert not any("panel 'trend'" in e and "inventory_health" in e for e in errors), errors


def test_scoped_and_hidden_filters_reach_the_same_queries_in_python_and_the_renderer(tmp_path):
    spec = copy.deepcopy(GOOD)
    _tabbed(spec)
    spec["filters"] = [*spec["filters"],
                       {"id": "pg", "dimension": "products.name", "scope": "page", "tab": "b", "label": "Page only"},
                       {"id": "pn", "dimension": "territories.country", "scope": "panel", "panel": "territories"},
                       {"id": "hid", "dimension": "territories.group_name", "visible": False, "default": "Europe"}]
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    path = tmp_path / "s.json"
    path.write_text(json.dumps(out))
    dumped = json.loads(subprocess.run(["node", str(REPO / "dashboards/tests/dump_queries.mjs"), str(path)], capture_output=True, text=True, check=True).stdout)
    assert len(dumped) >= 4
    for state in dumped:
        for p in out["panels"]:
            assert panel_queries(out, p, state["values"]) == state["panels"][p["id"]], f"{p['id']} under {state['values']}"
    # and the scopes mean what they say
    state = next(s for s in dumped if s["values"].get("pg") == "y" and s["values"].get("pn") == "y")
    members = lambda pid: {f["member"]: f["values"] for q in _queries(state["panels"][pid]) for f in q.get("filters", [])}
    tab_a, tab_b = members("kpis"), members("mix")          # `kpis` is on tab a, `mix` on tab b
    assert "products.name" not in tab_a and tab_b["products.name"] == ["y"], "the page filter narrows tab b's panels only"
    assert "territories.country" not in tab_b and "territories.country" not in tab_a and members("territories")["territories.country"] == ["y"], "the pane filter narrows its own panel only"
    assert tab_a["territories.group_name"] == ["Europe"] == tab_b["territories.group_name"], "the hidden filter holds its default on every panel, whatever the address says"


def _queries(panel_queries_out):
    """Every Cube query inside whatever a panel's builder returned (a list, or a dict of lists)."""
    if isinstance(panel_queries_out, dict):
        if "measures" in panel_queries_out or "dimensions" in panel_queries_out:
            return [panel_queries_out]
        return [q for v in panel_queries_out.values() for q in _queries(v)]
    if isinstance(panel_queries_out, list):
        return [q for v in panel_queries_out for q in _queries(v)]
    return []


# ---- the slicer
def _slicer(fid="category", **extra):
    def f(spec):
        spec["panels"].append({"id": "sl", "type": "slicer", "filter": fid, **extra})
        spec["layout"].append([{"sl": 12}])
    return f


@pytest.mark.parametrize("extra", [{}, {"display": "chips"}, {"display": "dropdown"}, {"title": "Pick a category"}])
def test_a_slicer_validates(extra):
    assert run(_slicer(**extra)) == []


def _hide_category(spec):
    next(f for f in spec["filters"] if f["id"] == "category").update(visible=False, default="Bikes")


def _second_slicer(spec):
    spec["panels"].append({"id": "sl2", "type": "slicer", "filter": "category"})
    spec["layout"].append([{"sl2": 12}])


def _category_as_text(spec):
    next(f for f in spec["filters"] if f["id"] == "category")["type"] = "text"
    next(p for p in spec["panels"] if p["id"] == "sl")["display"] = "list"


@pytest.mark.parametrize("mutate,needle", [
    (_slicer("nope"), "no filter with id 'nope'"),
    (_slicer(display="grid"), "display"),
    (lambda s: (_slicer()(s), _hide_category(s)), "is hidden"),
    (lambda s: (_slicer()(s), _second_slicer(s)), "already drawn by the slicer"),
    (lambda s: (_slicer()(s), _category_as_text(s)), "only a select or multiselect"),
], ids=["unknown-filter", "bad-display", "hidden", "two-slicers", "text-filter-list"])
def test_a_slicer_that_does_not_make_sense_is_refused(mutate, needle):
    errors = run(mutate)
    assert errors and any(needle in e for e in errors), errors


def test_a_slicer_for_a_page_filter_sits_on_its_tab():
    def tabbed(spec):
        _tabbed(spec)
        spec["filters"].append({"id": "pg", "dimension": "products.name", "scope": "page", "tab": "b"})
        spec["panels"].append({"id": "sl", "type": "slicer", "filter": "pg"})
        spec["tabs"][0]["layout"].append([{"sl": 12}])          # tab a: the wrong tab
    assert any("must sit on that tab" in e for e in run(tabbed))

    def right(spec):
        _tabbed(spec)
        spec["filters"].append({"id": "pg", "dimension": "products.name", "scope": "page", "tab": "b"})
        spec["panels"].append({"id": "sl", "type": "slicer", "filter": "pg"})
        spec["tabs"][1]["layout"].append([{"sl": 12}])
    assert run(right) == []


def test_slicer_options_are_queried_with_the_other_filters_and_the_period_but_not_their_own_filter(tmp_path):
    spec = copy.deepcopy(GOOD)
    _slicer("category")(spec)
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used, CATALOG)
    path = tmp_path / "s.json"
    path.write_text(json.dumps(out))
    dumped = json.loads(subprocess.run(["node", str(REPO / "dashboards/tests/dump_queries.mjs"), str(path)], capture_output=True, text=True, check=True).stdout)
    for state in dumped:
        assert panel_queries(out, panel(out, "sl"), state["values"]) == state["panels"]["sl"], f"under {state['values']}"
    both = next(s for s in dumped if s["values"].get("category") == "y" and s["values"].get("fy") == "y")
    qs = [q["query"] for q in both["panels"]["sl"]]
    assert qs and all(q["dimensions"] == ["products.category"] for q in qs)
    assert all(any(f["member"] == "dates.fiscal_year" for f in q["filters"]) for q in qs), "another filter narrows the options"
    assert all(all(f["member"] != "products.category" for f in q["filters"]) for q in qs), "its own filter does not"
    period = next(s for s in dumped if s["values"].get("_period"))
    assert any(q["query"].get("timeDimensions") for q in period["panels"]["sl"]), "a drill-down's period narrows them"


# ---- cross_filter: a click filters the other panels with no filter written
def _cross(pid, mode=True, **extra):
    def f(spec):
        panel(spec, pid)["cross_filter"] = mode
        panel(spec, pid).pop("on_click", None)
        panel(spec, pid).update(extra)
    return f


def test_cross_filter_validates_and_the_compiler_writes_the_filters_and_the_click_rule():
    spec = copy.deepcopy(GOOD)
    _cross("top")(spec)                      # a bar by products.name: no explicit filter on that field
    errors, used = validate(spec, CATALOG)
    assert errors == []
    assert "cross_filter" not in json.dumps(compile_spec(spec, used, CATALOG)["panels"]), "the renderer never sees it"
    out = compile_spec(spec, used, CATALOG)
    made = [f for f in out["filters"] if f.get("implicit") and f["source"] == "top"]
    assert [(f["id"], f["dimension"], f["source"]) for f in made] == [("xf_top_1", "products.name", "top")]
    assert panel(out, "top")["on_click"] == {"set_filter": ["xf_top_1"]}
    assert not any(f["id"].startswith("xf_") for f in spec["filters"]) and "on_click" not in panel(spec, "top"), "the source is not touched"


def test_an_existing_visible_select_filter_on_the_field_is_used_instead():
    spec = copy.deepcopy(GOOD)
    _cross("territories")(spec)              # a bar by territories.region, and there is a `region` filter
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used, CATALOG)
    assert not [f for f in out["filters"] if f.get("implicit") and f["dimension"] == "territories.region"]
    assert panel(out, "territories")["on_click"] == {"set_filter": ["region"]}


def test_a_treemap_carries_its_groups_in_order_and_page_scope_makes_page_filters():
    spec = copy.deepcopy(GOOD)
    _tabbed(spec)
    spec["filters"] = [f for f in spec["filters"] if f["id"] not in ("category", "subcategory")]
    _cross("mix", "page")(spec)
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    made = [f for f in out["filters"] if f.get("implicit") and f["source"] == "mix"]
    assert [f["dimension"] for f in made] == ["products.category", "products.subcategory"]
    assert all(f["scope"] == "page" and f["tab"] == "b" for f in made), "the tab of the treemap"
    assert panel(out, "mix")["on_click"] == {"set_filter": ["xf_mix_1", "xf_mix_2"]}


def test_panels_that_cannot_join_to_the_made_filter_ignore_it():
    spec = copy.deepcopy(GOOD)
    spec["panels"].append({"id": "stock", "type": "bar", "measure": "inventory_health.stockout_items", "by": "inventory_health.status", "cross_filter": True, "ignore_filters": ["fy", "region", "category", "subcategory"]})
    spec["layout"].append([{"stock": 12}])
    spec["roles"] = ["admin"]
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    assert "xf_stock_1" in panel(out, "kpis")["ignore_filters"], "sales panels cannot be combined with an inventory status"
    assert "xf_stock_1" not in panel(out, "stock").get("ignore_filters", []) and panel(out, "stock")["on_click"] == {"set_filter": ["xf_stock_1"]}


@pytest.mark.parametrize("mutate,needle", [
    (lambda s: panel(s, "top").update(cross_filter=True, on_click={"set_filter": "category"}), "not together with on_click"),
    (lambda s: panel(s, "top").update(cross_filter="page"), "has no tabs"),
    (lambda s: panel(s, "top").update(cross_filter="everywhere"), "cross_filter"),
    (lambda s: panel(s, "trend").update(cross_filter=True), "cross_filter"),
    (lambda s: panel(s, "kpis").update(cross_filter=True), "cross_filter"),
    (lambda s: s["filters"].append({"id": "xf_mine", "dimension": "products.name"}), "made by cross_filter"),
], ids=["with-on-click", "page-without-tabs", "bad-value", "time-chart", "kpi", "reserved-id"])
def test_a_cross_filter_that_does_not_make_sense_is_refused(mutate, needle):
    errors = run(mutate)
    assert errors and any(needle in e for e in errors), errors


def test_the_python_queries_and_the_renderers_agree_on_a_dashboard_with_cross_filter(tmp_path):
    spec = copy.deepcopy(GOOD)
    _cross("top")(spec)
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used, CATALOG)
    path = tmp_path / "x.json"
    path.write_text(json.dumps(out))
    dumped = json.loads(subprocess.run(["node", str(REPO / "dashboards/tests/dump_queries.mjs"), str(path)], capture_output=True, text=True, check=True).stdout)
    for state in dumped:
        for p in out["panels"]:
            assert panel_queries(out, p, state["values"]) == state["panels"][p["id"]], f"{p['id']} under {state['values']}"
    narrowed = next(s for s in dumped if s["values"].get("xf_top_1") == "y")
    assert not any(f["member"] == "products.name" for q in narrowed["panels"]["top"] for f in q["query"]["filters"]), "the clicked panel keeps showing every mark"
    assert any(f["member"] == "products.name" for q in narrowed["panels"]["trend"] for f in q["query"]["filters"]), "the others are narrowed"


# ---- table fields with an aggregate (Power BI style): groups, and values summarised over the rows of each group
def _inventory_table(columns, **extra):
    def f(spec):
        spec["roles"] = ["admin"]
        spec["panels"].append({"id": "inv", "type": "table", "columns": columns, "ignore_filters": ["fy", "region", "category", "subcategory"], **extra})
        spec["layout"].append([{"inv": 12}])
    return f


AGG_COLUMNS = ["inventory_health.status", {"member": "inventory_health.on_hand", "aggregate": "sum"}, {"member": "inventory_health.unit_cost", "aggregate": "avg", "label": "Average cost"},
               {"member": "inventory_health.vendor_name", "aggregate": "count_distinct"}, "inventory_health.stockout_items"]


def test_a_table_with_aggregated_fields_validates_and_compiles_the_row_key():
    spec = copy.deepcopy(GOOD)
    _inventory_table(AGG_COLUMNS, totals="footer")(spec)
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    assert out["rowKeys"] == {"inventory_health": "inventory_health.key"}
    queries = panel_queries(out, panel(out, "inv"), {})
    grouped = queries[0]["query"]
    assert grouped["dimensions"] == ["inventory_health.status"] and "order" not in grouped, "the measures are grouped by the key columns only and ordered here"
    assert queries[-1]["query"].get("dimensions") is None and queries[-1]["query"]["measures"] == ["inventory_health.stockout_items"], "and the total row is a query of its own"
    agg = next(q["query"] for q in queries if q["cube"] == "agg:inventory_health")
    assert agg["dimensions"] == ["inventory_health.status", "inventory_health.key", "inventory_health.on_hand", "inventory_health.unit_cost", "inventory_health.vendor_name"]
    assert agg["order"] == {"inventory_health.key": "asc"} and agg["limit"] == 20000 and "measures" not in agg


def test_an_aggregated_field_is_not_a_key_for_clicks():
    spec = copy.deepcopy(GOOD)
    _inventory_table(AGG_COLUMNS, cross_filter=True)(spec)
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    made = [f for f in out["filters"] if f.get("implicit") and f["source"] == "inv"]
    assert [f["dimension"] for f in made] == ["inventory_health.status"], "only the group column is carried by a click"


@pytest.mark.parametrize("columns,needle", [
    (["inventory_health.status", {"member": "inventory_health.stockout_items", "aggregate": "sum"}], "has its aggregation built in"),
    (["inventory_health.status", {"member": "inventory_health.status", "aggregate": "sum"}], "sum needs a number field"),
    (["inventory_health.vendor_name", {"member": "inventory_health.on_hand", "aggregate": "median"}], "aggregate"),
    (["products.name", {"member": "inventory_health.on_hand", "aggregate": "sum"}, {"member": "internet_sales.order_status", "aggregate": "max"}], "must come from one cube"),
    ([{"member": "inventory_health.on_hand", "aggregate": "sum"}, "territories.region"], "no join to 'territories'"),
    ([{"member": "inventory_health.on_hand", "aggregate": "sum"}, {"member": "inventory_health.on_hand", "aggregate": "max"}], "aggregated twice"),
], ids=["measure", "sum-of-text", "bad-name", "two-cubes", "unreachable-key", "twice"])
def test_an_aggregate_that_does_not_make_sense_is_refused(columns, needle):
    errors = run(_inventory_table(columns))
    assert errors and any(needle in e for e in errors), errors


def test_python_and_renderer_queries_agree_on_a_table_with_aggregated_fields(tmp_path):
    spec = copy.deepcopy(GOOD)
    _inventory_table(AGG_COLUMNS, totals="footer")(spec)
    spec["panels"].append({"id": "inv2", "type": "table", "ignore_filters": ["fy", "region", "category", "subcategory"],
                           "columns": [{"member": "inventory_health.on_hand", "aggregate": "max"}, {"member": "inventory_health.status", "aggregate": "first"}]})
    spec["layout"].append([{"inv2": 12}])
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    path = tmp_path / "a.json"
    path.write_text(json.dumps(out))
    dumped = json.loads(subprocess.run(["node", str(REPO / "dashboards/tests/dump_queries.mjs"), str(path)], capture_output=True, text=True, check=True).stdout)
    for state in dumped:
        for pid in ("inv", "inv2"):
            assert panel_queries(out, panel(out, pid), state["values"]) == state["panels"][pid], f"{pid} under {state['values']}"
    only_values = dumped[0]["panels"]["inv2"]
    assert len(only_values) == 1 and only_values[0]["query"]["dimensions"] == ["inventory_health.key", "inventory_health.on_hand", "inventory_health.status"], "no group column: one query, the cube's key and the fields"


# ---- a text field that sorts by another (a month's name by its number): `meta.sort_by` in the Cube model
def test_the_model_says_a_months_name_sorts_by_its_number_and_the_compiled_file_carries_it():
    assert CATALOG.sort_by("dates.month_name") == "dates.month_of_year" and CATALOG.sort_by("dates.fiscal_year") is None and CATALOG.sort_by("nope.x") is None
    spec = copy.deepcopy(GOOD)
    spec["panels"].append({"id": "bm", "type": "table", "columns": ["dates.month_name", "internet_sales.revenue"]})
    spec["layout"].append([{"bm": 12}])
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used, CATALOG)
    assert out["members"]["dates.month_name"] == {"kind": "dimension", "type": "string", "sort_by": "dates.month_of_year"}
    assert "sort_by" not in out["members"]["internet_sales.revenue"]


def test_python_and_renderer_queries_agree_where_a_field_sorts_by_another(tmp_path):
    spec = copy.deepcopy(GOOD)
    spec["filters"].append({"id": "mo", "dimension": "dates.month_name", "label": "Month"})
    spec["panels"] += [
        {"id": "bm", "type": "table", "columns": ["dates.month_name", "internet_sales.revenue"], "order": {"dates.month_name": "desc"}},
        {"id": "bm2", "type": "table", "columns": ["dates.month_name", "internet_sales.revenue", "reseller_sales.revenue"]},
        {"id": "pv", "type": "pivot", "rows": ["dates.month_name"], "columns": "territories.region", "measures": ["internet_sales.revenue"], "order": {"by": "label"}},
        {"id": "pv2", "type": "pivot", "rows": ["products.category"], "columns": "dates.month_name", "measures": ["internet_sales.revenue"]},
        {"id": "sl", "type": "slicer", "filter": "mo"},
    ]
    spec["layout"] += [[{"bm": 6}, {"bm2": 6}], [{"pv": 6}, {"pv2": 6}], [{"sl": 12}]]
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    path = tmp_path / "m.json"
    path.write_text(json.dumps(out))
    dumped = json.loads(subprocess.run(["node", str(REPO / "dashboards/tests/dump_queries.mjs"), str(path)], capture_output=True, text=True, check=True).stdout)
    for state in dumped:
        for pid in ("bm", "bm2", "pv", "pv2", "sl"):
            assert panel_queries(out, panel(out, pid), state["values"]) == state["panels"][pid], f"{pid} under {state['values']}"
    first = dumped[0]["panels"]
    assert first["bm"][0]["query"]["order"] == {"dates.month_of_year": "desc"} and first["bm"][0]["query"]["dimensions"] == ["dates.month_name", "dates.month_of_year"]
    assert first["pv"][0]["query"]["order"]["dates.month_of_year"] == "asc", "a pivot's rows ordered by label are in month order"
    assert first["sl"][0]["query"]["dimensions"] == ["dates.month_name", "dates.month_of_year"], "a filter's list asks for the number too"


# ---- sort_by in the semantic model: one standard, checked
def test_every_sort_by_in_the_model_points_to_a_number_or_time_dimension_of_its_own_cube():
    assert cat.sort_by_problems(CATALOG) == []
    assert {m for m in ("dates.month_name", "dates.year_month", "dates.quarter_name", "dates.year_quarter", "dates.fiscal_quarter_name", "dates.day_name") if CATALOG.sort_by(m)} == {
        "dates.month_name", "dates.year_month", "dates.quarter_name", "dates.year_quarter", "dates.fiscal_quarter_name", "dates.day_name"}
    assert CATALOG.sort_by("dates.year_month") == "dates.year_month_number" and CATALOG.sort_by("dates.quarter_name") == "dates.calendar_quarter"


def test_a_sort_by_that_is_not_a_proper_sort_field_is_reported():
    def model(**sort_by):
        return cat.Catalog({"c": {"measures": {}, "dimensions": {"name": "string", "num": "number", "txt": "string", "other": "string", "t": "time"}, "joins": set(), "sort_by": sort_by, "docs": {}}})
    assert cat.sort_by_problems(model(name="num", other="t")) == []
    assert any("the field itself" in p for p in cat.sort_by_problems(model(name="name")))
    assert any("not a dimension of the cube" in p for p in cat.sort_by_problems(model(name="missing")))
    assert any("must be a number or a time" in p for p in cat.sort_by_problems(model(name="txt")))
    assert any("no chains" in p for p in cat.sort_by_problems(model(name="num", num="t")))


def test_the_semantic_layer_shows_what_a_field_sorts_by():
    from dashspec.semantic import catalog_json, generate
    dims = {d["member"]: d for c in catalog_json(CATALOG) if c["cube"] == "dates" for d in c["dimensions"]}
    assert dims["dates.month_name"]["sort_by"] == "dates.month_of_year" and "sort_by" not in dims["dates.month_of_year"]
    assert "Sorted by `dates.year_month_number`." in generate(CATALOG)


# ---- role-playing dates: ship_dates and due_dates are the calendar again, joined by the fact's own key
def test_the_date_roles_have_the_calendars_fields_sorting_and_a_label_with_the_role_in_front():
    for role, prefix in (("ship_dates", "Ship"), ("due_dates", "Due")):
        assert CATALOG.cubes[role]["dimensions"] == CATALOG.cubes["dates"]["dimensions"] and CATALOG.cubes[role]["extends"] == "dates"
        assert CATALOG.cubes[role]["primary_key"] == "key" and CATALOG.reachable("internet_sales", role) and CATALOG.reachable("reseller_sales", role)
        assert CATALOG.sort_by(f"{role}.year_month") == f"{role}.year_month_number", "a role sorts by its own sort field"
        assert CATALOG.label(f"{role}.month_name") == f"{prefix} month name" and CATALOG.label(f"{role}.fiscal_year") == f"{prefix} fiscal year"
    assert CATALOG.label("dates.month_name") is None, "the order date keeps its plain names"
    assert "ship_dates" not in CATALOG.cubes["dates"]["joins"] and cat.sort_by_problems(CATALOG) == []


def test_a_dashboard_can_run_on_the_ship_date_and_its_fields_carry_the_role_in_their_label():
    spec = copy.deepcopy(GOOD)
    spec["time"]["dimension"] = "ship_dates.full_date"
    panel(spec, "trend").pop("on_click")                 # it set the order date's fiscal year; a click on a ship-date axis may only set the ship date's
    spec["panels"].append({"id": "by_ship_month", "type": "table", "columns": ["ship_dates.month_name", "dates.month_name", "internet_sales.revenue"]})
    spec["layout"].append([{"by_ship_month": 12}])
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    assert out["members"]["ship_dates.month_name"] == {"kind": "dimension", "type": "string", "sort_by": "ship_dates.month_of_year", "label": "Ship month name"}
    assert out["members"]["dates.month_name"] == {"kind": "dimension", "type": "string", "sort_by": "dates.month_of_year"}
    assert out["cubes"]["internet_sales"]["joins"].count("ship_dates") == 1


def test_the_semantic_layer_says_what_a_date_role_is():
    from dashspec.semantic import catalog_json, generate
    ship = next(c for c in catalog_json(CATALOG) if c["cube"] == "ship_dates")
    assert ship["extends"] == "dates" and ship["label_prefix"] == "Ship" and next(d for d in ship["dimensions"] if d["name"] == "month_name")["label"] == "Ship month name"
    assert 'A role of `dates`' in generate(CATALOG)


# ---- a time axis of the panel's own (the ship date while the dashboard follows the order date)
def _ship_chart(spec, **extra):
    spec["panels"] += [
        {"id": "ship_trend", "type": "timeseries", "time_dimension": "ship_dates.full_date", "series": [{"member": "internet_sales.revenue", "label": "Revenue"}], "granularity": "month", "style": "line", **extra},
        {"id": "ship_kpi", "type": "kpi", "time_dimension": "ship_dates.full_date", "measures": [{"member": "internet_sales.revenue", "label": "Revenue"}], "sparkline": {"granularity": "month"}},
    ]
    spec["layout"] += [[{"ship_trend": 8}, {"ship_kpi": 4}]]


def test_a_chart_and_a_sparkline_can_follow_the_ship_date():
    spec = copy.deepcopy(GOOD)
    _ship_chart(spec)
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    assert panel(out, "ship_trend")["time_dimension"] == "ship_dates.full_date" and "ship_dates.full_date" in out["members"] and "ship_dates" in out["cubes"]
    q = panel_queries(out, panel(out, "ship_trend"), {})[0]["query"]
    assert q["timeDimensions"] == [{"dimension": "ship_dates.full_date", "granularity": "month"}]
    k = [x["query"] for x in panel_queries(out, panel(out, "ship_kpi"), {}) if "timeDimensions" in x["query"]][0]
    assert k["timeDimensions"][0]["dimension"] == "ship_dates.full_date"
    assert panel_queries(out, panel(out, "trend"), {})[0]["query"]["timeDimensions"][0]["dimension"] == "dates.full_date", "the others keep the dashboard's date"


@pytest.mark.parametrize("mutate,needle", [
    (lambda s: _ship_chart(s, time_dimension="dates.fiscal_year"), "time_dimension"),
    (lambda s: (_ship_chart(s), panel(s, "ship_trend").update(time_dimension="nope.x")), "not in the Cube model"),
    (lambda s: (_ship_chart(s), panel(s, "ship_kpi").pop("sparkline")), "only has a time axis with a `sparkline`"),
    (lambda s: (_ship_chart(s), panel(s, "ship_trend").update(on_click={"set_filter": "fy"})), "same date field"),
], ids=["not-a-time-field", "unknown", "kpi-without-sparkline", "year-filter-of-another-date"])
def test_a_panel_time_dimension_that_does_not_make_sense_is_refused(mutate, needle):
    errors = run(mutate)
    assert errors and any(needle in e for e in errors), errors


def test_a_period_belongs_to_a_date_field_and_python_and_the_renderer_agree(tmp_path):
    spec = copy.deepcopy(GOOD)
    _ship_chart(spec)
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    path = tmp_path / "p.json"
    path.write_text(json.dumps(out))
    dumped = json.loads(subprocess.run(["node", str(REPO / "dashboards/tests/dump_queries.mjs"), str(path)], capture_output=True, text=True, check=True).stdout)
    for state in dumped:
        for p in out["panels"]:
            assert panel_queries(out, p, state["values"]) == state["panels"][p["id"]], f"{p['id']} under {state['values']}"
    order = next(s for s in dumped if s["values"].get("_period") == "2021-03-01..2021-03-31")
    ship = next(s for s in dumped if "_period:ship_dates.full_date" in s["values"])
    in_range = lambda queries, dim: any(t.get("dimension") == dim and t.get("dateRange") for q in queries for t in q["query"].get("timeDimensions", []))
    assert in_range(order["panels"]["top"], "dates.full_date") and not in_range(order["panels"]["ship_trend"], "ship_dates.full_date"), "the order-date period narrows panels on the order date, not the ship-date chart"
    assert in_range(ship["panels"]["ship_trend"], "ship_dates.full_date") and not in_range(ship["panels"]["top"], "dates.full_date"), "a ship-date period narrows the ship-date chart and not the order-date panels"


# ---- cross-filtering is the default: every panel that can carry a click does, on its page
def _made(out, source):
    return [f for f in out["filters"] if f.get("implicit") and f["source"] == source]


def test_a_panel_that_says_nothing_cross_filters_its_page_by_default():
    spec = copy.deepcopy(GOOD)
    panel(spec, "lines").pop("cross_filter", None)                       # the sample's orders table opts in; this test is about a panel that says nothing
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used, CATALOG)
    top = panel(out, "top")                                              # a bar by products.name, no on_click in the file
    assert "on_click" not in panel(spec, "top") and top["on_click"] == {"set_filter": ["xf_top_1"]}, "the click rule is made at compile time; the file is not touched"
    assert [(f["dimension"], f.get("scope")) for f in _made(out, "top")] == [("products.name", None)], "no tabs: the whole page is the whole dashboard, no scope"
    assert "cross_filter" not in json.dumps(out["panels"]) and "cross_filter" not in json.dumps(spec["panels"])
    assert "on_click" not in panel(out, "kpis") and not _made(out, "kpis"), "key figures have no mark to click"
    assert panel(out, "territories")["on_click"] == {"set_filter": "region"}, "a click rule written in the file is left alone"
    assert panel(out, "trend")["on_click"] == {"set_filter": "fy"}, "and so is the time chart's, which already sets the fiscal year"


def test_on_a_tabbed_dashboard_the_default_is_the_panels_own_tab_and_true_is_every_tab():
    spec = copy.deepcopy(GOOD)
    _tabbed(spec)
    panel(spec, "top")["cross_filter"] = True
    spec["panels"].append({"id": "cats", "type": "bar", "measure": "internet_sales.revenue", "by": "products.color"})
    spec["tabs"][0]["layout"].append([{"cats": 12}])                      # tab a
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    assert [(f["scope"], f["tab"]) for f in _made(out, "cats")] == [("page", "a")], "a panel that says nothing: its tab (cats is on tab a)"
    assert [f.get("scope") for f in _made(out, "top")] == [None], "cross_filter: true: every tab"


def test_cross_filter_false_turns_it_off_and_an_on_click_wins_over_the_default():
    spec = copy.deepcopy(GOOD)
    panel(spec, "top")["cross_filter"] = False
    errors, used = validate(spec, CATALOG)
    assert errors == []
    out = compile_spec(spec, used, CATALOG)
    assert "on_click" not in panel(out, "top") and not _made(out, "top") and "cross_filter" not in panel(out, "top")


def test_a_click_carries_all_the_dimension_values_of_the_mark_and_only_a_drilling_chart_is_left_out():
    spec = copy.deepcopy(GOOD)
    spec["filters"] = []
    for p in spec["panels"]:
        p.pop("on_click", None)
    spec["panels"] += [
        {"id": "three", "type": "table", "cross_filter": True, "columns": ["territories.region", "territories.country", "products.name", "internet_sales.revenue"]},          # three group columns
        {"id": "bymonth", "type": "bar", "measure": "internet_sales.revenue", "by": "dates.full_date"},                                                  # a time field
        {"id": "withdate", "type": "table", "cross_filter": True, "columns": ["internet_sales.order_number", "internet_sales.order_date", "territories.country", "internet_sales.revenue"]},
        {"id": "drilly", "type": "timeseries", "series": [{"member": "internet_sales.revenue", "label": "R"}], "granularity": "year", "drill": ["year", "month"]},
    ]
    spec["layout"] += [[{"three": 3}, {"bymonth": 3}, {"withdate": 3}, {"drilly": 3}]]
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    by_id = {f["id"]: f["dimension"] for f in out["filters"]}
    carried_by = lambda pid: [by_id[i] for i in panel(out, pid)["on_click"]["set_filter"]]
    assert carried_by("three") == ["territories.region", "territories.country", "products.name"], "no limit of two: every group column of the row"
    assert carried_by("withdate") == ["internet_sales.order_number", "internet_sales.order_date", "territories.country"], "the order number and the date are part of the row's values too"
    assert carried_by("bymonth") == ["dates.full_date"]
    assert panel(out, "three")["on_click"]["set_filter"][1] == panel(out, "withdate")["on_click"]["set_filter"][2], "two panels that carry the same field share one filter: a click on either shows in both"
    assert "on_click" not in panel(out, "drilly") and not _made(out, "drilly"), "a time chart that drills down keeps its drill-down"


def test_a_table_does_not_cross_filter_unless_it_says_so():
    spec = copy.deepcopy(GOOD)
    spec["filters"] = []
    for p in spec["panels"]:
        p.pop("on_click", None)
    spec["panels"] += [{"id": "plain", "type": "table", "columns": ["territories.country", "internet_sales.revenue"]},
                       {"id": "chosen", "type": "table", "cross_filter": True, "columns": ["territories.country", "internet_sales.revenue"]}]
    spec["layout"] += [[{"plain": 6}, {"chosen": 6}]]
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    assert "on_click" not in panel(out, "plain") and not _made(out, "plain"), "a table that says nothing leaves the other panels alone"
    assert panel(out, "chosen")["on_click"]["set_filter"], "cross_filter: true turns it on"


def test_a_hidden_column_is_there_to_sort_by_and_is_not_carried_by_a_click():
    spec = copy.deepcopy(GOOD)
    spec["filters"] = []
    for p in spec["panels"]:
        p.pop("on_click", None)
    panel(spec, "lines")["columns"] = [{"member": "internet_sales.order_number", "label": "Order"}, {"member": "internet_sales.order_date", "hidden": True}, "internet_sales.revenue"]
    panel(spec, "lines")["limit"] = 20
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    assert [by["dimension"] for by in _made(out, "lines")] == ["internet_sales.order_number"], "the click carries the shown field only"
    bad = copy.deepcopy(spec)
    panel(bad, "lines")["columns"][1]["aggregate"] = "max"
    assert any("hidden" in e and "aggregate" in e for e in validate(bad, CATALOG)[0])
    allhid = copy.deepcopy(spec)
    allhid_cols = [{"member": c if isinstance(c, str) else c["member"], "hidden": True} for c in panel(allhid, "lines")["columns"]]
    panel(allhid, "lines")["columns"] = allhid_cols
    assert any("every column is `hidden`" in e for e in validate(allhid, CATALOG)[0])


def test_a_pivot_and_a_time_chart_cross_filter_by_default_too():
    spec = copy.deepcopy(GOOD)
    spec["filters"] = [f for f in spec["filters"] if f["id"] != "fy"]
    panel(spec, "trend").pop("on_click")
    spec["panels"].append({"id": "pv", "type": "pivot", "rows": ["products.category"], "columns": "territories.region", "measures": ["internet_sales.revenue"]})
    spec["layout"].append([{"pv": 12}])
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    assert panel(out, "pv")["on_click"] == {"set_filter": ["category", "region"]}, "a pivot cell carries its row and its column (the dashboard's own filters on those fields are used)"
    assert [f["dimension"] for f in _made(out, "trend")] == ["dates.fiscal_year"], "a time chart sets the fiscal year of its date field"


def test_explicit_cross_filter_on_a_panel_that_cannot_carry_a_click_is_refused():
    def drilling(spec):
        t = panel(spec, "trend")
        t.pop("on_click")
        t.update(cross_filter=True, drill=["year", "month"], granularity="year")
        t.pop("granularities", None)
    errors = run(drilling)
    assert any("opens the next level" in e for e in errors), errors
    errors = run(lambda s: panel(s, "kpis").update(cross_filter=True))
    assert errors and any("cross_filter" in e for e in errors), errors


# ---------------------------------------------------------------------------------------------------------------- calculations
from dashspec import calculations as calc_mod  # noqa: E402

AVG = "sum(internet_sales.revenue, reseller_sales.revenue) / sum(internet_sales.units, reseller_sales.units)"


def with_calcs(spec=None):
    spec = copy.deepcopy(spec or GOOD)
    spec["calculations"] = [{"id": "avg_price", "label": "Average sales price", "formula": AVG, "format": "money"},
                            {"id": "tax", "label": "Tax amount", "formula": "(internet_sales.revenue + reseller_sales.revenue) * 0.2"}]
    return spec


def test_a_formula_is_read_into_a_tree_and_worked_out_with_missing_parts_skipped():
    tree = calc_mod.parse("sum(internet_sales.revenue + reseller_sales.revenue) / sum(internet_sales.units, reseller_sales.units) * 2 - -1")
    assert calc_mod.members_of(tree) == ["internet_sales.revenue", "reseller_sales.revenue", "internet_sales.units", "reseller_sales.units"]
    value = {"internet_sales.revenue": 10, "reseller_sales.revenue": 30, "internet_sales.units": 2, "reseller_sales.units": 2}.get
    assert calc_mod.evaluate(tree, value) == 21
    assert calc_mod.evaluate(tree, {"internet_sales.revenue": 10, "internet_sales.units": 2}.get) == 11, "a part with no value is skipped in a sum"
    assert calc_mod.evaluate(calc_mod.parse("a.x / b.y"), {"a.x": 1, "b.y": 0}.get) is None, "division by zero has no value"
    assert calc_mod.evaluate(calc_mod.parse("a.x * 2"), {}.get) is None, "a product needs both sides"
    for bad in ["", "a.x +", "revenue", "(a.x", "a.x $ 2", "sum(a.x", "a.x b.y"]:
        with pytest.raises(calc_mod.FormulaError):
            calc_mod.parse(bad)


def test_every_panel_type_can_use_a_calculation_and_the_page_asks_cube_for_its_parts():
    spec = with_calcs()
    spec["filters"] = []
    for p in spec["panels"]:
        p.pop("on_click", None)
    spec["panels"] += [
        {"id": "ckpi", "type": "kpi", "measures": [{"member": "calc.avg_price"}, {"member": "calc.tax"}], "sparkline": {"granularity": "month"}},
        {"id": "cbar", "type": "bar", "measure": "calc.avg_price", "by": "products.category", "limit": 5},
        {"id": "cstack", "type": "bar", "stack": [{"member": "calc.tax"}, {"member": "internet_sales.revenue"}], "by": "products.category"},
        {"id": "cpie", "type": "pie", "measure": "calc.tax", "by": "products.category"},
        {"id": "ctree", "type": "treemap", "measure": "calc.tax", "group": ["products.category"]},
        {"id": "ctab", "type": "table", "columns": ["products.category", "calc.avg_price", "calc.tax"], "order": {"calc.avg_price": "desc"}, "limit": 10, "totals": "footer"},
        {"id": "cpiv", "type": "pivot", "rows": ["products.category"], "columns": "territories.group_name", "measures": ["calc.avg_price"]},
        {"id": "cts", "type": "timeseries", "series": [{"member": "calc.avg_price", "label": "Price"}], "granularity": "month"},
    ]
    spec["layout"] += [[{"ckpi": 12}], [{"cbar": 6}, {"cstack": 6}], [{"cpie": 4}, {"ctree": 4}, {"cts": 4}], [{"ctab": 6}, {"cpiv": 6}]]
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    assert out["members"]["calc.avg_price"]["calc"]["members"] == ["internet_sales.revenue", "reseller_sales.revenue", "internet_sales.units", "reseller_sales.units"]
    assert out["members"]["calc.avg_price"]["label"] == "Average sales price"
    assert panel(out, "ctab")["columns"][1]["format"] == "money" and "format" not in panel(out, "ctab")["columns"][2], "the calculation's own format is the default"
    assert panel(out, "cbar")["format"] == "money"
    bar = panel_queries(out, panel(out, "cbar"), {})
    assert [q["cube"] for q in bar] == ["internet_sales", "reseller_sales"], "Cube is asked for the measures a calculation reads, one query per cube"
    assert all("calc.avg_price" not in json.dumps(q["query"]) and "limit" not in q["query"] and "order" not in q["query"] for q in bar)
    assert bar[0]["post"]["order"] == {"calc.avg_price": "desc"} and bar[0]["post"]["limit"] == 5
    path = None
    import pathlib, tempfile  # noqa: E401
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "calc.json"
        path.write_text(json.dumps(out))
        dumped = json.loads(subprocess.run(["node", str(REPO / "dashboards/tests/dump_queries.mjs"), str(path)], capture_output=True, text=True, check=True).stdout)
    assert dumped
    for state in dumped:
        for p in out["panels"]:
            assert panel_queries(out, p, state["values"]) == state["panels"][p["id"]], f"{p['id']} under {state['values']}"


CALC_BROKEN = [
    ("a formula that does not read", lambda s: s["calculations"][0].update(formula="sum(internet_sales.revenue"), ["calculation 'avg_price': formula: expected ')'"]),
    ("an unknown measure", lambda s: s["calculations"][0].update(formula="internet_sales.nope / 2"), ["calculation 'avg_price': formula: 'internet_sales.nope' is not in the Cube model"]),
    ("a dimension in a formula", lambda s: s["calculations"][0].update(formula="products.name * 2"), ["calculation 'avg_price': formula: 'products.name' is a dimension, a measure is needed here"]),
    ("a calculation of a calculation", lambda s: s["calculations"][0].update(formula="calc.tax * 2"), ["calculation 'avg_price': formula: 'calc.tax' is a calculation"]),
    ("an id used twice", lambda s: s["calculations"][1].update(id="avg_price"), ["dashboard: calculations: id 'avg_price' is used by more than one calculation"]),
    ("a calculation that does not exist", lambda s: s["panels"].append({"id": "bad", "type": "table", "columns": ["products.category", "calc.nope"]}) or s["layout"].append([{"bad": 12}]),
     ["panel 'bad' (table): columns[1]: 'calc.nope' is not in the Cube model (calculations: calc.avg_price, calc.tax)"]),
    ("a calculation that cannot join to a column", lambda s: s["panels"].append({"id": "bad", "type": "table", "columns": ["internet_sales.order_number", "calc.avg_price"]}) or s["layout"].append([{"bad": 12}]),
     ["panel 'bad' (table): 'reseller_sales.revenue' cannot be combined with 'internet_sales.order_number'"]),
    ("a calculation of what the role cannot read", lambda s: (s.update(roles=["rep"]), s["calculations"][0].update(formula="internet_sales.gross_profit / internet_sales.revenue")) and None,
     ["role 'rep' cannot read 'internet_sales.gross_profit' (profit and margin are hidden from reps)"]),
]


@pytest.mark.parametrize("name,mutate,expected", CALC_BROKEN, ids=[c[0] for c in CALC_BROKEN])
def test_a_broken_calculation_fails_with_a_message_that_names_the_place(name, mutate, expected):
    spec = with_calcs()
    spec["panels"].append({"id": "uses", "type": "table", "columns": ["products.category", "calc.avg_price"]})
    spec["layout"].append([{"uses": 12}])
    mutate(spec)
    errors, _ = validate(spec, CATALOG)
    text = "\n".join(errors)
    assert errors and all(e in text for e in expected), text


def test_a_bar_can_be_ordered_by_the_name_of_its_grouping_in_the_groupings_own_order(tmp_path):
    spec = copy.deepcopy(GOOD)
    spec["panels"] += [{"id": "byname", "type": "bar", "measure": "internet_sales.revenue", "by": "dates.month_name", "sort_by": "label", "sort": "asc", "limit": 12},
                       {"id": "bystack", "type": "bar", "stack": [{"member": "internet_sales.revenue"}, {"member": "reseller_sales.revenue"}], "by": "dates.month_name", "sort_by": "label"}]
    spec["layout"] += [[{"byname": 6}, {"bystack": 6}]]
    errors, used = validate(spec, CATALOG)
    assert errors == [], errors
    out = compile_spec(spec, used, CATALOG)
    (q,) = panel_queries(out, panel(out, "byname"), {})
    assert q["query"]["order"] == {"dates.month_of_year": "asc"} and q["query"]["dimensions"] == ["dates.month_name", "dates.month_of_year"], "a month's name is ordered by its number, which the query asks for"
    stack = panel_queries(out, panel(out, "bystack"), {})
    assert all("order" not in x["query"] and "dates.month_of_year" in x["query"]["dimensions"] for x in stack), "a stack is ordered by the page, after the totals are known"
    path = tmp_path / "b.json"
    path.write_text(json.dumps(out))
    dumped = json.loads(subprocess.run(["node", str(REPO / "dashboards/tests/dump_queries.mjs"), str(path)], capture_output=True, text=True, check=True).stdout)
    for state in dumped:
        for pid in ("byname", "bystack"):
            assert panel_queries(out, panel(out, pid), state["values"]) == state["panels"][pid]
    bad = copy.deepcopy(spec)
    panel(bad, "byname")["sort_by"] = "size"
    assert validate(bad, CATALOG)[0]
