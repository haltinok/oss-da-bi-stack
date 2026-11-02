"""The admin console service against a fake Keycloak: what an admin can do, and what the service refuses on its own.

  cd admin && PYTHONPATH=. uv run --with pytest --with fastapi --with httpx --with 'pyjwt[crypto]' python -m pytest tests -q
"""
import pytest
from fastapi.testclient import TestClient

import main
from fake_keycloak import FakeKeycloak

ME = main.Admin(id="me", name="root")


@pytest.fixture()
def kc(monkeypatch):
    fake = FakeKeycloak()
    fake.users_["me"] = {"id": "me", "username": "root", "enabled": True}
    fake.roles_["admin"].add("me")
    monkeypatch.setattr(main, "_kc", fake)
    main.app.dependency_overrides[main.current_admin] = lambda: ME
    yield fake
    main.app.dependency_overrides.clear()


@pytest.fixture()
def api(kc):
    return TestClient(main.app)


NEW = {"username": "ayse", "email": "ayse@example.com", "firstName": "Ayse", "lastName": "Y", "role": "manager", "password": "a-long-password-1"}


def test_create_gives_a_role_groups_and_a_temporary_password(api, kc):
    gid = api.post("/groups", json={"name": "Sales team"}).json()["id"]
    r = api.post("/users", json={**NEW, "groups": [gid]})
    assert r.status_code == 201
    u = r.json()
    assert u["username"] == "ayse" and u["role"] == "manager" and [g["name"] for g in u["groups"]] == ["Sales team"] and u["enabled"]
    assert kc.passwords[u["id"]] == ("a-long-password-1", True)


def test_create_refuses_a_short_password_an_unknown_role_and_a_taken_username(api):
    assert api.post("/users", json={**NEW, "password": "short"}).status_code == 422
    assert api.post("/users", json={**NEW, "role": "king"}).status_code == 400
    assert api.post("/users", json=NEW).status_code == 201
    assert api.post("/users", json=NEW).status_code == 409


def test_list_searches_filters_and_counts(api, kc):
    kc.add("na_manager", "manager", email="na@x.com")
    kc.add("de_rep", "rep")
    kc.add("old", "rep", enabled=False)
    gid = api.post("/groups", json={"name": "EU"}).json()["id"]
    api.put(f"/groups/{gid}/members/{next(u for u in kc.users_ if kc.users_[u]['username'] == 'de_rep')}")
    everyone = api.get("/users").json()
    assert everyone["total"] == 4 and [u["username"] for u in everyone["users"]] == ["de_rep", "na_manager", "old", "root"]
    assert [u["username"] for u in api.get("/users?role=rep").json()["users"]] == ["de_rep", "old"]
    assert [u["username"] for u in api.get("/users?enabled=false").json()["users"]] == ["old"]
    assert [u["username"] for u in api.get(f"/users?group={gid}").json()["users"]] == ["de_rep"]
    assert [u["username"] for u in api.get("/users?search=na@").json()["users"]] == ["na_manager"]
    assert len(api.get("/users?first=1&max=2").json()["users"]) == 2


def test_edit_changes_the_role_to_exactly_one_and_the_groups(api, kc):
    uid = api.post("/users", json=NEW).json()["id"]
    g1, g2 = api.post("/groups", json={"name": "A"}).json()["id"], api.post("/groups", json={"name": "B"}).json()["id"]
    r = api.put(f"/users/{uid}", json={"role": "rep", "groups": [g1, g2], "lastName": "Z"}).json()
    assert r["role"] == "rep" and r["lastName"] == "Z" and {g["name"] for g in r["groups"]} == {"A", "B"}
    assert [role for role, ids in kc.roles_.items() if uid in ids] == ["rep"]
    r = api.put(f"/users/{uid}", json={"groups": [g2]}).json()
    assert [g["name"] for g in r["groups"]] == ["B"]
    assert api.put(f"/users/{uid}", json={"groups": ["nope"]}).status_code == 400


def test_deactivate_ends_sessions_and_activate_undoes_it(api, kc):
    uid = api.post("/users", json=NEW).json()["id"]
    assert api.post(f"/users/{uid}/disable").json()["enabled"] is False and uid in kc.logged_out
    assert api.post(f"/users/{uid}/enable").json()["enabled"] is True


