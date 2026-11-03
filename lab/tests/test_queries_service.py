"""Saved queries over HTTP: running one runs it AS THE RUNNER (their Cube token, their rules), and the snapshot it leaves is the runner's own."""
import pytest
from fastapi.testclient import TestClient

import main
from store import MemoryStore

SQL = "select category, measure(revenue) from internet_sales cross join products group by 1"
PEOPLE = {"alice": {"token": "cube-token-alice", "role": "editor", "groups": []}, "bob": {"token": "cube-token-bob", "role": "editor", "groups": ["Ops"]}, "root": {"token": "cube-token-root", "role": "admin", "groups": []}}


@pytest.fixture()
def api(monkeypatch):
    who = {"name": "alice"}
    main.app.dependency_overrides[main.current_caller] = lambda: main.Caller(name=who["name"], raw="kc")
    monkeypatch.setattr(main, "cube_session", lambda caller: {"token": PEOPLE[caller.name]["token"], "role": PEOPLE[caller.name]["role"], "groups": PEOPLE[caller.name]["groups"], "lab": True, "blocked_cubes": []})
    monkeypatch.setattr(main, "STORE", MemoryStore())
    monkeypatch.setattr(main, "_per_user", {})
    monkeypatch.setattr(main, "audit", lambda entry: None)
    calls = []

    def execute(user, token, sql, limit):
        calls.append((user, token, sql))
        rows = [["Bikes", 9000.0]] if user == "alice" else [["Bikes", 1.0]]                          # what each person's rules give them
        return {"columns": [{"name": "category", "type": "string"}, {"name": "revenue", "type": "number"}], "rows": rows, "row_count": 1, "truncated": False}
    monkeypatch.setattr(main, "execute", execute)
    yield TestClient(main.app), who, calls
    main.app.dependency_overrides.clear()


def test_saving_off_says_so_and_info_tells_the_page(monkeypatch):
    main.app.dependency_overrides[main.current_caller] = lambda: main.Caller(name="alice", raw="kc")
    monkeypatch.setattr(main, "cube_session", lambda caller: {"token": "t", "role": "editor", "lab": True})
    monkeypatch.setattr(main, "STORE", None)
    client = TestClient(main.app)
    assert client.get("/info").json()["saving"] is False
    r = client.get("/queries")
    assert r.status_code == 503 and "LAB_DB_PASSWORD" in r.json()["detail"]
    main.app.dependency_overrides.clear()


def test_a_shared_query_runs_as_the_runner_and_leaves_the_runners_own_snapshot(api):
    client, who, calls = api
    q = client.post("/queries", json={"title": "Revenue", "sql": SQL, "shares": [{"type": "group", "principal": "Ops", "permission": "view"}]}).json()
    alice = client.post(f"/queries/{q['id']}/run").json()
    assert alice["rows"] == [["Bikes", 9000.0]] and alice["snapshot"]["expires_at"]
    who["name"] = "bob"
    bob_before = client.get(f"/queries/{q['id']}/snapshot")
    assert bob_before.status_code == 404, "alice's answer is not bob's to read"
    bob = client.post(f"/queries/{q['id']}/run").json()
    assert bob["rows"] == [["Bikes", 1.0]]
    assert calls[-1][:2] == ("bob", "cube-token-bob"), "the statement went to Cube with BOB's token, not the owner's"
    assert client.get(f"/queries/{q['id']}/snapshot").json()["rows"] == [["Bikes", 1.0]]
    who["name"] = "alice"
    assert client.get(f"/queries/{q['id']}/snapshot").json()["rows"] == [["Bikes", 9000.0]]


def test_a_stranger_cannot_run_or_read_and_the_http_rules_match_the_rules_module(api):
    client, who, _ = api
    q = client.post("/queries", json={"title": "Private", "sql": "select 1"}).json()
    who["name"] = "bob"
    assert client.get(f"/queries/{q['id']}").status_code == 404 and client.post(f"/queries/{q['id']}/run").status_code == 404 and client.get("/queries").json() == []
    assert client.put(f"/queries/{q['id']}", json={"title": "x"}).status_code == 404 and client.delete(f"/queries/{q['id']}").status_code == 404
    who["name"] = "alice"
    assert client.put(f"/queries/{q['id']}", json={"title": "Renamed", "shares": [{"type": "user", "principal": "bob", "permission": "edit"}]}).json()["title"] == "Renamed"
    who["name"] = "bob"
    assert client.put(f"/queries/{q['id']}", json={"sql": "select 2"}).json()["sql"] == "select 2"
    assert client.put(f"/queries/{q['id']}", json={"shares": []}).status_code == 403 and client.delete(f"/queries/{q['id']}").status_code == 403


def test_a_bad_query_is_refused_when_saved_and_a_run_is_audited_and_limited(api):
    client, _, calls = api
    assert client.post("/queries", json={"title": "x", "sql": "drop table t"}).status_code == 422
    assert client.post("/queries", json={"title": "", "sql": "select 1"}).status_code == 422
    q = client.post("/queries", json={"title": "ok", "sql": "select 1"}).json()
    assert client.post(f"/queries/{q['id']}/run").status_code == 200 and len(calls) == 1


def test_ownership_folders_null_and_the_admin_handover(api):
    client, who, _ = api
    q = client.post("/queries", json={"title": "x", "sql": "select 1"}).json()
    assert client.put(f"/queries/{q['id']}", json={"owner": "bob"}).json()["owner"] == "bob"
    assert client.post("/transfer", json={"from_user": "bob", "to_user": "root"}).status_code == 403
    who["name"] = "root"
    assert client.post("/transfer", json={"from_user": "bob", "to_user": "root"}).json() == {"transferred": 1}
    assert client.get("/queries").json()[0]["owner"] == "root"
    assert client.put(f"/queries/{q['id']}", json={"folder_id": None}).json()["folder_id"] is None
    assert client.delete(f"/queries/{q['id']}").status_code == 204


def test_the_folders_a_person_may_use_are_listed(api, monkeypatch):
    client, who, _ = api
    main.STORE.folder_rows.update({"f1": {"id": "f1", "name": "Mine", "owner": "alice", "shares": []},
                                   "f2": {"id": "f2", "name": "Theirs", "owner": "root", "shares": [{"type": "user", "principal": "alice", "permission": "view"}]},
                                   "f3": {"id": "f3", "name": "Edit", "owner": "root", "shares": [{"type": "group", "principal": "Ops", "permission": "edit"}]}, "f4": {"id": "f4", "name": "Hidden", "owner": "root", "shares": []}})
    names = {f["name"]: f["can_edit"] for f in client.get("/query-folders").json()}
    assert names == {"Mine": True, "Theirs": False}
    who["name"] = "bob"
    assert {f["name"]: f["can_edit"] for f in client.get("/query-folders").json()} == {"Edit": True}
    who["name"] = "root"
    assert len(client.get("/query-folders").json()) == 4
