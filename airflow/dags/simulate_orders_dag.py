from __future__ import annotations

import pendulum
from airflow.decorators import dag
from airflow.operators.bash import BashOperator

SIMULATE_SCRIPT = "/opt/airflow/scripts/simulate_orders.py"


@dag(
    dag_id="simulate_orders",
    description="Randomly insert/update/soft-delete orders in postgres_active to feed the Debezium CDC stream",
    schedule="*/5 * * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["simulation", "postgres", "cdc"],
)
def simulate_orders():

    run_simulator = BashOperator(
        task_id="run_order_simulator",
        bash_command=f"python {SIMULATE_SCRIPT}",
    )

    run_simulator


simulate_orders()
