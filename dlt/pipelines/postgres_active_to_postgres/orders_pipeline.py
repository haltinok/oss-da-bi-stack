"""Replicate the `public.orders` table from postgres_active into the `raw` schema of the analytics warehouse.

The source table is mutated every 5 minutes by the Airflow `simulate_orders` DAG
(inserts, updates, soft-deletes). This pipeline mirrors those changes into the
warehouse using:
- incremental loading on `updated_at` (only rows changed since the last run are fetched)
- `merge` write disposition (upsert by the reflected primary key `id`)

Each ingested row is stamped with `ingested_at` (UTC) so downstream consumers can
tell when a given version of a record landed in the warehouse.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import dlt
from dlt.destinations import postgres
from dlt.sources.sql_database import sql_table


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


def _source_credentials() -> dict:
    """Source `active_db` credentials, sharing the stack's POSTGRES_PASSWORD when set."""
    credentials = dict(dlt.secrets["sources.sql_database.credentials"])
    if os.environ.get("POSTGRES_PASSWORD"):
        credentials["password"] = os.environ["POSTGRES_PASSWORD"]
    return credentials


def add_ingested_at(row):
    row["ingested_at"] = datetime.now(timezone.utc)
    return row


def load_orders() -> None:
    pipeline = dlt.pipeline(
        pipeline_name="postgres_active_to_postgres",
        destination=postgres(credentials=_destination_credentials()),
        dataset_name="raw",
    )

    source = sql_table(
        credentials=_source_credentials(),
        table="orders",
        schema="public",
        incremental=dlt.sources.incremental("updated_at"),
        reflection_level="full",
        write_disposition="merge",
    ).add_map(add_ingested_at)

    load_info = pipeline.run(source)
    print(load_info)


if __name__ == "__main__":
    load_orders()
