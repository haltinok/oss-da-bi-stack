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
    assert admin["internet_sales"]["joins"] == ["customers", "dates", "products", "territories"] and admin["internet_sales"]["fact"]


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
    assert out["cubes"]["internet_sales"]["joins"] == ["customers", "dates", "products", "territories"] and out["cubes"]["dates"]["joins"] == []
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
