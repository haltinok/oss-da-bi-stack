"""Ingest all tables of the AdventureWorks2016 OLTP database (SQL Server) into the `raw` schema of the Postgres warehouse.

Uses the `sql_database` source bundled with dlt (>=1.0). The source database has six schemas
(dbo, HumanResources, Person, Production, Purchasing, Sales) whose table names are globally unique,
so each schema is reflected and loaded in turn, all landing in the single `raw` dataset.

Two adapters bridge MSSQL -> dlt/Postgres:
- `type_adapter_callback`: maps MSSQL-only column types (xml, uniqueidentifier) and the
  NullType placeholders for hierarchyid/geography to plain text in the dlt schema.
- `query_adapter_callback`: CASTs those hierarchyid/geography columns (reflected as NullType)
  to VARCHAR(max) in the SELECT, because pyodbc cannot otherwise fetch SQL type -151.
"""

import dlt
from dlt.sources.sql_database import sql_database

from sqlalchemy.types import NullType
from dlt.common.libs.sql_alchemy import sa

SCHEMAS = ["dbo", "HumanResources", "Person", "Production", "Purchasing", "Sales"]


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


def load_sqlserver_to_postgres() -> None:
    connection_url = dlt.secrets["sources.sql_database.credentials"]

    pipeline = dlt.pipeline(
        pipeline_name="sqlserver_to_postgres",
        destination="postgres",
        dataset_name="raw",
    )

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
    load_sqlserver_to_postgres()
