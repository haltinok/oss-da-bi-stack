"""The SQL lab against the real stack (Keycloak, auth, Cube's SQL API, StarRocks): the lab runs each statement as the signed-in person, so the dashboards' rules apply to it.

  set -a; . ./.env; set +a
  uv run --with pytest --with requests --with pymysql --with pyjwt python -I -m pytest cube/tests/test_lab.py -v

Needs the `lab` service up (LAB_URL, default http://localhost:8450) and the postgres container (LAB_PG_CONTAINER, default oss_postgres) to give a person the lab.
"""
import os
import subprocess

import pytest
import requests

KEYCLOAK = os.environ.get("KEYCLOAK_URL", "http://localhost:8180")
LAB = os.environ.get("LAB_URL", f"http://localhost:{os.environ.get('LAB_PORT', '8450')}")
PG = os.environ.get("LAB_PG_CONTAINER", "oss_postgres")
PASSWORD = os.environ["TEST_USER_PASSWORD"]
REVENUE = "select measure(revenue) as revenue from internet_sales"


def kc(user):
    r = requests.post(f"{KEYCLOAK}/realms/spike/protocol/openid-connect/token", data={"grant_type": "password", "client_id": "dashboard", "username": user, "password": PASSWORD}, timeout=30)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def query(user, sql):
    return requests.post(f"{LAB}/query", headers=kc(user), json={"sql": sql}, timeout=120)


def psql(sql):
    subprocess.run(["docker", "exec", PG, "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-c", sql], check=True, capture_output=True)


@pytest.fixture()
def lab_for_managers():
    """A dataset on an inventory cube (nobody's dashboards use it) whose grant gives the manager role the SQL lab; removed afterwards."""
    psql("insert into access.dataset (id, name, cubes, updated_by) values ('ci-lab', 'CI lab', array['offer_performance'], 'ci') on conflict (id) do nothing")
    psql("insert into access.\"grant\" (object_type, object_id, principal_type, principal, permission, granted_by) values ('dataset', 'ci-lab', 'role', 'manager', 'lab', 'ci') on conflict do nothing")
    try:
        yield
    finally:
        psql("delete from access.\"grant\" where object_id = 'ci-lab'")
        psql("delete from access.dataset where id = 'ci-lab'")


def test_the_lab_is_off_for_someone_who_was_not_given_it():
    assert requests.get(f"{LAB}/healthz", timeout=10).status_code == 200
    assert requests.post(f"{LAB}/query", json={"sql": "select 1"}, timeout=10).status_code == 401
    info = requests.get(f"{LAB}/info", headers=kc("na_manager"), timeout=60).json()
    assert info["lab"] is False and info["role"] == "manager"
    r = query("na_manager", REVENUE)
    assert r.status_code == 403 and "SQL lab" in r.json()["detail"]


def test_an_admin_runs_a_measure_query_and_gets_the_rows_in_order():
    r = query("admin", "select category, measure(revenue) as revenue from internet_sales cross join products group by 1 order by 2 desc")
    assert r.status_code == 200, r.text
    out = r.json()
    assert [c["name"] for c in out["columns"]] == ["category", "revenue"] and out["columns"][1]["type"] == "number"
    revenues = [row[1] for row in out["rows"]]
    assert out["row_count"] == len(out["rows"]) >= 2 and revenues == sorted(revenues, reverse=True) and out["truncated"] is False


def test_statements_that_are_not_one_select_are_refused_before_cube_sees_them():
    for sql in ("drop table internet_sales", "select 1; select 2", "insert into internet_sales(order_number) values ('x')"):
        assert query("admin", sql).status_code == 400
    r = query("admin", "select count(*) from mart.fact_internet_sales")
    assert r.status_code == 400, "the warehouse tables behind the cubes are not reachable: only cubes are"


def test_a_row_limit_cuts_a_long_result_and_says_so():
    r = query("admin", "select order_number from internet_sales limit 20000")
    assert r.status_code == 200
    out = r.json()
    assert out["row_count"] <= int(os.environ.get("LAB_ROW_LIMIT", "10000")) and (out["truncated"] or out["row_count"] < 10000)


