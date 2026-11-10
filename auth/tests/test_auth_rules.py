"""Row-level rules (Postgres, `access.rls_rule`) decide a person's values in each row-level dimension: the rules for them and for their groups, nothing else (the dbt seed is gone).

  uv run --with pytest --with fastapi --with httpx --with 'pyjwt[crypto]' --with psycopg2-binary python -m pytest auth/tests
"""
import importlib
import pathlib
import sys

import jwt
from fastapi.testclient import TestClient

REAL_DECODE = jwt.decode
SERVICE_DIR = str(pathlib.Path(__file__).resolve().parents[1])


def load(monkeypatch):
    monkeypatch.setenv("CUBEJS_API_SECRET", "secret")
    monkeypatch.setenv("KEYCLOAK_ISSUER", "http://kc/realms/spike")
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://kc/certs")
    sys.modules.pop("main", None)
    sys.path.insert(0, SERVICE_DIR)
    return importlib.import_module("main")


def sign_in(monkeypatch, *, rules_on, rules=None, role="editor", groups=("Sales",), blocked=(), lab=False, fields=()):
    main = load(monkeypatch)

    class Key:
        key = "k"

    monkeypatch.setattr(main, "jwks", type("J", (), {"get_signing_key_from_jwt": lambda self, raw: Key()})())
    monkeypatch.setattr(main.jwt, "decode", lambda raw, key, **kw: {"azp": "dashboard", "preferred_username": "ayse", "realm_access": {"roles": [role]}, "groups": list(groups)})
    monkeypatch.setattr(main, "RULES_ON", rules_on)
    calls = []

    def fake_access(user, role_, grps):
        calls.append((user, role_, list(grps)))
        if isinstance(rules, Exception):
            raise rules
        return ({"territory": list(rules)} if rules else {}), list(blocked), lab, list(fields)

    monkeypatch.setattr(main, "read_access", fake_access)
    r = TestClient(main.app).post("/token", headers={"Authorization": "Bearer t"})
    return r, calls


def cube_territories(r):
    return REAL_DECODE(r.json()["token"], "secret", algorithms=["HS256"])["rls"]["territory"]


def test_a_rule_gives_the_person_its_values(monkeypatch):
    r, calls = sign_in(monkeypatch, rules_on=True, rules=["Germany", "France"])
    assert r.status_code == 200 and r.json()["rls"]["territory"] == cube_territories(r) == ["Germany", "France"]
    assert calls == [("ayse", "editor", ["Sales"])]                                      # the person and their groups are what the rules are asked about
    assert "territories" not in r.json() and "territories" not in REAL_DECODE(r.json()["token"], "secret", algorithms=["HS256"]), "the old claim is gone: the token carries `rls` only"


def test_with_no_rule_a_person_has_no_values(monkeypatch):
    r, _ = sign_in(monkeypatch, rules_on=True, rules=[])
    assert r.status_code == 200 and r.json()["rls"] == {"territory": [], "product_category": []}, "no seed to fall back to: cube.js denies or allows by `when_empty`"


def test_without_a_rules_login_the_rules_are_not_even_asked(monkeypatch):
    r, calls = sign_in(monkeypatch, rules_on=False, rules=["Germany"])
    assert r.json()["rls"]["territory"] == [] and calls == []


def test_a_rules_database_that_cannot_be_read_fails_the_sign_in_instead_of_widening_access(monkeypatch):
    r, _ = sign_in(monkeypatch, rules_on=True, rules=RuntimeError("down"))
    assert r.status_code == 503


def test_a_rule_gives_an_editor_its_territories(monkeypatch):
    r, _ = sign_in(monkeypatch, rules_on=True, rules=["Germany"], role="editor")
    assert r.status_code == 200 and r.json()["rls"]["territory"] == ["Germany"]


