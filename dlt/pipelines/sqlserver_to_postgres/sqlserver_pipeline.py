"""Ingest all tables of the AdventureWorks2016 OLTP database (SQL Server) into the `raw` schema of the Postgres warehouse.

Uses the `sql_database` source bundled with dlt (>=1.0). The source database has six schemas
(dbo, HumanResources, Person, Production, Purchasing, Sales) whose table names are globally unique,
so each schema is reflected and loaded in turn, all landing in the single `raw` dataset.

This is a **one-time load**: the AdventureWorks source is a static demo dataset, so
re-running the pipeline is pointless (and re-copies 71 tables). The script skips the
load when the target already contains the data; pass ``--force`` to reload anyway
(drops and recreates the AdventureWorks tables in `raw`).

Two adapters bridge MSSQL -> dlt/Postgres:
- `type_adapter_callback`: maps MSSQL-only column types (xml, uniqueidentifier) and the
  NullType placeholders for hierarchyid/geography to plain text in the dlt schema.
- `query_adapter_callback`: CASTs those hierarchyid/geography columns (reflected as NullType)
  to VARCHAR(max) in the SELECT, because pyodbc cannot otherwise fetch SQL type -151.
"""

from __future__ import annotations

import argparse
import os

import dlt
from dlt.sources.sql_database import sql_database
from dlt.destinations import postgres

from sqlalchemy.types import NullType
from dlt.common.libs.sql_alchemy import sa

SCHEMAS = ["dbo", "HumanResources", "Person", "Production", "Purchasing", "Sales"]

# Presence of this table is the load marker: it is created by the first successful
# run and is not touched by the postgres_active pipeline, which shares the dataset.
SENTINEL_TABLE = "raw.customer"


def _destination_credentials() -> dict:
    """Destination Postgres credentials with `.env`'s POSTGRES_PASSWORD applied.

    dlt gives `secrets.toml` a higher priority than environment variables, so an
    env-var override is not possible through configuration alone. The stack's
    `.env` is the single source of truth for the database password, so it is
    applied explicitly here (falling back to `secrets.toml` when it is unset).
    """
    path = "destination.postgres.credentials"
    credentials: dict = {}
    for key in ("drivername", "host", "port", "database", "username"):
        value = dlt.config.get(f"{path}.{key}")
        if value is not None:
            credentials[key] = value
    credentials["password"] = os.environ.get("POSTGRES_PASSWORD") or dlt.secrets.get(
        f"{path}.password"
    )
    return credentials


def type_adapter_callback(sql_type):
    """Return a SQLAlchemy text type for MSSQL types dlt cannot map, else None (keep inference)."""
    if sql_type is None:
        return None
    type_name = type(sql_type).__name__.lower()
    if type_name in ("nulltype", "xml", "uniqueidentifier", "hierarchyid", "geography"):
        return sa.Text()
    return None


def query_adapter_callback(query, table, *args):
    """Cast hierarchyid/geography columns (reflected as NullType) to text so pyodbc can fetch them."""
    null_cols = [c for c in table.columns if isinstance(c.type, NullType)]
    if not null_cols:
        return query
    cols = [
        sa.cast(c, sa.String()).label(c.name) if isinstance(c.type, NullType) else c
        for c in table.columns
    ]
    return sa.select(*cols).select_from(table)


def already_loaded(pipeline: dlt.Pipeline) -> bool:
    """True when the raw dataset already holds the AdventureWorks load marker."""
    try:
        with pipeline.sql_client() as client:
            rows = client.execute_sql(f"select to_regclass('{SENTINEL_TABLE}')")
        return bool(rows and rows[0][0])
    except Exception:
        # Destination missing/unreachable: let the load decide what to do next.
        return False


def load_sqlserver_to_postgres(force: bool = False) -> None:
    connection_url = dlt.secrets["sources.sql_database.credentials"]

    pipeline = dlt.pipeline(
        pipeline_name="sqlserver_to_postgres",
        destination=postgres(credentials=_destination_credentials()),
        dataset_name="raw",
    )

    if not force and already_loaded(pipeline):
        print(
            f"AdventureWorks already loaded into raw.{SENTINEL_TABLE.split('.')[1]} "
            "via dlt; skipping (this source is static, use --force to reload)."
        )
        return

    sources = [
        sql_database(
            credentials=connection_url,
            schema=schema,
            reflection_level="full",
            type_adapter_callback=type_adapter_callback,
            query_adapter_callback=query_adapter_callback,
        )
        for schema in SCHEMAS
    ]

    load_info = pipeline.run(sources, write_disposition="replace")
    print(load_info)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reload even when the raw dataset already contains AdventureWorks.",
    )
    args = parser.parse_args()
    load_sqlserver_to_postgres(force=args.force)
