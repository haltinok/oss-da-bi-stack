#!/usr/bin/env bash
# Give the stack's read-only StarRocks users access to a benchmark dataset's schemas, so DATASET=<dataset> can be served:
#   cube_ro     SELECT on mart_<dataset>     (Cube reads the mart)
#   auth_ro     SELECT on rls_<dataset>      (the auth service reads the territory table)
#   actions_ro  SELECT on mart_<dataset>     (the actions service validates against inventory_health)
# Wildcard grants, so they survive dbt dropping and recreating tables. Idempotent. Run it once after the dataset's dbt build
# (a build with mart_suffix: _<dataset> makes mart_<dataset> and rls_<dataset>; the live users get nothing on them by default).
#
#   scripts/grant-dataset.sh 250m
set -euo pipefail
cd "$(dirname "$0")/.."
ds=${1:?usage: scripts/grant-dataset.sh <dataset, e.g. 250m>}
[[ "$ds" =~ ^[a-z0-9]+$ ]] || { echo "dataset must be letters and digits" >&2; exit 1; }
sr() { docker compose --profile starrocks exec -T starrocks-fe mysql -h127.0.0.1 -P9030 -uroot "$@"; }

exists() { [ -n "$(sr -N -e "show databases like '$1'")" ]; }
exists "mart_$ds" || { echo "schema mart_$ds does not exist: build the dataset first (dbt --vars '{..., mart_suffix: _$ds}')" >&2; exit 1; }
{
  echo "GRANT SELECT ON ALL TABLES IN DATABASE mart_$ds TO USER 'cube_ro'@'%';"
  echo "GRANT SELECT ON ALL VIEWS  IN DATABASE mart_$ds TO USER 'cube_ro'@'%';"
  echo "GRANT SELECT ON ALL TABLES IN DATABASE mart_$ds TO USER 'actions_ro'@'%';"
  # rls_<dataset> only matters for DATASET=<dataset> on its own; DATASET=both reads the live territories
  if exists "rls_$ds"; then echo "GRANT SELECT ON ALL TABLES IN DATABASE rls_$ds TO USER 'auth_ro'@'%';"; else echo "note: rls_$ds does not exist, auth_ro not granted (fine for DATASET=both)" >&2; fi
} | grep -v '^note' | sr
echo "granted: cube_ro + actions_ro on mart_$ds$(exists "rls_$ds" && echo ", auth_ro on rls_$ds")"
