"""Every model the repo ships (cube/model, and models/<name>/cube) loads, and every dashboard written for it validates and compiles against it.

The guard rail of PLAN-decouple.md: a second, deliberately different model keeps the app from learning the first one.
  PYTHONPATH=dashboards uv run --with pytest --with pyyaml --with 'jsonschema>=4.18' python -m pytest dashboards/tests/test_models.py -q
"""
import json
import pathlib

import pytest
import yaml

from dashspec import catalog as cat
from dashspec.compile import compile_spec
from dashspec.validate import validate

REPO = pathlib.Path(__file__).resolve().parents[2]


def models():
    """name -> (model dir, dashboard files)"""
    found = {"adventureworks": (REPO / "cube" / "model", sorted((REPO / "dashboards").glob("*.yml")))}
    for cube_dir in sorted((REPO / "models").glob("*/cube")):
        found[cube_dir.parent.name] = (cube_dir, sorted((cube_dir.parent / "dashboards").glob("*.yml")))
    return found


MODELS = models()
DASHBOARDS = [(name, f) for name, (_, files) in MODELS.items() for f in files]


def test_a_second_model_exists():
    assert len(MODELS) >= 2, "models/<name>/cube is the second model that keeps the app decoupled"


@pytest.mark.parametrize("name", MODELS)
def test_the_catalog_loads_and_its_sort_fields_are_sound(name):
    catalog = cat.from_model(MODELS[name][0])
    assert catalog.cubes
    assert cat.sort_by_problems(catalog) == []


@pytest.mark.parametrize("name,path", DASHBOARDS, ids=[f"{n}:{f.name}" for n, f in DASHBOARDS])
def test_every_dashboard_validates_and_compiles_on_its_model(name, path):
    catalog = cat.from_model(MODELS[name][0])
    spec = yaml.safe_load(path.read_text())
    errors, used = validate(spec, catalog)
    assert errors == []
    json.dumps(compile_spec(spec, used))


def test_the_models_share_no_cube_name():
    names = {n: set(cat.from_model(d).cubes) for n, (d, _) in MODELS.items()}
    first, *rest = names.values()
    for other in rest:
        assert not (first & other), f"a cube name shared between models hides coupling: {first & other}"


# ---------------------------------------------------------------------------------------------------------------- the model's meta (phase 1 of PLAN-decouple.md)
def test_each_model_says_which_cubes_are_facts_and_what_its_first_measure_is():
    for name, (model_dir, _) in MODELS.items():
        catalog = cat.from_model(model_dir)
        assert len(catalog.facts()) >= 2, name
        for fact in catalog.facts():
            assert catalog.primary(fact) in catalog.cubes[fact]["measures"], (name, fact)
            assert catalog.measure_meta(f"{fact}.{catalog.primary(fact)}").get("format"), (name, fact, "the first measure says how it is shown")
        assert not set(catalog.facts()) & {c for c in catalog.cubes if catalog.kind(c) == "dimension"}


def test_adventureworks_names_its_sales_series_and_the_second_model_has_none():
    aw, dist = (cat.from_model(MODELS[n][0]) for n in ("adventureworks", "distributor"))
    assert aw.series("internet_sales") == ("Internet", "series1") and aw.series("reseller_sales") == ("Reseller", "series2")
    assert dist.series("orders") == (None, None)
    assert aw.primary("internet_sales") == "revenue" and dist.primary("orders") == "revenue" and dist.primary("payments") == "collected"


def test_the_same_meta_is_read_from_cubes_v1_meta():
    meta = {"cubes": [
        {"name": "sales", "description": "", "meta": {"kind": "fact", "series": "Web", "color": "series1"},
         "measures": [{"name": "sales.total", "type": "sum"}, {"name": "sales.count", "type": "count", "meta": {"primary": True, "format": "int"}}],
         "dimensions": [{"name": "sales.day", "type": "time"}]},
        {"name": "shops", "measures": [], "dimensions": [{"name": "shops.city", "type": "string"}]},
    ]}
    catalog = cat.from_meta(meta)
    assert catalog.facts() == ["sales"] and catalog.kind("shops") == "dimension"
    assert catalog.series("sales") == ("Web", "series1")
    assert catalog.primary("sales") == "count" and catalog.measure_meta("sales.count") == {"primary": True, "format": "int"}
    assert catalog.primary("shops") is None
    assert cat.from_meta({"cubes": [{"name": "x", "measures": [{"name": "x.a", "type": "sum"}], "dimensions": []}]}).primary("x") == "a", "none marked: the cube's first measure"


def test_the_semantic_layer_guide_is_written_from_the_catalog_not_from_names():
    from dashspec.semantic import catalog_json, generate
    for name, (model_dir, _) in MODELS.items():
        catalog = cat.from_model(model_dir)
        page = generate(catalog)
        assert all(f"`{f}`" in page for f in catalog.facts()), name
        assert {c["cube"] for c in catalog_json(catalog) if c["fact"]} == set(catalog.facts())
    dist = generate(cat.from_model(MODELS["distributor"][0]))
    assert "internet_sales" not in dist and "reseller_sales" not in dist and "territor" not in dist.lower(), "nothing of the other model in this model's guide"
