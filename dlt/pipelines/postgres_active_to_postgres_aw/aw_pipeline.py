"""Replicate the AdventureWorks2016 tables from `postgres_active` into the warehouse.

The live OLTP sandbox in `postgres_active.active_db` (seeded from the static
AdventureWorks load, then kept moving by the `simulate_adventureworks` DAG) is
mirrored into the warehouse schema `analytics.raw_active`, so the dbt project can
be repointed at a live source:

    postgres_active.active_db.public.*  --(dlt, incremental + merge)-->  analytics.raw_active.*

Every table is loaded with:
- incremental loading on `modified_date` (only rows changed since the last run);
- `merge` on the reflected primary key (the sandbox tables carry real PKs).

`database_log` has no `modified_date`, so it is merged without an incremental
cursor. The dbt project reads `raw_active`; see
`dbt/adventureworks_dwh/models/staging/_sources.yml`.

`orders` and the Debezium signalling table are excluded: `orders` has its own
pipeline (`postgres_active_to_postgres`), and the signal table is connector
plumbing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import dlt
from dlt.destinations import postgres
from dlt.sources.sql_database import sql_table
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL

# The shared credentials helper lives one directory up (dlt/pipelines/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stack_credentials import destination_credentials, source_credentials  # noqa: E402

SOURCE_SCHEMA = "public"
EXCLUDED_TABLES = {"orders", "debezium_signal"}
CURSOR_COLUMN = "modified_date"
# Tables without a `modified_date` column: merged without an incremental cursor.
NO_CURSOR_TABLES = {"database_log"}


def _url(credentials: dict) -> URL:
    return URL.create(
        drivername=credentials.get("drivername", "postgresql+psycopg2"),
        username=credentials.get("username"),
        password=credentials.get("password"),
        host=credentials.get("host"),
        port=credentials.get("port"),
        database=credentials.get("database"),
    )


def _tables(credentials: dict) -> list[str]:
    inspector = inspect(create_engine(_url(credentials)))
    return sorted(
        name
        for name in inspector.get_table_names(schema=SOURCE_SCHEMA)
        if name not in EXCLUDED_TABLES
    )


def load_adventureworks() -> None:
    credentials = source_credentials()
    pipeline = dlt.pipeline(
        pipeline_name="postgres_active_to_postgres_aw",
        destination=postgres(credentials=destination_credentials()),
        dataset_name="raw_active",
    )

    sources = []
    for table in _tables(credentials):
        kwargs: dict = {}
        if table not in NO_CURSOR_TABLES:
            kwargs["incremental"] = dlt.sources.incremental(CURSOR_COLUMN)
        sources.append(
            sql_table(
                credentials=credentials,
                table=table,
                schema=SOURCE_SCHEMA,
                reflection_level="full",
                write_disposition="merge",
                **kwargs,
            )
        )

    load_info = pipeline.run(sources)
    print(load_info)


if __name__ == "__main__":
    load_adventureworks()
