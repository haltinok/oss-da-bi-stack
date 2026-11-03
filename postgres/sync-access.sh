#!/usr/bin/env bash
# Create the access schema, its tables and logins on a postgres that already exists (the init scripts in postgres/init only run on a fresh volume).
# Idempotent. Reads .env (ADMIN_DB_PASSWORD, AUTH_PG_PASSWORD).
#
#   postgres/sync-access.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
: "${ADMIN_DB_PASSWORD:?set ADMIN_DB_PASSWORD in .env (openssl rand -hex 16)}"
: "${AUTH_PG_PASSWORD:?set AUTH_PG_PASSWORD in .env (openssl rand -hex 16)}"
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d postgres -f /docker-entrypoint-initdb.d/04_access_schema.sql >/dev/null
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d postgres -f /docker-entrypoint-initdb.d/08_access_defaults.sql >/dev/null          # the starter datasets (once)
docker compose exec -T -e ADMIN_DB_PASSWORD -e AUTH_PG_PASSWORD -e POSTGRES_USER=postgres -e POSTGRES_DB=postgres postgres bash /docker-entrypoint-initdb.d/05_access_users.sh
echo "the access schema and its logins are in place"
