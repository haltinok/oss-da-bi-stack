"""A slicer on a field (`dimension:`, PLAN-slicer-fields.md phase 1a): the validator's rules, and the filter the compiler makes for it.

  PYTHONPATH=dashboards uv run --with pytest --with pyyaml --with 'jsonschema>=4.18' python -m pytest dashboards/tests/test_slicers.py -q
"""
import copy
import json
import pathlib
import shutil
import subprocess

import pytest
import yaml

from dashspec import catalog as cat
from dashspec.compile import compile_spec
from dashspec.queries import panel_queries
from dashspec.validate import validate

REPO = pathlib.Path(__file__).resolve().parents[2]
GOOD = yaml.safe_load((REPO / "dashboards" / "sales-overview.yml").read_text())      # filters fy, region, category, subcategory; no tabs
CATALOG = cat.from_model(REPO / "cube" / "model")


def tabbed(spec):
    """The sales overview split into two tabs: its first two rows on tab a, the rest on tab b."""
    spec["tabs"] = [{"id": "a", "title": "A", "layout": spec["layout"][:2]}, {"id": "b", "title": "B", "layout": spec["layout"][2:]}]
    del spec["layout"]


def with_slicer(spec, pid="colour", tab=None, **fields):
    spec["panels"].append({"id": pid, "type": "slicer", **({"dimension": "products.color"} | fields)})
    rows = next(t["layout"] for t in spec["tabs"] if t["id"] == tab) if tab else spec["layout"]
    rows.append([{pid: 12}])
    return spec


def check(spec):
    errors, used = validate(spec, CATALOG)
    return errors, used


def compiled(spec):
    errors, used = check(spec)
    assert errors == [], errors
    return compile_spec(spec, used, CATALOG), used


def by_id(items, id_):
    return next(x for x in items if x["id"] == id_)


# ---- what it becomes
def test_a_slicer_on_a_field_becomes_a_slicer_of_a_filter_made_for_it():
    out, used = compiled(with_slicer(copy.deepcopy(GOOD)))
    assert by_id(out["filters"], "sl_colour") == {"id": "sl_colour", "dimension": "products.color", "label": "Color", "source": "colour"}
    assert by_id(out["panels"], "colour") == {"id": "colour", "type": "slicer", "filter": "sl_colour"}
    assert "products.color" in used, "the field counts as one the dashboard reads (who may open it goes by those)"


def test_its_label_is_the_authors_when_given():
    out, _ = compiled(with_slicer(copy.deepcopy(GOOD), label="Colour", display="chips"))
    assert by_id(out["filters"], "sl_colour")["label"] == "Colour" and by_id(out["panels"], "colour") == {"id": "colour", "type": "slicer", "filter": "sl_colour", "display": "chips"}


def test_on_a_dashboard_with_tabs_it_narrows_only_its_own_tab():
    spec = copy.deepcopy(GOOD)
    tabbed(spec)
    out, _ = compiled(with_slicer(spec, tab="b"))
    assert by_id(out["filters"], "sl_colour") == {"id": "sl_colour", "dimension": "products.color", "label": "Color", "source": "colour", "scope": "page", "tab": "b"}


def test_a_panel_of_its_tab_that_cannot_be_filtered_by_the_field_leaves_it_out():
    spec = copy.deepcopy(GOOD)
    spec["panels"].append({"id": "stock", "type": "kpi", "measures": [{"member": "inventory_health.stockout_items"}], "ignore_filters": ["fy", "region", "category", "subcategory"]})
    spec["layout"].append([{"stock": 12}])
    out, _ = compiled(with_slicer(spec, dimension="territories.country"))
    assert "sl_colour" in by_id(out["panels"], "stock")["ignore_filters"], "inventory does not join territories"
    assert "sl_colour" not in by_id(out["panels"], "kpis").get("ignore_filters", [])


def test_a_click_on_a_chart_by_the_same_field_sets_the_slicer():
    spec = copy.deepcopy(GOOD)
    out, _ = compiled(with_slicer(spec, pid="product", dimension="products.name"))
    assert by_id(out["panels"], "top")["on_click"] == {"set_filter": ["sl_product"]}, "the cross-filtering reuses the slicer's filter, so the slicer shows the click"


def test_the_source_file_is_not_changed_by_validating_or_compiling():
    spec = with_slicer(copy.deepcopy(GOOD))
    before = copy.deepcopy(spec)
    compiled(spec)
    assert spec == before


