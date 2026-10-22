"""Which pre-aggregation serves each dashboard-shaped query, and how fast (warm).

  set -a; . ./.env.spike; set +a; uv run --with pyjwt python -I spike/cube/probe.py
"""
import json
import os
import time
import urllib.error
import urllib.request

import jwt

TOKEN = jwt.encode({"user_id": "probe", "role": "admin", "territories": [], "exp": int(time.time()) + 6 * 3600}, os.environ["CUBEJS_API_SECRET"], algorithm="HS256")


def cube(q):
    t = time.time()
    while True:
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(
                "http://localhost:4000/cubejs-api/v1/load", json.dumps({"query": q}).encode(),
                {"Authorization": TOKEN, "Content-Type": "application/json"}), timeout=900))
        except urllib.error.HTTPError as e:
            return {"error": e.read().decode()[:200]}, time.time() - t
        if r.get("error") == "Continue wait":
            time.sleep(1)
            continue
        return r, time.time() - t


def show(name, q):
    cube(q)  # warm
    r, dt = cube(q)
    used = [k.split(".")[-1] for k in r.get("usedPreAggregations", {})]
    how = ",".join(used) or ("DIRECT" if "error" not in r else "ERR " + r["error"])
    print(f"{dt*1000:7.0f} ms  {len(r.get('data', [])):4d} rows  {how:42.42}  {name}")


M = lambda *a: {"measures": list(a)}
fy = lambda v="2013": {"member": "dates.fiscal_year", "operator": "equals", "values": [v]}
region = lambda v="Germany": {"member": "territories.region", "operator": "equals", "values": [v]}
for ch in ("internet", "reseller"):
    c, d = f"{ch}_sales", f"{ch}_sales.order_date"
    month = [{"dimension": d, "granularity": "month"}]
    print(f"--- {ch}")
    show("KPIs: revenue/gp/units", M(f"{c}.revenue", f"{c}.gross_profit", f"{c}.units"))
    show("KPIs: orders total", M(f"{c}.orders_placed"))
    show("KPIs: orders, FY filter", {**M(f"{c}.orders_placed"), "filters": [fy()]})
    show("monthly revenue", {**M(f"{c}.revenue"), "timeDimensions": month})
    show("monthly orders", {**M(f"{c}.orders_placed"), "timeDimensions": month})
    show("monthly orders, FY filter", {**M(f"{c}.orders_placed"), "timeDimensions": month, "filters": [fy()]})
    show("monthly orders, region filter", {**M(f"{c}.orders_placed"), "timeDimensions": month, "filters": [region()]})
    show("monthly orders, region + FY filter", {**M(f"{c}.orders_placed"), "timeDimensions": month, "filters": [region(), fy()]})
    show("territories: group x region, FY", {**M(f"{c}.revenue", f"{c}.gross_profit", f"{c}.orders_placed"), "dimensions": ["territories.group_name", "territories.region"], "filters": [fy()]})
    show("mix: category x subcategory, FY", {**M(f"{c}.revenue", f"{c}.orders", f"{c}.units"), "dimensions": ["products.category", "products.subcategory"], "filters": [fy()]})
    show("mix: category x subcategory, FY + region", {**M(f"{c}.revenue", f"{c}.orders", f"{c}.units"), "dimensions": ["products.category", "products.subcategory"], "filters": [fy(), region()]})
    show("top 10 products, FY", {**M(f"{c}.revenue", f"{c}.units"), "dimensions": ["products.name", "products.category"], "filters": [fy()], "order": {f"{c}.revenue": "desc"}, "limit": 10})
    show("daily strip, June 2013", {**M(f"{c}.revenue", f"{c}.units"), "dimensions": ["territories.region"], "timeDimensions": [{"dimension": d, "granularity": "day", "dateRange": ["2013-06-01", "2013-06-30"]}]})
print("--- both channels (drill-across over shared dims; a month series is queried per channel and merged client-side)")
show("revenue by category", {**M("internet_sales.revenue", "reseller_sales.revenue"), "dimensions": ["products.category"]})
show("revenue by region x category, FY", {**M("internet_sales.revenue", "reseller_sales.revenue"), "dimensions": ["territories.region", "products.category"], "filters": [fy()]})
