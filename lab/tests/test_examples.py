"""The SQL lab's examples: the model's own, only for someone who can read the cubes they use; else made from the catalog (PLAN-decouple.md phase 3)."""
import pathlib

import examples
from dashspec import catalog as cat

REPO = pathlib.Path(__file__).resolve().parents[2]
AW = cat.from_model(REPO / "cube" / "model")
DIST = cat.from_model(REPO / "models" / "distributor" / "cube")



def _schema(catalog, blocked):
    """What schema_for gives for this catalog (it reads the module's own catalog, so build the same shape here)."""
    return [{"name": n, "description": "", "dimensions": [{"name": d, "type": t} for d, t in c["dimensions"].items()],
             "measures": [{"name": m, "type": t} for m, t in c["measures"].items()], "joins": sorted(c["joins"] or ())}
            for n, c in sorted(catalog.cubes.items()) if n not in blocked]


def test_the_models_own_examples_are_offered_when_the_person_can_read_their_cubes():
    ex = examples.examples_for(AW, _schema(AW, ()))
    assert [e["title"]["en"] for e in ex] == ["Revenue by category", "Orders by year", "Latest order lines"]
    assert all({"en", "tr"} <= set(e["title"]) for e in ex)


def test_an_example_whose_cube_is_blocked_is_left_out():
    ex = examples.examples_for(AW, _schema(AW, ("dates",)))
    assert [e["title"]["en"] for e in ex] == ["Revenue by category", "Latest order lines"]


def test_a_model_with_no_examples_gets_ones_made_from_its_catalog():
    bare = cat.from_model(REPO / "models" / "distributor" / "cube")
    bare.config = {k: v for k, v in bare.config.items() if k != "lab"}          # the model's own examples would win
    ex = examples.examples_for(bare, _schema(bare, ()))
    assert ex and all("internet_sales" not in e["sql"] for e in ex)
    first = ex[0]["sql"]
    assert first.startswith("select ") and "measure(invoiced)" in first and "from invoices cross join " in first and "group by 1" in first, first
    assert {"en", "tr"} <= set(ex[0]["title"])


def test_nothing_readable_gives_no_examples():
    assert examples.examples_for(DIST, []) == []
