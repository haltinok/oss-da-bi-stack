#!/usr/bin/env bash
# Create the builder's schema, tables and login on a postgres that already exists (the init scripts in postgres/init only run on a fresh volume).
# Idempotent. Reads .env (BUILDER_DB_PASSWORD).
#
#   postgres/sync-builder.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
: "${BUILDER_DB_PASSWORD:?set BUILDER_DB_PASSWORD in .env (openssl rand -hex 16)}"
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d postgres -f /docker-entrypoint-initdb.d/02_builder_schema.sql >/dev/null
docker compose exec -T -e BUILDER_DB_PASSWORD -e POSTGRES_USER=postgres -e POSTGRES_DB=postgres postgres bash /docker-entrypoint-initdb.d/03_builder_user.sh
echo "the builder's saved-dashboard tables and login are in place"