def test_with_the_lab_a_manager_gets_the_dashboards_rules_territories_and_all(lab_for_managers):
    admin = query("admin", REVENUE).json()["rows"][0][0]
    manager = query("na_manager", REVENUE)
    assert manager.status_code == 200, manager.text
    assert 0 < manager.json()["rows"][0][0] < admin, "a manager's revenue is only their territories' (the admin's is everyone's)"
    for sql, why in (("select count(*) from customers", "customer data is admin-only"), ("select count(*) from inventory_health", "inventory is not for managers")):
        r = query("na_manager", sql)
        assert r.status_code == 400 and "not available" in r.json()["detail"], why
    schema = requests.get(f"{LAB}/schema", headers=kc("na_manager"), timeout=60).json()["cubes"]
    names = {c["name"] for c in schema}
    assert "internet_sales" in names and "customers" not in names and "inventory_health" not in names


def test_a_rep_cannot_reach_profit_in_the_lab_either(lab_for_managers):
    psql("insert into access.\"grant\" (object_type, object_id, principal_type, principal, permission, granted_by) values ('dataset', 'ci-lab', 'role', 'rep', 'lab', 'ci') on conflict do nothing")
    r = query("de_rep", "select measure(gross_profit) from internet_sales")
    assert r.status_code == 400 and "Profit" in r.json()["detail"]
    assert query("de_rep", REVENUE).status_code == 200
    cubes = {c["name"]: c for c in requests.get(f"{LAB}/schema", headers=kc("de_rep"), timeout=60).json()["cubes"]}
    assert "gross_profit" not in {m["name"] for m in cubes["internet_sales"]["measures"]}


def test_a_result_exports_as_csv_and_excel_with_the_same_rules():
    sql = "select category, measure(revenue) as revenue from internet_sales cross join products group by 1 order by 2 desc"
    r = requests.post(f"{LAB}/export", headers=kc("admin"), json={"sql": sql, "format": "csv"}, timeout=120)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and r.headers["x-lab-truncated"] == "false"
    lines = r.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0] == "category,revenue" and len(lines) == int(r.headers["x-lab-rows"]) + 1 >= 3
    x = requests.post(f"{LAB}/export", headers=kc("admin"), json={"sql": sql, "format": "xlsx"}, timeout=120)
    assert x.status_code == 200 and x.content[:2] == b"PK" and "spreadsheetml" in x.headers["content-type"], "an .xlsx is a zip"
    assert requests.post(f"{LAB}/export", headers=kc("na_manager"), json={"sql": sql, "format": "csv"}, timeout=60).status_code == 403, "no lab, no export"
    assert requests.post(f"{LAB}/export", headers=kc("admin"), json={"sql": "drop table internet_sales", "format": "csv"}, timeout=60).status_code == 400


def test_a_saved_query_runs_as_the_runner_and_the_snapshot_is_the_runners_own(lab_for_managers):
    sql = "select measure(revenue) as revenue from internet_sales"
    h_admin, h_manager = kc("admin"), kc("na_manager")
    made = requests.post(f"{LAB}/queries", headers=h_admin, json={"title": "CI revenue", "sql": sql, "shares": [{"type": "user", "principal": "na_manager", "permission": "view"}]}, timeout=60)
    assert made.status_code == 201, made.text
    qid = made.json()["id"]
    try:
        assert requests.get(f"{LAB}/queries/{qid}/snapshot", headers=h_admin, timeout=60).status_code == 404, "nothing was run yet"
        admin_run = requests.post(f"{LAB}/queries/{qid}/run", headers=h_admin, timeout=120).json()
        manager_run = requests.post(f"{LAB}/queries/{qid}/run", headers=h_manager, timeout=120)
        assert manager_run.status_code == 200, manager_run.text
        assert 0 < manager_run.json()["rows"][0][0] < admin_run["rows"][0][0], "the shared query ran as the manager: only their territories"
        assert requests.get(f"{LAB}/queries/{qid}/snapshot", headers=h_admin, timeout=60).json()["rows"] == admin_run["rows"]
        assert requests.get(f"{LAB}/queries/{qid}/snapshot", headers=h_manager, timeout=60).json()["rows"] == manager_run.json()["rows"], "each keeps their own"
        assert [q["id"] for q in requests.get(f"{LAB}/queries", headers=h_manager, timeout=60).json()] == [qid]
        assert requests.put(f"{LAB}/queries/{qid}", headers=h_manager, json={"title": "mine now"}, timeout=60).status_code == 403
        assert requests.post(f"{LAB}/queries", headers=h_manager, json={"title": "bad", "sql": "drop table x"}, timeout=60).status_code == 422
    finally:
        requests.delete(f"{LAB}/queries/{qid}", headers=h_admin, timeout=60)
    assert requests.get(f"{LAB}/queries/{qid}", headers=h_manager, timeout=60).status_code == 404
