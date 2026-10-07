"""Every DAG in airflow/dags imports cleanly and has the expected shape.

Run with the Airflow image's packages (see the `dags` CI job):

    AIRFLOW__CORE__LOAD_EXAMPLES=false pytest tests/test_dag_integrity.py
"""

from __future__ import annotations

from pathlib import Path

import pytest
from airflow.models import DagBag

DAGS_DIR = Path(__file__).resolve().parent.parent / "airflow" / "dags"
EXPECTED_DAGS = {
    "postgres_active_to_postgres",
    "postgres_active_to_postgres_aw",
    "simulate_adventureworks",
    "simulate_orders",
    "sqlserver_to_postgres_elt",
}


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=str(DAGS_DIR))


def test_no_import_errors(dagbag: DagBag) -> None:
    assert dagbag.import_errors == {}


def test_expected_dags(dagbag: DagBag) -> None:
    assert set(dagbag.dag_ids) == EXPECTED_DAGS


def test_dags_do_not_overlap(dagbag: DagBag) -> None:
    for dag_id in dagbag.dag_ids:
        assert dagbag.get_dag(dag_id).max_active_runs == 1, dag_id
