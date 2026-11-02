"""Saved queries: who may see, run, change, share and delete them, and that a result snapshot is only ever its runner's own. Runs on memory, and on Postgres when LAB_TEST_PG_DSN points at one.

  LAB_TEST_PG_DSN="host=... dbname=postgres user=lab_app password=..." PYTHONPATH=. python -m pytest tests -q
"""
import os
import time

import pytest

import queries
from store import MemoryStore, PgStore

PG = os.environ.get("LAB_TEST_PG_DSN")
SQL = "select category, measure(revenue) from internet_sales cross join products group by 1"
OUT = {"columns": [{"name": "category", "type": "string"}], "rows": [["Bikes"]], "row_count": 1, "truncated": False, "ms": 5}


def who(name="alice", role="manager", groups=()):
    return queries.Who(name=name, role=role, groups=list(groups))


@pytest.fixture(params=["memory", pytest.param("pg", marks=pytest.mark.skipif(not PG, reason="LAB_TEST_PG_DSN is not set"))])
def store(request):
    if request.param == "memory":
        yield MemoryStore()
        return
    st = PgStore(**dict(p.split("=", 1) for p in PG.split()))
    with st._conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM lab.saved_queries")
    yield st
    with st._conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM lab.saved_queries")


def put_folder(store, id_, owner, shares=()):
    """A folder as the dashboards keep it (in Postgres it belongs to the builder's schema, which this login only reads)."""
    if isinstance(store, MemoryStore):
        store.folder_rows[id_] = {"id": id_, "name": f"Folder {id_}", "owner": owner, "shares": list(shares)}
        return
    with store._conn() as conn, conn.cursor() as cur:
        pytest.importorskip("psycopg2")
        cur.execute("SELECT to_regclass('builder.folders') IS NOT NULL AS ok")
        if not cur.fetchone()["ok"]:
            pytest.skip("builder.folders is not there")
    pytest.skip("the lab login only reads builder.folders; folder sharing is covered on memory")


def share(store, owner, id_, *shares):
    return queries.update(store, owner, id_, shares=[{"type": t, "principal": p, "permission": perm} for t, p, perm in shares])


def test_a_query_is_private_until_shared_with_a_person_or_a_group(store):
    q = queries.create(store, who("alice"), title="Revenue", sql=SQL + ";")
    assert q["mine"] and q["sql"] == SQL, "the trailing ; is dropped when it is saved"
    assert queries.list_queries(store, who("bob")) == []
    share(store, who("alice"), q["id"], ("user", "bob", "view"), ("group", "Ops", "view"))
    assert [x["id"] for x in queries.list_queries(store, who("bob"))] == [q["id"]]
    assert [x["id"] for x in queries.list_queries(store, who("carol", groups=["Ops"]))] == [q["id"]]
    assert queries.list_queries(store, who("dave", groups=["Other"])) == []
    seen = queries.list_queries(store, who("bob"))[0]
    assert seen["shared_with_me"] and not seen["can_edit"] and "shares" not in seen
    assert len(queries.get(store, who("alice"), q["id"])["shares"]) == 2


def test_edit_changes_the_sql_but_not_the_sharing_and_view_changes_nothing(store):
    q = queries.create(store, who("alice"), title="Revenue", sql=SQL)
    share(store, who("alice"), q["id"], ("user", "bob", "edit"), ("user", "carol", "view"))
    assert queries.update(store, who("bob"), q["id"], sql="select 1", title="By bob")["sql"] == "select 1"
    with pytest.raises(queries.QueryError) as e:
        queries.update(store, who("carol"), q["id"], sql="select 2")
    assert e.value.status == 403
    for kw in ({"shares": []}, {"folder_id": None}, {"owner": "bob"}):
        with pytest.raises(queries.QueryError) as e:
            queries.update(store, who("bob"), q["id"], **kw)
        assert e.value.status == 403, kw
    with pytest.raises(queries.QueryError) as e:
        queries.delete(store, who("bob"), q["id"])
    assert e.value.status == 403


def test_the_sql_is_checked_when_it_is_saved_and_when_it_is_changed(store):
    for bad in ("drop table x", "select 1; select 2", ""):
        with pytest.raises(queries.QueryError) as e:
            queries.create(store, who("alice"), title="x", sql=bad)
        assert e.value.status == 422
    q = queries.create(store, who("alice"), title="x", sql="select 1")
    with pytest.raises(queries.QueryError):
        queries.update(store, who("alice"), q["id"], sql="delete from t")
    with pytest.raises(queries.QueryError):
        queries.create(store, who("alice"), title="   ", sql="select 1")


def test_bad_shares_are_refused_and_a_person_twice_keeps_the_stronger_permission(store):
    q = queries.create(store, who("alice"), title="x", sql="select 1")
    for bad in ([{"type": "team", "principal": "x", "permission": "view"}], [{"type": "user", "principal": "", "permission": "view"}], [{"type": "user", "principal": "x", "permission": "own"}], "bob"):
        with pytest.raises(queries.QueryError) as e:
            queries.update(store, who("alice"), q["id"], shares=bad)
        assert e.value.status == 422
    assert share(store, who("alice"), q["id"], ("user", "bob", "view"), ("user", "bob", "edit"))["shares"] == [{"type": "user", "principal": "bob", "permission": "edit"}]


