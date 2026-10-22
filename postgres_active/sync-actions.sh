#!/usr/bin/env bash
# Create the actions service's writer login and audit table on a postgres_active that already exists
# (the init script in postgres_active/init only runs on a fresh volume). Idempotent. Reads .env.
#
#   postgres_active/sync-actions.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
: "${ACTIONS_DB_PASSWORD:?set ACTIONS_DB_PASSWORD in .env}"
docker compose exec -T -e ACTIONS_DB_PASSWORD -e POSTGRES_USER=postgres -e POSTGRES_DB=active_db \
  -e PGPORT=5434 postgres_active bash /docker-entrypoint-initdb.d/05_actions_user.sh
echo "actions login and audit table are in place"
