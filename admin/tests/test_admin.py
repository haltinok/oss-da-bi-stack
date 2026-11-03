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
    monkeypatch.setattr(main, "_rules", None)                                    # rules are off unless a test turns them on (whatever the environment says)
    monkeypatch.setattr(main, "_seed", None)
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


# ---- row-level rules
class FakeSeed:
    def __init__(self, by_user):
        self.by_user = by_user

    def regions(self):
        return ["Canada", "France", "Germany", "United States"]

    def regions_of(self, username):
        return self.by_user.get(username, [])


@pytest.fixture()
def ruled(api, kc, monkeypatch):
    from access import MemoryRules
    monkeypatch.setattr(main, "_rules", MemoryRules())
    monkeypatch.setattr(main, "_seed", FakeSeed({"de_rep": ["Germany"]}))
    return api


def test_rules_are_off_without_a_store(api, monkeypatch):
    monkeypatch.setattr(main, "_rules", None)
    r = api.get("/rls/rules")
    assert r.status_code == 503 and "ADMIN_DB_PASSWORD" in r.json()["detail"]


def test_set_list_and_delete_a_rule_for_a_user_and_a_group(ruled, kc):
    kc.add("de_rep", "rep")
    gid = ruled.post("/groups", json={"name": "EU team"}).json()["id"]
    assert gid
    assert ruled.put("/rls/rules/user/de_rep", json={"values": ["Germany", "France", "France"]}).json()["values"] == ["France", "Germany"]
    assert ruled.put("/rls/rules/group/EU team", json={"values": ["France"]}).status_code == 200
    out = ruled.get("/rls/rules").json()
    assert [(r["type"], r["principal"], r["values"]) for r in out["rules"]] == [("group", "EU team", ["France"]), ("user", "de_rep", ["France", "Germany"])]
    assert out["regions"] == ["Canada", "France", "Germany", "United States"]
    assert ruled.delete("/rls/rules/user/de_rep").status_code == 204
    assert ruled.delete("/rls/rules/user/de_rep").status_code == 404


def test_a_rule_needs_a_real_person_or_group_and_real_territories(ruled, kc):
    kc.add("de_rep", "rep")
    assert ruled.put("/rls/rules/user/nobody", json={"values": ["France"]}).status_code == 404
    assert ruled.put("/rls/rules/group/Nope", json={"values": ["France"]}).status_code == 404
    assert ruled.put("/rls/rules/user/de_rep", json={"values": ["Atlantis"]}).status_code == 400
    assert ruled.put("/rls/rules/user/de_rep", json={"values": []}).status_code == 422
    assert ruled.put("/rls/rules/team/x", json={"values": ["France"]}).status_code == 400


def test_preview_shows_the_union_of_the_rules_and_falls_back_to_the_seed(ruled, kc):
    uid = kc.add("de_rep", "rep")
    kc.add("na_manager", "manager")
    gid = ruled.post("/groups", json={"name": "EU team"}).json()["id"]
    assert ruled.get("/rls/preview/de_rep").json()["territories"] == ["Germany"] and ruled.get("/rls/preview/de_rep").json()["source"] == "seed"
    ruled.put("/rls/rules/group/EU team", json={"values": ["France"]})
    ruled.put(f"/groups/{gid}/members/{uid}")
    ruled.put("/rls/rules/user/de_rep", json={"values": ["Canada"]})
    p = ruled.get("/rls/preview/de_rep").json()
    assert p["source"] == "rules" and p["territories"] == ["Canada", "France"] and len(p["rules"]) == 2 and p["groups"] == ["EU team"]
    none = ruled.get("/rls/preview/na_manager").json()
    assert none["source"] == "none" and none["territories"] == []                        # no rule, nothing in the seed: they cannot sign in to sales data
    assert ruled.get("/rls/preview/ghost").status_code == 404
    kc.add("buyer", "purchasing")
    assert ruled.get("/rls/preview/buyer").json()["applies"] is False


def test_a_rule_follows_its_groups_name_and_goes_with_the_group_or_the_user(ruled, kc):
    uid = kc.add("de_rep", "rep")
    gid = ruled.post("/groups", json={"name": "EU team"}).json()["id"]
    ruled.put("/rls/rules/group/EU team", json={"values": ["France"]})
    ruled.put("/rls/rules/user/de_rep", json={"values": ["Germany"]})
    ruled.put(f"/groups/{gid}", json={"name": "Europe"})
    assert [(r["type"], r["principal"]) for r in ruled.get("/rls/rules").json()["rules"]] == [("group", "Europe"), ("user", "de_rep")]
    ruled.delete(f"/groups/{gid}")
    assert [(r["type"], r["principal"]) for r in ruled.get("/rls/rules").json()["rules"]] == [("user", "de_rep")]
    assert ruled.delete(f"/users/{uid}?confirm=de_rep").status_code == 204
    assert ruled.get("/rls/rules").json()["rules"] == []                                 # a new "de_rep" must not inherit the old rule


# ---- datasets and grants
def test_datasets_are_off_without_a_store(api, monkeypatch):
    monkeypatch.setattr(main, "_rules", None)
    assert api.get("/datasets").status_code == 503


