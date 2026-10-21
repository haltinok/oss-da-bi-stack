"""Phase 2: build scaled copies of the order tables inside StarRocks.

For copy k in [0, K):
  order ids        sales_order_id + k * 1_000_000            (bigint); sales_order_number = 'SO' || id
  customer-side    key + (k % 100) * 1_000_000               (customer/person/address/email/bea, x100)
  dates            + (k % 8) years  (order/due/ship/modified)
Builds scale_500m from raw, then scale_100m / scale_10m as copy-index subsets
(copy index = sales_order_id div 1_000_000). Unscaled tables are views over raw.

  uv run --with pymysql python -I spike/scale/build.py [--only 10m|100m|500m | --cust-only]
"""
import sys
import time

import pymysql

SCALES = {"10m": 83, "100m": 825, "500m": 4120}   # copies of the ~121k-line base
CUST_COPIES = 100
OFF = 1_000_000
CHUNK = 200                                        # copies per INSERT (~24M detail rows)

DATE_COLS = {"order_date", "due_date", "ship_date", "modified_date"}
# table -> {column: offset kind}; "o" = order copy (k), "c" = customer copy (k % 100)
KEYS = {
    "sales_order_header": {"sales_order_id": "o", "customer_id": "c", "bill_to_address_id": "c", "ship_to_address_id": "c"},
    "sales_order_detail": {"sales_order_id": "o"},
}
CUST_KEYS = {
    "customer": ["customer_id", "person_id", "store_id"],   # store_id too: one store per store-customer copy
    "store": ["business_entity_id"],
    "person": ["business_entity_id"],
    "email_address": ["business_entity_id"],
    "business_entity_address": ["business_entity_id", "address_id"],
    "address": ["address_id"],
}
ORDER_KEYS_DDL = {
    "sales_order_header": ("sales_order_id",),
    "sales_order_detail": ("sales_order_id", "sales_order_detail_id"),
    "customer": ("customer_id",), "store": ("business_entity_id",), "person": ("business_entity_id",), "email_address": ("business_entity_id", "email_address_id"),
    "business_entity_address": ("business_entity_id", "address_id", "address_type_id"), "address": ("address_id",),
}

# Base = the original AdventureWorks orders: drop Phase 1's cloned test orders
# (ids >= 75124, dated "now") and hard-deleted ones, so shifted dates stay in the past.
CLEAN = ("sales_order_id < 75124 and sales_order_id not in "
         "(select sales_order_id from raw.recon_deleted_sales_order_header)")

db = pymysql.connect(host="127.0.0.1", port=9030, user="root", autocommit=True, read_timeout=7200)
cur = db.cursor()


def run(sql):
    t = time.time()
    cur.execute(sql)
    return time.time() - t


def cols(table):
    cur.execute("select column_name, column_type from information_schema.columns where table_schema='raw' "
                "and table_name=%s and column_name not like '\\_ingestr%%' order by ordinal_position", (table,))
    return cur.fetchall()


def bigint_cols(table):
    return set(KEYS.get(table, {})) | set(CUST_KEYS.get(table, []))


def ddl(schema, table):
    out, bk = [], bigint_cols(table)
    for c, t in cols(table):
        out.append(f"`{c}` {'BIGINT' if c in bk else t}")
    key = ", ".join(f"`{k}`" for k in ORDER_KEYS_DDL[table])
    buckets = 32 if table in ("sales_order_header", "sales_order_detail") else 8
    return (f"CREATE TABLE {schema}.{table} ({', '.join(out)}) DUPLICATE KEY({key}) "
            f"DISTRIBUTED BY HASH({ORDER_KEYS_DDL[table][0]}) BUCKETS {buckets} PROPERTIES('replication_num'='1')")


def sel_order(table, a, b, base):
    """SELECT for order-table copies a..b (inclusive) from the clean base."""
    exprs = []
    for c, _ in cols(table):
        kind = KEYS[table].get(c)
        if kind == "o":
            e = f"cast(t.{c} as bigint) + n.k * {OFF}"
        elif kind == "c":
            e = f"if(t.{c} is null, null, cast(t.{c} as bigint) + (n.k % {CUST_COPIES}) * {OFF})"
        elif c == "sales_order_number":
            e = f"concat('SO', cast(cast(t.sales_order_id as bigint) + n.k * {OFF} as string))"
        elif c in DATE_COLS:
            e = f"years_add(t.{c}, cast(n.k % 8 as int))"
        else:
            e = f"t.{c}"
        exprs.append(f"{e} as {c}")
    return f"SELECT {', '.join(exprs)} FROM ({base}) t CROSS JOIN scale_meta.nums n WHERE n.k BETWEEN {a} AND {b}"


