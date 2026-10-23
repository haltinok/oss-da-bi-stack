"""Load the supply-side tables of the postgres_active sample into StarRocks `raw` (or SCALE_RAW_SCHEMA).

The spike's `raw` comes from the full SQL Server AdventureWorks copy, which does not include vendors,
purchase orders, work orders or product-vendor rows. postgres_active carries a 10% sample of them (same
product ids, 284 of the 504 products), which is enough to drive Phase 0's supply scaling (`build.py --supply`).
When the SQL Server source is available, add these tables to spike/ingest/tables.csv instead and ingest the full set.

  STARROCKS_MYSQL_PORT=9030 uv run --with pymysql python -I spike/scale/load_supply_sample.py [table ...]

Reads through `docker exec postgres_active psql` (no extra credentials), recreates <raw>.<table> each run (never run it with `raw` on a server where `raw` is the live pipeline's: it would drop the live tables).

The sample is thin and its references dangle (measured: 45 of 46 product_vendor rows and 359 of 402 purchase-order
headers point at a vendor that is not in `vendor`; 792 of 885 purchase-order lines have no header). Decisions:
  * vendor: stub rows ("Unknown vendor <id>", marked by credit_rating 0) are added for every referenced vendor
    that is missing, so a reorder always has a named vendor.
  * purchase_order_detail without a header: kept and counted (scale_meta.supply_orphans), but a line with no header
    has no status, so the supply models must inner-join the header: such lines never count as "on order".
  * everything else is counted only.
"""
import csv
import io
import os
import subprocess
import sys

import pymysql

TABLES = ["vendor", "product_vendor", "purchase_order_header", "purchase_order_detail", "work_order", "special_offer_product"]
PG = ["docker", "exec", "-i", "postgres_active", "psql", "-U", "postgres", "-p", "5434", "-d", "active_db", "-v", "ON_ERROR_STOP=1"]


def psql(sql):
    return subprocess.run([*PG, "-At", "-F", "\t", "-c", sql], check=True, capture_output=True, text=True).stdout


def sr_type(pg_type, prec, scale):
    t = pg_type.lower()
    if t in ("integer", "serial"):
        return "INT"
    if t in ("smallint", "bigint", "boolean", "date"):
        return t.upper()
    if t == "numeric":
        return f"DECIMAL({min(prec or 38, 38)},{scale or 0})"
    if t.startswith("timestamp"):
        return "DATETIME"
    return "STRING"   # text, varchar, uuid, ...


# Same as build.py: SCALE_RAW_SCHEMA=raw_spike on a server whose `raw` is the live pipeline's.
RAW = os.environ.get("SCALE_RAW_SCHEMA", "raw")

db = pymysql.connect(host="127.0.0.1", port=int(os.environ.get("STARROCKS_MYSQL_PORT", "9030")), user="root", autocommit=True)
cur = db.cursor()
for table in sys.argv[1:] or TABLES:
    cols = [r.split("\t") for r in psql(
        "select column_name, data_type, numeric_precision, numeric_scale from information_schema.columns "
        f"where table_schema='public' and table_name='{table}' order by ordinal_position").splitlines()]
    if not cols:
        sys.exit(f"{table}: not in postgres_active")
    names = [c[0] for c in cols]
    types = [sr_type(c[1], int(c[2]) if c[2] else None, int(c[3]) if c[3] else None) for c in cols]
    cur.execute(f"DROP TABLE IF EXISTS {RAW}.{table}")
    cur.execute(f"CREATE TABLE {RAW}.{table} ({', '.join(f'`{n}` {t}' for n, t in zip(names, types, strict=True))}) "
                f"DUPLICATE KEY(`{names[0]}`) DISTRIBUTED BY HASH(`{names[0]}`) BUCKETS 4 PROPERTIES('replication_num'='1')")
    out = subprocess.run([*PG, "-c", f"COPY (select * from public.{table}) TO STDOUT WITH (FORMAT csv, NULL '\\N')"],
                         check=True, capture_output=True, text=True).stdout
    rows = [[None if v == "\\N" else v for v in r] for r in csv.reader(io.StringIO(out))]
    for i in range(0, len(rows), 500):
        cur.executemany(f"INSERT INTO {RAW}.{table} VALUES ({', '.join(['%s'] * len(names))})", rows[i:i + 500])
    print(f"{RAW}.{table}: {len(rows)} rows", flush=True)

if "vendor" in (sys.argv[1:] or TABLES):
    cur.execute(f"select distinct id from (select business_entity_id as id from {RAW}.product_vendor "
                f"union select vendor_id from {RAW}.purchase_order_header) r where id is not null "
                f"and id not in (select business_entity_id from {RAW}.vendor)")
    missing = [r[0] for r in cur.fetchall()]
    for vid in missing:
        cur.execute(f"INSERT INTO {RAW}.vendor VALUES (%s, %s, %s, 0, 1, 1, now(), NULL)", (vid, f"STUB{vid}", f"Unknown vendor {vid}"))
    print(f"{RAW}.vendor: +{len(missing)} stub rows for referenced vendors that are not in the sample", flush=True)
