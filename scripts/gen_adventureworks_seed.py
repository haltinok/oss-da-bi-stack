#!/usr/bin/env python3
"""Generate ``postgres_active/init/03_adventureworks_seed.sql.gz`` from the warehouse.

Reads the AdventureWorks tables from ``analytics.raw`` and emits a ``COPY`` seed
that is a **referentially consistent sample** of the source, so the warehouse DWH
(``adventureworks_dwh``) can be repointed at it without its ``relationships``
tests failing.

Why not a plain 10% per table? An independent sample per table leaves ~90% of
fact rows with orphan dimension keys (measured on the previous seed). Instead:

* the tables the DWH reads get a **referential-closure** sample: 10% of three
  drivers (``business_entity``, ``product``, ``sales_order_header``), expanded
  along the foreign-key graph into the scratch schema ``seed_sel`` -- children of
  the sampled parents (all lines of a sampled order, all inventory of a sampled
  product) and the parents those rows reference (customers, addresses,
  territories, subcategories, currencies, ...);
* every other table (the OLTP/CDC demo's ``work_order``, ``transaction_history``,
  ... which the DWH never reads) gets an independent 10% sample, so the closure
  does not drag the large non-DWH tables in wholesale.

Dependency-free: talks to Postgres through ``psql``.

Usage (from the repository root, with the stack up)::

    python3 scripts/gen_adventureworks_seed.py
"""

from __future__ import annotations

import argparse
import gzip
import os
import subprocess
import sys
from pathlib import Path

from gen_adventureworks_schema import PRIMARY_KEYS, load_columns, q

SAMPLE_RATIO = 0.10
SCRATCH_SCHEMA = "seed_sel"

# Driver tables sampled at 10%; the DWH tables are derived from them.
SAMPLE_SQL = {
    "be_sample": "select business_entity_id from raw.business_entity order by random() limit (select greatest(1, ceil(count(*) * 0.10))::int from raw.business_entity)",
    "prod_sample": "select product_id from raw.product order by random() limit (select greatest(1, ceil(count(*) * 0.10))::int from raw.product)",
    "so": "select sales_order_id from raw.sales_order_header order by random() limit (select greatest(1, ceil(count(*) * 0.10))::int from raw.sales_order_header)",
}

