"""Row-level rules (Postgres, `access.rls_rule`) decide a person's territories when one applies to them or a group of theirs; the dbt seed decides otherwise.

  uv run --with pytest --with fastapi --with httpx --with 'pyjwt[crypto]' --with pymysql --with psycopg2-binary python -m pytest auth/tests
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


def sign_in(monkeypatch, *, rules_on, rules=None, seed=("Canada",), role="manager", groups=("Sales",)):
    main = load(monkeypatch)

    class Key:
        key = "k"

    monkeypatch.setattr(main, "jwks", type("J", (), {"get_signing_key_from_jwt": lambda self, raw: Key()})())
    monkeypatch.setattr(main.jwt, "decode", lambda raw, key, **kw: {"azp": "dashboard", "preferred_username": "ayse", "realm_access": {"roles": [role]}, "groups": list(groups)})
    monkeypatch.setattr(main, "RULES_ON", rules_on)
    monkeypatch.setattr(main, "territories_for", lambda user: list(seed))
    calls = []

    def fake_rules(user, grps):
        calls.append((user, list(grps)))
        if isinstance(rules, Exception):
            raise rules
        return list(rules or [])

    monkeypatch.setattr(main, "rule_territories", fake_rules)
    r = TestClient(main.app).post("/token", headers={"Authorization": "Bearer t"})
    return r, calls


def cube_territories(r):
    return REAL_DECODE(r.json()["token"], "secret", algorithms=["HS256"])["territories"]


def test_a_rule_replaces_the_seed(monkeypatch):
    r, calls = sign_in(monkeypatch, rules_on=True, rules=["Germany", "France"])
    assert r.status_code == 200 and r.json()["territories"] == cube_territories(r) == ["Germany", "France"]
    assert calls == [("ayse", ["Sales"])]                                      # the person and their groups are what the rules are asked about


def test_with_no_rule_the_seed_still_decides(monkeypatch):
    r, _ = sign_in(monkeypatch, rules_on=True, rules=[])
    assert r.status_code == 200 and r.json()["territories"] == ["Canada"]


def test_without_a_rules_login_the_rules_are_not_even_asked(monkeypatch):
    r, calls = sign_in(monkeypatch, rules_on=False, rules=["Germany"])
    assert r.json()["territories"] == ["Canada"] and calls == []


def test_a_rules_database_that_cannot_be_read_fails_the_sign_in_instead_of_widening_access(monkeypatch):
    r, _ = sign_in(monkeypatch, rules_on=True, rules=RuntimeError("down"))
    assert r.status_code == 503


def test_nobody_in_a_territory_role_without_rule_or_seed_gets_in(monkeypatch):
    r, _ = sign_in(monkeypatch, rules_on=True, rules=[], seed=())
    assert r.status_code == 403


def test_inventory_roles_have_no_territories_and_never_ask(monkeypatch):
    r, calls = sign_in(monkeypatch, rules_on=True, rules=["Germany"], role="purchasing")
    assert r.status_code == 200 and r.json()["territories"] == [] and calls == []
