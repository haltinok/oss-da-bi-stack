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

import sys
from datetime import datetime, timezone
from pathlib import Path

import dlt
from dlt.destinations import postgres
from dlt.sources.sql_database import sql_table

# The shared credentials helper lives one directory up (dlt/pipelines/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stack_credentials import destination_credentials, source_credentials  # noqa: E402


def add_ingested_at(row):
    row["ingested_at"] = datetime.now(timezone.utc)
    return row


def load_orders() -> None:
    pipeline = dlt.pipeline(
        pipeline_name="postgres_active_to_postgres",
        destination=postgres(credentials=destination_credentials()),
        dataset_name="raw",
    )

    source = sql_table(
        credentials=source_credentials(),
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
