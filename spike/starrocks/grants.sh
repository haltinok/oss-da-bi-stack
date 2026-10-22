#!/usr/bin/env bash
# Read-only StarRocks users for Cube and the auth service (run after the marts exist).
#   cube_ro   SELECT on the marts (what Cube reads to answer queries and build rollups)
#   auth_ro   SELECT on the two tables the auth service needs
# Passwords come from .env.spike.
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env.spike; set +a
docker exec -i spike-starrocks-1 mysql -h127.0.0.1 -P9030 -uroot <<SQL
CREATE USER IF NOT EXISTS 'cube_ro'@'%' IDENTIFIED BY '${CUBE_DB_PASSWORD}';
CREATE USER IF NOT EXISTS 'auth_ro'@'%' IDENTIFIED BY '${AUTH_DB_PASSWORD}';
GRANT SELECT ON ALL TABLES IN DATABASE mart TO USER 'cube_ro'@'%';
GRANT SELECT ON ALL VIEWS IN DATABASE mart TO USER 'cube_ro'@'%';
GRANT SELECT ON TABLE mart.dim_user_territory TO USER 'auth_ro'@'%';
GRANT SELECT ON TABLE mart.dim_sales_territory TO USER 'auth_ro'@'%';
SQL
echo "grants applied"
