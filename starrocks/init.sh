#!/usr/bin/env bash
# One-shot StarRocks bootstrap for the `starrocks` profile (idempotent; safe to re-run).
#
#   1. register the backend by its container hostname, so Stream Load redirects go to an
#      address other containers can reach (the all-in-one image advertises 127.0.0.1)
#   2. create the databases the pipeline uses
#   3. create the read-only users for Cube (mart) and the auth service (rls) with wildcard grants,
#      which persist when dbt drops and recreates tables
#   4. global settings the 500M spike needed: long query timeout, spill to disk
#
# Env: STARROCKS_FE, CUBE_DB_PASSWORD, AUTH_DB_PASSWORD, ACTIONS_SR_PASSWORD
set -euo pipefail
fe=${STARROCKS_FE:-starrocks-fe}
sr() { mysql -h"$fe" -P9030 -uroot --connect-timeout=5 "$@"; }

until sr -e "select 1" >/dev/null 2>&1; do echo "waiting for the frontend..."; sleep 3; done

if [ "$(sr -N -e 'show backends' | wc -l)" -eq 0 ]; then
  sr -e "ALTER SYSTEM ADD BACKEND \"starrocks-be:9050\""
fi
until [ "$(sr -N -e 'show backends' | awk -F'\t' '{print $9}' | head -1)" = "true" ]; do echo "waiting for the backend..."; sleep 3; done

sr <<SQL
CREATE DATABASE IF NOT EXISTS raw;
CREATE DATABASE IF NOT EXISTS stage;
CREATE DATABASE IF NOT EXISTS mart;
CREATE DATABASE IF NOT EXISTS rls;
CREATE DATABASE IF NOT EXISTS adventureworks_dwh;
CREATE USER IF NOT EXISTS 'cube_ro'@'%' IDENTIFIED BY '${CUBE_DB_PASSWORD}';
CREATE USER IF NOT EXISTS 'auth_ro'@'%' IDENTIFIED BY '${AUTH_DB_PASSWORD}';
CREATE USER IF NOT EXISTS 'actions_ro'@'%' IDENTIFIED BY '${ACTIONS_SR_PASSWORD}';
-- Wildcard (ALL TABLES IN DATABASE) grants are kept when dbt drops and recreates a table;
-- table-level grants are not. Cube reads the whole mart; the auth service only the rls schema.
GRANT SELECT ON ALL TABLES IN DATABASE mart TO USER 'cube_ro'@'%';
GRANT SELECT ON ALL VIEWS IN DATABASE mart TO USER 'cube_ro'@'%';
GRANT SELECT ON ALL TABLES IN DATABASE rls TO USER 'auth_ro'@'%';
-- The actions service checks a request against the current mart.inventory_health row.
GRANT SELECT ON ALL TABLES IN DATABASE mart TO USER 'actions_ro'@'%';
SET GLOBAL query_timeout = 7200;
SET GLOBAL enable_spill = true;
SET GLOBAL spill_mode = 'auto';
SQL
echo "starrocks ready"