def test_create_a_dataset_with_grants_and_list_it(ruled, kc):
    kc.add("de_rep", "rep")
    ruled.post("/groups", json={"name": "Finance"})
    r = ruled.put("/datasets/sales", json={"name": "Sales", "description": "revenue facts", "cubes": ["reseller_sales", "internet_sales", "internet_sales"],
                                           "grants": [{"type": "user", "principal": "de_rep"}, {"type": "group", "principal": "Finance"}, {"type": "role", "principal": "manager"}, {"type": "role", "principal": "manager"}]})
    assert r.status_code == 200 and r.json()["cubes"] == ["internet_sales", "reseller_sales"] and len(r.json()["grants"]) == 3
    out = ruled.get("/datasets").json()
    assert [d["id"] for d in out["datasets"]] == ["sales"] and "internet_sales" in {c["name"] for c in out["cubes"]} and "agent" in out["roles"]


def test_a_dataset_needs_real_cubes_principals_and_a_clean_id(ruled, kc):
    ok = {"name": "S", "cubes": ["internet_sales"], "grants": []}
    assert ruled.put("/datasets/Bad Id", json=ok).status_code in (400, 404)
    assert ruled.put("/datasets/s", json={**ok, "cubes": ["nope"]}).status_code == 400
    assert ruled.put("/datasets/s", json={**ok, "cubes": []}).status_code == 422
    assert ruled.put("/datasets/s", json={**ok, "grants": [{"type": "user", "principal": "ghost"}]}).status_code == 404
    assert ruled.put("/datasets/s", json={**ok, "grants": [{"type": "group", "principal": "Nope"}]}).status_code == 404
    assert ruled.put("/datasets/s", json={**ok, "grants": [{"type": "role", "principal": "king"}]}).status_code == 400
    assert ruled.put("/datasets/s", json={**ok, "grants": [{"type": "team", "principal": "x"}]}).status_code == 400


def test_replacing_and_deleting_a_dataset(ruled):
    body = {"name": "Sales", "cubes": ["internet_sales"], "grants": [{"type": "role", "principal": "manager"}]}
    ruled.put("/datasets/sales", json=body)
    ruled.put("/datasets/sales", json={**body, "name": "Sales 2", "grants": []})
    d = ruled.get("/datasets").json()["datasets"]
    assert len(d) == 1 and d[0]["name"] == "Sales 2" and d[0]["grants"] == []
    assert ruled.delete("/datasets/sales").status_code == 204
    assert ruled.delete("/datasets/sales").status_code == 404


def test_preview_lists_the_cubes_datasets_keep_from_a_person(ruled, kc):
    kc.add("de_rep", "rep")
    kc.add("na_manager", "manager")
    ruled.put("/datasets/sales", json={"name": "Sales", "cubes": ["internet_sales", "products"], "grants": [{"type": "user", "principal": "de_rep"}]})
    assert ruled.get("/rls/preview/de_rep").json()["blocked_cubes"] == []
    assert ruled.get("/rls/preview/na_manager").json()["blocked_cubes"] == ["internet_sales", "products"]
    assert ruled.get("/rls/preview/root").json()["blocked_cubes"] == []


def test_grants_follow_a_group_and_go_with_a_group_or_person(ruled, kc):
    kc.add("de_rep", "rep")
    gid = ruled.post("/groups", json={"name": "EU team"}).json()["id"]
    ruled.put("/datasets/sales", json={"name": "Sales", "cubes": ["internet_sales"], "grants": [{"type": "group", "principal": "EU team"}, {"type": "user", "principal": "de_rep"}]})
    ruled.put(f"/groups/{gid}", json={"name": "Europe"})
    assert {(g["type"], g["principal"]) for g in ruled.get("/datasets").json()["datasets"][0]["grants"]} == {("group", "Europe"), ("user", "de_rep")}
    ruled.delete(f"/groups/{gid}")
    assert [(g["type"], g["principal"]) for g in ruled.get("/datasets").json()["datasets"][0]["grants"]] == [("user", "de_rep")]
    uid = next(u for u, v in kc.users_.items() if v["username"] == "de_rep")
    assert ruled.delete(f"/users/{uid}?confirm=de_rep").status_code == 204
    assert ruled.get("/datasets").json()["datasets"][0]["grants"] == []


def test_a_grant_can_be_view_or_lab_and_the_preview_says_whether_the_lab_is_open(ruled, kc):
    kc.add("de_rep", "rep")
    kc.add("na_manager", "manager")
    r = ruled.put("/datasets/sales", json={"name": "Sales", "cubes": ["internet_sales"], "grants": [{"type": "user", "principal": "de_rep", "permission": "lab"}, {"type": "role", "principal": "manager"},
                                                                                                    {"type": "user", "principal": "de_rep", "permission": "view"}]})
    assert r.status_code == 200 and {(g["type"], g["principal"], g["permission"]) for g in r.json()["grants"]} == {("user", "de_rep", "lab"), ("role", "manager", "view")}
    assert ruled.put("/datasets/sales", json={"name": "S", "cubes": ["internet_sales"], "grants": [{"type": "role", "principal": "manager", "permission": "own"}]}).status_code == 400
    assert ruled.get("/rls/preview/de_rep").json()["lab"] is True and ruled.get("/rls/preview/na_manager").json()["lab"] is False and ruled.get("/rls/preview/root").json()["lab"] is True


def test_viewer_is_a_role_an_admin_can_give(api, kc):
    assert "viewer" in api.get("/roles").json()["roles"]
    u = api.post("/users", json={**NEW, "username": "vera", "role": "viewer"}).json()
    assert u["role"] == "viewer"
    assert api.put(f"/users/{u['id']}", json={"role": "manager"}).json()["role"] == "manager"
