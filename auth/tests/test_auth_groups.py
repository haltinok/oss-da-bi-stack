"""The groups a person belongs to (Keycloak's `groups` claim) travel in the Cube token.

  uv run --with pytest --with fastapi --with httpx --with 'pyjwt[crypto]' --with pymysql python -m pytest auth/tests
"""
import importlib
import pathlib
import sys

import jwt
from fastapi.testclient import TestClient

REAL_DECODE = jwt.decode                                                 # the test replaces jwt.decode for the Keycloak token, not for reading the Cube one
SERVICE_DIR = str(pathlib.Path(__file__).resolve().parents[1])


def load(monkeypatch):
    monkeypatch.setenv("CUBEJS_API_SECRET", "secret")
    monkeypatch.setenv("KEYCLOAK_ISSUER", "http://kc/realms/spike")
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://kc/certs")
    sys.modules.pop("main", None)
    sys.path.insert(0, SERVICE_DIR)
    return importlib.import_module("main")


def mint(monkeypatch, claims):
    main = load(monkeypatch)

    class Key:
        key = "k"

    monkeypatch.setattr(main, "territories_for", lambda user: ["Canada"])
    monkeypatch.setattr(main, "jwks", type("J", (), {"get_signing_key_from_jwt": lambda self, raw: Key()})())
    monkeypatch.setattr(main.jwt, "decode", lambda raw, key, **kw: {"azp": "dashboard", "preferred_username": "ayse", "realm_access": {"roles": ["admin"]}, **claims} if kw.get("issuer") else {})
    r = TestClient(main.app).post("/token", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200, r.text
    return r.json(), REAL_DECODE(r.json()["token"], "secret", algorithms=["HS256"])


def test_groups_are_sorted_and_carried_in_the_cube_token(monkeypatch):
    body, cube = mint(monkeypatch, {"groups": ["/Sales team", "Ops"]})
    assert body["groups"] == cube["groups"] == ["Ops", "Sales team"]


def test_a_token_without_groups_gives_an_empty_list(monkeypatch):
    body, cube = mint(monkeypatch, {})
    assert body["groups"] == cube["groups"] == []
