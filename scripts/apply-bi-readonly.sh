#!/usr/bin/env bash
#
# Create the read-only `bi_ro` role on an ALREADY-RUNNING stack.
#
# postgres/init/02_bi_readonly.sh only runs on first start of the data volume, so
# a stack that is already up (like yours) never gets the role. This applies it in
# place, non-destructively.
#
# Usage:  scripts/apply-bi-readonly.sh
#
# Environment:
#   POSTGRES_CONTAINER  default oss_postgres
#   POSTGRES_USER       default postgres
#   .env                read for BI_READONLY_PASSWORD
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$root/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$root/.env"
    set +a
fi

: "${BI_READONLY_PASSWORD:?BI_READONLY_PASSWORD must be set (in .env)}"
container="${POSTGRES_CONTAINER:-oss_postgres}"
user="${POSTGRES_USER:-postgres}"

if ! docker inspect "$container" >/dev/null 2>&1; then
    echo "ERROR: container '$container' not found. Set POSTGRES_CONTAINER." >&2
    exit 1
fi

echo "==> ensuring role bi_ro exists with the current BI_READONLY_PASSWORD"
docker exec -i "$container" psql -U "$user" -p 5432 -d postgres -v ON_ERROR_STOP=1 -q -c \
    "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bi_ro') THEN CREATE ROLE bi_ro WITH LOGIN; END IF; END \$\$;"
# Always re-apply the password, so a changed BI_READONLY_PASSWORD takes effect on
# an existing role too.
docker exec -i "$container" psql -U "$user" -p 5432 -d postgres -v ON_ERROR_STOP=1 -q -c \
    "ALTER ROLE bi_ro WITH LOGIN PASSWORD '$BI_READONLY_PASSWORD';"

echo "==> granting read-only access to the mart schema"
docker exec -i "$container" psql -U "$user" -p 5432 -d analytics -v ON_ERROR_STOP=1 -q -c \
    "GRANT CONNECT ON DATABASE analytics TO bi_ro;
     GRANT USAGE ON SCHEMA mart TO bi_ro;
     GRANT SELECT ON ALL TABLES IN SCHEMA mart TO bi_ro;
     ALTER DEFAULT PRIVILEGES IN SCHEMA mart GRANT SELECT ON TABLES TO bi_ro;"

echo "==> done. bi_ro can SELECT from mart (and nothing else)."