# Selection sets, in dependency order. Each entry is (name, sql) and creates a
# table seed_sel.<name> holding the key values to keep. Only the relationships
# the DWH actually joins are followed.
SELECTION_SETS = [
    (
        "customer",
        """
        select customer_id from raw.customer
        where person_id in (select business_entity_id from seed_sel.be_sample)
           or store_id in (select business_entity_id from seed_sel.be_sample)
           or customer_id in (select customer_id from raw.sales_order_header
                              where sales_order_id in (select sales_order_id from seed_sel.so))
           -- The DWH maps a reseller order to a store-only customer sharing its
           -- store_id (int_sales_order_lines.store_customer), so every customer
           -- on a store an order touches must be kept too.
           or store_id in (select c.store_id from raw.customer c
                           join raw.sales_order_header h on h.customer_id = c.customer_id
                           where h.sales_order_id in (select sales_order_id from seed_sel.so)
                             and c.store_id is not null)
        """,
    ),
    (
        "be",
        """
        select business_entity_id from seed_sel.be_sample
        union
        select c.person_id from raw.customer c
          where c.customer_id in (select customer_id from seed_sel.customer) and c.person_id is not null
        union
        select c.store_id from raw.customer c
          where c.customer_id in (select customer_id from seed_sel.customer) and c.store_id is not null
        union
        select h.sales_person_id from raw.sales_order_header h
          where h.sales_order_id in (select sales_order_id from seed_sel.so) and h.sales_person_id is not null
        union
        select s.sales_person_id from raw.store s
          where s.business_entity_id in (select store_id from raw.customer
                                         where customer_id in (select customer_id from seed_sel.customer) and store_id is not null)
            and s.sales_person_id is not null
        """,
    ),
    ("person", "select business_entity_id from raw.person where business_entity_id in (select business_entity_id from seed_sel.be)"),
    ("store", "select business_entity_id from raw.store where business_entity_id in (select business_entity_id from seed_sel.be)"),
    ("sales_person", "select business_entity_id from raw.sales_person where business_entity_id in (select business_entity_id from seed_sel.be)"),
    ("employee", "select business_entity_id from raw.employee where business_entity_id in (select business_entity_id from seed_sel.be)"),
    (
        "address",
        """
        select address_id from raw.address
        where address_id in (select bill_to_address_id from raw.sales_order_header
                             where sales_order_id in (select sales_order_id from seed_sel.so)
                             union
                             select ship_to_address_id from raw.sales_order_header
                             where sales_order_id in (select sales_order_id from seed_sel.so))
           or address_id in (select address_id from raw.business_entity_address
                             where business_entity_id in (select business_entity_id from seed_sel.be))
        """,
    ),
    (
        "state_province",
        "select state_province_id from raw.state_province where state_province_id in "
        "(select state_province_id from raw.address where address_id in (select address_id from seed_sel.address))",
    ),
    (
        "country_region",
        "select country_region_code from raw.country_region where country_region_code in "
        "(select country_region_code from raw.state_province where state_province_id in (select state_province_id from seed_sel.state_province))",
    ),
    (
        "territory",
        """
        select territory_id from raw.sales_territory
        where territory_id in (select territory_id from raw.state_province
                               where state_province_id in (select state_province_id from seed_sel.state_province))
           or territory_id in (select territory_id from raw.customer where customer_id in (select customer_id from seed_sel.customer))
           or territory_id in (select territory_id from raw.sales_order_header where sales_order_id in (select sales_order_id from seed_sel.so))
           or territory_id in (select territory_id from raw.sales_person where business_entity_id in (select business_entity_id from seed_sel.sales_person))
        """,
    ),
    (
        "product",
        """
        select product_id from raw.product
        where product_id in (select product_id from seed_sel.prod_sample)
           or product_id in (select product_id from raw.sales_order_detail where sales_order_id in (select sales_order_id from seed_sel.so))
        """,
    ),
    (
        "subcategory",
        "select product_subcategory_id from raw.product_subcategory where product_subcategory_id in "
        "(select product_subcategory_id from raw.product where product_id in (select product_id from seed_sel.product))",
    ),
    (
        "category",
        "select product_category_id from raw.product_category where product_category_id in "
        "(select product_category_id from raw.product_subcategory where product_subcategory_id in (select product_subcategory_id from seed_sel.subcategory))",
    ),
    (
        "special_offer",
        "select special_offer_id from raw.special_offer where special_offer_id in "
        "(select special_offer_id from raw.sales_order_detail where sales_order_id in (select sales_order_id from seed_sel.so))",
    ),
    (
        "currency_rate",
        "select currency_rate_id from raw.currency_rate where currency_rate_id in "
        "(select currency_rate_id from raw.sales_order_header where sales_order_id in (select sales_order_id from seed_sel.so))",
    ),
    (
        "currency",
        """
        select currency_code from raw.currency where currency_code in (
          select from_currency_code from raw.currency_rate where currency_rate_id in (select currency_rate_id from seed_sel.currency_rate)
          union
          select to_currency_code from raw.currency_rate where currency_rate_id in (select currency_rate_id from seed_sel.currency_rate))
        """,
    ),
    (
        "location",
        "select location_id from raw.location where location_id in "
        "(select location_id from raw.product_inventory where product_id in (select product_id from seed_sel.product))",
    ),
    (
        "department",
        "select department_id from raw.department where department_id in "
        "(select department_id from raw.employee_department_history where business_entity_id in (select business_entity_id from seed_sel.employee))",
    ),
]

# Referential-closure predicates for the tables the DWH reads. A table mapped to
# None is copied in full; a table absent from this map gets an independent 10%
# sample (the OLTP/CDC demo tables the DWH never joins).
TABLE_PREDICATES: dict[str, str | None] = {
    "address": "address_id in (select address_id from seed_sel.address)",
    "business_entity": "business_entity_id in (select business_entity_id from seed_sel.be)",
    "business_entity_address": "business_entity_id in (select business_entity_id from seed_sel.be)",
    "country_region": "country_region_code in (select country_region_code from seed_sel.country_region)",
    "currency": "currency_code in (select currency_code from seed_sel.currency)",
    "currency_rate": "currency_rate_id in (select currency_rate_id from seed_sel.currency_rate)",
    "customer": "customer_id in (select customer_id from seed_sel.customer)",
    "department": "department_id in (select department_id from seed_sel.department)",
    "email_address": "business_entity_id in (select business_entity_id from seed_sel.be)",
    "employee": "business_entity_id in (select business_entity_id from seed_sel.employee)",
    "employee_department_history": "business_entity_id in (select business_entity_id from seed_sel.employee)",
    "location": "location_id in (select location_id from seed_sel.location)",
    "person": "business_entity_id in (select business_entity_id from seed_sel.person)",
    "product": "product_id in (select product_id from seed_sel.product)",
    "product_category": "product_category_id in (select product_category_id from seed_sel.category)",
    "product_cost_history": "product_id in (select product_id from seed_sel.product)",
    "product_inventory": "product_id in (select product_id from seed_sel.product)",
    "product_subcategory": "product_subcategory_id in (select product_subcategory_id from seed_sel.subcategory)",
    "sales_order_detail": "sales_order_id in (select sales_order_id from seed_sel.so)",
    "sales_order_header": "sales_order_id in (select sales_order_id from seed_sel.so)",
    "sales_person": "business_entity_id in (select business_entity_id from seed_sel.sales_person)",
    "sales_person_quota_history": "business_entity_id in (select business_entity_id from seed_sel.sales_person)",
    "sales_territory": "territory_id in (select territory_id from seed_sel.territory)",
    "special_offer": "special_offer_id in (select special_offer_id from seed_sel.special_offer)",
    "state_province": "state_province_id in (select state_province_id from seed_sel.state_province)",
    "store": "business_entity_id in (select business_entity_id from seed_sel.store)",
    "aw_build_version": None,
}


