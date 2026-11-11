"""The lab with two models (PLAN-models.md phase 1): the schema, the examples and the Cube each statement goes to follow the model asked for."""
import pathlib

import pytest
from fastapi.testclient import TestClient

import main
from store import MemoryStore

ROOT = pathlib.Path(__file__).resolve().parents[2]
TWO = {"adventureworks": (str(ROOT / "cube" / "model"), "cube"), "distributor": (str(ROOT / "models" / "distributor" / "cube"), "cube-distributor")}


@pytest.fixture()
def api(monkeypatch):
    main.app.dependency_overrides[main.current_caller] = lambda: main.Caller(name="ayse", raw="kc")
    monkeypatch.setattr(main, "cube_session", lambda caller: {"token": "cube-token", "user": "ayse", "role": "editor", "blocked_cubes": [], "lab": True})
    monkeypatch.setattr(main, "served", lambda: TWO)
    monkeypatch.setattr(main, "_catalogs", {})
    monkeypatch.setattr(main, "STORE", MemoryStore())
    monkeypatch.setattr(main, "_per_user", {})
    monkeypatch.setattr(main, "audit", lambda entry: None)
    sent = []

    def execute(user, token, sql, limit, host=None):
        sent.append((sql, host))
        return {"columns": [{"name": "x", "type": "number"}], "rows": [[1]], "row_count": 1, "truncated": False}
    monkeypatch.setattr(main, "execute", execute)
    yield TestClient(main.app), sent
    main.app.dependency_overrides.clear()


def test_the_schema_and_the_examples_are_the_models_own(api):
    client, _ = api
    aw, dist = client.get("/schema").json(), client.get("/schema?model=distributor").json()
    assert aw["model"] == "adventureworks" and "internet_sales" in {c["name"] for c in aw["cubes"]} and "orders" not in {c["name"] for c in aw["cubes"]}
    assert dist["model"] == "distributor" and {"orders", "dealers"} <= {c["name"] for c in dist["cubes"]} and "internet_sales" not in {c["name"] for c in dist["cubes"]}
    assert dist["examples"] and not any("internet_sales" in e["sql"] for e in dist["examples"]) and "orders" in dist["examples"][0]["sql"]
    assert client.get("/schema?model=atlantis").status_code == 404


def test_a_statement_goes_to_the_cube_of_its_model(api):
    client, sent = api
    sql = "select region, measure(revenue) from orders cross join dealers group by 1"
    assert client.post("/query", json={"sql": sql, "model": "distributor"}).status_code == 200
    assert client.post("/query", json={"sql": "select category, measure(revenue) from internet_sales cross join products group by 1"}).status_code == 200
    assert sent[0][1] == "cube-distributor" and sent[1][1] is None, "only a model with a Cube of its own names its host; the default goes to CUBE_SQL_HOST"
    assert client.post("/query", json={"sql": sql, "model": "atlantis"}).status_code == 404


def test_a_saved_query_belongs_to_a_model_and_runs_on_its_cube(api):
    client, sent = api
    a = client.post("/queries", json={"title": "Dealers", "sql": "select region, measure(revenue) from orders cross join dealers group by 1", "model": "distributor"}).json()
    b = client.post("/queries", json={"title": "Sales", "sql": "select category, measure(revenue) from internet_sales cross join products group by 1"}).json()
    assert a["model"] == "distributor" and b["model"] == "adventureworks"
    ids = lambda q: {r["id"] for r in client.get(f"/queries{q}").json()}  # noqa: E731
    assert ids("") == {a["id"], b["id"]} and ids("?model=distributor") == {a["id"]} and ids("?model=adventureworks") == {b["id"]}
    client.post(f"/queries/{a['id']}/run")
    assert sent[-1][1] == "cube-distributor", "a saved query runs on the model it was saved for"
