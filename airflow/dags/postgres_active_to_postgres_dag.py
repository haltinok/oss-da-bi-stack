from __future__ import annotations

import pendulum
from airflow.decorators import dag
from airflow.operators.bash import BashOperator

DLT_PROJECT_DIR = "/opt/airflow/dlt/pipelines/postgres_active_to_postgres"


@dag(
    dag_id="postgres_active_to_postgres",
    description="Replicate the orders table from postgres_active into the analytics_2 raw schema via dlt (incremental + merge)",
    schedule="*/15 * * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["dlt", "postgres", "cdc"],
)
def postgres_active_to_postgres():

    ingest_orders = BashOperator(
        task_id="dlt_ingest_orders",
        bash_command=f"cd {DLT_PROJECT_DIR} && python orders_pipeline.py",
    )

    ingest_orders


postgres_active_to_postgres()
