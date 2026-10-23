# Spike: StarRocks + Cube + row-level security behind the AdventureWorks dashboard

Plan: [`../starrocks-cube-spike.md`](../starrocks-cube-spike.md). Findings and go/no-go: [`results.md`](results.md).

```
SQL Server -> ingestr (merge) -> StarRocks raw -> dbt-starrocks (star schema)
           -> Cube (+ Cube Store rollups, RLS) -> existing HTML/JS dashboard, behind Keycloak
```

## Run it
The spike used to run from its own `docker-compose.spike.yml` (a separate "spike" project with an
all-in-one StarRocks). That file is retired: the same services are the `starrocks` profile of
`docker-compose.yml` now, with a split FE/BE StarRocks. The last version of the old file is in git history
(`git show e6dd739:docker-compose.spike.yml`); a spike stack started from it keeps working on its own.

To re-run the 500M benchmark on the profile (memory is the constraint: the spike needed 40 GB):
```bash
./scripts/generate-env.sh                          # or add the secrets to .env by hand (see .env.example)
STARROCKS_MEM_LIMIT=40g docker compose --profile starrocks up -d --build
# SQL Server source (optional, Phase 1): MSSQL_HOST/PORT/DB/USER/PASSWORD in .env, then
spike/ingest/run.sh                                                              # SQL Server -> raw
STARROCKS_MYSQL_PORT=9030 uv run --with pymysql python -I spike/scale/build.py   # all tiers, largest first (STARROCKS_MYSQL_PORT as in .env)
#   --only 250m   builds one tier straight from raw (10m 83 copies, 100m 825, 250m 2060, 500m 4120; 1m = 8-copy smoke test, 25m = 206-copy development tier)
#   --supply      then scales inventory/purchase/work-order quantities by the measured sales factor (scale_meta.supply_factor)
#   load_supply_sample.py loads vendors/purchase orders/work orders from the postgres_active sample into raw first (see its docstring)
cd dbt/adventureworks_starrocks && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
. .venv/bin/activate
dbt run  --profiles-dir . --vars '{aw_source_schema: scale_500m, date_shift_years: 0}' --full-refresh --threads 1
```
For the 500M data Cube needs the model in `spike/cube/model` (time-based incremental refresh and year
partitions) instead of the live one in `cube/model`: mount it in place of `./cube/model` or use
`spike/bench/run_scale.sh`, which launches a second Cube on :4001 for a scale schema.
Everything below reads `.env` (`set -a; . ./.env; set +a`), including `STARROCKS_MYSQL_PORT`, `CUBE_URL`,
`KEYCLOAK_URL` and `AUTH_URL` where the defaults (9030, 4000, 8180, 8200) do not match.

## The 250M tier on the demo server

The full AdventureWorks base (`raw`, from SQL Server) lives on the workstation's spike StarRocks; the demo server runs
the live pipeline. This moves the base to the server and builds the 250M tier there, next to the live data and without
touching it. Nothing needs ingesting again. Steps 3-6 can run from the workstation through the tunnel; the long ones
(4 and 5) are safer on the server in `tmux`, with the same commands and `STARROCKS_MYSQL_PORT=9030` (a dropped tunnel
kills the client, not the query).

**Read this first: `raw` on the demo server is the live pipeline's schema.** The 5-minute DAG ingests postgres_active into
`raw` (same table names as the copy: `sales_order_header`, `product_inventory`, `vendor`, ...). Dropping and recreating those
tables would destroy the live data, and the next cycle would merge simulator rows into the copy. So the copy lands in
**`raw_spike`**, and `build.py` / `load_supply_sample.py` read it through `SCALE_RAW_SCHEMA=raw_spike`.
`copy_raw.py` refuses `--dst-schema raw` on a server whose `raw` holds the live pipeline's tables.

```bash
# 0. on the server: the starrocks profile is up. The build needs memory (the plan: STARROCKS_MEM_LIMIT=38g on a 48 GB box,
#    Cube and Keycloak stopped while it runs), so pause the live DAG for the duration:
#      docker compose exec airflow-scheduler airflow dags pause postgres_active_to_starrocks      (unpause at the end)
# 1. on the workstation: a tunnel to the server's StarRocks (the compose default publishes it on the server's localhost:9030;
#    use the server's STARROCKS_MYSQL_PORT if .env changed it)
ssh -N -L 19030:localhost:9030 -o ServerAliveInterval=60 demo &

# 2. copy raw (tables, then views incl. recon_deleted_*) from the spike StarRocks to the server's raw_spike; prints source vs target
#    row counts per object and exits 1 on any mismatch. Stop the spike Cube's refresh first if it is rebuilding rollups: it fills
#    the source's query memory (copy_raw.py retries a table when that happens, but waiting is quicker).
uv run --with pymysql python -I spike/scale/copy_raw.py --src 127.0.0.1:9030 --dst 127.0.0.1:19030      # --dst-schema raw_spike is the default

# 3. the supply side (vendors, purchase orders, work orders, offers) from the postgres_active sample. It reads through
#    `docker exec postgres_active`, so run it where that container is (the workstation's stack, or the server's).
export SCALE_RAW_SCHEMA=raw_spike STARROCKS_MYSQL_PORT=19030
set -a; . ./.env; set +a      # POSTGRES_ACTIVE_PORT etc.; then re-export the two lines above
uv run --with pymysql python -I spike/scale/load_supply_sample.py

# 4. the 250M tier: 2060 copies of the base, cross-joined inside the server's StarRocks (the longest step)
uv run --with pymysql python -I spike/scale/build.py --only 250m
# 5. scale inventory / purchase / work-order quantities to the tier's sales volume (scale_meta.supply_factor, ~257)
uv run --with pymysql python -I spike/scale/build.py --supply 250m

# 6. dbt on the tier: reads scale_250m, writes only the *_250m schemas (stage_250m, adventureworks_dwh_250m, mart_250m, rls_250m).
#    One thread: at this size the facts are built one at a time (~22 min each at 500M).
cd dbt/adventureworks_starrocks
DBT_SR_HOST=127.0.0.1 DBT_SR_PORT=19030 dbt build --profiles-dir . --threads 1 --full-refresh \
  --vars '{aw_source_schema: scale_250m, date_shift_years: 0, mart_suffix: _250m}'
cd ../..

# 7. on the server: a second Cube on :4001 reading mart_250m (the 500M-tuned model, year partitions, plus the inventory cubes),
#    with its own pre-aggregation schema bench_250m, so the live Cube and its rollups are untouched
spike/bench/run_scale.sh 250m
CUBE_URL=http://localhost:4001/cubejs-api/v1/load uv run --with pyjwt --with requests python -I spike/bench/bench.py --label 250m
```

