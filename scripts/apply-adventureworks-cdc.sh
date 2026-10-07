#!/usr/bin/env bash
#
# Wire the AdventureWorks tables into the CDC path on an ALREADY-RUNNING stack.
#
# Postgres and ClickHouse init scripts only run on first start of their volumes,
# so an existing stack does not pick up 04_debezium_signal.sql or
# 02_adventureworks_cdc.sql on its own. This script applies both in place and
# updates the running Debezium connector -- without touching any data volume.
#
#   1. create public.debezium_signal in postgres_active
#   2. apply clickhouse/init/02_adventureworks_cdc.sql
#   3. PUT the updated orders-connector config (adds the 9 AW tables)
#   4. trigger an incremental snapshot so existing rows are backfilled
#
# Usage:  scripts/apply-adventureworks-cdc.sh
#
# Environment:
#   POSTGRES_ACTIVE_CONTAINER  default postgres_active
#   POSTGRES_ACTIVE_PORT       default 5434
#   POSTGRES_USER / POSTGRES_DB default postgres / active_db
#   CLICKHOUSE_CONTAINER       default clickhouse
#   CONNECT_URL                default http://localhost:8083
#   .env                       read for DEBEZIUM_PASSWORD / CLICKHOUSE_PASSWORD
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f "$root/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$root/.env"
    set +a
fi

container="${POSTGRES_ACTIVE_CONTAINER:-postgres_active}"
port="${POSTGRES_ACTIVE_PORT:-5434}"
user="${POSTGRES_USER:-postgres}"
db="${POSTGRES_DB:-active_db}"
ch_container="${CLICKHOUSE_CONTAINER:-clickhouse}"
connect_url="${CONNECT_URL:-http://localhost:8083}"
spec="$root/debezium-connect/orders-connector.json"

: "${DEBEZIUM_PASSWORD:?DEBEZIUM_PASSWORD must be set (in .env)}"
: "${CLICKHOUSE_PASSWORD:?CLICKHOUSE_PASSWORD must be set (in .env)}"

# --- 1. Debezium signalling table -----------------------------------------
echo "==> creating public.debezium_signal in $container"
docker exec -i "$container" psql -U "$user" -p "$port" -d "$db" -v ON_ERROR_STOP=1 -q -f - \
    < "$root/postgres_active/init/04_debezium_signal.sql"

# --- 2. ClickHouse CDC objects --------------------------------------------
echo "==> applying AdventureWorks CDC objects in $ch_container"
docker exec -i "$ch_container" clickhouse-client --password "$CLICKHOUSE_PASSWORD" --multiquery \
    < "$root/clickhouse/init/02_adventureworks_cdc.sql"

# --- 3. Update the connector (PUT is idempotent) --------------------------
echo "==> updating Debezium connector at $connect_url"

CONNECT_URL="$connect_url" SPEC="$spec" python3 - <<'PY'
import json, os, re, sys, time, urllib.error, urllib.request

url = os.environ["CONNECT_URL"].rstrip("/")
spec = json.load(open(os.environ["SPEC"]))
name = spec["name"]

ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

def expand(value):
    if isinstance(value, str):
        def repl(match):
            key = match.group(1)
            if key not in os.environ:
                raise SystemExit(f"ERROR: connector config references ${{{key}}}, which is not set")
            return os.environ[key]
        return ENV_REFERENCE.sub(repl, value)
    if isinstance(value, dict):
        return {k: expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v) for v in value]
    return value

def request(method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url + path, data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()

config = expand(spec["config"])
status, body = request("PUT", f"/connectors/{name}/config", config)
if status not in (200, 201):
    print(f"ERROR: connector update failed (HTTP {status}): {body}", file=sys.stderr)
    sys.exit(1)
print(f"connector '{name}' {'created' if status == 201 else 'updated'} (HTTP {status})")

for _ in range(15):
    status, body = request("GET", f"/connectors/{name}/status")
    if status == 200:
        data = json.loads(body)
        states = [t["state"] for t in data.get("tasks", [])]
        if data["connector"]["state"] == "RUNNING" and states and all(s == "RUNNING" for s in states):
            print(f"connector state: RUNNING, tasks: {states}")
            sys.exit(0)
    time.sleep(2)
print(f"ERROR: connector never reported RUNNING (last HTTP {status}): {body}", file=sys.stderr)
sys.exit(1)
PY

# --- 4. Backfill existing rows via an incremental snapshot ----------------
# AdventureWorks tables only: `orders` already has its full history from the
# connector's initial snapshot, and re-snapshotting it would append duplicate
# rows to the append-only cdc.orders. Debezium wants the field named
# `data-collections` (plural) as an array of schema-qualified table names.
backfill_json="$(SPEC="$spec" python3 - <<'PY'
import json, os
spec = json.load(open(os.environ["SPEC"]))
tables = [
    t.strip()
    for t in spec["config"]["table.include.list"].split(",")
    if t.strip() and t.strip() != "public.orders"
]
print(json.dumps({"data-collections": tables}))
PY
)"

echo "==> triggering incremental snapshot for: $backfill_json"
# Debezium does not delete its own snapshot-window-open/close rows, so clear any
# left by a previous run before adding the next request.
docker exec -i "$container" psql -U "$user" -p "$port" -d "$db" -q -c \
    "delete from public.debezium_signal where type like 'snapshot-window-%';"
docker exec -i "$container" psql -U "$user" -p "$port" -d "$db" -v ON_ERROR_STOP=1 -q -c \
    "insert into public.debezium_signal (id, type, data) values (gen_random_uuid()::text, 'execute-snapshot', \$json\$${backfill_json}\$json\$);"

echo "==> done. AdventureWorks changes are streaming to Kafka/ClickHouse."
echo "    The snapshot runs in the background; watch cdc.aw_events for backfilled rows."
