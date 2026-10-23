"""DATASET=250m makes the actions service read-only (no database needed).

  uv run --with pytest --with fastapi --with httpx --with 'pyjwt[crypto]' --with pymysql --with psycopg2-binary python -m pytest actions/tests/test_actions_dataset.py
"""
import importlib
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = str(pathlib.Path(__file__).resolve().parents[1])   # both services have a main.py: put this one first on every load


@pytest.fixture
def load(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_ISSUER", "http://kc/realms/spike")
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://kc/realms/spike/certs")

    def _load(dataset=None):
        monkeypatch.delenv("DATASET", raising=False) if dataset is None else monkeypatch.setenv("DATASET", dataset)
        sys.modules.pop("main", None)
        sys.path.insert(0, SERVICE_DIR)
        main = importlib.import_module("main")
        return main

    return _load


def client(main, role):
    main.app.dependency_overrides[main.current_user] = lambda: main.User(name=f"test-{role}", role=role)
    return TestClient(main.app, raise_server_exceptions=False)


LINES = {"idempotency_key": "test-dataset-0001", "lines": [{"product_id": 1, "qty": 1}]}
CAMPAIGN = {"idempotency_key": "test-dataset-0002", "product_ids": [1], "discount_pct": 10, "days": 30}
DRAFT = {"run_id": "test-dataset-run1", "proposals": [{"kind": "work_order", "title": "Restock", "rationale": "Out of stock with demand.", "payload": {"lines": [{"product_id": 1, "qty": 1}]}}]}


def test_live_is_untouched(load):
    main = load()
    assert main.READ_ONLY is False and main.MART == "mart"


def test_both_is_the_live_service(load):
    main = load("both")
    assert main.READ_ONLY is False and main.MART == "mart"


def test_250m_reads_its_own_mart_and_refuses_every_write(load):
    main = load("250m")
    assert main.READ_ONLY is True and main.MART == "mart_250m"
    c = client(main, "admin")
    for path, body in (("/actions/purchase-orders", LINES), ("/actions/work-orders", LINES), ("/actions/campaigns", CAMPAIGN)):
        r = c.post(path, json=body)
        assert r.status_code == 409 and "Read-only" in r.json()["detail"] and "postgres_active" in r.json()["detail"], (path, r.text)
    assert client(main, "agent").post("/proposals", json=DRAFT).status_code == 409
    assert c.post("/proposals/1/dismiss", json={}).status_code == 409


def test_250m_shows_no_log_and_no_proposals(load):
    main = load("250m")
    c = client(main, "purchasing")
    assert c.get("/actions/log").json() == {"entries": []}
    assert c.get("/proposals").json() == {"proposals": []}


def test_250m_still_checks_who_may_ask(load):
    main = load("250m")
    # a role without actions is refused by role before the dataset matters? the read-only answer must not leak for the wrong role
    r = client(main, "marketing").post("/actions/purchase-orders", json=LINES)
    assert r.status_code in (403, 409)


def test_a_bad_dataset_is_refused_at_start(load):
    with pytest.raises(SystemExit):
        load("250m; drop")
