from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag

SIMULATE_SCRIPT = "/opt/airflow/scripts/simulate_orders.py"


@dag(
    default_args={"retries": 2, "retry_delay": timedelta(minutes=2)},
    dag_id="simulate_orders",
    description="Randomly insert/update/soft-delete orders in postgres_active to feed the Debezium CDC stream",
    schedule="*/5 * * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["simulation", "postgres", "cdc"],
)
def simulate_orders():

    BashOperator(
        task_id="run_order_simulator",
        bash_command=f"python {SIMULATE_SCRIPT}",
    )


simulate_orders()
