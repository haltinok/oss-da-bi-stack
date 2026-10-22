"""Phase 2: build scaled copies of the order tables inside StarRocks.

For copy k in [0, K):
  order ids        sales_order_id + k * 1_000_000            (bigint); sales_order_number = 'SO' || id
  customer-side    key + (k % 100) * 1_000_000               (customer/person/address/email/bea, x100)
  dates            + (k % 8) years  (order/due/ship/modified)
Each tier is cross-joined straight from raw (`--only 250m` builds just that tier). A tier smaller than one
that is already built is copied from it as a copy-index subset (copy index = sales_order_id div 1_000_000),
which is much faster than another cross join. Unscaled tables are views over raw.

Supply side (`--supply`): sales are multiplied, but inventory, purchase orders and work orders are not, so
unscaled every product would look out of stock. `--supply` measures how much more was sold in the scaled
tier (units in the trailing 90 days, each anchored at its own latest order date) and multiplies the
quantity columns of the supply tables by that factor, shifts their dates to sit with the scaled data, and
records it in scale_meta.supply_factor. Tables that are not in raw yet are skipped with a notice.

  uv run --with pymysql python -I spike/scale/build.py [--only 1m|10m|100m|250m|500m | --cust-only | --supply [tier]]
"""
import os
import sys
import time

import pymysql

SCALES = {"1m": 8, "10m": 83, "100m": 825, "250m": 2060, "500m": 4120}   # copies of the ~121k-line base; 1m is a smoke test
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

db = pymysql.connect(host="127.0.0.1", port=int(os.environ.get("STARROCKS_MYSQL_PORT", "9030")), user="root", autocommit=True, read_timeout=7200)
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


def build_tier(name):
    """Cross-join `raw` straight up to SCALES[name] copies."""
    s, K = f"scale_{name}", SCALES[name]
    run(f"DROP DATABASE IF EXISTS {s} FORCE")
    run(f"CREATE DATABASE {s}")
    base = {
        "sales_order_header": f"select * from raw.sales_order_header where {CLEAN}",
        "sales_order_detail": f"select * from raw.sales_order_detail where {CLEAN}",
    }
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


def built_tiers():
    cur.execute("select schema_name from information_schema.schemata where schema_name like 'scale\\_%' and schema_name <> 'scale_meta'")
    return [n.removeprefix("scale_") for (n,) in cur.fetchall() if n.removeprefix("scale_") in SCALES]


def build_subset(name, parent):
    s, K, src = f"scale_{name}", SCALES[name], f"scale_{parent}"
    run(f"DROP DATABASE IF EXISTS {s} FORCE")
    run(f"CREATE DATABASE {s}")
    for tbl in list(KEYS) + list(CUST_KEYS):
        run(ddl(s, tbl))
        where = f" WHERE sales_order_id < {K * OFF}" if tbl in KEYS else ""
        secs = run(f"INSERT INTO {s}.{tbl} SELECT * FROM {src}.{tbl}{where}")
        print(f"  {s}.{tbl}: {secs:.0f}s", flush=True)


def build(name):
    """A tier from the smallest already-built larger tier, else straight from raw."""
    parents = sorted((SCALES[t], t) for t in built_tiers() if SCALES[t] > SCALES[name])
    if parents:
        build_subset(name, parents[0][1])
    else:
        build_tier(name)


def build_cust_only():
    """Rebuild just the customer-side tables in all scales (no 15-minute fact rebuild)."""
    for tbl in CUST_KEYS:
        tiers = [f"scale_{t}" for t in sorted(built_tiers(), key=SCALES.get, reverse=True)]
        for s in tiers:
            cur.execute("select table_type from information_schema.tables where table_schema=%s and table_name=%s", (s, tbl))
            row = cur.fetchone()
            if row:
                run(f"DROP {'VIEW' if row[0] == 'VIEW' else 'TABLE'} {s}.{tbl}")
            run(ddl(s, tbl))
            src = sel_cust(tbl) if s == tiers[0] else f"SELECT * FROM {tiers[0]}.{tbl}"
            secs = run(f"INSERT INTO {s}.{tbl} {src}")
            print(f"  {s}.{tbl}: {secs:.0f}s", flush=True)


