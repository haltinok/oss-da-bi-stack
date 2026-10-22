"""Closed-loop timing: approve a work order, then watch it come back through the pipeline.

  set -a; . ./.env; set +a
  ACTIONS_URL=http://localhost:8300 KEYCLOAK_URL=http://localhost:8180 STARROCKS_MYSQL_PORT=9030 \
  uv run --with requests --with pymysql python -I actions/tests/loop_e2e.py

Needs the 5-minute DAGs running (simulator receives the order after its lead time, the pipeline rebuilds
the mart). Picks a stocked-out in-house product, approves a work order for the suggested quantity (at least 1) as
`buyer`, and reports when (1) the order shows as on order in mart.inventory_health and (2) the product
stops being a stockout. Creates a real work order in postgres_active: it is received like any other.
"""
import os
import sys
import time
import uuid

import pymysql
import requests

ACTIONS = os.environ.get("ACTIONS_URL", "http://localhost:8300")
KEYCLOAK = os.environ.get("KEYCLOAK_URL", "http://localhost:8180")


def sr(q):
    with pymysql.connect(host="127.0.0.1", port=int(os.environ.get("STARROCKS_MYSQL_PORT", "9030")), user="root").cursor() as cur:
        cur.execute(q)
        return cur.fetchall()


rows = sr("select product_key, greatest(suggested_order_qty, 1), lead_time_days from mart.inventory_health "
          "where status = 'stockout' and replenishment_type = 'manufacture' order by suggested_order_qty desc, daily_demand desc limit 1")
if not rows:
    sys.exit("no stocked-out in-house product")
pid, qty, lead = rows[0]   # the suggestion is 0 when open orders already cover the need; the smallest allowed quantity is 1
base_on_order = sr(f"select on_order from mart.inventory_health where product_key = {pid}")[0][0] or 0
kc = requests.post(f"{KEYCLOAK}/realms/spike/protocol/openid-connect/token", timeout=30, data={
    "grant_type": "password", "client_id": "dashboard", "username": "buyer", "password": os.environ["TEST_USER_PASSWORD"]}).json()
t0 = time.time()
r = requests.post(f"{ACTIONS}/actions/work-orders", headers={"Authorization": f"Bearer {kc['access_token']}"}, timeout=60,
                  json={"idempotency_key": "loop-" + uuid.uuid4().hex[:8], "lines": [{"product_id": pid, "qty": int(qty)}]})
r.raise_for_status()
print(f"approved work order {r.json()['work_orders'][0]['work_order_id']} for product {pid}, qty {qty}, lead time {lead} day(s) "
      f"(= about {int(lead) * 2} min in the simulator)", flush=True)
seen_on_order = None
while time.time() - t0 < 1500:
    status, on_order = sr(f"select status, on_order from mart.inventory_health where product_key = {pid}")[0]
    if seen_on_order is None and (on_order or 0) > base_on_order:
        seen_on_order = time.time() - t0
        print(f"  on order visible after {seen_on_order:.0f}s", flush=True)
    if status != "stockout":
        print(f"  no longer a stockout ({status}) after {time.time() - t0:.0f}s", flush=True)
        break
    time.sleep(5)
else:
    sys.exit("still a stockout after 25 minutes")
