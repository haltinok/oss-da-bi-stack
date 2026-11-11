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


def test_a_models_committed_dashboard_build_is_current(tmp_path):
    """models/<name>/dashboards/build is committed (nginx serves it as is, docker-compose.distributor.yml): rebuilding from the YAML must change nothing."""
    from dashspec.cli import main
    for name, (model_dir, _files) in MODELS.items():
        if name == "adventureworks":
            continue                                                           # test_dashspec.py checks dashboards/build
        out = tmp_path / name
        assert main(["build", "--model", str(model_dir), "--dir", str(model_dir.parent / "dashboards"), "--out", str(out)]) == 0
        committed = model_dir.parent / "dashboards" / "build"
        assert sorted(p.name for p in out.iterdir()) == sorted(p.name for p in committed.iterdir()), name
        for f in sorted(out.iterdir()):
            assert (committed / f.name).read_text() == f.read_text(), f"{name}/{f.name} is stale: scripts/dashspec build --model {model_dir} --dir {model_dir.parent}/dashboards --out {model_dir.parent}/dashboards/build"


# ---------------------------------------------------------------------------------------------------------------- models.yml and the `model:` field (PLAN-models.md phase 0)
def test_models_yml_lists_the_models_the_repo_ships_and_each_folder_exists():
    from dashspec import models
    listed = models.load()
    assert [m.id for m in listed][:2] == ["adventureworks", "distributor"] and models.default().id == "adventureworks"
    for m in listed:
        assert m.dir.is_dir() and m.dashboards.is_dir() and m.config_file.parent == m.dir.parent, m.id
    assert {m.id for m in listed} == set(MODELS), "test_models.py finds the same models by folder"
    assert models.get(None).id == "adventureworks" and models.get("distributor").label == "Anadolu Dağıtım" and models.get("nope") is None


@pytest.mark.parametrize("text,problem", [
    ("models: []", "at least one model"), ("models: [{id: a, label: A, dir: d}]", "needs id, label, dir, dashboards and cube"),
    ("models: [{id: A, label: A, dir: d, dashboards: x, cube: c}]", "lower-case"),
    ("models: [{id: a, label: A, dir: d, dashboards: x, cube: c}, {id: a, label: B, dir: d, dashboards: x, cube: c}]", "used once"),
])
def test_a_models_file_that_cannot_be_used_says_why(tmp_path, text, problem):
    from dashspec import models
    f = tmp_path / "models.yml"
    f.write_text(text)
    with pytest.raises(ValueError, match=problem):
        models.load(f)


def test_a_dashboard_is_checked_against_its_own_model_and_a_wrong_one_is_refused(tmp_path, capsys):
    from dashspec.cli import main
    dist = (REPO / "models" / "distributor" / "dashboards" / "collections.yml").read_text()
    good = tmp_path / "collections.yml"
    good.write_text(dist)
    assert main(["validate", str(good)]) == 0, "it says model: distributor, so it is checked against the distributor's cubes"
    no_model = tmp_path / "no_model.yml"
    no_model.write_text(dist.replace("model: distributor\n", ""))
    assert main(["validate", str(no_model)]) == 1 and "payments.collected" in capsys.readouterr().out, "no model: the default one (AdventureWorks), which has no payments cube"
    wrong = tmp_path / "wrong.yml"
    wrong.write_text(dist.replace("model: distributor", "model: atlantis"))
    assert main(["validate", str(wrong)]) == 1 and "is not a model of this stack" in capsys.readouterr().out


def test_the_compiled_dashboard_says_its_model_and_the_default_is_named(tmp_path):
    from dashspec.cli import main
    out = tmp_path / "out.json"
    assert main(["compile", str(REPO / "dashboards" / "sales-overview.yml"), "-o", str(out)]) == 0
    assert json.loads(out.read_text())["model"] == "adventureworks", "a dashboard that names no model is compiled with the default's"
    assert main(["compile", str(REPO / "models" / "distributor" / "dashboards" / "collections.yml"), "-o", str(out)]) == 0
    assert json.loads(out.read_text())["model"] == "distributor"


def test_build_with_no_arguments_builds_every_model_into_its_own_folder_and_a_folder_may_not_hold_another_models_dashboard(tmp_path):
    from dashspec import cli, models
    for m in models.load():
        committed = json.loads((m.build / "index.json").read_text())
        assert [d["id"] for d in committed] == sorted(p.stem for p in m.dashboards.glob("*.yml")), m.id
        assert all(json.loads(p.read_text())["model"] == m.id for p in m.build.glob("*.json") if p.name != "index.json"), m.id
    stray = tmp_path / "stray"
    stray.mkdir()
    (stray / "collections.yml").write_text((REPO / "models" / "distributor" / "dashboards" / "collections.yml").read_text())
    assert cli._build(stray, tmp_path / "out", cat.from_model(MODELS["adventureworks"][0]), "adventureworks") == 1, "a dashboard for another model in this model's folder is refused"
