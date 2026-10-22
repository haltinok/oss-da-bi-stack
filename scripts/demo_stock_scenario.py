#!/usr/bin/env python3
"""Put a believable inventory problem into the simulated ERP, so the reorder list has something to approve.

AdventureWorks stock covers a thousand days of demand, so on a healthy run nothing is ever short and the
reorder list stays empty (and a few days after an approved work order is received, it is empty again). This
lowers the on-hand stock of the N best-selling in-house products that have nothing on order: a few to zero
(stockouts) and a few to about three days of demand (reorder now). It writes to postgres_active's
product_inventory only (the same kind of write the simulator makes), and the next pipeline cycle shows the result.

  set -a; . ./.env; set +a
  STARROCKS_MYSQL_PORT=9030 POSTGRES_ACTIVE_PORT=5434 \
  uv run --with pymysql --with psycopg2-binary python -I scripts/demo_stock_scenario.py [--n 12] [--dry-run]
"""
import argparse
import math
import os

import psycopg2
import pymysql

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=12, help="products to put under pressure")
ap.add_argument("--dry-run", action="store_true")
args = ap.parse_args()

sr = pymysql.connect(host="127.0.0.1", port=int(os.environ.get("STARROCKS_MYSQL_PORT", "9030")), user="root").cursor()
sr.execute("select product_key, product_name, daily_demand from mart.inventory_health "
           "where status in ('healthy', 'overstock') and replenishment_type = 'manufacture' and daily_demand > 0 and on_order = 0 "
           f"order by daily_demand desc limit {int(args.n)}")
picked = sr.fetchall()
pg = psycopg2.connect(host="127.0.0.1", port=int(os.environ.get("POSTGRES_ACTIVE_PORT", "5434")), dbname="active_db",
                      user="postgres", password=os.environ["POSTGRES_PASSWORD"])
with pg, pg.cursor() as cur:
    for i, (pid, name, demand) in enumerate(picked):
        target = 0 if i < math.ceil(len(picked) / 2) else max(1, round(float(demand) * 3))
        print(f"{'stockout   ' if target == 0 else 'reorder now'}  {pid:>4}  {name}  (demand {float(demand):.1f}/day) -> on hand {target}")
        if args.dry_run:
            continue
        cur.execute("select location_id from public.product_inventory where product_id = %s order by quantity desc, location_id", (pid,))
        locs = [r[0] for r in cur.fetchall()]
        for n, loc in enumerate(locs):
            cur.execute("update public.product_inventory set quantity = %s, modified_date = now() where product_id = %s and location_id = %s",
                        (target if n == 0 else 0, pid, loc))
print("dry run, nothing written" if args.dry_run else f"updated {len(picked)} products; the list updates after the next pipeline cycle")
