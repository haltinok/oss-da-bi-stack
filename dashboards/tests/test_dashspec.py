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
    ("unknown cube", lambda s: panel(s, "top").update(measure="sales.revenue"),
     ["panel 'top' (bar)", "measure:", "'sales.revenue' is not in the Cube model", "cubes:"]),
    ("dimension used as a measure", lambda s: panel(s, "top").update(measure="products.name"),
     ["panel 'top'", "measure:", "is a dimension, a measure is needed"]),
    ("measure used as a dimension", lambda s: panel(s, "top").update(by="internet_sales.revenue"),
     ["panel 'top'", "by:", "is a measure, a dimension is needed"]),
    ("measure in a series, wrong index named", lambda s: panel(s, "trend")["series"].append({"member": "products.name"}),
     ["panel 'trend' (timeseries)", "series[2].member", "is a dimension"]),
    ("bad granularity", _set("trend", "granularity", "fortnight"),
     ["panel 'trend' (timeseries)", "granularity:", "'fortnight' is not one of"]),
    ("unknown panel type", _set("top", "type", "pie"),
     ["panel 'top' (pie)", "type:", "'pie' is not one of"]),
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
     ["panel 'trend'", "on_click.set_filter", "carries 1 value(s)"]),
    ("ignore_filters names an unknown filter", _set("top", "ignore_filters", ["nope"]),
     ["panel 'top'", "ignore_filters:", "no filter with id 'nope'"]),
    ("table order on a column that is not shown", _set("lines", "order", {"internet_sales.units": "desc"}),
     ["panel 'lines' (table)", "order.internet_sales.units", "not one of the table's columns"]),
    ("layout row not 12 wide", lambda s: s["layout"].__setitem__(1, [{"trend": 8}, {"lines": 3}]),
     ["layout:", "row 2", "add up to 11"]),
    ("layout names an unknown panel", lambda s: s["layout"].append([{"ghost": 12}]),
     ["layout:", "no panel with id 'ghost'"]),
    ("panel missing from the layout", lambda s: s["layout"].pop(),
     ["layout:", "panel 'mix' is placed 0 times", "panel 'top' is placed 0 times"]),
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
    assert run(add) == []


def test_a_bad_panel_type_is_reported_once_not_as_noise():
    errors = run(_set("top", "type", "pie"))
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
    cols = compile_spec(copy.deepcopy(GOOD), used)["panels"][4]["columns"]
    assert cols[0] == {"member": "internet_sales.order_number", "label": "Order"}
    spec = copy.deepcopy(GOOD)
    panel(spec, "lines")["columns"] = ["internet_sales.order_number", "internet_sales.revenue"]
    assert compile_spec(spec, used)["panels"][4]["columns"] == [{"member": "internet_sales.order_number"}, {"member": "internet_sales.revenue"}]


def test_build_writes_each_dashboard_and_an_index(tmp_path, capsys):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    (src / "sales-overview.yml").write_text((REPO / "dashboards" / "sales-overview.yml").read_text())
    assert main(["build", "--dir", str(src), "--out", str(out)]) == 0
    assert json.loads((out / "sales-overview.json").read_text())["id"] == "sales-overview"
    index = json.loads((out / "index.json").read_text())
    assert index == [{"id": "sales-overview", "title": "Sales overview", "description": GOOD["description"], "roles": ["admin", "manager"]}]
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
