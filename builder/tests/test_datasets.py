"""Datasets in the builder: a cube a person has no grant on is left out of their catalog and refused when they check a spec, so it never offers what Cube would refuse.

(The rule itself, access_resolve.blocked_cubes, is tested in admin/tests; Cube enforces it on every query.)
"""
import pathlib

from builder.tests.test_service import REPO, client, main, token  # noqa: F401  (the service, its keys and the token helper)

from builder import access_resolve, core
from dashspec import catalog as cat

CATALOG = cat.from_model(REPO / "cube" / "model")
SALES = (pathlib.Path(REPO) / "dashboards" / "sales-overview.yml").read_text()


def test_without_cubes_drops_a_cube_and_the_joins_to_it():
    small = core.without_cubes(CATALOG, ["reseller_sales", "territories"])
    assert "reseller_sales" not in small.cubes and "territories" not in small.cubes and "internet_sales" in small.cubes
    assert "territories" not in small.cubes["internet_sales"]["joins"] and "products" in small.cubes["internet_sales"]["joins"]
    assert "reseller_sales" in CATALOG.cubes                                         # the shared catalog is untouched


def test_a_spec_that_uses_a_blocked_cube_is_refused_for_that_person_only():
    ok, problems = core.check_submission(SALES, CATALOG, "admin")
    assert ok and not problems
    built, problems = core.check_submission(SALES, core.without_cubes(CATALOG, ["internet_sales"]), "admin")
    assert built is None and any("internet_sales" in p for p in problems)


def test_the_catalog_endpoint_leaves_out_blocked_cubes(monkeypatch):
    monkeypatch.setattr(main, "blocked_for", lambda user: ["reseller_sales"])
    names = {c["cube"] for c in client.get("/catalog", headers=token("manager")).json()}
    assert "reseller_sales" not in names and "internet_sales" in names
    monkeypatch.setattr(main, "blocked_for", lambda user: [])
    assert "reseller_sales" in {c["cube"] for c in client.get("/catalog", headers=token("manager")).json()}


def test_validate_refuses_a_spec_on_a_blocked_cube(monkeypatch):
    monkeypatch.setattr(main, "blocked_for", lambda user: ["internet_sales"])
    r = client.post("/validate", headers=token("admin"), json={"yaml": SALES}).json()
    assert not r["ok"] and any("internet_sales" in p for p in r["problems"])


def test_without_a_database_nothing_is_left_out_and_admins_are_never_checked(monkeypatch):
    monkeypatch.setattr(main, "STORE", None)
    assert main.blocked_for(main.User(name="a", role="manager")) == []
    monkeypatch.setattr(main, "STORE", object())                                        # a store that would fail if asked
    assert main.blocked_for(main.User(name="root", role="admin")) == []


def test_a_database_that_cannot_be_read_is_not_fatal(monkeypatch):
    class Down:
        dsn = {"host": "127.0.0.1", "port": 1, "dbname": "x", "user": "x", "password": "x"}

    monkeypatch.setattr(main, "STORE", Down())
    assert main.blocked_for(main.User(name="a", role="manager")) == []


def test_the_resolution_module_is_the_one_the_builder_ships():
    assert hasattr(access_resolve, "blocked_cubes") and hasattr(access_resolve, "load")
