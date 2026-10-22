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
STARROCKS_MYSQL_PORT=9030 uv run --with pymysql python -I spike/scale/build.py   # scale_10m/100m/500m (STARROCKS_MYSQL_PORT as in .env)
cd dbt/adventureworks_starrocks && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
. .venv/bin/activate
dbt run  --profiles-dir . --vars '{aw_source_schema: scale_500m, date_shift_years: 0}' --full-refresh --threads 1
```
For the 500M data Cube needs the model in `spike/cube/model` (time-based incremental refresh and year
partitions) instead of the live one in `cube/model`: mount it in place of `./cube/model` or use
`spike/bench/run_scale.sh`, which launches a second Cube on :4001 for a scale schema.
Everything below reads `.env` (`set -a; . ./.env; set +a`), including `STARROCKS_MYSQL_PORT`, `CUBE_URL`,
`KEYCLOAK_URL` and `AUTH_URL` where the defaults (9030, 4000, 8180, 8200) do not match.

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
| `spike/scale/` | builds the 10M / 100M / 500M-line schemas inside StarRocks |
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
