from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag

SIMULATE_SCRIPT = "/opt/airflow/scripts/simulate_adventureworks.py"


@dag(
    default_args={"retries": 2, "retry_delay": timedelta(minutes=2)},
    dag_id="simulate_adventureworks",
    description="Randomly mutate the AdventureWorks2016 tables in postgres_active to simulate a live OLTP database",
    # Offset from simulate_orders (*/5) so the two simulators do not write at the
    # same instant.
    schedule="3-59/5 * * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["simulation", "postgres", "adventureworks"],
)
def simulate_adventureworks():

    BashOperator(
        task_id="run_adventureworks_simulator",
        bash_command=f"python {SIMULATE_SCRIPT}",
    )


simulate_adventureworks()
