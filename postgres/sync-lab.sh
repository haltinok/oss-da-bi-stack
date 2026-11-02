#!/usr/bin/env bash
# Create the SQL lab's schema, tables and login on a postgres that already exists (the init scripts in postgres/init only run on a fresh volume).
# Idempotent. Reads .env (LAB_DB_PASSWORD). Run postgres/sync-builder.sh first if the builder's folders are not there yet.
#
#   postgres/sync-lab.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
: "${LAB_DB_PASSWORD:?set LAB_DB_PASSWORD in .env (openssl rand -hex 16)}"
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d postgres -f /docker-entrypoint-initdb.d/06_lab_schema.sql >/dev/null
docker compose exec -T -e LAB_DB_PASSWORD -e POSTGRES_USER=postgres -e POSTGRES_DB=postgres postgres bash /docker-entrypoint-initdb.d/07_lab_user.sh
echo "the SQL lab's saved-query tables and login are in place"
