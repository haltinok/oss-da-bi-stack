# The "distributor" example model

A second Cube model, deliberately **not** AdventureWorks and not a sales demo in the same shape: a Turkish SME that sells to dealers (bayi) and collects payments (tahsilat).
It exists to prove that the app (renderer, designer, builder, dashspec, lab, admin, auth) knows no model: see [`PLAN-decouple.md`](../../PLAN-decouple.md).

| | |
|---|---|
| Facts | `orders` (order lines), `payments` |
| Dimensions | `dealers`, `items`, `calendar`, `maturity_dates` (the calendar again, in the role of a due date) |
| Text field with `sort_by` | `calendar.month_name` (sorts by the month number) |
| No | channels, fiscal year, territories |
| Database | **Postgres**, schema `dist`: `postgres/10_init.sql` (deterministic, 6,000 order lines and 2,500 payments, 2024-01 to 2026-03) |

```bash
scripts/dashspec validate --model models/distributor/cube models/distributor/dashboards/*.yml
```

Load the data: `psql -f models/distributor/postgres/10_init.sql`, or mount the file into `/docker-entrypoint-initdb.d/` of a Postgres container.

## Run the whole app on it
`docker-compose.distributor.yml` points the same services (Keycloak, the auth service, Cube on Postgres, the dashboard pages, the builder, the SQL lab and the admin console) at this model; nothing else (no StarRocks, Kafka, Airflow, dbt) is needed. Add `DISTRIBUTOR_DB_PASSWORD` to `.env` (`openssl rand -hex 16`; `scripts/generate-env.sh` writes it for a new `.env`), then:

```bash
docker compose -p distributor -f docker-compose.yml -f docker-compose.distributor.yml --profile distributor up -d --build \
  postgres distributor-db cubestore cubestore-worker keycloak auth cube dashboard-cube builder lab admin
scripts/distributor-smoke.sh        # signs in as admin and checks the model end to end
```

Open http://localhost:8250 and sign in as `admin` (`TEST_USER_PASSWORD` in `.env`). Use the `-p distributor` project name (the access database is seeded on its first start with this model's row-level dimension, `access.sql`, generated from `rls_dimensions.json` by `python3 scripts/rls_dimensions_sql.py --model models/distributor`), and stop the AdventureWorks stack first or move this one's ports (every published port is a variable in `.env`).
CI runs the same thing (job `distributor-stack`).
