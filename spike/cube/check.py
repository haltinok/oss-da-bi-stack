"""Cube vs direct SQL on the mart (Phase 4 correctness). Needs the spike stack up.

  set -a; . ./.env.spike; set +a
  uv run --with pymysql --with pyjwt python -I spike/cube/check.py
Totals must match to the cent. Prints which pre-aggregations served each query.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal

import jwt
import pymysql

URL = os.environ.get("CUBE_URL", "http://localhost:4000/cubejs-api/v1/load")
TOKEN = jwt.encode({"user_id": "check"}, os.environ["CUBEJS_API_SECRET"], algorithm="HS256")
db = pymysql.connect(host="127.0.0.1", port=9030, user="root", read_timeout=3600).cursor()
LIVE = "order_status NOT IN (4, 6)"


def sql(q):
    db.execute(q)
    return db.fetchall()


def cube(query):
    while True:
        req = urllib.request.Request(URL, json.dumps({"query": query}).encode(),
                                     {"Authorization": TOKEN, "Content-Type": "application/json"})
        try:
            body = json.load(urllib.request.urlopen(req, timeout=3600))
        except urllib.error.HTTPError as e:
            sys.exit(f"HTTP {e.code}: {e.read().decode()[:600]}")
        if body.get("error") == "Continue wait":
            time.sleep(2)
            continue
        if "error" in body:
            sys.exit(f"cube error: {body['error']}")
        return body


fails = 0


def check(name, got, want, body=None):
    global fails
    ok = same(got, want)
    fails += not ok
    used = list((body or {}).get("usedPreAggregations", {}))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {'[pre-agg: ' + ','.join(used) + ']' if used else '[direct]'}")
    if not ok:
        print("   cube:", got, "\n   sql: ", want)


def dec(x):
    # Cube Store keeps 5 decimals per rollup row, so large sums can drift ~0.001 and
    # round to a different cent; compare to the nearest 0.01 with that tolerance.
    return Decimal(str(x))


def same(a, b):
    """Recursive equality; numbers may differ by 0.011 (Cube Store 5-decimal rounding)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return abs(a - b) <= Decimal("0.011")
    return a == b


for ch in ("internet", "reseller"):
    t0 = time.time()
    b = cube({"measures": [f"{ch}_sales.revenue", f"{ch}_sales.gross_profit", f"{ch}_sales.units", f"{ch}_sales.lines"]})
    r = b["data"][0]
    (rev, cost, units, lines), = sql(
        f"select sum(sales_amount), sum(sales_amount - coalesce(total_product_cost,0)), sum(order_quantity), "
        f"count(*) from mart.fact_{ch}_sales where {LIVE}")
    check(f"{ch} totals (revenue, gross profit, units, lines) {time.time()-t0:.1f}s",
          (dec(r[f"{ch}_sales.revenue"]), dec(r[f"{ch}_sales.gross_profit"]), int(r[f"{ch}_sales.units"]), int(r[f"{ch}_sales.lines"])),
          (dec(rev), dec(cost), int(units), int(lines)), b)

    b = cube({"measures": [f"{ch}_sales.revenue", f"{ch}_sales.margin_pct"], "dimensions": ["territories.region"]})
    got = {d["territories.region"]: (dec(d[f"{ch}_sales.revenue"]), dec(d[f"{ch}_sales.margin_pct"])) for d in b["data"]}
    want = {r[0]: (dec(r[1]), dec(r[2])) for r in sql(
        f"select t.sales_territory_region, sum(f.sales_amount), 100*sum(f.sales_amount - coalesce(f.total_product_cost,0))/sum(f.sales_amount) "
        f"from mart.fact_{ch}_sales f join mart.dim_sales_territory t on t.sales_territory_key=f.sales_territory_key where {LIVE} group by 1")}
    check(f"{ch} revenue + margin% by territory ({len(want)} regions)", got, want, b)

    # Fiscal-year filter + category/month grain, as the dashboard slices it.
    b = cube({"measures": [f"{ch}_sales.revenue", f"{ch}_sales.units"], "dimensions": ["products.category"],
              "timeDimensions": [{"dimension": f"{ch}_sales.order_date", "granularity": "month"}],
              "filters": [{"member": "dates.fiscal_year", "operator": "equals", "values": ["2013"]}]})
    got = {(d["products.category"], d[f"{ch}_sales.order_date.month"][:7]): (dec(d[f"{ch}_sales.revenue"]), int(d[f"{ch}_sales.units"])) for d in b["data"]}
    want = {(r[0], r[1].strftime("%Y-%m")): (dec(r[2]), int(r[3])) for r in sql(
        f"select coalesce(p.product_category_name,'Uncategorized'), date_trunc('month', f.order_date), sum(f.sales_amount), sum(f.order_quantity) "
        f"from mart.fact_{ch}_sales f join mart.dim_product p on p.product_key=f.product_key join mart.dim_date d on d.date_key=f.order_date_key "
        f"where {LIVE} and d.fiscal_year=2013 group by 1,2")}
    check(f"{ch} FY2013 revenue + units by category x month ({len(want)} cells)", got, want, b)

    # count_distinct: served by its own exact-grain rollup.
    t0 = time.time()
    b = cube({"measures": [f"{ch}_sales.orders"], "timeDimensions": [{"dimension": f"{ch}_sales.order_date", "granularity": "month"}]})
    got = {d[f"{ch}_sales.order_date.month"][:7]: int(d[f"{ch}_sales.orders"]) for d in b["data"]}
    want = {r[0].strftime("%Y-%m"): int(r[1]) for r in sql(
        f"select date_trunc('month', order_date), count(distinct sales_order_number) from mart.fact_{ch}_sales where {LIVE} group by 1")}
    check(f"{ch} orders by month ({len(want)} months) {time.time()-t0:.1f}s", got, want, b)

# Drill-across: both facts by product category, vs each fact aggregated separately.
t0 = time.time()
b = cube({"measures": ["internet_sales.revenue", "reseller_sales.revenue"], "dimensions": ["products.category"]})
got = {d["products.category"]: (dec(d["internet_sales.revenue"] or 0), dec(d["reseller_sales.revenue"] or 0)) for d in b["data"]}
agg = lambda ch: {r[0]: r[1] for r in sql(
    f"select coalesce(p.product_category_name,'Uncategorized'), sum(f.sales_amount) from mart.fact_{ch}_sales f "
    f"join mart.dim_product p on p.product_key=f.product_key where {LIVE} group by 1")}
i, r_ = agg("internet"), agg("reseller")
want = {k: (dec(i.get(k, 0)), dec(r_.get(k, 0))) for k in set(i) | set(r_)}
check(f"drill-across internet + reseller revenue by category ({len(want)}) {time.time()-t0:.1f}s", got, want, b)

print("\nFAILED" if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
