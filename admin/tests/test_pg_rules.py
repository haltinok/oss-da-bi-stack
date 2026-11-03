"""The rules store on a real Postgres (skipped without ADMIN_TEST_PG_DSN; CI's builder job provides one, after applying postgres/init/04 and 05).

The access_auth login may read the rules and nothing else: it is what the auth service signs in with.
"""
import os

import pytest

DSN = os.environ.get("ADMIN_TEST_PG_DSN")
AUTH_DSN = os.environ.get("AUTH_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="ADMIN_TEST_PG_DSN is not set")


@pytest.fixture()
def store():
    import psycopg2

    from access import PgRules
    parts = dict(p.split("=", 1) for p in DSN.split())
    s = PgRules(host=parts["host"], port=int(parts.get("port", 5432)), dbname=parts["dbname"], user=parts["user"], password=parts["password"])
    with psycopg2.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("delete from access.rls_rule")
    yield s


def test_put_list_update_rename_delete(store):
    row = store.put("user", "ayse", ["Germany", "France"], "root")
    assert row["values"] == ["Germany", "France"] and row["updated_by"] == "root"
    store.put("user", "ayse", ["Canada"], "root2")
    store.put("group", "EU", ["France"], "root")
    assert [(r["type"], r["principal"], r["values"]) for r in store.list()] == [("group", "EU", ["France"]), ("user", "ayse", ["Canada"])]
    store.rename("group", "EU", "Europe")
    assert [r["principal"] for r in store.list() if r["type"] == "group"] == ["Europe"]
    assert store.delete("user", "ayse") and not store.delete("user", "ayse")


def test_the_table_refuses_what_a_rule_cannot_be(store):
    import psycopg2
    for type_, principal, values in (("team", "x", ["A"]), ("user", "x", [])):
        with pytest.raises(psycopg2.errors.CheckViolation):
            store.put(type_, principal, values, "root")


@pytest.mark.skipif(not AUTH_DSN, reason="AUTH_TEST_PG_DSN is not set")
def test_the_auth_login_can_read_but_not_write():
    import psycopg2
    with psycopg2.connect(AUTH_DSN) as conn, conn.cursor() as cur:
        cur.execute("select count(*) from access.rls_rule")
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("delete from access.rls_rule")


def test_datasets_and_grants_on_postgres(store):
    import psycopg2
    with psycopg2.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute('delete from access."grant"')
        cur.execute("delete from access.dataset")
    row = store.put_dataset("sales", "Sales", "facts", ["internet_sales", "reseller_sales"], [{"type": "role", "principal": "editor"}, {"type": "group", "principal": "EU"}], "root")
    assert row["cubes"] == ["internet_sales", "reseller_sales"] and {(g["type"], g["principal"]) for g in row["grants"]} == {("role", "editor"), ("group", "EU")}
    store.put_dataset("sales", "Sales 2", "", ["internet_sales"], [], "root")
    assert [(d["name"], d["grants"]) for d in store.datasets()] == [("Sales 2", [])]
    store.put_dataset("sales", "Sales 2", "", ["internet_sales"], [{"type": "group", "principal": "EU"}], "root")
    store.rename_grants("group", "EU", "Europe")
    assert store.datasets()[0]["grants"] == [{"type": "group", "principal": "Europe", "permission": "view"}]
    ds, gs = store.resolve_input()
    assert ds == [{"id": "sales", "cubes": ["internet_sales"], "members": []}] and gs == [{"object_id": "sales", "principal_type": "group", "principal": "Europe", "permission": "view"}]
    store.drop_grants("group", "Europe")
    assert store.datasets()[0]["grants"] == []
    assert store.delete_dataset("sales") and not store.delete_dataset("sales")


def test_the_dataset_tables_refuse_a_bad_id_or_an_empty_cube_list(store):
    import psycopg2
    with pytest.raises(psycopg2.errors.CheckViolation):
        store.put_dataset("Bad Id", "x", "", ["a"], [], "root")
    with pytest.raises(psycopg2.errors.CheckViolation):
        store.put_dataset("ok", "x", "", [], [], "root")


def test_the_auth_and_builder_logins_read_datasets_but_cannot_write():
    import psycopg2
    for dsn in (AUTH_DSN, os.environ.get("BUILDER_TEST_PG_DSN")):
        if not dsn:
            continue
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("select count(*) from access.dataset")
            cur.execute('select count(*) from access."grant"')
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("delete from access.dataset")


def test_a_lab_grant_is_stored_and_a_bad_permission_refused(store):
    import psycopg2
    row = store.put_dataset("labs", "Labs", "", ["internet_sales"], [{"type": "role", "principal": "editor", "permission": "lab"}], "root")
    assert row["grants"] == [{"type": "role", "principal": "editor", "permission": "lab"}]
    with pytest.raises(psycopg2.errors.CheckViolation):
        store.put_dataset("labs", "Labs", "", ["internet_sales"], [{"type": "role", "principal": "editor", "permission": "own"}], "root")
    store.delete_dataset("labs")


def test_a_dataset_of_single_fields_on_postgres(store):
    import psycopg2
    with psycopg2.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute('delete from access."grant"')
        cur.execute("delete from access.dataset")
    row = store.put_dataset("profit", "Profit", "", [], [{"type": "role", "principal": "admin", "permission": "view"}], "root", members=["internet_sales.gross_profit"])
    assert row["cubes"] == [] and row["members"] == ["internet_sales.gross_profit"]
    ds, _ = store.resolve_input()
    assert ds == [{"id": "profit", "cubes": [], "members": ["internet_sales.gross_profit"]}]
    with pytest.raises(psycopg2.errors.CheckViolation):
        store.put_dataset("empty", "Empty", "", [], [], "root", members=[])
    store.delete_dataset("profit")


def test_a_rule_is_per_dimension(store):
    import psycopg2
    store.put("user", "ayse", ["Germany"], "root")
    store.put("user", "ayse", ["Internet"], "root", "channel")
    assert sorted((r["dimension"], r["values"]) for r in store.list()) == [("channel", ["Internet"]), ("territory", ["Germany"])]
    store.rename("user", "ayse", "ayse2")
    assert {r["principal"] for r in store.list()} == {"ayse2"}
    assert store.delete("user", "ayse2", "channel") and [r["dimension"] for r in store.list()] == ["territory"]
    store.put("user", "ayse2", ["Internet"], "root", "channel")
    assert store.delete("user", "ayse2") and store.list() == [], "no dimension: all of them"
    with pytest.raises(psycopg2.errors.CheckViolation):
        store.put("user", "x", ["A"], "root", "Not A Dimension")
