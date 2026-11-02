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
