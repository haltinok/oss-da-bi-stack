#!/usr/bin/env python3
"""Build the AdventureWorks Superset dashboard, then export it as a ZIP.

Creates (idempotently, by name):
  * a Postgres connection to the warehouse as the read-only ``bi_ro`` role;
  * one virtual dataset over the ``mart`` star (fact joined to its dimensions);
  * four charts (total revenue, revenue over time, revenue by category, top products);
  * a dashboard holding them.

Run it against the running stack:

    set -a && . ./.env && set +a
    python3 scripts/build_superset_dashboard.py

Then export the dashboard to ``superset/dashboards/adventureworks.zip`` (also done
by ``--export``), which ``superset-init`` imports on first start.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("SUPERSET_URL", "http://localhost:8089").rstrip("/")
ADMIN_USER = os.environ.get("SUPERSET_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ["SUPERSET_ADMIN_PASSWORD"]
BI_PASSWORD = os.environ["BI_READONLY_PASSWORD"]

_COOKIE_JAR = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_COOKIE_JAR))
_CSRF = {"token": None}
_TOKEN = {"value": None}

DB_NAME = "AdventureWorks mart (read-only)"
DATASET_NAME = "aw_sales"
DASHBOARD_TITLE = "AdventureWorks Sales"

DATASET_SQL = """
select
    f.order_date,
    f.order_status,
    f.sales_amount,
    f.tax_amt,
    f.freight,
    f.sales_order_number,
    f.sales_order_line_number,
    p.product_category_name,
    p.product_name,
    p.product_subcategory_name,
    c.customer_key,
    c.first_name as customer_first_name,
    c.last_name as customer_last_name,
    t.sales_territory_region
