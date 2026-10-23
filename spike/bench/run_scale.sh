#!/usr/bin/env bash
# Start a second Cube on :4001 (next to the `starrocks` profile's Cube) that reads the marts of another scale (mart_10m / mart_100m / mart_250m),
# with its own pre-aggregation schema in Cube Store, so the 500M instance and its rollups are
# untouched. Build the marts first:
#   dbt run --profiles-dir dbt/adventureworks_starrocks --project-dir dbt/adventureworks_starrocks \
#       --vars '{aw_source_schema: scale_10m, date_shift_years: 0, mart_suffix: _10m}' --full-refresh
# Usage: spike/bench/run_scale.sh 10m|100m|250m      (stop with: docker rm -f spike-cube-bench)
set -euo pipefail
cd "$(dirname "$0")/../.."
scale=${1:?scale: 10m, 100m or 250m}
set -a; . ./.env; set +a
FE=$(docker compose --profile starrocks ps -q starrocks-fe)
NET=$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$FE")

conf=spike/bench/conf-$scale
rm -rf "$conf"; mkdir -p "$conf"
cp -r spike/cube/model "$conf/model"
# the inventory cubes (Phase 1) are not in the 500M-tuned model; they are small and need no rollup
for c in inventory_health offer_performance; do cp "cube/model/cubes/$c.yml" "$conf/model/cubes/$c.yml"; done
cp cube/cube.js "$conf/cube.js"
# same model, pointed at this scale's mart schema
grep -rl 'mart\.' "$conf/model" | xargs sed -i "s/\bmart\./mart_${scale}./g"

docker compose --profile starrocks exec -T starrocks-fe mysql -h127.0.0.1 -P9030 -uroot <<SQL
GRANT SELECT ON ALL TABLES IN DATABASE mart_${scale} TO USER 'cube_ro'@'%';
SQL
docker rm -f spike-cube-bench >/dev/null 2>&1 || true
docker run -d --name spike-cube-bench --network "$NET" -p 127.0.0.1:4001:4000 \
  -v "$PWD/$conf:/cube/conf" \
  -e CUBEJS_DEV_MODE=false -e CUBEJS_API_SECRET="$CUBEJS_API_SECRET" \
  -e CUBEJS_DB_TYPE=mysql -e CUBEJS_DB_HOST=starrocks-fe -e CUBEJS_DB_PORT=9030 \
  -e CUBEJS_DB_NAME="mart_${scale}" -e CUBEJS_DB_USER=cube_ro -e CUBEJS_DB_PASS="$CUBE_DB_PASSWORD" \
  -e CUBEJS_CUBESTORE_HOST=cubestore -e CUBEJS_PRE_AGGREGATIONS_SCHEMA="bench_${scale}" \
  -e CUBEJS_REFRESH_WORKER=true -e CUBEJS_DB_QUERY_TIMEOUT=7200 \
  -e CUBEJS_CONCURRENCY="${BENCH_CONCURRENCY:-2}" -e CUBEJS_DB_MAX_POOL="${BENCH_CONCURRENCY:-2}" \
  cubejs/cube:latest >/dev/null
until curl -sf -o /dev/null localhost:4001/readyz; do sleep 2; done
echo "cube for scale $scale on http://localhost:4001 (pre-aggregations schema bench_${scale})"