def test_a_stranger_is_told_nothing_exists_and_an_admin_sees_everything(store):
    q = queries.create(store, who("alice"), title="x", sql="select 1")
    with pytest.raises(queries.QueryError) as e:
        queries.get(store, who("mallory"), q["id"])
    assert e.value.status == 404
    assert [x["id"] for x in queries.list_queries(store, who("root", "admin"))] == [q["id"]]
    assert queries.get(store, who("root", "admin"), q["id"])["can_manage"] and not queries.get(store, who("root", "admin"), q["id"])["mine"]


def test_ownership_moves_and_an_admin_hands_a_persons_queries_over(store):
    q = queries.create(store, who("alice"), title="x", sql="select 1")
    assert queries.update(store, who("alice"), q["id"], owner="bob")["owner"] == "bob"
    queries.create(store, who("bob"), title="y", sql="select 2")
    with pytest.raises(queries.QueryError) as e:
        queries.transfer_all(store, who("bob"), "bob", "carol")
    assert e.value.status == 403
    assert queries.transfer_all(store, who("root", "admin"), "bob", "root") == 2
    assert {x["owner"] for x in queries.list_queries(store, who("root", "admin"))} == {"root"}


def test_delete_is_the_owners_or_an_admins_and_takes_the_snapshots_with_it(store):
    q = queries.create(store, who("alice"), title="x", sql="select 1")
    store.put_snapshot(q["id"], "alice", OUT, 24)
    with pytest.raises(queries.QueryError):
        queries.delete(store, who("bob"), q["id"])
    queries.delete(store, who("alice"), q["id"])
    assert store.get(q["id"]) is None and store.snapshot(q["id"], "alice") is None


def test_a_person_may_keep_only_so_many_queries(store, monkeypatch):
    monkeypatch.setattr(queries, "MAX_QUERIES", 2)
    queries.create(store, who("alice"), title="1", sql="select 1")
    queries.create(store, who("alice"), title="2", sql="select 1")
    with pytest.raises(queries.QueryError) as e:
        queries.create(store, who("alice"), title="3", sql="select 1")
    assert e.value.status == 409
    queries.create(store, who("bob"), title="b", sql="select 1")


def test_a_snapshot_is_its_runners_own_and_nobody_elses(store):
    q = queries.create(store, who("alice"), title="x", sql=SQL)
    share(store, who("alice"), q["id"], ("user", "bob", "view"))
    store.put_snapshot(q["id"], "alice", {**OUT, "rows": [["Bikes", 9000]]}, 24)
    assert queries.snapshot_of(store, who("alice"), q["id"])["rows"] == [["Bikes", 9000]]
    with pytest.raises(queries.QueryError) as e:
        queries.snapshot_of(store, who("bob"), q["id"])
    assert e.value.status == 404, "bob has the query but not alice's answer (it was computed under alice's rules)"
    store.put_snapshot(q["id"], "bob", {**OUT, "rows": [["Bikes", 1]]}, 24)
    assert queries.snapshot_of(store, who("bob"), q["id"])["rows"] == [["Bikes", 1]] and queries.snapshot_of(store, who("alice"), q["id"])["rows"] == [["Bikes", 9000]]
    with pytest.raises(queries.QueryError):
        queries.snapshot_of(store, who("mallory"), q["id"])


def test_a_snapshot_expires_and_a_new_run_replaces_it(store):
    q = queries.create(store, who("alice"), title="x", sql=SQL)
    store.put_snapshot(q["id"], "alice", OUT, 24)
    store.put_snapshot(q["id"], "alice", {**OUT, "row_count": 7}, 24)
    assert store.snapshot(q["id"], "alice")["row_count"] == 7 and store.snapshot_runners(q["id"]) == ["alice"]
    store.put_snapshot(q["id"], "alice", OUT, 0.0002)                       # a moment
    time.sleep(1.2)
    assert store.snapshot(q["id"], "alice") is None
    store.put_snapshot(q["id"], "bob", OUT, 0.0002)
    time.sleep(1.2)
    assert store.purge() >= 1 and store.snapshot_runners(q["id"]) == []


def test_a_query_in_a_shared_folder_is_shared_with_the_folders_people(store):
    if not isinstance(store, MemoryStore):
        pytest.skip("folders belong to the builder's schema; covered on memory")
    put_folder(store, "f1", "alice", [{"type": "group", "principal": "Ops", "permission": "edit"}])
    q = queries.create(store, who("alice"), title="x", sql=SQL, folder_id="f1")
    assert q["folder_name"] == "Folder f1"
    assert [x["id"] for x in queries.list_queries(store, who("carol", groups=["Ops"]))] == [q["id"]]
    assert queries.update(store, who("carol", groups=["Ops"]), q["id"], title="by ops")["title"] == "by ops", "edit on the folder is edit on what is in it"
    with pytest.raises(queries.QueryError) as e:
        queries.update(store, who("alice"), q["id"], folder_id="nope")
    assert e.value.status == 404
    assert queries.update(store, who("alice"), q["id"], folder_id=None)["folder_id"] is None
