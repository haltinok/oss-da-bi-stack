"""The rule-based stand-in and the model's prompt on the second model (models/distributor): the app knows no model (PLAN-decouple.md phase 4)."""
import pathlib

import pytest
import yaml
from dashspec import catalog as cat
from dashspec.compile import compile_spec
from dashspec.validate import validate

from builder import composer, core
from builder.standin import StandInClient

REPO = pathlib.Path(__file__).resolve().parents[2]
CATALOG = cat.from_model(REPO / "models" / "distributor" / "cube")
AW = cat.from_model(REPO / "cube" / "model")
AW_NAMES = ("internet_sales", "reseller_sales", "inventory_health", "territories", "products.", "AdventureWorks", "Internet", "Reseller")


def members_of(spec):
    return {m for p in spec["panels"] for m in yaml.safe_dump(p).replace(":", " ").split() if "." in m and m.split(".")[0] in CATALOG.cubes}


@pytest.mark.parametrize("prompt", ["revenue by month", "orders by region", "aylık ciro", "revenue and orders by month, by region and top 5 category, a table",
                                    "tahsilat ve ciro, bölgeye göre", "collected by method as a pie", "a dashboard", "revenue by dealer, top 8", "payments"])
def test_the_stand_in_builds_a_valid_dashboard_on_another_model(prompt):
    comp = composer.compose(prompt, CATALOG, "admin")
    assert comp.spec, comp.reason
    errors, used = validate(comp.spec, CATALOG)
    assert errors == [], errors
    compile_spec(comp.spec, used, CATALOG)
    assert not any(n in yaml.safe_dump(comp.spec) for n in AW_NAMES)


def test_it_understands_the_members_own_names_and_the_models_vocabulary():
    spec = composer.compose("orders by region and a table", CATALOG, "admin").spec
    kinds = {p["type"] for p in spec["panels"]}
    assert {"kpi", "bar", "table"} <= kinds
    assert any(p.get("by") == "dealers.region" and p.get("measure") == "orders.order_count" for p in spec["panels"]), "'orders' is order_count, 'region' is dealers.region"
    tr = composer.compose("aylık ciro", CATALOG, "admin").spec
    assert any(p["type"] == "timeseries" and p["series"][0]["member"] == "orders.revenue" and p["granularity"] == "month" for p in tr["panels"]), "ciro is the vocabulary's word for orders.revenue"
    assert tr["locale"] == "tr-TR" and tr["currency"] == "TRY", "the model's own locale and currency"


def test_a_year_comparison_uses_the_models_year_field_and_a_model_without_one_has_none():
    spec = composer.compose("revenue by month", CATALOG, "admin").spec
    assert any(f["dimension"] == "calendar.calendar_year" for f in spec["filters"]) and next(p for p in spec["panels"] if p["type"] == "kpi")["compare"] == "previous_year"
    bare = cat.Catalog(CATALOG.cubes, {"time": CATALOG.config["time"] | {"year_fields": {}}, "vocabulary": CATALOG.config["vocabulary"]})
    spec = composer.compose("revenue by month", bare, "admin").spec
    assert not spec["filters"] and "compare" not in next(p for p in spec["panels"] if p["type"] == "kpi")


def test_the_models_prompt_carries_examples_and_a_guide_with_nothing_of_another_model():
    examples = core.example_spec(CATALOG, "admin")
    assert "panels:" in examples and "orders." in examples
    system = core.system_blocks(CATALOG, "admin") if hasattr(core, "system_blocks") else None
    text = yaml.safe_dump(system) if system else examples
    assert not any(n in text for n in AW_NAMES), [n for n in AW_NAMES if n in text]


def test_the_builder_page_offers_requests_made_from_the_catalog_in_both_languages():
    en, tr = core.examples_for("admin", "en", CATALOG), core.examples_for("admin", "tr", CATALOG)
    assert en and tr and all(any(w in e for w in ("revenue", "order", "collected", "payment")) for e in en), en
    assert not any(n in " ".join(en + tr) for n in AW_NAMES)
    assert composer.compose(en[0], CATALOG, "admin").spec, "the first suggestion works"


def test_nothing_changes_on_adventureworks_it_has_its_recipe():
    assert composer.recipe_of(AW).__name__ == "builder.recipes.adventureworks" and composer.recipe_of(CATALOG) is None
    assert core.examples_for("admin", "en", AW)[0].startswith("Monthly revenue")


def test_an_existing_dashboard_is_not_edited_by_the_generic_stand_in_it_says_so():
    spec = composer.compose("revenue by month", CATALOG, "admin").spec
    comp = composer.compose("make it a pie", CATALOG, "admin", yaml.safe_dump(spec))
    assert comp.spec is None and "edit the YAML" in comp.reason


def test_the_standin_client_goes_through_the_same_loop_on_another_model():
    client = StandInClient(CATALOG, "admin")
    out = client.messages.create(messages=[{"role": "user", "content": "revenue by region"}])
    call = out.content[0]
    assert call.name == "submit_dashboard" and "dealers.region" in call.input["yaml"]