# ---- what is refused
@pytest.mark.parametrize("fields,needle", [
    ({"dimension": "products.nope"}, "is not in the Cube model"),
    ({"dimension": "internet_sales.revenue"}, "a dimension is needed here"),
    ({"dimension": "products.color", "filter": "category"}, "needs exactly one of: filter, dimension"),
    ({"dimension": "products.category"}, "the filter 'category' already narrows these panels by 'products.category'; draw it as a slicer with `filter: category`"),
    ({"dimension": "inventory_health.status"}, "can be filtered by 'inventory_health.status', so the slicer would narrow nothing"),
], ids=["unknown-field", "a-measure", "both-filter-and-dimension", "a-header-filter-has-it", "narrows-nothing"])
def test_a_field_slicer_that_does_not_make_sense_is_refused(fields, needle):
    spec = copy.deepcopy(GOOD)
    spec["panels"].append({"id": "colour", "type": "slicer", **fields})
    spec["layout"].append([{"colour": 12}])
    errors, _ = check(spec)
    assert errors and any(needle in e for e in errors), errors


def test_neither_a_filter_nor_a_field_is_refused():
    spec = copy.deepcopy(GOOD)
    spec["panels"].append({"id": "colour", "type": "slicer"})
    spec["layout"].append([{"colour": 12}])
    errors, _ = check(spec)
    assert errors and any("panel 'colour' (slicer)" in e and "needs exactly one of: filter, dimension" in e for e in errors), errors


def test_two_slicers_on_one_field_for_the_same_panels_are_refused_but_on_two_tabs_they_are_fine():
    spec = with_slicer(with_slicer(copy.deepcopy(GOOD)), pid="colour2")
    errors, _ = check(spec)
    assert any("panel 'colour2'" in e and "the slicer 'colour' already narrows these panels" in e for e in errors), errors
    spec = copy.deepcopy(GOOD)
    tabbed(spec)
    errors, _ = check(with_slicer(with_slicer(spec, tab="a"), pid="colour2", tab="b"))
    assert errors == [], errors


def test_a_header_filter_of_another_tab_does_not_stop_a_slicer_on_the_same_field():
    spec = copy.deepcopy(GOOD)
    tabbed(spec)
    spec["filters"].append({"id": "col", "dimension": "products.color", "scope": "page", "tab": "a"})
    errors, _ = check(with_slicer(spec, tab="b"))
    assert errors == [], errors
    errors, _ = check(with_slicer(spec, pid="colour_a", tab="a"))
    assert any("the filter 'col' already narrows these panels" in e for e in errors), errors


def test_a_hidden_filter_on_the_field_is_not_a_second_control():
    spec = copy.deepcopy(GOOD)
    spec["filters"].append({"id": "col", "dimension": "products.color", "visible": False, "default": "Red"})
    errors, _ = check(with_slicer(spec))
    assert errors == [], errors


def test_a_files_own_filter_may_not_take_the_ids_made_for_slicers():
    spec = copy.deepcopy(GOOD)
    spec["filters"].append({"id": "sl_x", "dimension": "products.color"})
    errors, _ = check(spec)
    assert any("ids starting with 'sl_' are made for slicers on a field" in e for e in errors), errors


# ---- the browser's code asks the same
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_python_and_the_renderer_ask_cube_the_same_for_a_field_slicer(tmp_path):
    out, _ = compiled(with_slicer(copy.deepcopy(GOOD), display="chips"))
    path = tmp_path / "s.json"
    path.write_text(json.dumps(out))
    dumped = json.loads(subprocess.run(["node", str(REPO / "dashboards/tests/dump_queries.mjs"), str(path)], capture_output=True, text=True, check=True).stdout)
    for state in dumped:
        for p in out["panels"]:
            assert panel_queries(out, p, state["values"]) == state["panels"][p["id"]], f"{p['id']} under {state['values']}"
    options = dumped[0]["panels"]["colour"]
    assert options and all("products.color" in q["query"]["dimensions"] for q in options), "the slicer asks for the colours"
    narrowed = next(s for s in dumped if s["values"].get("sl_colour"))
    assert any(f["member"] == "products.color" for q in narrowed["panels"]["kpis"] for f in q["query"].get("filters", [])), "a chosen colour narrows the key figures"
