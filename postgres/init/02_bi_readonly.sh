#!/usr/bin/env bash
# Read-only role for the BI tools (Superset/Metabase).
#
# They only read the `mart` schema, so they should not connect as the postgres
# superuser. Split out of SQL because Postgres init SQL cannot read
# BI_READONLY_PASSWORD from the environment; this script can.
set -euo pipefail

: "${BI_READONLY_PASSWORD:?BI_READONLY_PASSWORD must be set (see .env.example)}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    CREATE ROLE bi_ro WITH LOGIN PASSWORD '${BI_READONLY_PASSWORD}';
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname analytics <<-EOSQL
    GRANT CONNECT ON DATABASE analytics TO bi_ro;
    GRANT USAGE ON SCHEMA mart TO bi_ro;
    GRANT SELECT ON ALL TABLES IN SCHEMA mart TO bi_ro;
    -- dbt recreates the mart tables on every build, so cover future ones too.
    ALTER DEFAULT PRIVILEGES IN SCHEMA mart GRANT SELECT ON TABLES TO bi_ro;
EOSQL
