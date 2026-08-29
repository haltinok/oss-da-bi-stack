# Open-Source Data & Analytics Stack

An end-to-end ELT/CDC demo stack orchestrated by Airflow, built from open-source tools:

- **SQL Server** (`AdventureWorks2016`) → (dlt) → Postgres `analytics_2.raw` → (dbt-core) → `stage` → `mart` → (Superset)
- **Postgres CDC source** (`postgres_active`) → (dlt, incremental + merge) → Postgres `analytics_2.raw`, kept fresh by an Airflow data simulator

## Stack

| Layer                | Tool                              |
|----------------------|-----------------------------------|
| Orchestration        | Airflow 3.3.1 (LocalExecutor)     |
| Ingestion / CDC      | dlt                               |
| Transformation       | dbt-core                          |
| Warehouse            | Postgres 16                       |
| Reporting/dashboarding | Superset                         |
| Data simulation      | Faker (Python)                    |
| Change-data-capture source | Postgres 16 (`wal_level=logical`, ready for Debezium) |

## Databases & containers

Two Postgres containers:

**`postgres`** (host port `5433`) — the warehouse/metadata instance, three databases:
- `airflow` — Airflow's own metadata (implementation detail)
- `superset_meta` — Superset's own metadata (dashboards, charts, users)
- `analytics_2` — the warehouse, with three schemas:
  - `raw` — dlt lands data here (AdventureWorks tables + `orders`)
  - `stage` — dbt staging views
  - `mart` — dbt mart tables (dims/facts), what Superset reads

**`postgres_active`** (host port `5434`) — a "live" OLTP source, configured for Debezium logical replication:
- database `active_db`, table `public.orders`
- `wal_level=logical`, `max_replication_slots=10`, `max_wal_senders=10`
- dedicated `debezium` replication user + `dbz_publication` publication (built-in `pgoutput` plugin)

## Pipelines

| Pipeline | Direction | Strategy | DAG / schedule |
|----------|-----------|----------|----------------|
| `sqlserver_to_postgres` | SQL Server `AdventureWorks2016` (all 71 tables) → `analytics_2.raw` | full refresh (`replace`) | `sqlserver_to_postgres_elt` / daily |
| `postgres_active_to_postgres` | `postgres_active.active_db.orders` → `analytics_2.raw.orders` | incremental on `updated_at` + `merge` (upsert by `id`) | `postgres_active_to_postgres` / every 15 min |
| `simulate_orders` | mutates `orders` (insert/update/soft-delete) with Faker | — | `simulate_orders` / every 5 min |

The `simulate_orders` DAG generates a steady stream of changes in `active_db.orders`,
which the `postgres_active_to_postgres` pipeline replicates into the warehouse, and which
a Debezium connector (not yet wired in) could capture via `dbz_publication`.

## Folder structure

```
oss-data-stack/
├── docker-compose.yml
├── .env.example              # copy to .env and fill in
├── airflow/
│   ├── Dockerfile            # apache/airflow:3.3.1 + dlt + dbt-core + pyodbc + faker
│   ├── requirements.txt
│   ├── dags/
│   │   ├── sqlserver_to_postgres_dag.py
│   │   ├── postgres_active_to_postgres_dag.py
│   │   └── simulate_orders_dag.py
│   └── scripts/
│       └── simulate_orders.py
├── dlt/
│   └── pipelines/
│       ├── sqlserver_to_postgres/
│       │   ├── sqlserver_pipeline.py
│       │   └── .dlt/
│       │       ├── config.toml       # non-secret settings
│       │       └── secrets.toml      # real creds, keep out of git
│       └── postgres_active_to_postgres/
│           ├── orders_pipeline.py
│           └── .dlt/
│               ├── config.toml
│               └── secrets.toml
├── dbt/
│   └── adventureworks_dwh/
│       ├── dbt_project.yml
│       ├── profiles.yml
│       ├── macros/
│       │   └── generate_schema_name.sql
│       └── models/
│           ├── staging/
│           │   ├── _sources.yml
│           │   └── stg_*.sql
│           └── marts/
│               ├── dim_*.sql
│               └── fact_*.sql
├── postgres/
│   └── init/
│       └── 01_init.sql       # airflow + superset_meta + analytics databases
├── postgres_active/
│   └── init/
│       └── 01_init.sql       # debezium user + orders table + publication
└── superset/
    ├── Dockerfile            # apache/superset + psycopg2 + compiled language packs
    ├── superset_config.py    # metadata in superset_meta, Turkish default locale
    └── compile_translations.py
```

## Setup

1. **Copy env template:**
   ```bash
   cp .env.example .env
   # fill in AIRFLOW_FERNET_KEY, AIRFLOW_WEBSERVER_SECRET_KEY, SUPERSET_SECRET_KEY
   ```

2. **Bring the stack up:**
   ```bash
   docker compose up -d --build
   ```
   First run builds images and runs `airflow-init` / `superset-init`.

3. **Access:**
   - Airflow UI: http://localhost:8080 (user/pass from `.env`, default admin/admin)
   - Superset UI: http://localhost:8088 (admin/admin)
   - Warehouse Postgres: `localhost:5433`, db `analytics_2`, user/pass `postgres`/`postgres`
   - CDC source Postgres: `localhost:5434`, db `active_db`, user/pass `postgres`/`postgres` (Debezium user: `debezium`/`debezium`)

4. **In Superset**, add a database connection to `postgresql+psycopg2://postgres:postgres@postgres:5432/analytics_2` (use the Docker service name `postgres`, not `localhost`) and build charts/dashboards against the `mart` schema.

5. **Unpause the DAGs** (`sqlserver_to_postgres_elt`, `postgres_active_to_postgres`, `simulate_orders`) or trigger them manually from the Airflow UI.

## Notes

- **CDC source config**: `postgres_active` runs `wal_level=logical` so Debezium can use the built-in `pgoutput` plugin. To add a connector, point it at `postgres_active:5434/active_db` with the `debezium` user and `dbz_publication` publication. No external extensions (`wal2json`/`decoderbufs`) are required.
- **Incremental + merge**: `postgres_active_to_postgres` uses `dlt.sources.incremental("updated_at")` with `write_disposition="merge"`, keyed on the reflected primary key `id`. It only fetches rows changed since the last run and upserts them, so `raw.orders` mirrors the current source state (soft-deleted rows remain, flagged by `deleted_at`).
- **Airflow 3** runs four services (api-server, scheduler, dag-processor, triggerer). FAB auth manager is enabled to keep env-var admin-user provisioning.
- **dlt normalize race**: `[normalize] workers = 1` is set in each pipeline's `.dlt/config.toml` to avoid a process-pool race condition observed when loading many small tables.
- **Superset metadata** lives in Postgres (`superset_meta`); the image compiles the shipped `.po` translation sources into `messages.json` at build time so language packs work.
- Pinned versions in `airflow/requirements.txt` are reasonable as of writing — bump and rebuild if needed.
