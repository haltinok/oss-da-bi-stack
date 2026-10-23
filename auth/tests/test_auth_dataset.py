"""The auth service's territory table follows DATASET.

  uv run --with pytest --with fastapi --with 'pyjwt[crypto]' --with pymysql python -m pytest auth/tests
"""
import importlib
import pathlib
import sys

import pytest

SERVICE_DIR = str(pathlib.Path(__file__).resolve().parents[1])   # both services have a main.py: put this one first on every load


@pytest.fixture
def load(monkeypatch):
    monkeypatch.setenv("CUBEJS_API_SECRET", "x")
    monkeypatch.setenv("KEYCLOAK_ISSUER", "http://kc/realms/spike")
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://kc/realms/spike/certs")
    monkeypatch.delenv("AUTH_REGIONS_TABLE", raising=False)

    def _load(dataset=None, table=None):
        for k, v in (("DATASET", dataset), ("AUTH_REGIONS_TABLE", table)):
            monkeypatch.delenv(k, raising=False) if v is None else monkeypatch.setenv(k, v)
        sys.modules.pop("main", None)
        sys.path.insert(0, SERVICE_DIR)
        return importlib.import_module("main")

    return _load


def test_live_reads_the_live_territories(load):
    assert load().REGIONS_TABLE == "rls.user_regions"
    assert load("live").REGIONS_TABLE == "rls.user_regions"


def test_a_benchmark_dataset_reads_its_own_schema(load):
    assert load("250m").REGIONS_TABLE == "rls_250m.user_regions"


def test_the_table_can_still_be_set_explicitly(load):
    assert load("250m", "rls.other").REGIONS_TABLE == "rls.other"


@pytest.mark.parametrize("bad", ["250m; drop table x", "a-b", "250 m", "../x"])
def test_a_dataset_that_is_not_letters_and_digits_is_refused(load, bad):
    with pytest.raises(SystemExit):
        load(bad)
