#!/usr/bin/env python3
"""Create or update the Debezium orders connector via the Kafka Connect REST API.

Kafka Connect rejects a flat config body with
`Unrecognized field "connector.class" (class CreateConnectorRequest)`, so it
requires the {"name", "config"} envelope; this script reads that envelope from
orders-connector.json.

String values in the spec may reference the environment as `${VAR}` (the
database password is written that way so the literal never lives in git); this
script expands them before calling the REST API and fails loudly if a
referenced variable is unset.

Semantics measured against Connect 8.0.7:
  PUT  /connectors/{name}/config  -> 201 when it creates, 200 when it updates,
                                     so it is idempotent on its own
  POST /connectors                -> 201 on create, 409 if it already exists
PUT is therefore used for both, which keeps re-running compose from triggering
another initial snapshot. The POST fallback only covers Connect versions whose
PUT does not create (it answers 404).

The status check is retried because it can briefly answer 404 in the moment
right after the connector is created, which previously made this script report
a failure even though registration had succeeded.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

CONNECT_URL = "http://kafka-connect:8083"
SPEC_PATH = "/connectors/orders-connector.json"
CONNECT_READY_ATTEMPTS = 60
CONNECT_READY_DELAY = 2
STATUS_ATTEMPTS = 10
STATUS_DELAY = 2

ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(value):
    """Recursively replace `${VAR}` references with environment values."""
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise SystemExit(
                    f"ERROR: connector config references ${{{name}}}, which is not set"
                )
            return os.environ[name]

        return ENV_REFERENCE.sub(replace, value)
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    return value


def request(method: str, path: str, payload: dict | None = None) -> tuple[int, str]:
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        CONNECT_URL + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def wait_for_connect() -> bool:
    print(f"waiting for Kafka Connect at {CONNECT_URL} ...", flush=True)
    for _ in range(CONNECT_READY_ATTEMPTS):
        try:
            status, _ = request("GET", "/connectors")
            if status == 200:
                return True
        except Exception:
            pass
        time.sleep(CONNECT_READY_DELAY)
    return False


def main() -> int:
    spec = json.loads(open(SPEC_PATH).read())
    name = spec["name"]
    # Accept both the canonical envelope and a flat config with a "name" key.
    raw_config = spec["config"] if "config" in spec else {
        k: v for k, v in spec.items() if k != "name"
    }
    config = expand_env(raw_config)

    if not wait_for_connect():
        print("ERROR: Kafka Connect REST API never became ready", file=sys.stderr)
        return 1

    status, body = request("PUT", f"/connectors/{name}/config", config)
    if status == 404:
        status, body = request("POST", "/connectors", {"name": name, "config": config})
    if status not in (200, 201):
        print(f"ERROR: connector registration failed (HTTP {status}): {body}", file=sys.stderr)
        return 1
    print(f"connector '{name}' {('created' if status == 201 else 'updated')} (HTTP {status})")

    # Status can lag slightly behind creation, so retry before declaring failure.
    for _ in range(STATUS_ATTEMPTS):
        status, body = request("GET", f"/connectors/{name}/status")
        if status == 200:
            status_body = json.loads(body)
            connector_state = status_body["connector"]["state"]
            task_states = [task["state"] for task in status_body.get("tasks", [])]
            if connector_state == "RUNNING" and task_states and all(
                state == "RUNNING" for state in task_states
            ):
                print(f"connector state: {connector_state}, task states: {task_states}")
                return 0
        time.sleep(STATUS_DELAY)

    print(f"ERROR: connector never reported RUNNING (last HTTP {status}): {body}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
