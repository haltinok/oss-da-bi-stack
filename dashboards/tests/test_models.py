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
