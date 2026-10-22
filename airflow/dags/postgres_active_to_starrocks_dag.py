from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag

INGEST_SCRIPT = "/opt/airflow/scripts/ingest_starrocks.py"
DBT_PROJECT_DIR = "/opt/airflow/dbt/adventureworks_starrocks"
# dbt-starrocks lives in its own virtualenv (see airflow/Dockerfile).
DBT = "/home/airflow/dbt-starrocks/bin/dbt"
# Read the live raw schema, and honour the primary-key snapshots (hard deletes at the source).
DBT_VARS = "{aw_source_schema: raw, use_pk_snapshots: true}"


@dag(
    # A cycle is short (seconds at demo volume), so a retry is cheap and must fit inside the 5 minutes.
    default_args={"retries": 2, "retry_delay": timedelta(minutes=1)},
    dag_id="postgres_active_to_starrocks",
    description=(
        "5-minute micro-batch: ingestr loads the changed AdventureWorks rows from postgres_active into "
        "StarRocks raw (incremental merge), then dbt-starrocks rebuilds and tests the star in mart"
    ),
    # One minute after simulate_adventureworks (3-59/5), so a cycle sees the simulator's latest writes.
    # max_active_runs=1: a cycle that overruns makes the next one wait instead of stacking.
    schedule="4-59/5 * * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=15),
    tags=["ingestr", "dbt", "starrocks", "adventureworks"],
)
def postgres_active_to_starrocks():

    ingest_raw = BashOperator(
        task_id="ingestr_to_starrocks",
        bash_command=f"python {INGEST_SCRIPT}",
        execution_timeout=timedelta(minutes=8),
    )

    # `dbt build` runs seeds, models, the product-version log and the tests, so a bad cycle fails here
    # and the dashboard keeps the last good mart. Grants for the read-only users are re-applied by the
    # project's on-run-end hook.
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=(
            f"{DBT} build --project-dir {DBT_PROJECT_DIR} --profiles-dir {DBT_PROJECT_DIR} "
            f"--vars '{DBT_VARS}' --threads 4"
        ),
        execution_timeout=timedelta(minutes=8),
    )

    ingest_raw >> dbt_build


postgres_active_to_starrocks()
