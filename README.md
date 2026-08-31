# Open-Source Data & Analytics Stack

An end-to-end ELT/CDC demo stack orchestrated by Airflow, built from open-source tools:

- **SQL Server** (`AdventureWorks2016`) → (dlt) → Postgres `analytics_2.raw` → (dbt-core) → `stage` → `mart` → (Superset)
- **Postgres CDC source** (`postgres_active`) → (Debezium) → Kafka topic → **ClickHouse** (real-time OLAP) → (Superset)
- **Postgres CDC source** (`postgres_active`) → (dlt, incremental + merge) → Postgres `analytics_2.raw`, kept fresh by an Airflow data simulator

## Stack

| Layer                | Tool                              |
|----------------------|-----------------------------------|
| Orchestration        | Airflow 3.3.1 (LocalExecutor)     |
| Ingestion / CDC      | dlt                               |
| Streaming / CDC      | Kafka (KRaft) + Kafka Connect + Debezium |
| Transformation       | dbt-core                          |
| Warehouse            | Postgres 16                       |
| Real-time OLAP       | ClickHouse 25.8                   |
| Reporting/dashboarding | Superset                         |
| Kafka UI             | provectuslabs/kafka-ui            |
| Data simulation      | Faker (Python)                    |
| Change-data-capture source | Postgres 16 (`wal_level=logical`) |

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

**`clickhouse`** (ports `8123` HTTP / `9000` native) — real-time OLAP landing zone for the CDC stream:
- database `cdc`, table `cdc.orders` (MergeTree, full history per `(id, ts_ms)`)
- consumed from Kafka via a Kafka-engine table + materialized view (`cdc/init/01_init.sql`)
- user `clickhouse` / `clickhouse` (defined in `cdc/users.d/users.xml`)

## Kafka / Debezium CDC

The CDC path streams `postgres_active.active_db.orders` changes into Kafka and then ClickHouse:

```
simulate_orders (Airflow, every 5 min)
        │  INSERT / UPDATE / soft-DELETE
        ▼
postgres_active.active_db.orders  (wal_level=logical)
        │  Debezium PostgreSQL connector (pgoutput, dbz_publication)
        ▼
Kafka topic `active_db.public.orders`
        │
        ├──▶ Kafka UI (http://localhost:8081)
        │
        └──▶ ClickHouse cdc.orders_kafka (Kafka engine)
                  │ materialized view cdc.orders_mv (JSONAsString → MergeTree)
                  ▼
              cdc.orders  → Superset (clickhousedb+connect://clickhouse:8123/cdc)
```

Containers:
- **`kafka`** — single-node broker, KRaft combined mode (`confluentinc/cp-kafka:8.0.7`)
- **`kafka-connect`** — Debezium source connector host (`cp-kafka-connect:8.0.7` + `debezium-connector-postgresql:2.5.4`), REST on port `8083`
- **`kafka-ui`** — browse topics/events at http://localhost:8081
- **`clickhouse`** — Kafka engine + MergeTree landing zone (see `clickhouse/init/01_init.sql`)

The Debezium connector (`orders-connector`) is registered via the Connect REST API from `debezium-connect/orders-connector.json`. Topic name follows Debezium's convention: `<topic.prefix>.<schema>.<table>` = `active_db.public.orders`. Event op codes: `r` (snapshot read), `c` (insert), `u` (update), `d` (delete). Soft-deletes appear as `u` events with `deleted_at` set.

## Pipelines

| Pipeline | Direction | Strategy | DAG / schedule |
|----------|-----------|----------|----------------|
| `sqlserver_to_postgres` | SQL Server `AdventureWorks2016` (all 71 tables) → `analytics_2.raw` | full refresh (`replace`) | `sqlserver_to_postgres_elt` / daily |
| `postgres_active_to_postgres` | `postgres_active.active_db.orders` → `analytics_2.raw.orders` | incremental on `updated_at` + `merge` (upsert by `id`) | `postgres_active_to_postgres` / every 15 min |
| `simulate_orders` | mutates `orders` (insert/update/soft-delete) with Faker | — | `simulate_orders` / every 5 min |