def views(schema):
    scaled = set(KEYS) | set(CUST_KEYS)
    cur.execute("select table_name from information_schema.tables where table_schema='raw' "
                "and table_name not like 'pk\\_%' and table_name not like 'recon\\_%'")
    for (t,) in cur.fetchall():
        if t not in scaled:
            run(f"CREATE VIEW IF NOT EXISTS {schema}.{t} AS SELECT * FROM raw.{t}")


# --- supply side ---------------------------------------------------------------------------
# table -> (quantity columns multiplied by the factor, date columns shifted with the scaled data)
SUPPLY = {
    "product": (["safety_stock_level", "reorder_point"], []),
    "product_inventory": (["quantity"], ["modified_date"]),
    "product_vendor": (["min_order_qty", "max_order_qty", "on_order_qty"], ["last_receipt_date", "modified_date"]),
    "purchase_order_header": ([], ["order_date", "ship_date", "modified_date"]),
    "purchase_order_detail": (["order_qty", "received_qty", "rejected_qty", "stocked_qty"], ["due_date", "modified_date"]),
    "work_order": (["order_qty", "stocked_qty", "scrapped_qty"], ["start_date", "end_date", "due_date", "modified_date"]),
}
# (table, column, parent table, parent column): rows whose parent is missing are counted, not dropped.
FKS = [
    ("product_inventory", "product_id", "product", "product_id"),
    ("product_vendor", "product_id", "product", "product_id"),
    ("product_vendor", "business_entity_id", "vendor", "business_entity_id"),
    ("purchase_order_header", "vendor_id", "vendor", "business_entity_id"),
    ("purchase_order_detail", "purchase_order_id", "purchase_order_header", "purchase_order_id"),
    ("purchase_order_detail", "product_id", "product", "product_id"),
    ("work_order", "product_id", "product", "product_id"),
    ("special_offer_product", "special_offer_id", "special_offer", "special_offer_id"),
    ("special_offer_product", "product_id", "product", "product_id"),
]


def exists(schema, table):
    cur.execute("select count(*) from information_schema.tables where table_schema=%s and table_name=%s", (schema, table))
    return cur.fetchone()[0] > 0


def trailing_units(header, detail):
    """(as-of date, units sold in the 90 days up to it); header/detail are table names or subselects."""
    cur.execute(f"select max(order_date) from {header} h")
    as_of = cur.fetchone()[0]
    cur.execute(f"select sum(d.order_qty) from {detail} d join {header} h on h.sales_order_id = d.sales_order_id "
                "where h.order_date > date_sub(%s, interval 90 day) and h.order_date <= %s", (as_of, as_of))
    return as_of, cur.fetchone()[0] or 0


def supply_factor(tier):
    s = f"scale_{tier}"
    raw_asof, raw_units = trailing_units(f"(select * from raw.sales_order_header where {CLEAN})",
                                         f"(select * from raw.sales_order_detail where {CLEAN})")
    as_of, units = trailing_units(f"{s}.sales_order_header", f"{s}.sales_order_detail")
    if not raw_units:
        raise SystemExit("no sales in the last 90 days of the unscaled base: cannot derive a supply factor")
    return as_of, raw_asof, units / raw_units


def reconcile_supply(schema):
    """Count rows whose parent row is missing (the source is a sample, so some references dangle)."""
    run("DROP TABLE IF EXISTS scale_meta.supply_orphans")
    run("CREATE TABLE scale_meta.supply_orphans (schema_name VARCHAR(64), child VARCHAR(64), child_column VARCHAR(64), "
        "parent VARCHAR(64), orphan_rows BIGINT, total_rows BIGINT) DUPLICATE KEY(schema_name) "
        "DISTRIBUTED BY HASH(schema_name) BUCKETS 1 PROPERTIES('replication_num'='1')")
    for child, col, parent, pcol in FKS:
        if not (exists(schema, child) and exists(schema, parent)):
            print(f"  reconcile {child}.{col}: skipped ({child} or {parent} not in {schema})")
            continue
        cur.execute(f"select count(*), sum(case when p.{pcol} is null then 1 else 0 end) from {schema}.{child} c "
                    f"left join (select distinct {pcol} from {schema}.{parent}) p on p.{pcol} = c.{col}")
        total, orphans = cur.fetchone()
        run(f"INSERT INTO scale_meta.supply_orphans VALUES ('{schema}', '{child}', '{col}', '{parent}', {int(orphans or 0)}, {int(total)})")
        print(f"  reconcile {child}.{col} -> {parent}: {int(orphans or 0)} of {total} rows have no parent", flush=True)


