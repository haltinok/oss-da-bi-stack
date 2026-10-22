from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag

# The agent lives in its own virtualenv (see airflow/Dockerfile) and in the repo's agent/ directory, mounted
# read-only at /opt/airflow/agent. Its connection settings and the service account's secret come from the
# container environment (docker-compose.yml); with ANTHROPIC_API_KEY set it drafts with a model, otherwise
# with plain rules. It can only draft: a person approves in the dashboard.
AGENT_PYTHON = "/home/airflow/agent/bin/python"


@dag(
    dag_id="inventory_weekly_proposals",
    description=(
        "Weekly: the proposal agent reads inventory through Cube and drafts reorders and campaigns for a person "
        "to approve (needs the starrocks profile services: cube, auth, actions, keycloak)"
    ),
    schedule="0 6 * * 1",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    # Off until someone turns it on: drafting is harmless, but the DAG needs the starrocks profile running and
    # AGENT_CLIENT_SECRET set, which a fresh checkout does not have.
    is_paused_upon_creation=True,
    dagrun_timeout=timedelta(minutes=30),
    default_args={"retries": 1, "retry_delay": timedelta(minutes=5)},
    tags=["agent", "inventory", "proposals"],
)
def inventory_weekly_proposals():
    BashOperator(
        task_id="draft_proposals",
        bash_command=f"cd /opt/airflow && {AGENT_PYTHON} -m agent.run",
        execution_timeout=timedelta(minutes=20),
    )


inventory_weekly_proposals()