The `simulate_orders` DAG generates a steady stream of changes in `active_db.orders`.
Two consumers replicate it in parallel: the `postgres_active_to_postgres` dlt pipeline
(→ warehouse) and the Debezium connector (→ Kafka topic).

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
├── debezium-connect/
│   ├── Dockerfile            # cp-kafka-connect + debezium-connector-postgresql
│   └── orders-connector.json # Debezium connector config (POST to Connect REST)
├── clickhouse/
│   ├── init/
│   │   └── 01_init.sql       # Kafka engine + MergeTree + materialized view
│   └── users.d/
│       └── users.xml         # clickhouse user (password, network access)
└── superset/
    ├── Dockerfile            # apache/superset + psycopg2 + clickhouse-connect + language packs
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
   - Kafka UI: http://localhost:8081
   - Kafka Connect REST: http://localhost:8083
   - ClickHouse HTTP: http://localhost:8123 (user/pass `clickhouse`/`clickhouse`)
   - Warehouse Postgres: `localhost:5433`, db `analytics_2`, user/pass `postgres`/`postgres`
   - CDC source Postgres: `localhost:5434`, db `active_db`, user/pass `postgres`/`postgres` (Debezium user: `debezium`/`debezium`)

4. **In Superset**, add database connections:
   - `postgresql+psycopg2://postgres:postgres@postgres:5432/analytics_2` (use the Docker service name `postgres`, not `localhost`) — charts/dashboards against the `mart` schema
   - `clickhousedb+connect://clickhouse:clickhouse@clickhouse:8123/cdc` — real-time CDC data in `cdc.orders`

5. **Unpause the DAGs** (`sqlserver_to_postgres_elt`, `postgres_active_to_postgres`, `simulate_orders`) or trigger them manually from the Airflow UI.

6. **Register the Debezium connector** (once, after first `up`):
   ```bash
   curl -X POST http://localhost:8083/connectors \
     -H "Content-Type: application/json" \
     -d '{"name":"orders-connector","config":{...}}'
   ```
   (the full config lives in `debezium-connect/orders-connector.json`). Then watch CDC events in the `active_db.public.orders` topic via Kafka UI.

## Notes

- **CDC source config**: `postgres_active` runs `wal_level=logical` so Debezium can use the built-in `pgoutput` plugin. No external extensions (`wal2json`/`decoderbufs`) are required.
- **Debezium decimals**: the connector uses `decimal.handling.mode=string`, so DECIMAL columns arrive as plain strings in Kafka (e.g. `"1234.56"`). ClickHouse's materialized view casts them back to `Decimal(12,2)`.
- **Kafka is single-node KRaft** (broker+controller combined), no ZooKeeper — the current Confluent recommendation for new deployments.
- **ClickHouse ingestion**: the Kafka-engine table consumes the Debezium topic as `JSONAsString`; the materialized view parses the envelope with `JSONExtract*` and `parseDateTime64BestEffortOrNull` (the `OrNull` variant is important — `parseDateTime64BestEffort('')` throws instead of returning NULL for JSON-null `deleted_at`). ClickHouse must be **25.x** — 24.8's bundled librdkafka doesn't support the Kafka 4.0 protocol ("Required feature not supported by broker").
- **Incremental + merge**: `postgres_active_to_postgres` uses `dlt.sources.incremental("updated_at")` with `write_disposition="merge"`, keyed on the reflected primary key `id`. It only fetches rows changed since the last run and upserts them, so `raw.orders` mirrors the current source state (soft-deleted rows remain, flagged by `deleted_at`).
- **Airflow 3** runs four services (api-server, scheduler, dag-processor, triggerer). FAB auth manager is enabled to keep env-var admin-user provisioning.
- **dlt normalize race**: `[normalize] workers = 1` is set in each pipeline's `.dlt/config.toml` to avoid a process-pool race condition observed when loading many small tables.
- **Superset metadata** lives in Postgres (`superset_meta`); the image compiles the shipped `.po` translation sources into `messages.json` at build time so language packs work.
- Pinned versions in `airflow/requirements.txt` are reasonable as of writing — bump and rebuild if needed.
