"""The proposal agent's contract with the actions service (needs the stack; see test_actions.py for the env).

The agent is a Keycloak service account: it may draft proposals and read inventory, and nothing else. A
person approves or dismisses a proposal; approving goes through the normal action endpoints.
"""
import os
import uuid

import psycopg2
import pymysql
import pytest
import requests

ACTIONS = os.environ.get("ACTIONS_URL", "http://localhost:8300")
KEYCLOAK = os.environ.get("KEYCLOAK_URL", "http://localhost:8180")
PASSWORD = os.environ["TEST_USER_PASSWORD"]
TAG = "test-" + uuid.uuid4().hex[:8]


def human(user):
    r = requests.post(f"{KEYCLOAK}/realms/spike/protocol/openid-connect/token", timeout=30,
                      data={"grant_type": "password", "client_id": "dashboard", "username": user, "password": PASSWORD})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def agent():
    r = requests.post(f"{KEYCLOAK}/realms/spike/protocol/openid-connect/token", timeout=30,
                      data={"grant_type": "client_credentials", "client_id": "inventory-agent", "client_secret": os.environ["AGENT_CLIENT_SECRET"]})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def who():
    return {"agent": agent(), "buyer": human("buyer"), "marketer": human("marketer"), "admin": human("admin")}


def sr(q):
    with pymysql.connect(host="127.0.0.1", port=int(os.environ.get("STARROCKS_MYSQL_PORT", "9030")), user="root").cursor() as cur:
        cur.execute(q)
        return cur.fetchall()


@pytest.fixture
def pgdb():
    conn = psycopg2.connect(host="127.0.0.1", port=int(os.environ.get("POSTGRES_ACTIVE_PORT", "5434")), dbname="active_db",
                            user="postgres", password=os.environ["POSTGRES_PASSWORD"])
    conn.autocommit = True
    yield conn
    with conn.cursor() as cur:
        cur.execute("delete from public.proposals where run_id like %s", (TAG + "%",))
        cur.execute("delete from public.actions_log where idempotency_key like %s", (TAG + "%",))
    conn.close()


def run_id(name):
    return f"{TAG}-{name}-{uuid.uuid4().hex[:6]}"


def wo_proposal(pid, qty, title="Restock in-house item"):
    return {"kind": "work_order", "title": title, "rationale": "Out of stock with demand; the suggested quantity covers lead time and review period.",
            "payload": {"lines": [{"product_id": pid, "qty": qty}]}}


def eligible():
    rows = sr("select product_key, suggested_order_qty from mart.inventory_health where status in ('stockout', 'reorder_now') "
              "and replenishment_type = 'manufacture' order by product_key limit 1")
    if not rows:
        pytest.skip("no at-risk in-house product in this data")
    return rows[0][0], max(1, int(rows[0][1] or 1))


def post(path, who_, token, body):
    return requests.post(f"{ACTIONS}{path}", json=body, headers=token[who_], timeout=60)


def test_only_the_agent_drafts_and_the_agent_only_drafts(who):
    body = {"run_id": run_id("who"), "proposals": [wo_proposal(1, 1)]}
    for human_role in ("buyer", "marketer", "admin"):
        assert post("/proposals", human_role, who, body).status_code == 403
    # the agent cannot create, approve or dismiss anything
    assert post("/actions/work-orders", "agent", who, {"idempotency_key": run_id("a"), "lines": [{"product_id": 1, "qty": 1}]}).status_code == 403
    assert post("/actions/campaigns", "agent", who, {"idempotency_key": run_id("c"), "product_ids": [1], "discount_pct": 10, "days": 30}).status_code == 403
    assert post("/proposals/1/dismiss", "agent", who, {}).status_code in (403, 404)
    assert requests.post(f"{ACTIONS}/proposals", json=body, timeout=30).status_code == 401


def test_proposal_is_validated_stored_and_visible_to_the_right_roles(who, pgdb):
    pid, qty = eligible()
    rid = run_id("ok")
    r = post("/proposals", "agent", who, {"run_id": rid, "proposals": [wo_proposal(pid, qty)]})
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["ok"] and res["id"]
    mine = lambda role: [p for p in requests.get(f"{ACTIONS}/proposals", headers=who[role], timeout=30).json()["proposals"] if p["run_id"] == rid]  # noqa: E731
    assert len(mine("buyer")) == 1 and len(mine("admin")) == 1 and len(mine("agent")) == 1
    assert mine("marketer") == []                        # a work order is not a marketing matter
    p = mine("buyer")[0]
    assert p["created_by"].startswith("service-account") and p["status"] == "proposed"
    assert p["numbers"]["products"][0]["product_id"] == pid and "on_hand" in p["numbers"]["products"][0]
    # the same run drafted again does not duplicate
    again = post("/proposals", "agent", who, {"run_id": rid, "proposals": [wo_proposal(pid, qty)]}).json()["results"][0]
    assert again["ok"] and again["duplicate"] is True
    with pgdb.cursor() as cur:
        cur.execute("select count(*) from public.proposals where run_id = %s", (rid,))
        assert cur.fetchone()[0] == 1
        cur.execute("select outcome from public.actions_log where idempotency_key like %s", (rid + "#drafted-%",))
        assert cur.fetchone()[0] == "drafted"


