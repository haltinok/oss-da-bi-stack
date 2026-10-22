#!/usr/bin/env bash
# SQL Server -> StarRocks (raw schema) via ingestr, one run per table.
# Usage: spike/ingest/run.sh [--full-refresh] [table ...]   (default: all in tables.csv)
# Needs MSSQL_* in .env (see .env.example) and the `starrocks` compose profile up
# (docker compose --profile starrocks up -d). Appends timings to spike/ingest/timings.csv.
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; . ./.env; set +a
: "${MSSQL_HOST:?set MSSQL_HOST, MSSQL_PORT, MSSQL_DB, MSSQL_USER, MSSQL_PASSWORD in .env}"

IMAGE=${INGESTR_IMAGE:-ghcr.io/bruin-data/ingestr:latest}
# Join the compose network of the StarRocks frontend: the backend registers by hostname, so
# Stream Load redirects are reachable from here.
FE=$(docker compose --profile starrocks ps -q starrocks-fe)
NET=$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$FE")
SRC="mssql://${MSSQL_USER}:${MSSQL_PASSWORD}@${MSSQL_HOST}:${MSSQL_PORT}/${MSSQL_DB}?TrustServerCertificate=yes"
DEST="starrocks://root:@starrocks-fe:9030/raw"
TIMINGS=spike/ingest/timings.csv
[ -f "$TIMINGS" ] || echo "ts,table,strategy,seconds,status" > "$TIMINGS"

EXTRA=()
[ "${1:-}" = "--full-refresh" ] && { EXTRA+=(--full-refresh); shift; }
ONLY=("$@")

tail -n +2 spike/ingest/tables.csv | while IFS=, read -r src dest strategy pk _rows; do
  if [ ${#ONLY[@]} -gt 0 ] && [[ ! " ${ONLY[*]} " =~ " $dest " ]]; then continue; fi
  args=(--source-uri "$SRC" --source-table "$src" --dest-uri "$DEST" --dest-table "raw.$dest"
        --incremental-strategy "$strategy")
  if [ "$strategy" = merge ]; then
    args+=(--incremental-key ModifiedDate)
    IFS=';' read -ra cols <<< "$pk"
    for c in "${cols[@]}"; do args+=(--primary-key "$c"); done
  fi
  t0=$(date +%s.%N)
  if docker run --rm --network "$NET" --entrypoint ingestr "$IMAGE" ingest "${args[@]}" "${EXTRA[@]}" >/tmp/ingestr_$dest.log 2>&1; then st=ok; else st=FAIL; fi
  secs=$(printf '%.1f' "$(echo "$(date +%s.%N) - $t0" | bc)")
  echo "$(date -Is),$dest,$strategy,$secs,$st" | tee -a "$TIMINGS"
  [ "$st" = ok ] || { sed "s#${MSSQL_PASSWORD}#***#g" /tmp/ingestr_$dest.log | tail -5; }
done