def test_the_last_active_admin_and_your_own_account_are_protected(api, kc):
    assert api.post("/users/me/disable").status_code == 409                                    # your own account
    assert api.delete("/users/me?confirm=root").status_code == 409
    other = api.post("/users", json={**NEW, "username": "boss", "role": "admin"}).json()["id"]
    assert api.post(f"/users/{other}/disable").status_code == 200                              # root is still active, so this admin may go
    assert api.put(f"/users/{other}", json={"role": "rep"}).status_code == 200
    kc.roles_["admin"].add(other)
    ME2 = main.Admin(id=other, name="boss")
    main.app.dependency_overrides[main.current_admin] = lambda: ME2
    kc.users_[other]["enabled"] = True
    kc.users_["me"]["enabled"] = False                                                         # boss is now the only active admin
    third = api.post("/users", json={**NEW, "username": "third", "role": "admin"}).json()["id"]
    kc.users_[third]["enabled"] = False
    assert api.put("/users/me", json={"role": "rep"}).status_code == 200                      # root is inactive: demoting it leaves boss, fine
    kc.roles_["admin"] = {other}
    main.app.dependency_overrides[main.current_admin] = lambda: main.Admin(id="someone-else", name="x")
    assert api.post(f"/users/{other}/disable").status_code == 409                              # nobody else is active
    assert api.put(f"/users/{other}", json={"role": "rep"}).status_code == 409
    assert api.delete(f"/users/{other}?confirm=boss").status_code == 409


def test_set_password_and_reset(api, kc):
    uid = api.post("/users", json=NEW).json()["id"]
    assert api.post(f"/users/{uid}/password", json={"password": "another-long-one", "temporary": False}).status_code == 200
    assert kc.passwords[uid] == ("another-long-one", False)
    assert api.post(f"/users/{uid}/password", json={"password": "tiny"}).status_code == 422
    r = api.post(f"/users/{uid}/reset-password").json()
    assert not r["emailed"] and len(r["temporary_password"]) >= 12 and kc.passwords[uid] == (r["temporary_password"], True)
    assert api.post(f"/users/{uid}/reset-password", json={"email": True}).json() == {"ok": True, "emailed": True} and kc.emailed == [uid]
    bare = kc.add("noemail", "rep")
    assert api.post(f"/users/{bare}/reset-password", json={"email": True}).status_code == 400


def test_delete_needs_the_username_typed(api, kc):
    uid = api.post("/users", json=NEW).json()["id"]
    assert api.delete(f"/users/{uid}").status_code == 400
    assert api.delete(f"/users/{uid}?confirm=wrong").status_code == 400
    assert api.delete(f"/users/{uid}?confirm=ayse").status_code == 204
    assert api.get(f"/users/{uid}").status_code == 404


def test_groups_create_rename_members_delete(api, kc):
    gid = api.post("/groups", json={"name": "Ops"}).json()["id"]
    assert api.post("/groups", json={"name": "Ops"}).status_code == 409
    uid = api.post("/users", json=NEW).json()["id"]
    assert api.put(f"/groups/{gid}/members/{uid}").status_code == 204
    assert api.get("/groups").json()["groups"] == [{"id": gid, "name": "Ops", "members": 1}]
    assert api.put(f"/groups/{gid}", json={"name": "Operations"}).json()["name"] == "Operations"
    assert api.delete(f"/groups/{gid}/members/{uid}").status_code == 204
    assert api.delete(f"/groups/{gid}").status_code == 204
    assert api.delete(f"/groups/{gid}").status_code == 404


def test_only_an_admin_with_the_dashboard_token_gets_in(monkeypatch):
    main.app.dependency_overrides.clear()
    api = TestClient(main.app)
    assert api.get("/users").status_code == 401                                                # no token
    assert api.get("/users", headers={"Authorization": "Bearer junk"}).status_code == 401

    class Key:
        key = "k"

    class Jwks:
        def get_signing_key_from_jwt(self, raw):
            return Key()

    monkeypatch.setattr(main, "jwks", Jwks())
    for claims, status in [({"azp": "dashboard", "sub": "1", "preferred_username": "x", "realm_access": {"roles": ["manager"]}}, 403),
                           ({"azp": "other", "sub": "1", "preferred_username": "x", "realm_access": {"roles": ["admin"]}}, 401)]:
        monkeypatch.setattr(main.jwt, "decode", lambda *a, _c=claims, **k: _c)
        assert api.get("/roles", headers={"Authorization": "Bearer t"}).status_code == status
    monkeypatch.setattr(main.jwt, "decode", lambda *a, **k: {"azp": "dashboard", "sub": "1", "preferred_username": "x", "realm_access": {"roles": ["admin"]}})
    assert api.get("/roles", headers={"Authorization": "Bearer t"}).json() == {"roles": list(main.ROLES)}
    assert api.get("/healthz").status_code == 200
