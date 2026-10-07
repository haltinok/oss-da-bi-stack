"""Postgres credentials shared by the dlt pipelines in this directory.

Non-secret connection settings (driver, host, port, database, user) live in each
pipeline's `.dlt/config.toml` under `[stack.warehouse]` / `[stack.postgres_active]`.
They are deliberately not under dlt's own `...credentials` paths: dlt (1.30+)
rejects a `credentials` section in config.toml as a secret in a non-secret
provider, even when the pipeline passes credentials explicitly. Override them
with env vars such as `STACK__WAREHOUSE__HOST`.

The password is the stack's `POSTGRES_PASSWORD` from `.env`, applied here
explicitly, so the Postgres->Postgres pipelines need no `secrets.toml`. A
`password` under the same section in `secrets.toml` is only a fallback for
running a pipeline outside the stack.

The pipelines run as scripts (``cd <pipeline dir> && python <pipeline>.py``), so
each one puts this directory on ``sys.path`` before importing the module.
"""

from __future__ import annotations

import os

import dlt

DESTINATION_PATH = "stack.warehouse"
SOURCE_PATH = "stack.postgres_active"
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
