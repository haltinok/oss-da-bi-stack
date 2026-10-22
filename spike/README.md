# Spike: StarRocks + Cube + row-level security behind the AdventureWorks dashboard

Plan: [`../starrocks-cube-spike.md`](../starrocks-cube-spike.md). Findings and go/no-go: [`results.md`](results.md).

```
SQL Server -> ingestr (merge) -> StarRocks raw -> dbt-starrocks (star schema)
           -> Cube (+ Cube Store rollups, RLS) -> existing HTML/JS dashboard, behind Keycloak
```

## Run it
```bash
cp .env.spike.example .env.spike     # fill in (openssl rand -hex 16); MSSQL_* for Phase 1
docker compose -f docker-compose.spike.yml --env-file .env.spike up -d --build   # Phase 0 + 5 + 6 services
spike/ingest/run.sh                                                              # Phase 1: SQL Server -> raw
uv run --with pymysql python -I spike/scale/build.py                            # Phase 2: scale_10m/100m/500m
cd spike/dbt && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
. .venv/bin/activate
dbt seed --profiles-dir . --vars '{aw_source_schema: scale_500m, apply_ro_grants: false}'
../starrocks/grants.sh                                                           # read-only users
dbt run  --profiles-dir . --vars '{aw_source_schema: scale_500m}' --full-refresh --threads 1   # Phase 3
dbt test --profiles-dir . --vars '{aw_source_schema: scale_500m}' --threads 1
```
Then open http://localhost:8250 (users `admin`, `na_manager`, `de_rep`; password = `TEST_USER_PASSWORD`).
Cube builds its rollups in the background on first start (about 2 h at 500M, on this machine).

## Tests
| What | Command |
|---|---|
| Cube == direct SQL (totals, margin, drill-across) | `uv run --with pymysql --with pyjwt python -I spike/cube/check.py` |
| Which rollup serves which dashboard query | `uv run --with pyjwt python -I spike/cube/probe.py` |
| RLS + auth (29 tests) | `uv run --with pytest --with requests --with pymysql --with pyjwt python -I -m pytest spike/cube/tests -v` |
| Dashboard in a real browser, per role | `uv run --with playwright python -I spike/dashboard/e2e.py` |
| Progressive rendering + cancel on filter change | `uv run --with playwright python -I spike/dashboard/progressive.py na_manager "Mountain Bikes"` |
| Latency per dashboard query, rollup vs direct | `uv run --with pyjwt --with requests python -I spike/bench/bench.py --label 500m` |
| Concurrent users with RLS | `uv run --with pyjwt --with requests python -I spike/bench/load.py --label 500m --users 1,10,25` |
(all after `set -a; . ./.env.spike; set +a`)

## Layout
| Path | |
|---|---|
| `docker-compose.spike.yml` | StarRocks, Cube + Cube Store, Keycloak, auth service, dashboard (nginx) |
| `spike/ingest/` | ingestr runner, table list, delete reconciliation, source mutator (spike copies only) |
| `spike/scale/` | builds the 10M / 100M / 500M-line schemas inside StarRocks |
| `spike/dbt/` | StarRocks port of the star schema, tests, `dim_user_territory` seed |
| `spike/cube/` | Cube model (`model/`), `cube.js` (dialect, auth, RLS), check/probe/tests |
| `spike/keycloak/` | realm import (users, roles, `dashboard` client) |
| `spike/auth/` | FastAPI: Keycloak token in, 15-minute Cube JWT out |
| `spike/dashboard/` | nginx config + Cube data source injected into the unchanged dashboard, browser e2e |
| `spike/bench/` | latency and load benchmarks, per-scale Cube launcher |

## Security notes
- Secrets live only in `.env.spike` (gitignored). Test-user passwords are injected into the Keycloak import.
- Cube and the auth service use read-only StarRocks users (`cube_ro`, `auth_ro`); dbt re-applies their grants after each run.
- Cube runs in production mode; the SQL API port (15432) is not published, since it would bypass `queryRewrite`.
- Keycloak runs in `start-dev` (H2, HTTP) and the `dashboard` client allows direct grants only so the tests can log in headlessly. Both would change for a real deployment.
