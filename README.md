# Open-Source Data & Analytics Stack

An end-to-end ELT/CDC demo stack orchestrated by Airflow, built from open-source tools:

- **SQL Server** (`AdventureWorks2016`) → (dlt) → Postgres `analytics.raw` → (dbt-core) → `stage` → `mart` → (Superset)
- **Postgres CDC source** (`postgres_active`) → (Debezium) → Kafka topic → **ClickHouse** (real-time OLAP) → (Superset)
- **Postgres CDC source** (`postgres_active`) → (dlt, incremental + merge) → Postgres `analytics.raw`, kept fresh by an Airflow data simulator
- **AdventureWorks2016 OLTP sandbox** in `postgres_active` — a ~10% sample of the AdventureWorks tables, kept live by the `simulate_adventureworks` simulator, so you can practise against a churning OLTP database without the real SQL Server

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
- database `active_db`
- `public.orders` — the small demo table mutated by `simulate_orders`
- the **AdventureWorks2016 OLTP tables** (~70 tables, schema + a 10% sample seed in
  `postgres_active/init/`), mutated by `simulate_adventureworks` — see
  [AdventureWorks OLTP sandbox](#adventureworks-oltp-sandbox)
- `wal_level=logical`, `max_replication_slots=10`, `max_wal_senders=10`,
  `max_slot_wal_keep_size=2GB` (see [Notes](#notes))
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
- **`kafka-connect`** — Debezium source connector host (`cp-kafka-connect:8.0.7` + `debezium-connector-postgresql:3.2.6`), REST on port `8083`
- **`kafka-ui`** — browse topics/events at http://localhost:8081
- **`clickhouse`** — Kafka engine + MergeTree landing zone (see `clickhouse/init/01_init.sql`)

The Debezium connector (`orders-connector`) is registered automatically by the
`debezium-register` Compose service (script `debezium-connect/register_connector.py`,
config `debezium-connect/orders-connector.json`), so no manual `curl` is needed. The
connector's DB password is `DEBEZIUM_PASSWORD` from `.env`: the JSON holds
`${env:DEBEZIUM_PASSWORD}`, which Kafka Connect's `EnvVarConfigProvider` resolves at
runtime, so the password is never stored in Connect's `_connect_configs` topic or
returned by `GET /connectors/orders-connector/config`. Topic name follows
Debezium's convention: `<topic.prefix>.<schema>.<table>` = `active_db.public.orders`.
Event op codes: `r` (snapshot read), `c` (insert), `u` (update), `d` (delete).
Soft-deletes appear as `u` events with `deleted_at` set.

### AdventureWorks CDC stream

The nine AdventureWorks tables the OLTP simulator mutates are streamed the same
way, so `simulate_adventureworks` produces a second, wider CDC feed:

```
simulate_adventureworks (Airflow, every 5 min)
        │  INSERT / UPDATE / DELETE on 9 tables
        ▼
postgres_active.active_db.public.<table>   (sales_order_header, sales_order_detail,
        │                                   product, product_inventory, work_order,
        │                                   transaction_history, product_review,
        │                                   shopping_cart_item, person)
        ▼  Debezium (same connector, extended table.include.list)
Kafka topics `active_db.public.<table>` (9)
        ▼
ClickHouse cdc.aw_kafka (ONE multi-topic Kafka engine table)
        │ cdc.aw_events_mv (JSONAsString → cdc.aw_events, the raw envelope per row)
        ├──▶ cdc.aw_events          generic history: source_table, op, ts_ms, before, after
        └──▶ typed current state:   cdc.sales_order_header_current, cdc.product_inventory_current
```

`cdc.aw_events` keeps the raw Debezium envelope per change (90-day TTL), so any
streamed table can be decoded at read time with `JSONExtract*` without new DDL —
adding a table later is one line in Debezium's `table.include.list` and in
`cdc.aw_kafka`'s `kafka_topic_list`. The two typed tables show how to go from the
generic envelope to a dashboard-ready `ReplacingMergeTree` current state,
mirroring `cdc.orders_active`.

Deletes (`product_review`, `shopping_cart_item`) arrive as `op = 'd'` with a null
`after`; the primary key is in `before` (the source tables keep the default
`REPLICA IDENTITY`, so only key columns are populated).

**Backfill.** Adding tables to a running connector streams them from that moment;
it does not snapshot existing rows. `scripts/apply-adventureworks-cdc.sh` uses
Debezium's **incremental snapshot** (via `public.debezium_signal`, created by
`postgres_active/init/04_debezium_signal.sql`) to backfill the seeded rows without
re-snapshotting `orders`. Debezium leaves its own `snapshot-window-*` rows in the
signal table; the script clears them before each run. Because the signal table is
part of the `FOR ALL TABLES` publication, Debezium also captures it — hence the
extra `active_db.public.debezium_signal` topic, which is harmless.

## ClickHouse mart (star copy)

The dbt star (`dim_*` / `fact_*`) is built in Postgres `mart`, and copied into a
ClickHouse `mart` database so the same tables can be browsed and queried in
ClickHouse (fast OLAP):

```
dbt build  →  analytics.mart (19 dim/fact tables)
                    │  scripts/sync_mart_to_clickhouse.py
                    │  CREATE OR REPLACE TABLE mart.<t> AS SELECT * FROM postgresql(...)
                    ▼
              ClickHouse mart.*
```

- **Where:** the last task of the `postgres_active_to_postgres_aw` DAG, right after `dbt build` (so a slow or retried build is never copied half-rebuilt).
- **Mechanism:** ClickHouse's built-in `postgresql()` table function — a full
  `CREATE OR REPLACE TABLE … AS SELECT` per table. No staging, no extra driver,
  and the copy always matches the latest `dbt build`.
- **Caveat:** the Postgres password travels in the query text; the sync sets
  `log_queries=0` on the session so it stays out of `system.query_log`.

## Pipelines

| Pipeline | Direction | Strategy | DAG / schedule |
|----------|-----------|----------|----------------|
| `sqlserver_to_postgres` | SQL Server `AdventureWorks2016` (all 71 tables) → `analytics.raw` | full refresh (`replace`), loaded **once** (static source) | `sqlserver_to_postgres_elt` / manual |
| `postgres_active_to_postgres` | `postgres_active.active_db.orders` → `analytics.raw.orders` | incremental on `updated_at` + `merge` (upsert by `id`) | `postgres_active_to_postgres` / every 15 min |
| `simulate_orders` | mutates `orders` (insert/update/soft-delete) with Faker | — | `simulate_orders` / every 5 min |
| `simulate_adventureworks` | mutates the AdventureWorks OLTP tables (insert/update/delete) with Faker | — | `simulate_adventureworks` / every 5 min |
| `postgres_active_to_postgres_aw` | `postgres_active` AdventureWorks tables → `analytics.raw_active` | incremental on `modified_date` + `merge` (upsert by primary key) | `postgres_active_to_postgres_aw` / every 15 min |
| `postgres_active_to_postgres_aw` → `sync_mart_to_clickhouse` | `analytics.mart` (the dbt star) → ClickHouse `mart` | full replace, via ClickHouse's `postgresql()` table function | task in `postgres_active_to_postgres_aw` / after each build |

The AdventureWorks source is a static demo database, so `sqlserver_to_postgres_elt` is
not scheduled: trigger it once from the UI and the dlt step skips itself on later runs
(pass `--force` to reload).

The DWH (`adventureworks_dwh`) reads `raw_active`, which `postgres_active_to_postgres_aw`
keeps fresh from `postgres_active`. The static `analytics.raw` SQL Server load and the
`sqlserver_to_postgres` pipeline remain available as an alternative source:
`sqlserver_to_postgres_elt` only loads `raw`, and
`dbt build --vars '{aw_source_schema: raw}'` builds the star from it. See
[AdventureWorks OLTP sandbox](#adventureworks-oltp-sandbox).

The `simulate_orders` DAG generates a steady stream of changes in `active_db.orders`.
Two consumers replicate it in parallel: the `postgres_active_to_postgres` dlt pipeline
(→ warehouse) and the Debezium connector (→ Kafka topic).

The `simulate_adventureworks` DAG is the OLTP-sandbox counterpart: it keeps the
AdventureWorks tables in `active_db` moving. Three consumers read them: the
`postgres_active_to_postgres_aw` pipeline (→ `raw_active` → the DWH → ClickHouse), and
the Debezium CDC stream (→ ClickHouse).

## AdventureWorks OLTP sandbox

`postgres_active` also carries a working copy of the AdventureWorks2016 tables, so you
have a realistic, continuously changing OLTP database to practise against — no SQL
Server required.

- **Schema** — `postgres_active/init/02_adventureworks_schema.sql`: ~70 tables with
  their AdventureWorks primary keys restored. Foreign keys are deliberately **not**
  enforced (the seed is a random sample).
- **Seed** — `postgres_active/init/03_adventureworks_seed.sql.gz`: a random 10% sample of
  every table (full copies of tables with 100 rows or fewer). The Postgres image runs it
  automatically on first start.
- **Simulation** — the `simulate_adventureworks` DAG (every 5 min) creates a sales
  order with probability `SIM_ORDER_CHANCE` (default 0.05 ≈ 14 orders/day; set 0.01
  to match the seeded ~2.7 orders/day), inserts work orders, transaction history,
  reviews and cart items; advances order statuses forward through the lifecycle
  (in process → approved → shipped, with occasional backordered / rejected /
  cancelled); updates prices, inventory and names; and deletes leaf rows — always
  bumping `modified_date`.
- **CDC** — the nine tables the simulator touches are also streamed through
  Debezium → Kafka → ClickHouse; see
  [AdventureWorks CDC stream](#adventureworks-cdc-stream).
- **Warehouse DWH** — `postgres_active_to_postgres_aw` replicates the tables into
  `analytics.raw_active`, and `adventureworks_dwh` is pointed at it, so the star
  schema is built from the live source. The seed is **referentially consistent**
  (10% of the driver tables expanded along the foreign-key graph), so the DWH's
  `relationships` tests pass.

Both init files are **generated** from the warehouse `analytics.raw` (dlt's bookkeeping
columns are dropped and the primary keys restored), so re-run the generators after a
fresh AdventureWorks load:

```bash
set -a && . ./.env && set +a
python3 scripts/gen_adventureworks_schema.py
python3 scripts/gen_adventureworks_seed.py
```

Postgres init scripts only run on the **first** start of a data volume. On a stack that
is already running, apply them in place — this does **not** touch the warehouse, Kafka or
ClickHouse volumes:

```bash
./scripts/apply-postgres-active-init.sh          # schema, then seed if empty
./scripts/apply-postgres-active-init.sh --force  # truncate and reload the sample
```

Explore it:

```bash
psql "postgresql://postgres:$POSTGRES_PASSWORD@localhost:5434/active_db" -c '\dt public.*'
```

## Folder structure

```
oss-da-bi-stack/
├── docker-compose.yml
├── .env.example              # required secrets; copy to .env or use the generator
├── scripts/
│   ├── generate-env.sh               # writes .env with strong random secrets
│   ├── gen_adventureworks_schema.py  # regenerate 02_adventureworks_schema.sql
│   ├── gen_adventureworks_seed.py    # regenerate 03_adventureworks_seed.sql.gz
│   ├── apply-postgres-active-init.sh # apply schema+seed to a running container
│   ├── apply-adventureworks-cdc.sh   # wire the AW tables into CDC on a running stack
│   ├── apply-bi-readonly.sh          # create the bi_ro role on a running stack
│   └── build_superset_dashboard.py   # build + export the AdventureWorks dashboard
├── .pre-commit-config.yaml   # gitleaks, private-key detection, ruff
├── ruff.toml
├── tests/
│   └── test_dag_integrity.py # every DAG imports cleanly (CI `dags` job)
├── SECURITY.md               # how secrets are handled, guard rails, reporting
├── skills/                   # agent skills for working with this stack
├── docs/
│   ├── superset-dashboard.png
│   ├── superset-dashboard.pdf
│   └── Metabase - Internet Sales.pdf
├── .github/
│   ├── dependabot.yml          # monthly grouped updates: actions, pip, Docker images
│   └── workflows/
│       └── ci.yml              # gitleaks, pre-commit, DAG import, seed→dlt→dbt build, compose config
├── airflow/
│   ├── Dockerfile            # apache/airflow:3.3.1 + dlt + dbt-core + pyodbc + faker
│   ├── requirements.txt
│   ├── dags/
│   │   ├── sqlserver_to_postgres_dag.py
│   │   ├── postgres_active_to_postgres_dag.py
│   │   ├── postgres_active_to_postgres_aw_dag.py
│   │   ├── simulate_orders_dag.py
│   │   └── simulate_adventureworks_dag.py
│   └── scripts/
│       ├── simulate_orders.py
│       ├── simulate_adventureworks.py
│       └── sync_mart_to_clickhouse.py
├── dlt/
│   └── pipelines/
│       ├── stack_credentials.py      # shared Postgres credentials (password from .env)
│       ├── sqlserver_to_postgres/
│       │   ├── sqlserver_pipeline.py
│       │   └── .dlt/
│       │       ├── config.toml           # non-secret settings
│       │       └── secrets.toml.example  # copy to secrets.toml (git-ignored)
│       ├── postgres_active_to_postgres/
│       │   ├── orders_pipeline.py
│       │   └── .dlt/
│       │       └── config.toml           # source + destination; no secrets file needed
│       └── postgres_active_to_postgres_aw/   # live AdventureWorks -> raw_active
│           ├── aw_pipeline.py
│           └── .dlt/
│               └── config.toml
├── dbt/
│   └── adventureworks_dwh/
│       ├── dbt_project.yml
│       ├── profiles.yml
│       ├── macros/
│       │   └── generate_schema_name.sql
│       ├── snapshots/
│       │   └── dim_product_snapshot.sql  # Type 2 product history
│       └── models/
│           ├── staging/
│           │   ├── _sources.yml      # source: analytics.raw_active (live sandbox)
│           │   └── stg_*.sql
│           ├── intermediate/
│           │   └── int_sales_order_lines.sql  # shared fact logic (ephemeral)
│           └── marts/
│               ├── dim_*.sql          # includes dim_product_history (from the snapshot)
│               └── fact_*.sql
├── postgres/
│   └── init/
│       ├── 01_init.sql           # airflow + superset_meta + analytics databases
│       └── 02_bi_readonly.sh     # read-only bi_ro role (from BI_READONLY_PASSWORD)
├── postgres_active/
│   └── init/
│       ├── 00_debezium_user.sh            # replication user from DEBEZIUM_PASSWORD
│       ├── 01_init.sql                    # orders table + trigger + publication + grants
│       ├── 02_adventureworks_schema.sql   # generated: AdventureWorks DDL + primary keys
│       ├── 03_adventureworks_seed.sql.gz  # generated: 10% sample seed (COPY)
│       └── 04_debezium_signal.sql         # incremental-snapshot signalling table
├── debezium-connect/
│   ├── Dockerfile            # cp-kafka-connect + debezium-connector-postgresql
│   ├── orders-connector.json # connector config (password via ${env:DEBEZIUM_PASSWORD})
│   └── register_connector.py # idempotent PUT to the Connect REST API
├── clickhouse/
│   ├── config.d/
│   │   └── kafka.xml         # librdkafka: 10 s topic metadata refresh (CDC topic discovery)
│   └── init/
│       ├── 01_init.sql       # orders: Kafka engine + history + current-state + rejected views
│       └── 02_adventureworks_cdc.sql  # AW: multi-topic Kafka table + aw_events + typed tables
└── superset/
    ├── Dockerfile            # apache/superset + psycopg2 + clickhouse-connect + language packs
    ├── superset_config.py    # metadata in superset_meta, default locale from SUPERSET_DEFAULT_LOCALE (tr)
    ├── set_bi_database.py    # restore the BI connection's password after import
    ├── compile_translations.py
    └── dashboards/
        └── adventureworks.zip  # exported dashboard, imported by superset-init
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

   The two Postgres→Postgres dlt pipelines need nothing else: their hosts are
   in `.dlt/config.toml` and the password is `POSTGRES_PASSWORD` from `.env`.
   Only the optional SQL Server load needs a secrets file: copy
   `dlt/pipelines/sqlserver_to_postgres/.dlt/secrets.toml.example` to
   `secrets.toml` (git-ignored) and fill in the real SQL Server host/login/password.

2. **Bring the stack up.** Services are grouped into Compose profiles, so you can
   start just the batch path or the whole demo:

   | Profile | Services |
   |---------|----------|
   | *(default / core)* | `postgres`, `postgres_active`, the Airflow services |
   | `cdc` | `kafka`, `kafka-connect`, `kafka-ui`, `debezium-register`, `clickhouse` |
   | `bi` | `superset-init`, `superset`, `superset-mcp`, `metabase`, `clickhouse` |

   ```bash
   # everything (batch + CDC + BI)
   docker compose --profile cdc --profile bi up -d --build

   # or just Postgres + Airflow
   docker compose up -d --build
   ```
   First run builds images and runs `airflow-init` / `superset-init`.

   Every published host port is overridable from `.env` (see `.env.example`),
   so this stack can run next to another one on the same machine:

   ```bash
   # e.g. if 5434 and 8080 are already taken by another stack
   POSTGRES_ACTIVE_PORT=5444 AIRFLOW_PORT=8090 docker compose --profile cdc --profile bi up -d --build
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

4. **BI connections.** `superset-init` imports the AdventureWorks dashboard and a
   read-only connection automatically, so Superset is ready to use. To add more by
   hand, connect as the read-only `bi_ro` role (it can only `SELECT` from `mart` —
   not the `postgres` superuser):

   Superset:
   - `postgresql+psycopg2://bi_ro:<BI_READONLY_PASSWORD>@postgres:5432/analytics` (use the Docker service name `postgres`, not `localhost`) — charts/dashboards against the `mart` schema
   - `clickhousedb+connect://clickhouse:<CLICKHOUSE_PASSWORD>@clickhouse:8123/cdc` — real-time CDC data (`cdc.orders_active` is the dashboard-ready current state)

   Metabase (create the admin on first visit, then **Add a database**):
   - PostgreSQL: host `postgres`, port `5432`, db `analytics`, user `bi_ro`, password from `BI_READONLY_PASSWORD`, schema `mart`
   - ClickHouse: host `clickhouse`, port `8123`, db `cdc`, user `clickhouse`, password from `.env` — dashboard `cdc.orders_active` for current state

   On a stack that is **already running**, `bi_ro` is not created automatically
   (init scripts only run on first start): run `scripts/apply-bi-readonly.sh` to
   create it (or update its password).

5. **Run the DAGs:**
   - Unpause `postgres_active_to_postgres`, `postgres_active_to_postgres_aw`,
     `simulate_orders` and `simulate_adventureworks` (they run on a schedule).
     `postgres_active_to_postgres_aw` replicates the sandbox into `raw_active`,
     runs `dbt source freshness` + `dbt build` (which includes the product
     snapshot), then copies the resulting star into ClickHouse.
   - `sqlserver_to_postgres_elt` is unscheduled: trigger it once if you want the
     static SQL Server load in `analytics.raw` (an alternative DWH source; it
     only loads, it does not run dbt).
   - The AdventureWorks tables in `postgres_active` are seeded automatically on first
     start; see [AdventureWorks OLTP sandbox](#adventureworks-oltp-sandbox) for an
     existing volume.

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
- **Replication slot WAL cap**: `max_slot_wal_keep_size=2GB` bounds the WAL the Debezium slot can pin while Connect is down or the `cdc` profile is off (the simulators keep writing). Without it the slot would retain WAL until the volume fills. A slot that falls more than 2GB behind is invalidated and the connector fails; recover by deleting the connector, dropping the slot (`select pg_drop_replication_slot('debezium')`) and registering it again under a new `name` in `orders-connector.json` (Connect keeps offsets per connector name, so only a new name re-snapshots; the ClickHouse current-state tables absorb the replayed rows). If you stop using CDC for good, drop the slot.
- **Debezium decimals**: the connector uses `decimal.handling.mode=string`, so DECIMAL columns arrive as plain strings in Kafka (e.g. `"1234.56"`). ClickHouse's materialized view casts them back to `Decimal(12,2)`.
- **AdventureWorks CDC stream**: the connector's `table.include.list` covers `orders` plus the nine simulated AdventureWorks tables. They land in `cdc.aw_events` (generic envelope) and two typed current-state tables; see [AdventureWorks CDC stream](#adventureworks-cdc-stream). Deletes carry the primary key in `before`, not `after` (the source tables keep `REPLICA IDENTITY DEFAULT`). The `public.debezium_signal` table used for incremental snapshots is also captured by Debezium (it is in the `FOR ALL TABLES` publication), producing one extra topic that is harmless. Backfill existing rows with `scripts/apply-adventureworks-cdc.sh`.
- **Kafka is single-node KRaft** (broker+controller combined), no ZooKeeper — the current Confluent recommendation for new deployments.
- **ClickHouse ingestion**: the Kafka-engine table consumes the Debezium topic as `JSONAsString`; the materialized view parses the envelope with `JSONExtract*` and `parseDateTime64BestEffortOrNull` (the `OrNull` variant is important — `parseDateTime64BestEffort('')` throws instead of returning NULL for JSON-null `deleted_at`). ClickHouse must be **25.x** — 24.8's bundled librdkafka doesn't support the Kafka 4.0 protocol ("Required feature not supported by broker"). `clickhouse/config.d/kafka.xml` lowers librdkafka's topic metadata refresh to 10 s: Debezium creates the AdventureWorks topics during its snapshot, after ClickHouse has subscribed, and with the 300 s default most of them reached `cdc.aw_events` up to 5 minutes late on a fresh stack.
- **ClickHouse current state**: `cdc.orders` keeps full history (90-day TTL). A cascading materialized view feeds `cdc.orders_latest` (`ReplacingMergeTree(ts_ms)`, one row per `id`), and `cdc.orders_current` / `cdc.orders_active` read that with `FINAL`. This replaced a view that ran `row_number()` over the entire history on every query.
- **Incremental + merge**: `postgres_active_to_postgres` uses `dlt.sources.incremental("updated_at")` with `write_disposition="merge"`, keyed on the reflected primary key `id`. It only fetches rows changed since the last run and upserts them, so `raw.orders` mirrors the current source state (soft-deleted rows remain, flagged by `deleted_at`).
- **Airflow 3** runs four services (api-server, scheduler, dag-processor, triggerer). FAB auth manager is enabled to keep env-var admin-user provisioning.
- **dlt normalize race**: `[normalize] workers = 1` is set in each pipeline's `.dlt/config.toml` to avoid a process-pool race condition observed when loading many small tables.
- **Init containers fail loudly**: `airflow-init` and `superset-init` run with `set -euo pipefail`, so a failed `airflow db migrate` / `superset db upgrade` stops the stack instead of starting services on a half-migrated schema. Only the admin-user creation (already exists on re-runs) and the dashboard import may fail.
- **Superset metadata** lives in Postgres (`superset_meta`); the image compiles the shipped `.po` translation sources into `messages.json` at build time so language packs work.
- **One-time SQL Server load**: `sqlserver_to_postgres` treats AdventureWorks2016 as a static source. `sqlserver_pipeline.py` checks for a load marker (`raw.customer`) and skips when present; `--force` reloads. The DAG is therefore unscheduled.
- **Secrets come from `.env`**: Compose requires each secret (`${VAR:?}`) and fails fast rather than falling back to a placeholder. `scripts/generate-env.sh` creates them. The Debezium connector and ClickHouse user read their passwords from the same file, so nothing sensitive lives in a tracked file.
- **Metabase**: metadata lives in the shared Postgres (`metabase_meta`). The ClickHouse driver is bundled in the image (core since Metabase 54), so no plugin or custom image is needed. `MB_ENCRYPTION_SECRET_KEY` must be 16/24/32 characters (the generator emits 32) and must not change after first start, or stored DB credentials can no longer be decrypted. English locale on purpose.
- **Pinned versions**: base images are pinned (`apache/superset:6.1.0`, `metabase/metabase:v0.63.18`, `provectuslabs/kafka-ui:v0.7.2`, `clickhouse/clickhouse-server:25.8`, `postgres:16`, Confluent 8.0.7), as are the Airflow requirements (`dlt[postgres]==1.30.0`, `dbt-core==1.11.9` + `dbt-postgres==1.11.0`, `faker`) and the Debezium connector (`debezium-connector-postgresql:3.2.6` — the newest 3.x on Confluent Hub). Bump and rebuild deliberately; Dependabot handles minor/patch bumps, majors stay manual.
- **AdventureWorks OLTP sandbox**: `postgres_active` holds a generated, seeded copy of the AdventureWorks tables (see [AdventureWorks OLTP sandbox](#adventureworks-oltp-sandbox)). The schema and seed are **generated files** — edit `scripts/gen_adventureworks_schema.py` / `scripts/gen_adventureworks_seed.py`, not the SQL. Primary keys are restored; foreign keys are not enforced, but the seed is **referentially consistent** (10% of the driver tables expanded along the FK graph), so joins resolve. `simulate_adventureworks` mutates the tables every 5 min.
- **DWH source**: `dbt/adventureworks_dwh` reads `analytics.raw_active`, fed by the `postgres_active_to_postgres_aw` dlt pipeline. The static `analytics.raw` (SQL Server load) is an alternative source. `dim_date` runs to 2040 because the simulator stamps new rows with `now()`.
- **ClickHouse mart**: the dbt star is copied into ClickHouse `mart` by `scripts/sync_mart_to_clickhouse.py` (the last task of the `postgres_active_to_postgres_aw` DAG) using ClickHouse's `postgresql()` table function. It reads the mart as the read-only `bi_ro` role, and since the password rides the query text it sets `log_queries=0` to keep it out of `system.query_log`. (dlt's ClickHouse destination works on dlt 1.30 — native port 9000, `http_port` 8123, `secure=False` — but needs `dlt[clickhouse]`, which the Airflow image doesn't install; `postgresql()` needs no extra driver.)
- **Hard deletes**: the dlt path (`raw_active`) cannot see hard deletes, so it keeps deleted `product_review` / `shopping_cart_item` rows while the Debezium/ClickHouse path records them as `op='d'`. The contrast is intentional in the demo; a production feed would add a soft-delete column (like `orders.deleted_at`) or a full refresh for those tables.
- **dlt incremental cursor**: `modified_date` is often a date at midnight, so many rows share the cursor value; dlt warns about it but `merge` on the primary key keeps the load correct.
- **Pre-commit**: `.pre-commit-config.yaml` runs gitleaks, private-key detection and `ruff check` (config in `ruff.toml`); run `pre-commit install` once after cloning.
- **Dependabot** (`.github/dependabot.yml`): monthly grouped PRs (on the 1st) for the SHA-pinned Actions, `airflow/requirements.txt` and the Docker base images (major image bumps are skipped; those need code changes). Each PR goes through CI, including the `images`, `dwh` and `cdc-smoke` jobs; merge only once they are green on the current `main`. Security fixes don't wait for the schedule (Dependabot alerts / security updates).
- **CI** (`.github/workflows/ci.yml`): besides gitleaks, pre-commit and `docker compose config`, the `dags` job imports every DAG under the Airflow version from `airflow/Dockerfile`, and the `dwh` job loads the committed `postgres_active` schema + seed into a Postgres service, runs the AW and orders dlt pipelines and then `dbt build` (all models, the snapshot and every data test).
