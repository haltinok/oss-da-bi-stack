from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag

DLT_PROJECT_DIR = "/opt/airflow/dlt/pipelines/postgres_active_to_postgres"


@dag(
    default_args={"retries": 2, "retry_delay": timedelta(minutes=2)},
    dag_id="postgres_active_to_postgres",
    description="Replicate the orders table from postgres_active into the analytics raw schema via dlt (incremental + merge)",
    # Two minutes after the simulator's 0/15/30/45 slots so the pipeline reads the
    # rows it just wrote instead of racing it.
    schedule="2-59/15 * * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["dlt", "postgres", "cdc"],
)
def postgres_active_to_postgres():

    BashOperator(
        task_id="dlt_ingest_orders",
        bash_command=f"cd {DLT_PROJECT_DIR} && python orders_pipeline.py",
    )


postgres_active_to_postgres()