def sel_cust(table):
    exprs, ks = [], set(CUST_KEYS[table])
    for c, _ in cols(table):
        e = (f"if(t.{c} is null, null, cast(t.{c} as bigint) + n.k * {OFF})" if c in ks else f"t.{c}")
        exprs.append(f"{e} as {c}")
    return f"SELECT {', '.join(exprs)} FROM raw.{table} t CROSS JOIN scale_meta.nums n WHERE n.k < {CUST_COPIES}"


def build_500m():
    s = "scale_500m"
    run(f"DROP DATABASE IF EXISTS {s} FORCE")
    run(f"CREATE DATABASE {s}")
    base = {
        "sales_order_header": f"select * from raw.sales_order_header where {CLEAN}",
        "sales_order_detail": f"select * from raw.sales_order_detail where {CLEAN}",
    }
    K = SCALES["500m"]
    for tbl in ("sales_order_header", "sales_order_detail"):
        run(ddl(s, tbl))
        for a in range(0, K, CHUNK):
            b = min(a + CHUNK, K) - 1
            secs = run(f"INSERT INTO {s}.{tbl} " + sel_order(tbl, a, b, base[tbl]))
            print(f"  {s}.{tbl} copies {a}-{b}: {secs:.0f}s", flush=True)
    for tbl in CUST_KEYS:
        run(ddl(s, tbl))
        secs = run(f"INSERT INTO {s}.{tbl} " + sel_cust(tbl))
        print(f"  {s}.{tbl}: {secs:.0f}s", flush=True)


def build_subset(name):
    s, K = f"scale_{name}", SCALES[name]
    run(f"DROP DATABASE IF EXISTS {s} FORCE")
    run(f"CREATE DATABASE {s}")
    for tbl in list(KEYS) + list(CUST_KEYS):
        run(ddl(s, tbl))
        where = f" WHERE sales_order_id < {K * OFF}" if tbl in KEYS else ""
        secs = run(f"INSERT INTO {s}.{tbl} SELECT * FROM scale_500m.{tbl}{where}")
        print(f"  {s}.{tbl}: {secs:.0f}s", flush=True)


def build_cust_only():
    """Rebuild just the customer-side tables in all scales (no 15-minute fact rebuild)."""
    for tbl in CUST_KEYS:
        for s in ("scale_500m", "scale_100m", "scale_10m"):
            cur.execute("select table_type from information_schema.tables where table_schema=%s and table_name=%s", (s, tbl))
            row = cur.fetchone()
            if row:
                run(f"DROP {'VIEW' if row[0] == 'VIEW' else 'TABLE'} {s}.{tbl}")
            run(ddl(s, tbl))
            src = sel_cust(tbl) if s == "scale_500m" else f"SELECT * FROM scale_500m.{tbl}"
            secs = run(f"INSERT INTO {s}.{tbl} {src}")
            print(f"  {s}.{tbl}: {secs:.0f}s", flush=True)


def views(schema):
    scaled = set(KEYS) | set(CUST_KEYS)
    cur.execute("select table_name from information_schema.tables where table_schema='raw' "
                "and table_name not like 'pk\\_%' and table_name not like 'recon\\_%'")
    for (t,) in cur.fetchall():
        if t not in scaled:
            run(f"CREATE VIEW IF NOT EXISTS {schema}.{t} AS SELECT * FROM raw.{t}")


if __name__ == "__main__":
    if "--cust-only" in sys.argv:
        build_cust_only()
        print("done")
        sys.exit(0)
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    run("CREATE DATABASE IF NOT EXISTS scale_meta")
    run("DROP TABLE IF EXISTS scale_meta.nums")
    run("CREATE TABLE scale_meta.nums (k BIGINT) DUPLICATE KEY(k) DISTRIBUTED BY HASH(k) BUCKETS 1 PROPERTIES('replication_num'='1')")
    run(f"INSERT INTO scale_meta.nums SELECT generate_series FROM TABLE(generate_series(0, {max(SCALES.values()) - 1}))")
    if only in (None, "500m"):
        build_500m()
    for n in ("100m", "10m"):
        if only in (None, n):
            build_subset(n)
    for n in SCALES:
        if only in (None, n):
            views(f"scale_{n}")
    print("done")
