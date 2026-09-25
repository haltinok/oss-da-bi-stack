#!/usr/bin/env bash
# Debezium replication user. Split out of 01_init.sql because Postgres init SQL
# cannot read DEBEZIUM_PASSWORD from the environment; this script can.
#
# Least privilege: REPLICATION for the logical slot, LOGIN for the connector.
set -euo pipefail

: "${DEBEZIUM_PASSWORD:?DEBEZIUM_PASSWORD must be set (see .env.example)}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER debezium WITH REPLICATION LOGIN PASSWORD '${DEBEZIUM_PASSWORD}';
EOSQL
