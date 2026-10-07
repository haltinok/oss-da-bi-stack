#!/usr/bin/env python3
"""Generate ``postgres_active/init/02_adventureworks_schema.sql`` from the warehouse.

The AdventureWorks2016 OLTP tables were loaded into the warehouse ``analytics.raw``
schema by the dlt SQL Server pipeline. dlt drops the source primary/foreign keys and
adds its own ``_dlt_load_id`` / ``_dlt_id`` bookkeeping columns, so this script
reconstructs a clean, keyed schema for the ``postgres_active`` OLTP sandbox:

* every source column except ``_dlt_*`` is kept, with its type and nullability;
* a curated primary key is added per table (single or composite);
* ``modified_date`` gets a btree index so an incremental consumer can use it.

It is dependency-free: it talks to Postgres through ``psql`` rather than a Python
driver, so it runs on any machine that has the client installed.

Usage (from the repository root, with the stack up)::

    python3 scripts/gen_adventureworks_schema.py

Connection settings come from the environment, falling back to the local demo
defaults: ``PGHOST``/``PGPORT``/``PGDATABASE``/``PGUSER``/``PGPASSWORD`` or the
``.env`` values ``POSTGRES_PORT`` / ``POSTGRES_PASSWORD``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Tables that are NOT AdventureWorks OLTP tables and must not be copied:
# dlt's own bookkeeping tables plus the separately simulated `orders` table.
EXCLUDED_TABLES = {"_dlt_loads", "_dlt_pipeline_state", "_dlt_version", "orders"}

# Columns dlt adds that have no place in the source schema.
DLT_COLUMNS = {"_dlt_load_id", "_dlt_id"}

# Curated primary keys. The warehouse lost the source constraints, so the natural
# key of each AdventureWorks table is declared here. The generator verifies every
# key is unique (and non-null) before emitting it.
PRIMARY_KEYS: dict[str, list[str]] = {
    "address": ["address_id"],
    "address_type": ["address_type_id"],
    "aw_build_version": ["system_information_id"],
    "bill_of_materials": ["bill_of_materials_id"],
    "business_entity": ["business_entity_id"],
    "business_entity_address": ["business_entity_id", "address_id", "address_type_id"],
    "business_entity_contact": ["business_entity_id", "person_id", "contact_type_id"],
    "contact_type": ["contact_type_id"],
    "country_region": ["country_region_code"],
    "country_region_currency": ["country_region_code", "currency_code"],
    "credit_card": ["credit_card_id"],
    "culture": ["culture_id"],
    "currency": ["currency_code"],
    "currency_rate": ["currency_rate_id"],
    "customer": ["customer_id"],
    "database_log": ["database_log_id"],
    "department": ["department_id"],
    "document": ["document_node"],
    "email_address": ["email_address_id"],
    "employee": ["business_entity_id"],
    "employee_department_history": ["business_entity_id", "department_id", "shift_id", "start_date"],
    "employee_pay_history": ["business_entity_id", "rate_change_date"],
    "illustration": ["illustration_id"],
    "job_candidate": ["job_candidate_id"],
    "location": ["location_id"],
    "password": ["business_entity_id"],
    "person": ["business_entity_id"],
    "person_credit_card": ["business_entity_id", "credit_card_id"],
    "person_phone": ["business_entity_id", "phone_number", "phone_number_type_id"],
    "phone_number_type": ["phone_number_type_id"],
    "product": ["product_id"],
    "product_category": ["product_category_id"],
    "product_cost_history": ["product_id", "start_date"],
    "product_description": ["product_description_id"],
    "product_document": ["document_node", "product_id"],
    "product_inventory": ["product_id", "location_id"],
    "product_list_price_history": ["product_id", "start_date"],
    "product_model": ["product_model_id"],
    "product_model_illustration": ["product_model_id", "illustration_id"],
    "product_model_product_description_culture": [
        "product_model_id",
        "product_description_id",
        "culture_id",
    ],
    "product_photo": ["product_photo_id"],
    "product_product_photo": ["product_id", "product_photo_id"],
    "product_review": ["product_review_id"],
    "product_subcategory": ["product_subcategory_id"],
    "product_vendor": ["product_id", "business_entity_id"],
    "purchase_order_detail": ["purchase_order_id", "purchase_order_detail_id"],
    "purchase_order_header": ["purchase_order_id"],
    "sales_order_detail": ["sales_order_id", "sales_order_detail_id"],
    "sales_order_header": ["sales_order_id"],
    "sales_order_header_sales_reason": ["sales_order_id", "sales_reason_id"],
    "sales_person": ["business_entity_id"],
    "sales_person_quota_history": ["business_entity_id", "quota_date"],
    "sales_reason": ["sales_reason_id"],
    "sales_tax_rate": ["sales_tax_rate_id"],
    "sales_territory": ["territory_id"],
    "sales_territory_history": ["business_entity_id", "territory_id", "start_date"],
    "scrap_reason": ["scrap_reason_id"],
    "shift": ["shift_id"],
    "ship_method": ["ship_method_id"],
    "shopping_cart_item": ["shopping_cart_item_id"],
    "special_offer": ["special_offer_id"],
    "special_offer_product": ["special_offer_id", "product_id"],
    "state_province": ["state_province_id"],
    "store": ["business_entity_id"],
    "transaction_history": ["transaction_id"],
    "transaction_history_archive": ["transaction_id"],
    "unit_measure": ["unit_measure_code"],
    "vendor": ["business_entity_id"],
    "work_order": ["work_order_id"],
    "work_order_routing": ["work_order_id", "product_id", "operation_sequence"],
}

# Types that dlt widened but that read more naturally in a hand-written schema.
TYPE_ALIASES = {
    "character varying": "text",
    "timestamp with time zone": "timestamptz",
    "time without time zone": "time",
}


def run_psql(sql: str, args: argparse.Namespace) -> list[list[str]]:
    """Run a query with psql and return rows split on the unit separator."""
    env = dict(os.environ)
    env["PGPASSWORD"] = args.password
    cmd = [
        "psql",
        "-X",
        "-q",
        "-A",
        "-t",
        "-F",
        "\x1f",
        "-h",
        args.host,
        "-p",
        str(args.port),
        "-U",
        args.user,
        "-d",
        args.db,
        "-c",
        sql,
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(f"psql failed for: {sql[:120]}")
    rows = []
    for line in result.stdout.splitlines():
        if line:
            rows.append(line.split("\x1f"))
    return rows


def q(identifier: str) -> str:
    """Quote a Postgres identifier."""
    return '"' + identifier.replace('"', '""') + '"'


def load_columns(args: argparse.Namespace) -> dict[str, list[tuple[str, str, bool]]]:
    """Return {table: [(column, type, nullable), ...]} for the AdventureWorks tables."""
    rows = run_psql(
        """
        select table_name, column_name, data_type, is_nullable
        from information_schema.columns
        where table_schema = 'raw'
        order by table_name, ordinal_position
        """,
        args,
    )
    tables: dict[str, list[tuple[str, str, bool]]] = {}
    for table, column, data_type, nullable in rows:
        if table in EXCLUDED_TABLES or column in DLT_COLUMNS:
            continue
        tables.setdefault(table, []).append((column, data_type, nullable == "YES"))
    return tables


def validate_primary_keys(
    tables: dict[str, list[tuple[str, str, bool]]], args: argparse.Namespace
) -> None:
    """Fail loudly if a curated key is not unique and non-null in the source."""
    problems = []
    for table in sorted(tables):
        columns = {c for c, _, _ in tables[table]}
        pk = PRIMARY_KEYS.get(table)
        if not pk:
            problems.append(f"{table}: no curated primary key")
            continue
        missing = [c for c in pk if c not in columns]
        if missing:
            problems.append(f"{table}: primary key columns not in source: {missing}")
            continue
        key = ", ".join(q(c) for c in pk)
        not_null = " and ".join(f"{q(c)} is not null" for c in pk)
        sql = (
            f"select count(*), count(distinct ({key})), "
            f"count(*) filter (where not ({not_null})) from raw.{q(table)}"
        )
        (total, distinct, nulls), = run_psql(sql, args)
        if total != distinct:
            problems.append(f"{table}: primary key {pk} is not unique ({total} rows, {distinct} keys)")
        if int(nulls) > 0:
            problems.append(f"{table}: primary key {pk} has {nulls} null(s)")
    if problems:
        for problem in problems:
            sys.stderr.write(f"ERROR: {problem}\n")
        raise SystemExit("primary-key validation failed; fix PRIMARY_KEYS and re-run")


def render_schema(tables: dict[str, list[tuple[str, str, bool]]]) -> str:
    lines = [
        "-- AdventureWorks2016 OLTP tables for the postgres_active sandbox.",
        "--",
        "-- GENERATED FILE -- do not edit by hand.",
        "-- Regenerate with: python3 scripts/gen_adventureworks_schema.py",
        "--",
        "-- Source: the warehouse analytics.raw schema (loaded from SQL Server by",
        "-- dlt). dlt's bookkeeping columns are dropped and the AdventureWorks",
        "-- primary keys are restored. Foreign keys are deliberately NOT enforced:",
        "-- the seed is a random 10% sample per table and the simulator inserts",
        "-- freely, so referential integrity is illustrative rather than enforced.",
        "",
        "\\set ON_ERROR_STOP on",
        "",
    ]
    for table in sorted(tables):
        columns = tables[table]
        pk = PRIMARY_KEYS[table]
        col_defs = []
        for name, data_type, nullable in columns:
            sql_type = TYPE_ALIASES.get(data_type, data_type)
            null = "" if nullable else " not null"
            col_defs.append(f"    {q(name):<32} {sql_type}{null}")
        col_defs.append(f"    primary key ({', '.join(q(c) for c in pk)})")
        lines.append(f"create table if not exists public.{q(table)} (")
        lines.append(",\n".join(col_defs))
        lines.append(");")
        if "modified_date" in {c for c, _, _ in columns}:
            lines.append(
                f"create index if not exists {q(table + '_modified_date_idx')} "
                f"on public.{q(table)} (modified_date);"
            )
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("PGHOST", "localhost"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PGPORT", os.environ.get("POSTGRES_PORT", "5433")))
    )
    parser.add_argument("--db", default=os.environ.get("PGDATABASE", "analytics"))
    parser.add_argument("--user", default=os.environ.get("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.environ.get("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "")))
    parser.add_argument(
        "--out",
        default="postgres_active/init/02_adventureworks_schema.sql",
        help="output SQL file",
    )
    args = parser.parse_args()

    tables = load_columns(args)
    validate_primary_keys(tables, args)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_schema(tables))
    print(f"wrote {out} ({len(tables)} tables)")


if __name__ == "__main__":
    main()
