# Open-Source Data & Analytics Stack

An end-to-end ELT/CDC demo stack orchestrated by Airflow, built from open-source tools:

- **SQL Server** (`AdventureWorks2016`) → (dlt) → Postgres `analytics.raw` → (dbt-core) → `stage` → `mart` → (Superset)
- **Postgres CDC source** (`postgres_active`) → (Debezium) → Kafka topic → **ClickHouse** (real-time OLAP) → (Superset)
- **Postgres CDC source** (`postgres_active`) → (dlt, incremental + merge) → Postgres `analytics.raw`, kept fresh by an Airflow data simulator

## Stack

| Layer                | Tool                              |
|----------------------|-----------------------------------|
| Orchestration        | Airflow 3.3.1 (LocalExecutor)     |
| Ingestion / CDC      | dlt                               |
| Streaming / CDC      | Kafka (KRaft) + Kafka Connect + Debezium |
| Transformation       | dbt-core                          |
| Warehouse            | Postgres 16                       |
| Real-time OLAP       | ClickHouse 25.8                   |
| Reporting/dashboarding | Superset + Metabase        |
| Kafka UI             | provectuslabs/kafka-ui            |
| Data simulation      | Faker (Python)                    |
| Change-data-capture source | Postgres 16 (`wal_level=logical`) |

## Databases & containers

Two Postgres containers:

**`postgres`** (host port `5433`) — the warehouse/metadata instance, four databases:
- `airflow` — Airflow's own metadata (implementation detail)
- `superset_meta` — Superset's own metadata (dashboards, charts, users)
- `metabase_meta` — Metabase's own metadata (questions, dashboards, users)
- `analytics` — the warehouse, with three schemas:
  - `raw` — dlt lands data here (AdventureWorks tables + `orders`)
  - `stage` — dbt staging views
  - `mart` — dbt mart tables (dims/facts), what Superset reads

**`postgres_active`** (host port `5434`) — a "live" OLTP source, configured for Debezium logical replication:
- database `active_db`, table `public.orders`
- `wal_level=logical`, `max_replication_slots=10`, `max_wal_senders=10`
- dedicated `debezium` replication user + `dbz_publication` publication (built-in `pgoutput` plugin)

**`clickhouse`** (ports `8123` HTTP / `9000` native) — real-time OLAP landing zone for the CDC stream:
- database `cdc`, table `cdc.orders` (MergeTree, full CDC history per `(id, ts_ms)`, 90-day TTL)
- consumed from Kafka via a Kafka-engine table + materialized view (`clickhouse/init/01_init.sql`)
- `cdc.orders_latest` (ReplacingMergeTree) keeps one row per order, fed by a cascading
  materialized view; `cdc.orders_current` / `cdc.orders_active` read it with `FINAL`
- user `clickhouse`, password from `CLICKHOUSE_PASSWORD` in `.env` (the image creates
  the user; there is no committed `users.xml`)

Two BI tools read the same data:
- **Superset** — OSS, ClickHouse + Postgres, and a built-in MCP server for agent access.
- **Metabase** — friendlier self-service UX; metadata in `metabase_meta`, ClickHouse
  driver bundled in the image (promoted to core in Metabase 54).

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

The Debezium connector (`orders-connector`) is registered automatically by the
`debezium-register` Compose service (script `debezium-connect/register_connector.py`,
config `debezium-connect/orders-connector.json`), so no manual `curl` is needed. The
connector's DB password is taken from `DEBEZIUM_PASSWORD` in `.env` (the JSON holds a
`${DEBEZIUM_PASSWORD}` reference, expanded at registration time). Topic name follows
Debezium's convention: `<topic.prefix>.<schema>.<table>` = `active_db.public.orders`.
Event op codes: `r` (snapshot read), `c` (insert), `u` (update), `d` (delete).
Soft-deletes appear as `u` events with `deleted_at` set.

## Pipelines

| Pipeline | Direction | Strategy | DAG / schedule |
|----------|-----------|----------|----------------|
| `sqlserver_to_postgres` | SQL Server `AdventureWorks2016` (all 71 tables) → `analytics.raw` | full refresh (`replace`), loaded **once** (static source) | `sqlserver_to_postgres_elt` / manual |
| `postgres_active_to_postgres` | `postgres_active.active_db.orders` → `analytics.raw.orders` | incremental on `updated_at` + `merge` (upsert by `id`) | `postgres_active_to_postgres` / every 15 min |
| `simulate_orders` | mutates `orders` (insert/update/soft-delete) with Faker | — | `simulate_orders` / every 5 min |

The AdventureWorks source is a static demo database, so `sqlserver_to_postgres_elt` is
not scheduled: trigger it once from the UI and the dlt step skips itself on later runs
(pass `--force` to reload).

