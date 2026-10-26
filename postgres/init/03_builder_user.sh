#!/usr/bin/env bash
# The dashboard builder's database login. Least privilege: it can read and write the two builder tables and nothing else in the database.
# Idempotent (postgres/sync-builder.sh runs it on a volume that exists). Skipped when BUILDER_DB_PASSWORD is empty: the builder then runs without saving.
set -euo pipefail

if [ -z "${BUILDER_DB_PASSWORD:-}" ]; then
    echo "03_builder_user: BUILDER_DB_PASSWORD is empty, skipping"
    exit 0
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
    \getenv pw BUILDER_DB_PASSWORD
    SELECT format('CREATE ROLE builder_app LOGIN PASSWORD %L', :'pw')
      WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'builder_app') \gexec
    SELECT format('ALTER ROLE builder_app PASSWORD %L', :'pw') \gexec

    GRANT USAGE ON SCHEMA builder TO builder_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON builder.saved_dashboards, builder.saved_versions TO builder_app;
    REVOKE ALL ON SCHEMA builder FROM PUBLIC;
EOSQL
echo "03_builder_user: builder_app is in place"
