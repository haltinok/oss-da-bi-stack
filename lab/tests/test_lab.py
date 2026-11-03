"""The lab service with the auth service and Cube replaced by fakes: who gets in, what is refused, the limits, the audit line, the schema each role sees.

  cd lab && PYTHONPATH=. uv run --with pytest --with fastapi --with httpx --with 'pyjwt[crypto]' --with psycopg2-binary --with pyyaml python -m pytest tests -q
"""
import datetime
import decimal
import threading
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main

ME = main.Caller(name="ayse", raw="kc-token")


def session(**kw):
    return {"token": "cube-token", "user": "ayse", "role": "editor", "territories": ["Canada"], "blocked_cubes": [], "lab": True, **kw}


@pytest.fixture()
def api(monkeypatch):
    main.app.dependency_overrides[main.current_caller] = lambda: ME
    monkeypatch.setattr(main, "cube_session", lambda caller: session())
    monkeypatch.setattr(main, "_per_user", {})
    lines = []
    monkeypatch.setattr(main, "audit", lambda entry: lines.append(entry))
    yield TestClient(main.app), lines
    main.app.dependency_overrides.clear()


def fake_execute(rows=None, columns=None, delay=0.0, boom=None):
    calls = []

    def run(user, token, sql, limit):
        calls.append((user, token, sql, limit))
        time.sleep(delay)
        if boom:
            raise boom
        data = rows if rows is not None else [[1, "a"]]
        return {"columns": columns or [{"name": "n", "type": "number"}, {"name": "s", "type": "string"}], "rows": data[:limit], "row_count": min(len(data), limit), "truncated": len(data) > limit}
    run.calls = calls
    return run


def test_a_query_runs_as_the_person_with_their_cube_token_and_is_audited(api, monkeypatch):
    client, lines = api
    run = fake_execute(rows=[[1, "a"], [2, "b"]])
    monkeypatch.setattr(main, "execute", run)
    r = client.post("/query", json={"sql": "select n, s from internet_sales;"})
    assert r.status_code == 200 and r.json()["rows"] == [[1, "a"], [2, "b"]] and r.json()["row_count"] == 2 and r.json()["truncated"] is False and r.json()["ms"] >= 0
    assert run.calls == [("ayse", "cube-token", "select n, s from internet_sales", main.ROW_LIMIT)]
    assert lines[0]["user"] == "ayse" and lines[0]["role"] == "editor" and lines[0]["rows"] == 2 and "select n, s" in lines[0]["sql"]


