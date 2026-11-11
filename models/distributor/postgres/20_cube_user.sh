#!/bin/bash
# Runs once, after 10_schema.sql, when the distributor database is first created: a read-only login for Cube (it can only SELECT on the dist schema, now and later).
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE cube_ro LOGIN PASSWORD '${CUBE_DB_PASSWORD:?set CUBE_DB_PASSWORD}';
GRANT USAGE ON SCHEMA dist TO cube_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA dist TO cube_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA dist GRANT SELECT ON TABLES TO cube_ro;
SQL