def test_invalid_proposals_are_refused_per_item_and_never_stored(who, pgdb):
    pid, qty = eligible()
    healthy = sr("select product_key from mart.inventory_health where status = 'healthy' limit 1")
    items = [wo_proposal(pid, qty * 2 + 5),                                       # above twice the suggestion
             {**wo_proposal(pid, qty), "payload": {"lines": "nonsense"}},         # malformed
             wo_proposal(999999999, 1),                                           # unknown product
             wo_proposal(pid, qty, title="Valid one")]
    if healthy:
        items.insert(0, wo_proposal(healthy[0][0], 1))                            # a product that is fine
    rid = run_id("bad")
    r = post("/proposals", "agent", who, {"run_id": rid, "proposals": items})
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert [x["ok"] for x in results] == [False] * (len(items) - 1) + [True]
    with pgdb.cursor() as cur:
        cur.execute("select count(*) from public.proposals where run_id = %s", (rid,))
        assert cur.fetchone()[0] == 1


def test_a_person_approves_through_the_action_endpoint_and_it_is_linked(who, pgdb):
    pid, qty = eligible()
    rid = run_id("approve")
    pr = post("/proposals", "agent", who, {"run_id": rid, "proposals": [wo_proposal(pid, qty)]}).json()["results"][0]["id"]
    wrong = post("/actions/campaigns", "marketer", who, {"idempotency_key": run_id("w"), "product_ids": [pid], "discount_pct": 10, "days": 30, "proposal_id": pr})
    assert wrong.status_code == 422                       # not an open campaign proposal (and not even overstock)
    key = run_id("go")
    r = post("/actions/work-orders", "buyer", who, {"idempotency_key": key, "lines": [{"product_id": pid, "qty": qty}], "proposal_id": pr})
    assert r.status_code == 200, r.text
    wo_id = r.json()["work_orders"][0]["work_order_id"]
    try:
        with pgdb.cursor() as cur:
            cur.execute("select status, decided_by, action_log_id from public.proposals where id = %s", (pr,))
            status, by, log_id = cur.fetchone()
            assert (status, by) == ("approved", "buyer") and log_id == r.json()["log_id"]
        again = post("/actions/work-orders", "buyer", who, {"idempotency_key": run_id("go2"), "lines": [{"product_id": pid, "qty": qty}], "proposal_id": pr})
        assert again.status_code == 422                   # already approved: cannot be approved twice
        assert post(f"/proposals/{pr}/dismiss", "buyer", who, {}).status_code == 409
    finally:
        with pgdb.cursor() as cur:
            cur.execute("delete from public.work_order where work_order_id = %s", (wo_id,))


def test_dismiss_is_for_the_role_that_owns_the_kind(who):
    pid, qty = eligible()
    pr = post("/proposals", "agent", who, {"run_id": run_id("dis"), "proposals": [wo_proposal(pid, qty)]}).json()["results"][0]["id"]
    assert post(f"/proposals/{pr}/dismiss", "marketer", who, {}).status_code == 403
    r = post(f"/proposals/{pr}/dismiss", "buyer", who, {})
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    assert post(f"/proposals/{pr}/dismiss", "buyer", who, {}).status_code == 409
    assert post("/proposals/999999999/dismiss", "buyer", who, {}).status_code == 404


def test_campaign_proposal_rules(who, pgdb):
    rows = sr("select product_key, suggested_discount_pct from mart.inventory_health where status in ('overstock', 'dead_stock') order by product_key limit 2")
    if len(rows) < 2:
        pytest.skip("no overstock products in this data")
    ids = [r[0] for r in rows]
    top = max(int(r[1] or 0) for r in rows)
    ok = min(50, max(2 * top, 5))
    camp = lambda pct, products=ids: {"kind": "campaign", "title": "Clear excess stock", "payload": {"product_ids": products, "discount_pct": pct, "days": 30},  # noqa: E731
                                      "rationale": "Overstock with months of cover; a discount of this depth moved similar items before."}
    rid = run_id("camp")
    res = post("/proposals", "agent", who, {"run_id": rid, "proposals": [camp(ok), camp(min(100, ok + 60)), camp(ok, ids + [999999999])]}).json()["results"]
    assert [x["ok"] for x in res] == [True, False, False]