The `simulate_orders` DAG generates a steady stream of changes in `active_db.orders`.
Two consumers replicate it in parallel: the `postgres_active_to_postgres` dlt pipeline
(→ warehouse) and the Debezium connector (→ Kafka topic).

## Folder structure

```
oss-data-stack/
├── docker-compose.yml
├── .env.example              # required secrets; copy to .env or use the generator
├── scripts/
│   └── generate-env.sh       # writes .env with strong random secrets
├── .pre-commit-config.yaml   # gitleaks + private-key detection
├── SECURITY.md               # credential-rotation + history-purge checklist
├── docs/
│   ├── superset-dashboard.png
│   └── superset-dashboard.pdf
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
│       │       ├── config.toml           # non-secret settings
│       │       └── secrets.toml.example  # copy to secrets.toml (git-ignored)
│       └── postgres_active_to_postgres/
│           ├── orders_pipeline.py
│           └── .dlt/
│               ├── config.toml
│               └── secrets.toml.example
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
│           ├── intermediate/
│           │   └── int_sales_order_lines.sql  # shared fact logic (ephemeral)
│           └── marts/
│               ├── dim_*.sql
│               └── fact_*.sql
├── postgres/
│   └── init/
│       └── 01_init.sql       # airflow + superset_meta + analytics databases
├── postgres_active/
│   └── init/
│       ├── 00_debezium_user.sh  # replication user from DEBEZIUM_PASSWORD
│       └── 01_init.sql          # orders table + trigger + publication + grants
├── debezium-connect/
│   ├── Dockerfile            # cp-kafka-connect + debezium-connector-postgresql
│   ├── orders-connector.json # connector config (password via ${DEBEZIUM_PASSWORD})
│   └── register_connector.py # idempotent PUT to the Connect REST API
├── clickhouse/
│   └── init/
│       └── 01_init.sql       # Kafka engine + history + current-state + rejected views
└── superset/
    ├── Dockerfile            # apache/superset + psycopg2 + clickhouse-connect + language packs
    ├── superset_config.py    # metadata in superset_meta, Turkish default locale
    └── compile_translations.py
```

## Setup

1. **Create `.env` with real secrets:**
   ```bash
   ./scripts/generate-env.sh
   ```
   This writes strong random values for the Postgres, Debezium, ClickHouse and
   Airflow/Superset secrets (mode `0600`). If you prefer to do it by hand, copy
   `.env.example` to `.env` and fill in every `REPLACE_ME` / empty value —
   Compose refuses to start with any of them unset.

   Then copy `dlt/pipelines/*/.dlt/secrets.toml.example` to `secrets.toml`
   (git-ignored) and fill in the real SQL Server host/login/password. The
   Postgres password is not stored there: both dlt pipelines read it from
   `POSTGRES_PASSWORD` in `.env`.

2. **Bring the stack up:**
   ```bash
   docker compose up -d --build
   ```
   First run builds images and runs `airflow-init` / `superset-init`.

   Every published host port is overridable from `.env` (see `.env.example`),
   so this stack can run next to another one on the same machine:

   ```bash
   # e.g. if 5434 and 8080 are already taken by another stack
   POSTGRES_ACTIVE_PORT=5444 AIRFLOW_PORT=8090 docker compose up -d --build
   ```

3. **Access:**
   - Airflow UI: http://localhost:8080 (user/pass from `.env`)
   - Superset UI: http://localhost:8089 (user/pass from `.env`)
   - Superset MCP server: http://localhost:5008 (dev-only, unauthenticated)
   - Metabase UI: http://localhost:3001 (create the admin on first visit)
   - Kafka UI: http://localhost:8081
   - Kafka Connect REST: http://localhost:8083
   - ClickHouse HTTP: http://localhost:8123 (user `clickhouse`, password from `.env`)
   - Warehouse Postgres: `localhost:5433`, db `analytics`, user `postgres`, password from `.env`
   - CDC source Postgres: `localhost:5434`, db `active_db`, user `postgres` / Debezium user `debezium`, passwords from `.env`

4. **In Superset and Metabase**, add database connections.

   Superset:
   - `postgresql+psycopg2://postgres:<POSTGRES_PASSWORD>@postgres:5432/analytics` (use the Docker service name `postgres`, not `localhost`) — charts/dashboards against the `mart` schema
   - `clickhousedb+connect://clickhouse:<CLICKHOUSE_PASSWORD>@clickhouse:8123/cdc` — real-time CDC data (`cdc.orders_active` is the dashboard-ready current state)

   Metabase (create the admin on first visit, then **Add a database**):
   - PostgreSQL: host `postgres`, port `5432`, db `analytics`, user `postgres`, password from `.env`, schema `mart`
   - ClickHouse: host `clickhouse`, port `8123`, db `cdc`, user `clickhouse`, password from `.env` — dashboard `cdc.orders_active` for current state

