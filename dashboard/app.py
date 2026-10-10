"""Live sales dashboard over the dbt star (analytics.mart).

A deliberately small service: the standard-library HTTP server serves the
static page and a JSON API, and every API call queries the mart directly as the
read-only `bi_ro` role, so the page is as fresh as the last `dbt build`
(the `postgres_active_to_postgres_aw` DAG rebuilds it every 15 minutes).

    GET /                 the dashboard (static/index.html)
    GET /api/meta         filter options + data freshness
    GET /api/dashboard    every panel's data for the current filters
    GET /healthz          liveness (also checks the database)

Filters (all optional query parameters): fy, channel, group, region, category.
"""

import datetime as dt
import decimal
import json
import logging
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg
from psycopg.rows import dict_row

STATIC_DIR = Path(__file__).parent / "static"

DSN = (
    f"host={os.environ.get('DASHBOARD_PG_HOST', 'postgres')} "
    f"port={os.environ.get('DASHBOARD_PG_PORT', '5432')} "
    f"dbname={os.environ.get('DASHBOARD_PG_DATABASE', 'analytics')} "
    f"user={os.environ.get('DASHBOARD_PG_USER', 'bi_ro')} "
    "application_name=sales-dashboard connect_timeout=5"
)
# Kept out of the DSN string so it never shows up in a logged connection error.
PASSWORD = os.environ["BI_READONLY_PASSWORD"]

log = logging.getLogger("dashboard")

# Both sales facts share one line grain and the same measures, so the panels
# read them as one relation with a `channel` column. Rejected (4) and cancelled
# (6) orders are not revenue and are left out everywhere.
#
# `%(name)s::type is null or ...` makes every filter optional. A panel that
# cross-filters (it highlights the selected member instead of hiding the rest)
# is queried with its own filter cleared.
BASE = """
with sales as (
    select 'Internet' as channel, order_date_key, order_date, sales_order_number,
           product_key, sales_territory_key, order_status, order_quantity,
           sales_amount, coalesce(total_product_cost, 0) as product_cost, discount_amount
    from mart.fact_internet_sales
    union all
    select 'Reseller', order_date_key, order_date, sales_order_number,
           product_key, sales_territory_key, order_status, order_quantity,
           sales_amount, coalesce(total_product_cost, 0), discount_amount
    from mart.fact_reseller_sales
),

f as (
    select
        s.*,
        d.fiscal_year,
        date_trunc('month', d.full_date)::date as month,
        coalesce(st.sales_territory_group, 'Unassigned') as grp,
        coalesce(st.sales_territory_region, 'Unassigned') as region,
        coalesce(p.product_category_name, 'Uncategorized') as category,
        coalesce(p.product_subcategory_name, 'Uncategorized') as subcategory,
        p.product_name
    from sales s
    join mart.dim_date d on d.date_key = s.order_date_key
    left join mart.dim_sales_territory st on st.sales_territory_key = s.sales_territory_key
    left join mart.dim_product p on p.product_key = s.product_key
    where s.order_status not in (4, 6)
      and (%(channel)s::text is null or s.channel = %(channel)s)
      and (%(grp)s::text is null or coalesce(st.sales_territory_group, 'Unassigned') = %(grp)s)
      and (%(region)s::text is null or coalesce(st.sales_territory_region, 'Unassigned') = %(region)s)
      and (%(category)s::text is null
           or coalesce(p.product_category_name, 'Uncategorized') = %(category)s)
),

cur as (
    select * from f where %(fy)s::int is null or fiscal_year = %(fy)s
)
"""

MEASURES = """
    sum(sales_amount) as revenue,
    sum(sales_amount - product_cost) as gross_profit,
    count(distinct sales_order_number) as orders,
    sum(order_quantity) as units
"""

# Current period vs the prior fiscal year (only when a fiscal year is picked).
KPIS = BASE + f"""
select
    case when %(fy)s::int is null or fiscal_year = %(fy)s then 'current' else 'previous' end
        as period,
    {MEASURES}
from f
where %(fy)s::int is null or fiscal_year in (%(fy)s, %(fy)s - 1)
group by 1
"""

MONTHLY = BASE + f"""
select month, channel, {MEASURES}
from cur
group by 1, 2
order by 1, 2
"""

MIX = BASE + f"""
select category, subcategory, {MEASURES}
from cur
group by 1, 2
order by revenue desc
"""

TOP_PRODUCTS = BASE + """
select
    product_name,
    category,
    sum(sales_amount) as revenue,
    sum(sales_amount) filter (where channel = 'Internet') as internet,
    sum(sales_amount) filter (where channel = 'Reseller') as reseller,
    sum(sales_amount - product_cost) as gross_profit,
    sum(order_quantity) as units
from cur
group by 1, 2
order by revenue desc
limit 10
"""