def test_the_cubes_a_person_may_not_read_travel_in_the_cube_token(monkeypatch):
    r, _ = sign_in(monkeypatch, rules_on=True, rules=[], blocked=["internet_sales"])
    assert r.json()["blocked_cubes"] == ["internet_sales"]
    assert REAL_DECODE(r.json()["token"], "secret", algorithms=["HS256"])["blocked_cubes"] == ["internet_sales"]


def test_without_a_rules_login_nothing_is_blocked(monkeypatch):
    r, _ = sign_in(monkeypatch, rules_on=False, blocked=["internet_sales"])
    assert r.json()["blocked_cubes"] == []


def test_the_sql_lab_claim_follows_the_grants_and_admins_always_have_it(monkeypatch):
    r, _ = sign_in(monkeypatch, rules_on=True, rules=[], lab=True)
    assert r.json()["lab"] is True and REAL_DECODE(r.json()["token"], "secret", algorithms=["HS256"])["lab"] is True
    r, _ = sign_in(monkeypatch, rules_on=True, rules=[], lab=False)
    assert r.json()["lab"] is False
    r, _ = sign_in(monkeypatch, rules_on=False, role="editor")
    assert r.json()["lab"] is False, "without the access database only admins have the lab"
    r, _ = sign_in(monkeypatch, rules_on=False, role="admin")
    assert r.json()["lab"] is True


def test_a_viewer_is_scoped_by_territory_like_a_rep_and_never_has_the_lab(monkeypatch):
    r, _ = sign_in(monkeypatch, rules_on=True, rules=["Canada"], role="viewer", lab=False)
    assert r.status_code == 200 and r.json()["role"] == "viewer" and r.json()["rls"]["territory"] == ["Canada"] and r.json()["lab"] is False
    r, _ = sign_in(monkeypatch, rules_on=True, rules=[], role="viewer")
    assert r.status_code == 200 and r.json()["rls"]["territory"] == [], "no territory: cube.js refuses the sales cubes"


def test_the_fields_a_person_may_not_read_travel_in_the_cube_token_too(monkeypatch):
    r, _ = sign_in(monkeypatch, rules_on=True, rules=[], fields=["internet_sales.gross_profit"])
    assert r.json()["blocked_members"] == ["internet_sales.gross_profit"]
    assert REAL_DECODE(r.json()["token"], "secret", algorithms=["HS256"])["blocked_members"] == ["internet_sales.gross_profit"]
    r, _ = sign_in(monkeypatch, rules_on=False, fields=["x.y"])
    assert r.json()["blocked_members"] == []


def test_the_token_carries_the_values_of_every_dimension_in_rls(monkeypatch):
    r, _ = sign_in(monkeypatch, rules_on=True, rules=["Germany"])
    assert r.json()["rls"] == {"territory": ["Germany"], "product_category": []}
    assert REAL_DECODE(r.json()["token"], "secret", algorithms=["HS256"])["rls"] == {"territory": ["Germany"], "product_category": []}
    r, _ = sign_in(monkeypatch, rules_on=True, rules=[])
    assert r.json()["rls"] == {"territory": [], "product_category": []}, "no rule, no value (there is no seed to decide the territory)"


def test_the_dimensions_file_is_the_one_cube_reads():
    root = pathlib.Path(__file__).resolve().parents[2]
    assert not (root / "auth" / "rls_dimensions.json").exists() and not (root / "admin" / "rls_dimensions.json").exists(), "one file: images copy cube/rls_dimensions.json at build time"
    import rls_registry
    assert rls_registry.default_file() == root / "cube" / "rls_dimensions.json"


def test_the_cube_token_carries_the_registry_version_cube_checks(monkeypatch):
    r, _ = sign_in(monkeypatch, rules_on=True, rules=["Germany"])
    main = sys.modules["main"]
    claims = REAL_DECODE(r.json()["token"], "secret", algorithms=["HS256"])
    assert claims["rls_version"] == main.RLS_VERSION == main.rls_registry.version(main.rls_registry.from_file(main.rls_registry.default_file()))
    assert main.REGISTRY_SOURCE == "file", "without AUTH_PG_PASSWORD the default file is the registry"