def scale_supply(tier):
    s = f"scale_{tier}"
    as_of, raw_asof, factor = supply_factor(tier)
    shift_days = (as_of - raw_asof).days
    print(f"{s}: as-of {as_of:%Y-%m-%d} (base {raw_asof:%Y-%m-%d}), supply factor {factor:.1f}, date shift {shift_days} days", flush=True)
    run("CREATE DATABASE IF NOT EXISTS scale_meta")
    run("CREATE TABLE IF NOT EXISTS scale_meta.supply_factor (tier VARCHAR(16), factor DOUBLE, as_of DATETIME, "
        "shift_days INT, computed_at DATETIME) DUPLICATE KEY(tier) DISTRIBUTED BY HASH(tier) BUCKETS 1 PROPERTIES('replication_num'='1')")
    run(f"DELETE FROM scale_meta.supply_factor WHERE tier = '{tier}'")
    run(f"INSERT INTO scale_meta.supply_factor VALUES ('{tier}', {factor}, '{as_of:%Y-%m-%d %H:%M:%S}', {shift_days}, now())")
    for tbl, (qty, dates) in SUPPLY.items():
        if not exists("raw", tbl):
            print(f"  {s}.{tbl}: not in raw, skipped (ingest it first)")
            continue
        exprs = []
        for c, _ in cols(tbl):
            if c in qty:
                exprs.append(f"cast(round(t.{c} * {factor}) as bigint) as {c}")
            elif c in dates:
                exprs.append(f"date_add(t.{c}, interval {shift_days} day) as {c}")
            else:
                exprs.append(f"t.{c} as {c}")
        cur.execute("select table_type from information_schema.tables where table_schema=%s and table_name=%s", (s, tbl))
        row = cur.fetchone()
        if row:
            run(f"DROP {'VIEW' if row[0] == 'VIEW' else 'TABLE'} {s}.{tbl}")
        run(f"CREATE TABLE {s}.{tbl} PROPERTIES('replication_num'='1') AS SELECT {', '.join(exprs)} FROM raw.{tbl} t")
        print(f"  {s}.{tbl}: quantities x{factor:.1f} ({', '.join(qty) or 'none'}), dates {shift_days:+d} days", flush=True)
    reconcile_supply(s)


if __name__ == "__main__":
    if "--cust-only" in sys.argv:
        build_cust_only()
        print("done")
        sys.exit(0)
    if "--supply" in sys.argv:
        k = sys.argv.index("--supply")
        tiers = [sys.argv[k + 1]] if k + 1 < len(sys.argv) and sys.argv[k + 1] in SCALES else built_tiers()
        for t in tiers:
            scale_supply(t)
        print("done")
        sys.exit(0)
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    wanted = [n for n in sorted(SCALES, key=SCALES.get, reverse=True) if only in (None, n) and not (only is None and n == "1m")]
    run("CREATE DATABASE IF NOT EXISTS scale_meta")
    run("DROP TABLE IF EXISTS scale_meta.nums")
    run("CREATE TABLE scale_meta.nums (k BIGINT) DUPLICATE KEY(k) DISTRIBUTED BY HASH(k) BUCKETS 1 PROPERTIES('replication_num'='1')")
    run(f"INSERT INTO scale_meta.nums SELECT generate_series FROM TABLE(generate_series(0, {max(SCALES.values()) - 1}))")
    for n in wanted:   # largest first, so smaller tiers are copied from it
        build(n)
        views(f"scale_{n}")
    print("done")
