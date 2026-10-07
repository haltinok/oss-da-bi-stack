"""Postgres credentials shared by the dlt pipelines in this directory.

Non-secret connection settings (driver, host, port, database, user) live in each
pipeline's `.dlt/config.toml`. The password is the stack's `POSTGRES_PASSWORD`
from `.env`, applied here explicitly (dlt gives `secrets.toml` a higher priority
than environment variables, so an env-var override is not possible through
configuration alone).

dlt 1.30 requires credentials to resolve from a secrets provider, so each
pipeline's `.dlt/secrets.toml` carries the `credentials` *password* sections as
placeholders (see the committed `secrets.toml.example`); their presence shadows
the config.toml sections, and the values are never used for the connection.

The pipelines run as scripts (``cd <pipeline dir> && python <pipeline>.py``), so
each one puts this directory on ``sys.path`` before importing the module.
"""

from __future__ import annotations

import os

import dlt

DESTINATION_PATH = "destination.postgres.credentials"
SOURCE_PATH = "sources.sql_database.credentials"
_KEYS = ("drivername", "host", "port", "database", "username")


def _lookup(key: str):
    value = dlt.config.get(key)
    return value if value is not None else dlt.secrets.get(key)


def postgres_credentials(path: str) -> dict:
    """Credentials under `path`, with `.env`'s POSTGRES_PASSWORD applied."""
    credentials: dict = {}
    for key in _KEYS:
        value = _lookup(f"{path}.{key}")
        if value is not None:
            credentials[key] = value
    password = os.environ.get("POSTGRES_PASSWORD") or dlt.secrets.get(f"{path}.password")
    if not password:
        raise SystemExit(
            f"No Postgres password for {path}: set POSTGRES_PASSWORD (see .env.example)."
        )
    credentials["password"] = password
    return credentials


def destination_credentials() -> dict:
    """The warehouse (`analytics`) Postgres."""
    return postgres_credentials(DESTINATION_PATH)


def source_credentials() -> dict:
    """The `postgres_active` OLTP source."""
    return postgres_credentials(SOURCE_PATH)
