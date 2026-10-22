"""Integration tests for the actions service against the running stack (Keycloak, StarRocks, postgres_active).

  set -a; . ./.env; set +a
  ACTIONS_URL=http://localhost:8300 KEYCLOAK_URL=http://localhost:8180 STARROCKS_MYSQL_PORT=9030 POSTGRES_ACTIVE_PORT=5434 \
  uv run --with pytest --with requests --with pymysql --with psycopg2-binary python -I -m pytest actions/tests/test_actions.py

Each test that writes finds an eligible product in mart.inventory_health first and skips if there is none
(a stack whose data has no purchased product at risk cannot exercise the purchase-order path). Everything a
test creates is deleted again, including its audit rows.
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


def token(user):
    r = requests.post(f"{KEYCLOAK}/realms/spike/protocol/openid-connect/token", timeout=30,
                      data={"grant_type": "password", "client_id": "dashboard", "username": user, "password": PASSWORD})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def auth():
    return {u: token(u) for u in ("admin", "buyer", "marketer", "na_manager")}


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
        cur.execute("delete from public.actions_log where idempotency_key like %s", (TAG + "%",))
    conn.close()


def key(name):
    return f"{TAG}-{name}-{uuid.uuid4().hex[:6]}"


def post(path, who, auth, body):
    return requests.post(f"{ACTIONS}{path}", json=body, headers=auth[who] if who else {}, timeout=60)


def eligible(kind):
    """(product_id, suggested qty, min, max) of an at-risk product replenished by `kind`, or skip."""
    rows = sr("select product_key, suggested_order_qty, min_order_qty, max_order_qty from mart.inventory_health "
              f"where status in ('stockout', 'reorder_now') and replenishment_type = '{kind}' "
              + ("and vendor_id is not null " if kind == "purchase" else "") + "order by product_key limit 1")
    if not rows:
        pytest.skip(f"no at-risk {kind} product in this data")
    return rows[0]


# --- who may call what --------------------------------------------------------------------------

def test_no_token_and_bad_tokens_are_rejected(auth):
    assert post("/actions/work-orders", None, auth, {"idempotency_key": key("a"), "lines": []}).status_code == 401
    r = requests.post(f"{ACTIONS}/actions/work-orders", json={}, headers={"Authorization": "Bearer nonsense"}, timeout=30)
    assert r.status_code == 401


def test_managers_and_reps_have_no_actions(auth):
    r = post("/actions/work-orders", "na_manager", auth, {"idempotency_key": key("m"), "lines": [{"product_id": 1, "qty": 1}]})
    assert r.status_code == 403
    assert requests.get(f"{ACTIONS}/actions/log", headers=auth["na_manager"], timeout=30).status_code == 403


def test_marketing_cannot_create_a_purchase_or_work_order(auth):
    for path in ("/actions/purchase-orders", "/actions/work-orders"):
        assert post(path, "marketer", auth, {"idempotency_key": key("x"), "lines": [{"product_id": 1, "qty": 1}]}).status_code == 403


def test_purchasing_cannot_create_a_campaign(auth):
    r = post("/actions/campaigns", "buyer", auth, {"idempotency_key": key("c"), "product_ids": [1], "discount_pct": 10, "days": 30})
    assert r.status_code == 403


# --- work orders ----------------------------------------------------------------------------------

def test_work_order_is_written_audited_and_idempotent(auth, pgdb):
    pid, suggested, _, _ = eligible("manufacture")
    qty = max(1, int(suggested or 1))
    k = key("wo")
    body = {"idempotency_key": k, "lines": [{"product_id": pid, "qty": qty}]}
    r = post("/actions/work-orders", "buyer", auth, body)
    assert r.status_code == 200, r.text
    wo_id = r.json()["work_orders"][0]["work_order_id"]
    try:
        with pgdb.cursor() as cur:
            cur.execute("select product_id, order_qty, stocked_qty, end_date from public.work_order where work_order_id = %s", (wo_id,))
            assert cur.fetchone() == (pid, qty, 0, None)
            cur.execute("select username, role, action, outcome, product_ids from public.actions_log where idempotency_key = %s", (k,))
            assert cur.fetchone() == ("buyer", "purchasing", "work_order", "approved", [pid])
        again = post("/actions/work-orders", "buyer", auth, body)
        assert again.status_code == 200 and again.json()["idempotent"] is True
        assert again.json()["work_orders"][0]["work_order_id"] == wo_id
        with pgdb.cursor() as cur:
            cur.execute("select count(*) from public.work_order where product_id = %s and work_order_id = %s", (pid, wo_id))
            assert cur.fetchone()[0] == 1
        assert post("/actions/work-orders", "admin", auth, body).status_code == 409   # someone else's key
    finally:
        with pgdb.cursor() as cur:
            cur.execute("delete from public.work_order where work_order_id = %s", (wo_id,))


def test_tampered_quantity_is_refused_and_logged(auth, pgdb):
    pid, suggested, _, _ = eligible("manufacture")
    k = key("tamper")
    r = post("/actions/work-orders", "buyer", auth, {"idempotency_key": k, "lines": [{"product_id": pid, "qty": int(suggested or 1) * 2 + 1}]})
    assert r.status_code == 422, r.text
    with pgdb.cursor() as cur:
        cur.execute("select outcome, reason from public.actions_log where idempotency_key like %s", (k + "#refused-%",))
        outcome, reason = cur.fetchone()
        assert outcome == "refused" and "outside the allowed range" in reason
        cur.execute("select count(*) from public.work_order where start_date > now() - interval '1 minute' and product_id = %s and order_qty = %s",
                    (pid, int(suggested or 1) * 2 + 1))
        assert cur.fetchone()[0] == 0


def test_healthy_product_and_wrong_kind_are_refused(auth):
    healthy = sr("select product_key from mart.inventory_health where status = 'healthy' limit 1")
    if healthy:
        r = post("/actions/work-orders", "buyer", auth, {"idempotency_key": key("h"), "lines": [{"product_id": healthy[0][0], "qty": 1}]})
        assert r.status_code == 422
    pid, *_ = eligible("manufacture")
    r = post("/actions/purchase-orders", "buyer", auth, {"idempotency_key": key("k"), "lines": [{"product_id": pid, "qty": 1}]})
    assert r.status_code == 422                    # a made-in-house product cannot be bought
    assert post("/actions/work-orders", "buyer", auth, {"idempotency_key": key("u"), "lines": [{"product_id": 999999999, "qty": 1}]}).status_code == 422


def test_malformed_requests_are_rejected(auth):
    for body in ({"idempotency_key": "short", "lines": [{"product_id": 1, "qty": 1}]},
                 {"idempotency_key": key("n"), "lines": [{"product_id": 1, "qty": -5}]},
                 {"idempotency_key": key("d"), "lines": [{"product_id": 1, "qty": 1}, {"product_id": 1, "qty": 1}]},
                 {"idempotency_key": key("e"), "lines": []}):
        assert post("/actions/work-orders", "buyer", auth, body).status_code == 422, body


# --- purchase orders ------------------------------------------------------------------------------

def test_purchase_order_uses_the_servers_vendor_and_price(auth, pgdb):
    pid, suggested, low, high = eligible("purchase")
    qty = max(int(low or 1), min(int(suggested or 1), int(high) if high else 10**9))
    k = key("po")
    # client-supplied price / vendor fields are not part of the contract and must be ignored
    r = post("/actions/purchase-orders", "buyer", auth,
             {"idempotency_key": k, "lines": [{"product_id": pid, "qty": qty, "unit_price": 0.01, "vendor_id": 1}]})
    assert r.status_code == 200, r.text
    po = r.json()["purchase_orders"][0]
    try:
        (vendor, unit_cost) = sr(f"select vendor_id, unit_cost from mart.inventory_health where product_key = {pid}")[0]
        with pgdb.cursor() as cur:
            cur.execute("select status, vendor_id from public.purchase_order_header where purchase_order_id = %s", (po["purchase_order_id"],))
            assert cur.fetchone() == (2, vendor)
            cur.execute("select order_qty, unit_price, received_qty from public.purchase_order_detail "
                        "where purchase_order_id = %s and product_id = %s", (po["purchase_order_id"], pid))
            line = cur.fetchone()
            assert line[0] == qty and float(line[1]) == pytest.approx(float(unit_cost)) and line[2] == 0
    finally:
        with pgdb.cursor() as cur:
            cur.execute("delete from public.purchase_order_detail where purchase_order_id = %s and product_id = %s", (po["purchase_order_id"], pid))
            cur.execute("delete from public.purchase_order_header where purchase_order_id = %s", (po["purchase_order_id"],))
    over = (int(high) if high else (int(suggested or 1) * 2)) + 1
    r = post("/actions/purchase-orders", "buyer", auth, {"idempotency_key": key("po2"), "lines": [{"product_id": pid, "qty": over}]})
    assert r.status_code == 422, r.text


def test_new_purchase_order_id_does_not_adopt_an_orphan_line(auth, pgdb):
    pid, suggested, low, high = eligible("purchase")
    qty = max(int(low or 1), min(int(suggested or 1), int(high) if high else 10**9))
    with pgdb.cursor() as cur:
        cur.execute("select coalesce(max(purchase_order_id), 0) from public.purchase_order_detail")
        top_detail = cur.fetchone()[0]
    r = post("/actions/purchase-orders", "buyer", auth, {"idempotency_key": key("id"), "lines": [{"product_id": pid, "qty": qty}]})
    assert r.status_code == 200, r.text
    po_id = r.json()["purchase_orders"][0]["purchase_order_id"]
    try:
        assert po_id > top_detail
    finally:
        with pgdb.cursor() as cur:
            cur.execute("delete from public.purchase_order_detail where purchase_order_id = %s", (po_id,))
            cur.execute("delete from public.purchase_order_header where purchase_order_id = %s", (po_id,))


# --- campaigns --------------------------------------------------------------------------------------

def test_campaign_is_written_and_bounded(auth, pgdb):
    rows = sr("select product_key, suggested_discount_pct from mart.inventory_health where status in ('overstock', 'dead_stock') order by product_key limit 2")
    if len(rows) < 2:
        pytest.skip("no overstock products in this data")
    ids = [r[0] for r in rows]
    top = max(int(r[1] or 0) for r in rows)
    ok = min(50, max(2 * top, 5))
    r = post("/actions/campaigns", "marketer", auth, {"idempotency_key": key("camp"), "product_ids": ids, "discount_pct": ok, "days": 30})
    assert r.status_code == 200, r.text
    offer = r.json()["special_offer_id"]
    try:
        with pgdb.cursor() as cur:
            cur.execute("select discount_pct, type from public.special_offer where special_offer_id = %s", (offer,))
            pct, typ = cur.fetchone()
            assert float(pct) == pytest.approx(ok / 100) and typ == "Excess Inventory"
            cur.execute("select count(*) from public.special_offer_product where special_offer_id = %s", (offer,))
            assert cur.fetchone()[0] == len(ids)
    finally:
        with pgdb.cursor() as cur:
            cur.execute("delete from public.special_offer_product where special_offer_id = %s", (offer,))
            cur.execute("delete from public.special_offer where special_offer_id = %s", (offer,))
    for body in ({"product_ids": ids, "discount_pct": min(100, ok + 1) if ok < 50 else 51, "days": 30},
                 {"product_ids": ids, "discount_pct": ok, "days": 1},
                 {"product_ids": [1], "discount_pct": 10, "days": 30} if not sr("select 1 from mart.inventory_health where product_key = 1 and status in ('overstock','dead_stock')") else {"product_ids": ids, "discount_pct": 0, "days": 30}):
        assert post("/actions/campaigns", "marketer", auth, {"idempotency_key": key("bad"), **body}).status_code == 422, body


# --- log -----------------------------------------------------------------------------------------------

def test_log_shows_each_role_only_its_own_kinds(auth, pgdb):
    pid, suggested, _, _ = eligible("manufacture")
    k = key("log")
    r = post("/actions/work-orders", "buyer", auth, {"idempotency_key": k, "lines": [{"product_id": pid, "qty": max(1, int(suggested or 1))}]})
    assert r.status_code == 200, r.text
    wo_id = r.json()["work_orders"][0]["work_order_id"]
    try:
        buyer = requests.get(f"{ACTIONS}/actions/log", headers=auth["buyer"], timeout=30).json()["entries"]
        marketer = requests.get(f"{ACTIONS}/actions/log", headers=auth["marketer"], timeout=30).json()["entries"]
        admin = requests.get(f"{ACTIONS}/actions/log", headers=auth["admin"], timeout=30).json()["entries"]
        assert any(e["action"] == "work_order" and pid in e["product_ids"] for e in buyer)
        assert all(e["action"] in ("purchase_order", "work_order") for e in buyer)
        assert all(e["action"] == "campaign" for e in marketer)
        assert any(e["action"] == "work_order" for e in admin)
    finally:
        with pgdb.cursor() as cur:
            cur.execute("delete from public.work_order where work_order_id = %s", (wo_id,))
