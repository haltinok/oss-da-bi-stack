from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag

DLT_PROJECT_DIR = "/opt/airflow/dlt/pipelines/postgres_active_to_postgres_aw"
DBT_PROJECT_DIR = "/opt/airflow/dbt/adventureworks_dwh"
DBT_PROFILES_DIR = "/opt/airflow/dbt/adventureworks_dwh"
SYNC_MART_SCRIPT = "/opt/airflow/scripts/sync_mart_to_clickhouse.py"


@dag(
    default_args={"retries": 2, "retry_delay": timedelta(minutes=2)},
    dag_id="postgres_active_to_postgres_aw",
    description="Replicate the AdventureWorks tables from postgres_active into analytics.raw_active (dlt, incremental + merge), then build the warehouse DWH with dbt",
    # Offset from postgres_active_to_postgres and simulate_adventureworks so the
    # three never fire in the same minute.
    schedule="9-59/15 * * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["dlt", "dbt", "adventureworks"],
)
def postgres_active_to_postgres_aw():

    ingest_raw = BashOperator(
        task_id="dlt_ingest_adventureworks",
        bash_command=f"cd {DLT_PROJECT_DIR} && python aw_pipeline.py",
    )

    source_freshness = BashOperator(
        task_id="dbt_source_freshness",
        # Informational only. It reports source *activity* (max modified_date), which
        # is stale until the simulator has run, so it must not gate or fail the build.
        bash_command=(
            f"dbt source freshness --project-dir {DBT_PROJECT_DIR} "
            f"--profiles-dir {DBT_PROFILES_DIR} || true"
        ),
    )

    # `dbt build` runs seeds, snapshots, models and tests, so the product SCD2
    # snapshot (dim_product_snapshot) is built here too -- no separate `dbt snapshot`.
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"dbt build --project-dir {DBT_PROJECT_DIR} --profiles-dir {DBT_PROFILES_DIR}",
    )

    # Copy the freshly built star into ClickHouse. Chained here (not on a clock
    # offset) so a slow or retried build can never be copied half-rebuilt. The
    # script exits 99 when ClickHouse is absent (core-only stack), which marks
    # this task SKIPPED instead of SUCCESS.
    sync_mart = BashOperator(
        task_id="sync_mart_to_clickhouse",
        bash_command=f"python {SYNC_MART_SCRIPT}",
        skip_on_exit_code=99,
    )

    # The build and the ClickHouse copy are the critical path; freshness runs
    # alongside them (after the build) and never blocks.
    ingest_raw >> dbt_build >> sync_mart
    dbt_build >> source_freshness


postgres_active_to_postgres_aw()
