#!/usr/bin/env bash
#
# Apply the AdventureWorks schema + seed to an ALREADY-RUNNING postgres_active
# container.
#
# Postgres init scripts only run on first start of the data volume, so an
# existing stack (like the one you are looking at) will not pick up
# 02_adventureworks_schema.sql / 03_adventureworks_seed.sql.gz on its own.
# This script applies them in place, without touching any other volume -- which
# matters because the warehouse, Kafka and ClickHouse volumes hold data that
# cannot be rebuilt (the AdventureWorks SQL Server source is not reachable).
#
# Usage:
#   scripts/apply-postgres-active-init.sh            # schema, then seed if empty
#   scripts/apply-postgres-active-init.sh --force    # truncate AW tables, reload seed
#
# Environment:
#   POSTGRES_ACTIVE_CONTAINER  container name (default: postgres_active)
#   POSTGRES_ACTIVE_PORT       in-container port (default: 5434)
#   POSTGRES_USER              superuser (default: postgres)
#   POSTGRES_DB                database (default: active_db)
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
init_dir="$root/postgres_active/init"
container="${POSTGRES_ACTIVE_CONTAINER:-postgres_active}"
port="${POSTGRES_ACTIVE_PORT:-5434}"
user="${POSTGRES_USER:-postgres}"
db="${POSTGRES_DB:-active_db}"
force=0
[ "${1:-}" = "--force" ] && force=1

psql_in() {
    docker exec -i "$container" psql -U "$user" -p "$port" -d "$db" -v ON_ERROR_STOP=1 "$@"
}

if ! docker inspect "$container" >/dev/null 2>&1; then
    echo "ERROR: container '$container' not found. Set POSTGRES_ACTIVE_CONTAINER." >&2
    exit 1
fi

echo "==> applying schema (02_adventureworks_schema.sql)"
psql_in -q -f - < "$init_dir/02_adventureworks_schema.sql"

# Has the seed already been loaded? sales_order_header is a good proxy: the
# schema step just created it, so a non-zero count means the seed ran.
seeded="$(psql_in -Atc "select count(*) from public.sales_order_header" 2>/dev/null || echo 0)"

if [ "$force" -eq 1 ]; then
    echo "==> --force: truncating existing AdventureWorks tables"
    tables="$(psql_in -Atc "select table_name from information_schema.tables where table_schema='public' and table_name <> 'orders'")"
    if [ -n "$tables" ]; then
        # shellcheck disable=SC2086
        printf '%s\n' "$tables" | sed 's/.*/truncate table public."&";/' | psql_in -q -f -
    fi
    seeded=0
fi

if [ "${seeded:-0}" != "0" ]; then
    echo "==> seed already present (${seeded} sales_order_header rows); skipping."
    echo "    Re-run with --force to truncate and reload the 10% sample."
    exit 0
fi

echo "==> loading seed (03_adventureworks_seed.sql.gz)"
gunzip -c "$init_dir/03_adventureworks_seed.sql.gz" | psql_in -q

echo "==> done. AdventureWorks OLTP tables are live in $container/$db"