TERRITORIES = BASE + """
select
    grp,
    region,
    sum(sales_amount) as revenue,
    sum(sales_amount) filter (where channel = 'Internet') as internet,
    sum(sales_amount) filter (where channel = 'Reseller') as reseller,
    sum(sales_amount - product_cost) as gross_profit,
    count(distinct sales_order_number) as orders
from cur
group by 1, 2
order by revenue desc
"""

# The live feed ignores the fiscal-year filter: it is always "what just landed".
LATEST_ORDERS = BASE + """
select
    sales_order_number,
    channel,
    min(order_date) as order_date,
    min(region) as region,
    min(order_status) as order_status,
    count(*) as lines,
    sum(sales_amount) as revenue
from f
group by 1, 2
order by order_date desc, sales_order_number desc
limit 8
"""

META = """
select
    (select array_agg(distinct d.fiscal_year order by d.fiscal_year)
       from (select order_date_key from mart.fact_internet_sales
             union select order_date_key from mart.fact_reseller_sales) k
       join mart.dim_date d on d.date_key = k.order_date_key) as fiscal_years,
    (select json_agg(t order by t.grp, t.region) from (
        select sales_territory_group as grp, sales_territory_region as region
        from mart.dim_sales_territory) t) as territories,
    (select array_agg(distinct product_category_name order by product_category_name)
       from mart.dim_product where product_category_name is not null) as categories,
    (select max(order_date) from (
        select order_date from mart.fact_internet_sales
        union all select order_date from mart.fact_reseller_sales) o) as last_order_at,
    (select count(*) from mart.fact_internet_sales)
      + (select count(*) from mart.fact_reseller_sales) as fact_rows
"""

FILTERS = ("fy", "channel", "group", "region", "category")


def parse_filters(query):
    raw = {k: (v[0].strip() or None) for k, v in parse_qs(query).items() if k in FILTERS}
    params = {
        "fy": None,
        "channel": raw.get("channel"),
        "grp": raw.get("group"),
        "region": raw.get("region"),
        "category": raw.get("category"),
    }
    if raw.get("fy"):
        params["fy"] = int(raw["fy"])
    if params["channel"] not in (None, "Internet", "Reseller"):
        raise ValueError("channel must be Internet or Reseller")
    return params


def to_json(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


class Database:
    """One lazily (re)opened connection, serialised by a lock.

    The page polls every 30 s and each request runs a handful of
    millisecond-scale aggregates, so a pool would buy nothing. dbt drops and
    recreates the mart tables on every build, so a query can fail mid-rebuild:
    the connection is reset and the error surfaces as a 503, which the page
    shows as "stale" while keeping its last good render.
    """

    def __init__(self):
        self._conn = None
        self._lock = threading.Lock()

    def run(self, queries):
        with self._lock:
            try:
                if self._conn is None or self._conn.closed:
                    self._conn = psycopg.connect(
                        DSN, password=PASSWORD, autocommit=True, row_factory=dict_row
                    )
                with self._conn.cursor() as cur:
                    cur.execute("set statement_timeout = '10s'")
                    out = {}
                    for name, (sql, params) in queries.items():
                        cur.execute(sql, params)
                        out[name] = cur.fetchall()
                    return out
            except psycopg.Error:
                if self._conn is not None:
                    self._conn.close()
                self._conn = None
                raise


db = Database()


def dashboard(params):
    without = lambda *keys: {**params, **dict.fromkeys(keys)}  # noqa: E731
    rows = db.run({
        "kpis": (KPIS, params),
        "monthly": (MONTHLY, params),
        # Cross-filtering panels: drop their own dimension, highlight it client-side.
        "mix": (MIX, without("category")),
        "top_products": (TOP_PRODUCTS, params),
        "territories": (TERRITORIES, without("grp", "region")),
        "latest_orders": (LATEST_ORDERS, without("fy")),
    })
    kpis = {r.pop("period"): r for r in rows.pop("kpis")}
    return {
        "kpis": {"current": kpis.get("current"), "previous": kpis.get("previous")},
        **rows,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def meta():
    row = db.run({"meta": (META, None)})["meta"][0]
    row["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return row


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        url = urlparse(self.path)
        routes = {
            "/api/dashboard": lambda: dashboard(parse_filters(url.query)),
            "/api/meta": meta,
            "/healthz": lambda: db.run({"ok": ("select 1 as ok", None)})["ok"][0],
        }
        if url.path not in routes:
            return super().do_GET()
        try:
            self.send_json(200, routes[url.path]())
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except psycopg.Error as exc:
            log.warning("query failed: %s", exc)
            self.send_json(503, {"error": "warehouse unavailable (dbt rebuild in progress?)"})

    def send_json(self, status, payload):
        body = json.dumps(payload, default=to_json).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        if not urlparse(self.path).path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        if self.path == "/healthz":  # the container healthcheck, every 15 s
            return
        log.info("%s %s", self.address_string(), fmt % args)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    port = int(os.environ.get("DASHBOARD_LISTEN_PORT", "8050"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log.info("serving on :%d", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
