"""cube/rls_dimensions.json against the Cube model: a dimension that Cube could not filter on must fail the build, not silently leave rows open."""
import json
import pathlib

from dashspec import catalog as cat

REPO = pathlib.Path(__file__).resolve().parents[2]
DIMS = json.loads((REPO / "cube" / "rls_dimensions.json").read_text(encoding="utf-8"))["dimensions"]
CATALOG = cat.from_model(REPO / "cube" / "model")


def test_every_dimension_is_well_formed_and_unique():
    ids = [d["id"] for d in DIMS]
    assert len(ids) == len(set(ids)) and all(__import__("re").fullmatch(r"[a-z][a-z0-9_]{0,39}", i) for i in ids)
    for d in DIMS:
        assert d["when_empty"] in ("deny", "allow") and d["cubes"] and d["values"]["kind"] in ("seed_regions", "list", "cube"), d["id"]
        assert d["labels"]["en"], d["id"]


def test_each_dimension_member_exists_and_is_reachable_from_every_cube_it_filters():
    for d in DIMS:
        cube, member = d["member"].split(".")
        assert cube in CATALOG.cubes and member in CATALOG.cubes[cube]["dimensions"], f"{d['id']}: {d['member']} is not a dimension in the model"
        for c in d["cubes"]:
            assert c in CATALOG.cubes, f"{d['id']}: no cube {c}"
            assert c == cube or cube in (CATALOG.cubes[c]["joins"] or ()), f"{d['id']}: {c} does not join {cube}, so a filter on {d['member']} would not be valid for it"


def test_the_copies_the_services_read_are_identical():
    text = (REPO / "cube" / "rls_dimensions.json").read_text()
    for svc in ("auth", "admin"):
        assert (REPO / svc / "rls_dimensions.json").read_text() == text, f"{svc}/rls_dimensions.json differs from cube/rls_dimensions.json"