from mart.fact_internet_sales f
left join mart.dim_product p on f.product_key = p.product_key
left join mart.dim_customer c on f.customer_key = c.customer_key
left join mart.dim_sales_territory t on f.sales_territory_key = t.sales_territory_key
""".strip()

_REVENUE_METRIC = {
    "expressionType": "SIMPLE",
    "column": {"column_name": "sales_amount"},
    "aggregate": "SUM",
    "label": "Revenue",
}

# Revenue charts exclude rejected (4) and cancelled (6) orders by default.
# `form_data.adhoc_filters` uses the adhoc shape; `queries[].filters` uses the
# legacy col/op/val shape.
_STATUS_FILTER = {
    "expressionType": "SIMPLE",
    "subject": "order_status",
    "operator": "NOT IN",
    "comparator": [4, 6],
    "clause": "WHERE",
}
_STATUS_QUERY_FILTER = {"col": "order_status", "op": "NOT IN", "val": [4, 6]}


def request(method: str, path: str, token: str | None = None, payload=None, raw=False):
    url = BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # Superset requires a CSRF token (bound to the session cookie) for writes.
    if method in ("POST", "PUT", "DELETE") and _CSRF["token"]:
        headers["X-CSRFToken"] = _CSRF["token"]
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with _OPENER.open(req, timeout=60) as resp:
            body = resp.read()
            return resp.status, (body if raw else json.loads(body or b"{}"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise SystemExit(f"{method} {path} -> HTTP {exc.code}: {detail[:400]}") from exc


def login() -> str:
    status, body = request(
        "POST",
        "/api/v1/security/login",
        payload={"username": ADMIN_USER, "password": ADMIN_PASSWORD, "provider": "db"},
    )
    _TOKEN["value"] = body["access_token"]
    # Fetch the CSRF token bound to the session cookie the login just set.
    _, csrf = request("GET", "/api/v1/security/csrf_token/", _TOKEN["value"])
    _CSRF["token"] = csrf["result"]
    return _TOKEN["value"]


def find_by_name(token: str, collection: str, name: str) -> int | None:
    key = {
        "database": "database_name",
        "dataset": "table_name",
        "chart": "slice_name",
        "dashboard": "dashboard_title",
    }[collection]
    _, body = request("GET", f"/api/v1/{collection}/?q=(page_size:1000)", token)
    for row in body.get("result", []):
        if row.get(key) == name:
            return row["id"]
    return None


def create_database(token: str) -> int:
    existing = find_by_name(token, "database", DB_NAME)
    if existing:
        return existing
    uri = f"postgresql+psycopg2://bi_ro:{urllib.parse.quote(BI_PASSWORD)}@postgres:5432/analytics"
    _, body = request(
        "POST",
        "/api/v1/database/",
        token,
        {
            "database_name": DB_NAME,
            "sqlalchemy_uri": uri,
            "expose_in_sqllab": False,
            "allow_run_async": False,
        },
    )
    return body["id"]


def create_dataset(token: str, database_id: int) -> int:
    existing = find_by_name(token, "dataset", DATASET_NAME)
    if existing:
        return existing
    _, body = request(
        "POST",
        "/api/v1/dataset/",
        token,
        {
            "database": database_id,
            "schema": "mart",
            "table_name": DATASET_NAME,
            "sql": DATASET_SQL,
            "is_managed_externally": False,
        },
    )
    return body["id"]


def create_chart(token: str, dataset_id: int, name: str, viz_type: str, form_data: dict, queries: list[dict]) -> tuple[int, str]:
    form_data = {**form_data, "viz_type": viz_type, "datasource": f"{dataset_id}__table"}
    form_data["adhoc_filters"] = form_data.get("adhoc_filters", []) + [_STATUS_FILTER]
    # Mirror the fields the Explore UI puts in each query; the chart renderer
    # expects them even when empty.
    enriched = [
        {"filters": [_STATUS_QUERY_FILTER], "extras": {"having": "", "where": ""},
         "applied_time_extras": {}, **q}
        for q in queries
    ]
    query_context = json.dumps({
        "datasource": {"id": dataset_id, "type": "table"},
        "force": False,
        "queries": enriched,
        "form_data": form_data,
        "result_format": "json",
        "result_type": "full",
    })
    payload = {
        "slice_name": name,
        "viz_type": viz_type,
        "datasource_id": dataset_id,
        "datasource_type": "table",
        "params": json.dumps(form_data),
        "query_context": query_context,
    }
    existing = find_by_name(token, "chart", name)
    if existing:
        request("PUT", f"/api/v1/chart/{existing}", token, payload)
        chart_id = existing
    else:
        _, body = request("POST", "/api/v1/chart/", token, payload)
        chart_id = body.get("id") or body["result"]["id"]
    # Return the uuid too: the dashboard layout needs it, or Superset's export
    # appends a duplicate of every chart whose uuid is missing from the layout.
    _, chart = request("GET", f"/api/v1/chart/{chart_id}", token)
    return chart_id, chart["result"]["uuid"]


def create_dashboard(token: str, charts: list[tuple[int, str, str]]) -> int:
    existing = find_by_name(token, "dashboard", DASHBOARD_TITLE)
    if existing:
        dashboard_id = existing
    else:
        _, body = request("POST", "/api/v1/dashboard/", token, {"dashboard_title": DASHBOARD_TITLE})
        dashboard_id = body["id"]

    row1 = [c for c in charts[:2]]
    row2 = [c for c in charts[2:]]
    position = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": DASHBOARD_TITLE}},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": ["ROW-1", "ROW-2"], "parents": ["ROOT_ID"]},
    }
    for row_id, row_charts in (("ROW-1", row1), ("ROW-2", row2)):
        position[row_id] = {
            "type": "ROW", "id": row_id,
            "children": [f"CHART-{cid}" for cid, _, _ in row_charts],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for cid, name, uuid in row_charts:
            position[f"CHART-{cid}"] = {
                "type": "CHART", "id": f"CHART-{cid}", "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {"chartId": cid, "width": 6, "height": 50,
                         "sliceName": name, "uuid": uuid},
            }

    # Associate the charts with the dashboard FIRST (the export bundles them via
    # this M2M, which the dashboard endpoint does not expose). Doing it before the
    # layout PUT stops Superset from appending its own chart nodes on top of ours.
    for cid, _, _ in charts:
        request("PUT", f"/api/v1/chart/{cid}", token, {"dashboards": [dashboard_id]})
    request("PUT", f"/api/v1/dashboard/{dashboard_id}", token, {
        "position_json": json.dumps(position),
        "dashboard_title": DASHBOARD_TITLE,
        "published": True,
    })
    return dashboard_id


def export_dashboard(token: str, dashboard_id: int, out_path: str) -> None:
    query = urllib.parse.quote(f"[{dashboard_id}]")
    _, body = request("GET", f"/api/v1/dashboard/export/?q={query}", token, raw=True)
    with open(out_path, "wb") as fh:
        fh.write(body)
    print(f"exported dashboard {dashboard_id} -> {out_path} ({len(body)} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", default="superset/dashboards/adventureworks.zip")
    parser.add_argument("--no-export", action="store_true")
    args = parser.parse_args()

    token = login()
    database_id = create_database(token)
    dataset_id = create_dataset(token, database_id)
    print(f"database={database_id} dataset={dataset_id}")

    specs = [
        ("Total revenue", "big_number_total",
         {"metric": _REVENUE_METRIC, "adhoc_filters": [], "time_range": "No filter", "y_axis_format": "SMART_NUMBER"},
         [{"metrics": [_REVENUE_METRIC], "columns": [], "row_limit": 1, "time_range": "No filter", "is_timeseries": False}]),
        ("Revenue over time", "echarts_timeseries_line",
         {"x_axis": "order_date", "granularity_sqla": "order_date", "time_grain_sqla": "P1M",
          "metrics": [_REVENUE_METRIC], "groupby": [], "adhoc_filters": [], "time_range": "No filter"},
         [{"metrics": [_REVENUE_METRIC], "columns": [], "granularity": "order_date",
           "time_range": "No filter", "row_limit": 10000, "is_timeseries": True}]),
        ("Revenue by product category", "pie",
         {"groupby": ["product_category_name"], "metric": _REVENUE_METRIC, "adhoc_filters": [], "time_range": "No filter"},
         [{"metrics": [_REVENUE_METRIC], "columns": [], "groupby": ["product_category_name"],
           "row_limit": 100, "time_range": "No filter", "is_timeseries": False}]),
        ("Top products", "table",
         {"query_mode": "aggregate", "groupby": ["product_name"], "metrics": [_REVENUE_METRIC],
          "adhoc_filters": [], "time_range": "No filter"},
         [{"metrics": [_REVENUE_METRIC], "columns": [], "groupby": ["product_name"],
           "row_limit": 100, "time_range": "No filter", "is_timeseries": False}]),
    ]
    charts = []
    for name, viz, form, queries in specs:
        cid, uuid = create_chart(token, dataset_id, name, viz, form, queries)
        charts.append((cid, name, uuid))
    print("charts:", [(c, n) for c, n, _ in charts])

    dashboard_id = create_dashboard(token, charts)
    print(f"dashboard={dashboard_id} '{DASHBOARD_TITLE}'")

    if not args.no_export:
        os.makedirs(os.path.dirname(args.export), exist_ok=True)
        export_dashboard(token, dashboard_id, args.export)


if __name__ == "__main__":
    main()
