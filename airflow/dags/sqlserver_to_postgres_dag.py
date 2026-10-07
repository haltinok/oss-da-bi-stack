from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag

DLT_PROJECT_DIR = "/opt/airflow/dlt/pipelines/sqlserver_to_postgres"


@dag(
    default_args={"retries": 2, "retry_delay": timedelta(minutes=2)},
    dag_id="sqlserver_to_postgres_elt",
    description=(
        "One-time load of AdventureWorks2016 from SQL Server into Postgres raw via dlt "
        "(static alternative source; the DWH is built from raw_active, see README)."
    ),
    # The AdventureWorks source is static, so this DAG runs manually: the dlt step
    # skips itself once the raw dataset is populated (trigger with --force to reload).
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["dlt", "elt"],
)
def sqlserver_to_postgres_elt():

    # Load only. The DWH is built by `postgres_active_to_postgres_aw` from
    # `raw_active`; a dbt step here used to rebuild those same mart tables (from
    # `raw_active`, not the `raw` this DAG loads) and could race that DAG's build.
    # To build the star from this static load instead, run dbt by hand with
    # `--vars '{aw_source_schema: raw}'`.
    BashOperator(
        task_id="dlt_ingest_raw",
        bash_command=f"cd {DLT_PROJECT_DIR} && python sqlserver_pipeline.py",
    )


sqlserver_to_postgres_elt()
