#!/usr/bin/env bash
# The SQL lab's database login. Least privilege: it reads and writes the lab tables, and may only READ the folders the dashboards keep (builder.folders: ids, names, owners, shares), so a
# saved query can live in a folder without the lab being able to create or change one. Idempotent (postgres/sync-lab.sh runs it on a volume that exists). Skipped when LAB_DB_PASSWORD is empty:
# the lab then runs without saving.
set -euo pipefail

if [ -z "${LAB_DB_PASSWORD:-}" ] || [ "${LAB_DB_PASSWORD}" = "REPLACE_ME" ]; then
    echo "07_lab_user: LAB_DB_PASSWORD is empty, skipping"
    exit 0
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
    \getenv pw LAB_DB_PASSWORD
    SELECT format('CREATE ROLE lab_app LOGIN PASSWORD %L', :'pw')
      WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lab_app') \gexec
    SELECT format('ALTER ROLE lab_app PASSWORD %L', :'pw') \gexec

    GRANT USAGE ON SCHEMA lab TO lab_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON lab.saved_queries, lab.snapshots TO lab_app;
    REVOKE ALL ON SCHEMA lab FROM PUBLIC;
    DO $$ BEGIN
      IF to_regclass('builder.folders') IS NOT NULL THEN
        GRANT USAGE ON SCHEMA builder TO lab_app;
        GRANT SELECT ON builder.folders TO lab_app;
      END IF;
    END $$;
EOSQL
echo "07_lab_user: lab_app is in place"