5. **Run the DAGs:**
   - Unpause `postgres_active_to_postgres` and `simulate_orders` (they run on a schedule).
   - Trigger `sqlserver_to_postgres_elt` **once**; it is unscheduled because the SQL Server source is static, and the dlt step skips itself on later runs.

6. **Debezium registration is automatic.** The `debezium-register` Compose service
   PUTs `debezium-connect/orders-connector.json` to the Connect REST API after
   `kafka-connect` is healthy, so there is no manual step. Re-running
   `docker compose up` updates the connector in place (idempotent `PUT`, no second
   snapshot). Watch CDC events in the `active_db.public.orders` topic via Kafka UI.

   To inspect the connector manually:
   ```bash
   curl -s http://localhost:8083/connectors/orders-connector/status
   ```

## Notes

- **CDC source config**: `postgres_active` runs `wal_level=logical` so Debezium can use the built-in `pgoutput` plugin. No external extensions (`wal2json`/`decoderbufs`) are required.
- **Debezium decimals**: the connector uses `decimal.handling.mode=string`, so DECIMAL columns arrive as plain strings in Kafka (e.g. `"1234.56"`). ClickHouse's materialized view casts them back to `Decimal(12,2)`.
- **Kafka is single-node KRaft** (broker+controller combined), no ZooKeeper — the current Confluent recommendation for new deployments.
- **ClickHouse ingestion**: the Kafka-engine table consumes the Debezium topic as `JSONAsString`; the materialized view parses the envelope with `JSONExtract*` and `parseDateTime64BestEffortOrNull` (the `OrNull` variant is important — `parseDateTime64BestEffort('')` throws instead of returning NULL for JSON-null `deleted_at`). ClickHouse must be **25.x** — 24.8's bundled librdkafka doesn't support the Kafka 4.0 protocol ("Required feature not supported by broker").
- **ClickHouse current state**: `cdc.orders` keeps full history (90-day TTL). A cascading materialized view feeds `cdc.orders_latest` (`ReplacingMergeTree(ts_ms)`, one row per `id`), and `cdc.orders_current` / `cdc.orders_active` read that with `FINAL`. This replaced a view that ran `row_number()` over the entire history on every query.
- **Incremental + merge**: `postgres_active_to_postgres` uses `dlt.sources.incremental("updated_at")` with `write_disposition="merge"`, keyed on the reflected primary key `id`. It only fetches rows changed since the last run and upserts them, so `raw.orders` mirrors the current source state (soft-deleted rows remain, flagged by `deleted_at`).
- **Airflow 3** runs four services (api-server, scheduler, dag-processor, triggerer). FAB auth manager is enabled to keep env-var admin-user provisioning.
- **dlt normalize race**: `[normalize] workers = 1` is set in each pipeline's `.dlt/config.toml` to avoid a process-pool race condition observed when loading many small tables.
- **Superset metadata** lives in Postgres (`superset_meta`); the image compiles the shipped `.po` translation sources into `messages.json` at build time so language packs work.
- **One-time SQL Server load**: `sqlserver_to_postgres` treats AdventureWorks2016 as a static source. `sqlserver_pipeline.py` checks for a load marker (`raw.customer`) and skips when present; `--force` reloads. The DAG is therefore unscheduled.
- **Secrets come from `.env`**: Compose requires each secret (`${VAR:?}`) and fails fast rather than falling back to a placeholder. `scripts/generate-env.sh` creates them. The Debezium connector and ClickHouse user read their passwords from the same file, so nothing sensitive lives in a tracked file.
- **Metabase**: metadata lives in the shared Postgres (`metabase_meta`). The ClickHouse driver is bundled in the image (core since Metabase 54), so no plugin or custom image is needed. `MB_ENCRYPTION_SECRET_KEY` must be 16/24/32 characters (the generator emits 32) and must not change after first start, or stored DB credentials can no longer be decrypted. English locale on purpose.
- **Pinned versions**: base images are pinned (`apache/superset:6.1.0`, `metabase/metabase:v0.63.18`, `provectuslabs/kafka-ui:v0.7.2`, `clickhouse/clickhouse-server:25.8`, `postgres:16`, Confluent 8.0.7), as are the Airflow requirements. Bump and rebuild deliberately.
- **Pre-commit**: `.pre-commit-config.yaml` runs gitleaks and private-key detection; run `pre-commit install` once after cloning.