def run_psql(sql: str, args: argparse.Namespace, text: bool = True):
    env = dict(os.environ)
    env["PGPASSWORD"] = args.password
    cmd = [
        "psql", "-X", "-q", "-A", "-t", "-h", args.host,
        "-p", str(args.port), "-U", args.user, "-d", args.db, "-c", sql,
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=text)
    if result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        sys.stderr.write(stderr)
        raise SystemExit(f"psql failed for: {sql[:200]}")
    return result.stdout


def build_selection(args: argparse.Namespace) -> None:
    run_psql(f"drop schema if exists {SCRATCH_SCHEMA} cascade", args)
    run_psql(f"create schema {SCRATCH_SCHEMA}", args)
    for name, sql in SAMPLE_SQL.items():
        run_psql(f"create table {SCRATCH_SCHEMA}.{name} as {sql}", args)
    for name, sql in SELECTION_SETS:
        run_psql(f"create table {SCRATCH_SCHEMA}.{name} as {sql}", args)


def drop_selection(args: argparse.Namespace) -> None:
    run_psql(f"drop schema if exists {SCRATCH_SCHEMA} cascade", args)


def sample_predicate(table: str) -> str:
    return (
        f"ctid in (select ctid from raw.{q(table)} order by random() "
        f"limit (select greatest(1, ceil(count(*) * {SAMPLE_RATIO}))::int from raw.{q(table)}))"
    )


def row_count(table: str, predicate: str | None, args: argparse.Namespace) -> int:
    where = f" where {predicate}" if predicate else ""
    return int(run_psql(f"select count(*) from raw.{q(table)}{where}", args).strip())


def copy_out(table: str, columns: list[str], predicate: str | None, args: argparse.Namespace) -> bytes:
    cols = ", ".join(q(c) for c in columns)
    where = f" where {predicate}" if predicate else ""
    return run_psql(f"copy (select {cols} from raw.{q(table)}{where}) to stdout", args, text=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("PGHOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PGPORT", os.environ.get("POSTGRES_PORT", "5433"))))
    parser.add_argument("--db", default=os.environ.get("PGDATABASE", "analytics"))
    parser.add_argument("--user", default=os.environ.get("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.environ.get("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "")))
    parser.add_argument("--out", default="postgres_active/init/03_adventureworks_seed.sql.gz")
    args = parser.parse_args()

    tables = load_columns(args)
    tables = {t: cols for t, cols in tables.items() if t in PRIMARY_KEYS}

    print("building referential-closure selection ...")
    build_selection(args)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    total_rows = 0
    try:
        with gzip.open(out, "wb", compresslevel=6) as fh:
            fh.write(
                (
                    "-- AdventureWorks2016 sample seed for the postgres_active sandbox.\n"
                    "--\n"
                    "-- GENERATED FILE -- do not edit by hand.\n"
                    "-- Regenerate with: python3 scripts/gen_adventureworks_seed.py\n"
                    "--\n"
                    "-- DWH tables: a referentially consistent sample (10% of the driver\n"
                    "-- tables expanded along the foreign-key graph), so every star join\n"
                    "-- resolves. Other tables: an independent 10% sample. Loaded\n"
                    "-- automatically by the Postgres image on first start.\n\n"
                    "\\set ON_ERROR_STOP on\n\n"
                ).encode()
            )
            for table in sorted(tables):
                columns = [c for c, _, _ in tables[table]]
                if table in TABLE_PREDICATES:
                    predicate = TABLE_PREDICATES[table]
                else:
                    predicate = sample_predicate(table)
                count = row_count(table, predicate, args)
                payload = copy_out(table, columns, predicate, args)
                cols = ", ".join(q(c) for c in columns)
                fh.write(f"-- {table}: {count} rows\n".encode())
                fh.write(f"copy public.{q(table)} ({cols}) from stdin;\n".encode())
                fh.write(payload)
                if not payload.endswith(b"\n"):
                    fh.write(b"\n")
                fh.write(b"\\.\n\n")
                total_rows += count
                print(f"{table}: {count}")
    finally:
        drop_selection(args)

    print(f"\nwrote {out} ({total_rows} rows across {len(tables)} tables)")


if __name__ == "__main__":
    main()