### Does the live pipeline touch any of this?
No, and nothing here touches the live pipeline's objects, as long as the copy is not put in `raw`. Checked in the code:

| Live pipeline | Reads / writes | Overlap |
|---|---|---|
| `ingest_starrocks.py` (task 1 of `postgres_active_to_starrocks`) | writes `raw.<tables in _sources.yml>` and `raw.pk_sales_order_header` (`STARROCKS_RAW_DB`, default `raw`) | none with `raw_spike`, `scale_*`, `scale_meta`, `*_250m`; **identical table names in `raw` if the copy were put there** |
| `dbt build` (task 2) with `aw_source_schema: raw`, no `mart_suffix` | reads `raw`; writes `stage`, `mart`, `rls`, `adventureworks_dwh` (macro `generate_schema_name`) | none: the tier reads `scale_250m` and writes `*_250m` only |
| `grant` hooks | `GRANT ... ON mart` for `cube_ro` | `mart_250m` is granted by the tier's own dbt run, not by the live one |
| simulators, Airflow metadata | `postgres_active`, Airflow's `postgres` | none (not StarRocks) |

No DAG, ingest or simulator script, macro or compose service mentions `raw_spike`, `scale_*` or a `_250m` schema; only comments in `dbt_project.yml` document the `aw_source_schema` values (`grep -rn "scale_\|_250m\|raw_spike" airflow/dags airflow/scripts dbt/adventureworks_starrocks/macros docker-compose.yml`).
To see it for yourself, after a live cycle (every 5 minutes) the copy's counts do not move:
```sql
select table_schema, count(*) from information_schema.tables where table_schema in ('raw_spike', 'scale_250m', 'mart_250m') group by 1;
select count(*) from raw_spike.sales_order_header;      -- unchanged between cycles (the live raw.sales_order_header grows)
```
What the two do share is the backend: memory and CPU. A 250M build next to a 5-minute dbt cycle competes for the same BE, which is
why step 0 pauses the DAG; at 500M one fact build needed ~40 GB.

## Tests
| What | Command |
|---|---|
| Cube == direct SQL (totals, margin, drill-across) | `uv run --with pymysql --with pyjwt python -I spike/cube/check.py` |
| Which rollup serves which dashboard query | `uv run --with pyjwt python -I spike/cube/probe.py` |
| RLS + auth (29 tests) | `uv run --with pytest --with requests --with pymysql --with pyjwt python -I -m pytest cube/tests -v` |
| Dashboard in a real browser, per role | `uv run --with playwright python -I dashboard/cube/tests/e2e.py` |
| Progressive rendering + cancel on filter change | `uv run --with playwright python -I dashboard/cube/tests/progressive.py na_manager "Mountain Bikes"` |
| Latency per dashboard query, rollup vs direct | `uv run --with pyjwt --with requests python -I spike/bench/bench.py --label 500m` |
| Concurrent users with RLS | `uv run --with pyjwt --with requests python -I spike/bench/load.py --label 500m --users 1,10,25` |
(all after `set -a; . ./.env; set +a`)

## Layout
| Path | |
|---|---|
| `spike/ingest/` | ingestr runner, table list, delete reconciliation, source mutator (spike copies only) |
| `spike/scale/` | builds the 10M / 100M / 250M / 500M-line schemas inside StarRocks; `copy_raw.py` moves the base `raw` to another StarRocks; `load_supply_sample.py` adds the supply tables |
| `dbt/adventureworks_starrocks/` | StarRocks port of the star schema, tests, `dim_user_territory` seed |
| `spike/cube/` | the 500M-tuned Cube model (time-based incremental refresh) and the check/probe scripts; `cube.js` and the security tests are in `cube/` |
| `auth/`, `keycloak/`, `dashboard/cube/` | no longer spike-only: the auth service, the realm import and the dashboard's Cube data source (+ browser tests), shared with the `starrocks` compose profile |
| `spike/screenshots/` | evidence screenshots from the 500M run |
| `spike/bench/` | latency and load benchmarks, per-scale Cube launcher |

## Security notes
- Secrets live only in `.env` (gitignored). Test-user passwords are injected into the Keycloak import.
- Cube and the auth service use read-only StarRocks users (`cube_ro`, `auth_ro`), created with wildcard grants by `starrocks/init.sh`.
- Cube runs in production mode; the SQL API port (15432) is not published, since it would bypass `queryRewrite`.
- Keycloak runs in `start-dev` (H2, HTTP) and the `dashboard` client allows direct grants only so the tests can log in headlessly. Both would change for a real deployment.
