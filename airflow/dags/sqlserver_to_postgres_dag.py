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
        "(optional static load; the star schema is built in StarRocks from postgres_active, see README)."
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

    # Load only. The star schema is built by `postgres_active_to_starrocks` from the live
    # postgres_active tables; this static load only feeds `gen_adventureworks_*` (the sandbox seed).
    BashOperator(
        task_id="dlt_ingest_raw",
        bash_command=f"cd {DLT_PROJECT_DIR} && python sqlserver_pipeline.py",
    )


sqlserver_to_postgres_elt()