def test_without_the_lab_nothing_runs_and_the_page_is_told_why(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(main, "cube_session", lambda caller: session(lab=False))
    run = fake_execute()
    monkeypatch.setattr(main, "execute", run)
    for path, method in (("/query", "post"), ("/schema", "get")):
        r = getattr(client, method)(path, **({"json": {"sql": "select 1"}} if method == "post" else {}))
        assert r.status_code == 403 and "SQL lab" in r.json()["detail"]
    assert run.calls == []
    assert client.get("/info").json()["lab"] is False, "info says so without refusing, so the page can explain"


def test_statements_that_are_not_one_select_never_reach_cube(api, monkeypatch):
    client, _ = api
    run = fake_execute()
    monkeypatch.setattr(main, "execute", run)
    for sql in ("drop table x", "select 1; select 2", "", "insert into x values (1)"):
        assert client.post("/query", json={"sql": sql}).status_code == 400
    assert run.calls == []


def test_the_row_cap_marks_a_result_as_cut(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(main, "ROW_LIMIT", 3)
    monkeypatch.setattr(main, "execute", fake_execute(rows=[[i, "x"] for i in range(10)]))
    r = client.post("/query", json={"sql": "select n, s from t"}).json()
    assert r["row_count"] == 3 and r["truncated"] is True and len(r["rows"]) == 3


def test_cubes_refusals_come_back_in_cubes_words_without_the_statement(api, monkeypatch):
    client, lines = api
    monkeypatch.setattr(main, "execute", fake_execute(boom=RuntimeError("Database Execution Error: Profit and margin are not available for your role\nQUERY: SELECT measure(gross_profit)")))
    r = client.post("/query", json={"sql": "select measure(gross_profit) from internet_sales"})
    assert r.status_code == 400 and r.json()["detail"] == "Profit and margin are not available for your role" and "QUERY" not in r.json()["detail"]
    assert "error" in lines[0]
    monkeypatch.setattr(main, "execute", fake_execute(boom=RuntimeError('FATAL:  password authentication failed for user "ayse"')))
    assert "could not reach" in client.post("/query", json={"sql": "select 1"}).json()["detail"], "connection details do not leak"


def test_a_slow_query_is_given_up_on_and_its_slot_is_freed_when_cube_finishes(api, monkeypatch):
    client, lines = api
    monkeypatch.setattr(main, "TIMEOUT", 0.2)
    monkeypatch.setattr(main, "execute", fake_execute(delay=0.6))
    t0 = time.time()
    r = client.post("/query", json={"sql": "select 1"})
    assert r.status_code == 504 and "longer than" in r.json()["detail"] and time.time() - t0 < 0.55
    assert lines[0]["error"] == "timeout"
    time.sleep(0.8)
    monkeypatch.setattr(main, "execute", fake_execute())
    assert client.post("/query", json={"sql": "select 1"}).status_code == 200, "the slot came back"


def test_a_person_has_a_few_queries_at_a_time(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(main, "PER_USER", 1)
    monkeypatch.setattr(main, "_per_user", {})
    monkeypatch.setattr(main, "execute", fake_execute(delay=0.5))
    out = {}
    first = threading.Thread(target=lambda: out.setdefault("first", client.post("/query", json={"sql": "select 1"})))
    first.start()
    time.sleep(0.15)
    second = client.post("/query", json={"sql": "select 2"})
    first.join()
    assert second.status_code == 429 and "already have" in second.json()["detail"] and out["first"].status_code == 200


def test_values_are_made_safe_for_json():
    assert main.plain(decimal.Decimal("1.50")) == 1.5 and main.plain(decimal.Decimal("NaN")) == "NaN"
    assert main.plain(datetime.datetime(2026, 1, 2, 3, 4)) == "2026-01-02T03:04:00" and main.plain(datetime.date(2026, 1, 2)) == "2026-01-02"
    assert main.plain(float("inf")) == "inf" and main.plain(None) is None and main.plain(b"\x01\xff") == "01ff" and main.plain(True) is True and main.plain(7) == 7
    assert [main.kind_of(c) for c in (1700, 23, 1114, 16, 25)] == ["number", "number", "time", "boolean", "string"]


def test_each_role_sees_the_cubes_and_members_it_may_query(api, monkeypatch):
    client, _ = api

    def schema_as(**kw):
        monkeypatch.setattr(main, "cube_session", lambda caller: session(**kw))
        return {c["name"]: c for c in client.get("/schema").json()["cubes"]}

    admin = schema_as(role="admin")
    assert {"internet_sales", "customers", "inventory_health", "products"} <= set(admin)
    editor = schema_as(role="editor", blocked_cubes=["customers", "inventory_health"])
    assert "customers" not in editor and "inventory_health" not in editor and "internet_sales" in editor
    assert "gross_profit" in {m["name"] for m in editor["internet_sales"]["measures"]}
    limited = schema_as(role="editor", blocked_members=["internet_sales.gross_profit", "internet_sales.margin_pct"])
    assert "gross_profit" not in {m["name"] for m in limited["internet_sales"]["measures"]} and "margin_pct" not in {m["name"] for m in limited["internet_sales"]["measures"]}
    buyer = schema_as(role="editor", blocked_cubes=["internet_sales", "reseller_sales", "customers", "territories"])
    assert {"inventory_health", "products"} <= set(buyer) and "internet_sales" not in buyer and "vendor_name" in {d["name"] for d in buyer["inventory_health"]["dimensions"]}
    hidden = schema_as(role="editor", blocked_members=["inventory_health.vendor_name"])
    assert "vendor_name" not in {d["name"] for d in hidden["inventory_health"]["dimensions"]}
    blocked = schema_as(role="editor", blocked_cubes=["products"])
    assert "products" not in blocked and "products" not in blocked["internet_sales"]["joins"], "a blocked cube is not listed, nor offered as a join"


def test_who_is_let_in(monkeypatch):
    main.app.dependency_overrides.clear()
    client = TestClient(main.app)
    assert client.get("/info").status_code == 401 and client.post("/query", json={"sql": "select 1"}).status_code == 401
    assert client.get("/info", headers={"Authorization": "Bearer junk"}).status_code == 401

    class Key:
        key = "k"

    monkeypatch.setattr(main, "jwks", type("J", (), {"get_signing_key_from_jwt": lambda self, raw: Key()})())
    monkeypatch.setattr(main.jwt, "decode", lambda *a, **k: {"azp": "other", "preferred_username": "x"})
    assert client.get("/info", headers={"Authorization": "Bearer t"}).status_code == 401
    monkeypatch.setattr(main.jwt, "decode", lambda *a, **k: {"azp": "dashboard", "preferred_username": "ayse"})
    monkeypatch.setattr(main, "cube_session", lambda caller: session())
    assert client.get("/info", headers={"Authorization": "Bearer t"}).json()["user"] == "ayse"
    assert client.get("/healthz").status_code == 200


def test_the_auth_services_refusals_are_passed_on(monkeypatch):
    class R:
        status_code = 403
        headers = {"content-type": "application/json"}

        def json(self):
            return {"detail": "no territories assigned"}

    monkeypatch.setattr(main.httpx, "post", lambda *a, **k: R())
    with pytest.raises(HTTPException) as e:
        main.cube_session(ME)
    assert e.value.status_code == 403 and "territories" in e.value.detail


def test_a_blocked_field_is_left_out_of_the_schema_browser(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(main, "cube_session", lambda caller: session(role="admin", blocked_members=["internet_sales.revenue"]))
    cubes = {c["name"]: c for c in client.get("/schema").json()["cubes"]}
    assert "revenue" not in {m["name"] for m in cubes["internet_sales"]["measures"]} and "orders" in {m["name"] for m in cubes["internet_sales"]["measures"]}
