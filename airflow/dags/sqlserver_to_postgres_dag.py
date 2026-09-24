from __future__ import annotations

import pendulum
from airflow.decorators import dag
from airflow.operators.bash import BashOperator

DLT_PROJECT_DIR = "/opt/airflow/dlt/pipelines/sqlserver_to_postgres"
DBT_PROJECT_DIR = "/opt/airflow/dbt/adventureworks_dwh"
DBT_PROFILES_DIR = "/opt/airflow/dbt/adventureworks_dwh"


@dag(
    dag_id="sqlserver_to_postgres_elt",
    description="Ingest AdventureWorks2016 from SQL Server into Postgres raw schema via dlt, then build stage/mart with dbt-core",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["dlt", "dbt", "elt"],
)
def sqlserver_to_postgres_elt():

    ingest_raw = BashOperator(
        task_id="dlt_ingest_raw",
        bash_command=f"cd {DLT_PROJECT_DIR} && python sqlserver_pipeline.py",
    )

    # A single `dbt build` instead of `dbt run` staging -> `dbt run` marts ->
    # `dbt test`: dbt interleaves each model's tests in dependency order, so a
    # failing staging test stops the run before the marts are rebuilt on top of
    # bad data. Per-node results are still visible in the task log.
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=(
            f"dbt build --project-dir {DBT_PROJECT_DIR} --profiles-dir {DBT_PROFILES_DIR}"
        ),
    )

    ingest_raw >> dbt_build


sqlserver_to_postgres_elt()
