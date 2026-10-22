---
name: oss-da-bi-stack
description: >-
  Work with the OSS data & analytics stack in this repository: the ingestr/dbt pipeline
  into StarRocks served through Cube behind Keycloak sign-in, the Debezium → Kafka →
  ClickHouse CDC path, the AdventureWorks OLTP sandbox in postgres_active, its
  simulators, and the Airflow orchestration. Use when regenerating the AdventureWorks
  sandbox, applying init scripts, running or debugging a pipeline/DAG, querying the
  StarRocks/CDC databases, or extending the stack.
---

# OSS data & analytics stack

An Airflow-orchestrated ELT/CDC demo. Read `README.md` first for the full picture;
this skill is the operator's shortcut for the common tasks.

## Architecture in one breath

- **OLTP sandbox / CDC source** `postgres_active` (`localhost:5434`, db `active_db`).
- **Serving path** (compose profile `starrocks`): `postgres_active` → ingestr (DAG
  `postgres_active_to_starrocks`, every 5 min) → StarRocks `raw` → dbt-starrocks → `mart`
  → Cube (`cube/`, rollups + row-level security) → dashboard (`localhost:8250`, Keycloak sign-in).
- **Streaming** Debezium → Kafka (`localhost:8081` UI) → ClickHouse (`localhost:8123`, db `cdc`): independent of the serving path.
- **Orchestration** Airflow (`localhost:8080`); **metadata / small warehouse** `postgres` (`localhost:5433`: `airflow`, and `analytics.raw` for the optional SQL Server load and `orders`).

The Postgres serving path (dbt-postgres mart, Superset, Metabase, `dashboard/app.py`, the ClickHouse mart
copy, MetricFlow) was retired; it is in git history. Don't look for it.

## Rules of engagement

- **Never commit secrets.** Everything sensitive is in `.env` (git-ignored). Copy
  `scripts/generate-env.sh` output; never paste values into tracked files.
- **`docker compose down -v` is destructive and forbidden here.** It wipes the
  warehouse, StarRocks and ClickHouse volumes, and the AdventureWorks SQL Server
  source is not reachable, so `analytics.raw` cannot be rebuilt. Apply schema changes in place.
- The container-internal port for `postgres_active` is **5434**, not 5432. Use
  `-p 5434` for `psql` inside that container.
- The AdventureWorks sandbox files (`postgres_active/init/02_*.sql`, `03_*.sql.gz`) are
  **generated**; edit the generator scripts, not the output.

## Common tasks

Load the env first:

```bash
set -a && . ./.env && set +a
```

**Regenerate the AdventureWorks sandbox** (from Postgres `analytics.raw`, the SQL Server load):

```bash
python3 scripts/gen_adventureworks_schema.py   # -> postgres_active/init/02_adventureworks_schema.sql
python3 scripts/gen_adventureworks_seed.py     # -> postgres_active/init/03_adventureworks_seed.sql.gz
```

**Apply it to a running stack** (Postgres init only runs on a fresh volume):

```bash
./scripts/apply-postgres-active-init.sh          # schema, then seed if empty
./scripts/apply-postgres-active-init.sh --force  # truncate and reload the sample
```

**Run a simulator** (they live in the Airflow image, which has psycopg2 + Faker):

```bash
docker exec oss_airflow_scheduler python /opt/airflow/scripts/simulate_adventureworks.py
docker exec oss_airflow_scheduler python /opt/airflow/scripts/simulate_orders.py
```

**Query the databases:**

```bash
psql "postgresql://postgres:$POSTGRES_PASSWORD@localhost:5434/active_db" -c '\dt public.*'
psql "postgresql://postgres:$POSTGRES_PASSWORD@localhost:5433/analytics" -c 'select count(*) from raw.orders'
mysql -h127.0.0.1 -P${STARROCKS_MYSQL_PORT:-9030} -uroot -e 'select count(*) from mart.fact_internet_sales'   # StarRocks
docker exec clickhouse clickhouse-client --password "$CLICKHOUSE_PASSWORD" -q 'select count() from cdc.orders'
```

**dbt** (dbt-starrocks lives in its own virtualenv in the Airflow image; project `dbt/adventureworks_starrocks`):

```bash
docker exec oss_airflow_scheduler bash -c 'cd /opt/airflow/dbt/adventureworks_starrocks && \
  /home/airflow/dbt-starrocks/bin/dbt build --project-dir . --profiles-dir . \
  --vars "{aw_source_schema: raw, use_pk_snapshots: true}"'
```

**Airflow DAGs:** `postgres_active_to_starrocks` (ingestr → `dbt build`; 5 min), `sqlserver_to_postgres_elt`
(manual, dlt load only), `postgres_active_to_postgres` (orders → Postgres `analytics.raw.orders`, 15 min),
`simulate_orders` (5 min), `simulate_adventureworks` (5 min). New DAGs start paused: unpause them.

**Wire the AdventureWorks tables into CDC** (existing stack; non-destructive):

```bash
./scripts/apply-adventureworks-cdc.sh
```

This creates `public.debezium_signal`, applies `clickhouse/init/02_adventureworks_cdc.sql`,
updates the connector, and triggers an incremental snapshot to backfill existing rows.
It never touches the warehouse/Kafka/ClickHouse volumes.

**Inspect the AdventureWorks stream:**

```bash
docker exec kafka kafka-topics --bootstrap-server kafka:9092 --list | grep active_db
docker exec clickhouse clickhouse-client --password "$CLICKHOUSE_PASSWORD" -q \
  "select source_table, count() from cdc.aw_events group by source_table"
docker exec clickhouse clickhouse-client --password "$CLICKHOUSE_PASSWORD" -q \
  "select * from cdc.sales_order_header_current order by ts_ms desc limit 5"
```

## AdventureWorks CDC stream

Nine simulator-mutated tables stream through Debezium → Kafka → ClickHouse:
`sales_order_header`, `sales_order_detail`, `product`, `product_inventory`,
`work_order`, `transaction_history`, `product_review`, `shopping_cart_item`, `person`.

- ClickHouse: one multi-topic Kafka table `cdc.aw_kafka` → generic envelope
  `cdc.aw_events` (`source_table, op, ts_ms, before, after`), plus typed
  `cdc.sales_order_header_current` / `cdc.product_inventory_current`.
- **Deletes** (`op='d'`) have a null `after`; the primary key is in `before`
  (`REPLICA IDENTITY DEFAULT`). Do not look for it in the Kafka message key.
- **Backfill** uses Debezium's incremental snapshot via `public.debezium_signal`.
  Debezium leaves `snapshot-window-*` rows behind; the apply script clears them.
  The signal table is captured too (one harmless extra topic).
- **Adding a table:** append it to Debezium's `table.include.list`, to
  `cdc.aw_kafka`'s `kafka_topic_list`, and (optionally) add a typed MV. No other
  ClickHouse DDL is needed.

## StarRocks serving path

- **Ingest by hand:** `docker exec oss_airflow_scheduler python /opt/airflow/scripts/ingest_starrocks.py [--full-refresh] [table ...]`.
  Tables come from the dbt project's sources; primary keys and the `modified_date` cursor from the source catalog.
- **Reset raw** (e.g. after re-seeding the sandbox): `drop database raw force; create database raw` in StarRocks,
  then run the ingest. ingestr's incremental state lives with the destination tables.
- **dbt drops and recreates tables each build**, and StarRocks drops table-level grants with them. Don't
  grant on tables: `starrocks/init.sh` gives `cube_ro` a wildcard grant on `mart` and `auth_ro` one on
  `rls` (whose table is `rls.user_regions`), and wildcard grants survive.
- **Cube** (`cube/`): rollups refresh when `mart.data_version` changes (rewritten every build). Rollups are
  deliberately **unpartitioned**: Cube answers from whichever partitions are built, so a partitioned
  rollup returns incomplete totals while rebuilding. Restart Cube after editing the model.
- **Row-level security** lives in `cube/cube.js` (`checkAuth`, `queryRewrite`); users and territories are
  `dbt/adventureworks_starrocks/seeds/dim_user_territory.csv`. After changing either, run the security
  tests (`spike/cube/tests`, see `spike/README.md`) and the browser test `spike/dashboard/e2e.py`.
- **StarRocks needs a split FE/BE** here: the all-in-one image advertises its backend as `127.0.0.1`, which
  breaks Stream Load from other containers. Memory is the constraint at scale (`spike/results.md`).
- **`dim_date` runs to 2040** because the simulator stamps new rows with `now()`. `date_shift_years: 12`
  moves the seeded history onto live dates (the simulator and backfill read it from the dbt project).

## Extending the sandbox

- **Add a table to the star:** append it to `TABLE_PREDICATES` in
  `scripts/gen_adventureworks_seed.py` (closure) or let it default to a 10% sample,
  regenerate the seed, re-apply. The ingest picks up any source listed in the dbt project's
  `_sources.yml`, so add the source and a staging model there.

## Gotchas

- `sqlserver_to_postgres_elt` skips itself once `raw.customer` exists; pass `--force`
  to reload.
- ClickHouse must stay on 25.x (24.8's librdkafka rejects the Kafka 4.0 protocol).
- `postgres_active` init order is alphabetical: `00_debezium_user.sh`, `01_init.sql`,
  `02_adventureworks_schema.sql`, `03_adventureworks_seed.sql.gz`.
- The simulator creates an order with probability `SIM_ORDER_CHANCE` (default 0.05 ≈
  14 orders/day; 0.01 matches the seeded ~2.7/day). It sells only products the
  seeded *internet* history sells (weighted by line frequency), and order statuses
  advance probabilistically, forward-only (`STATUS_ADVANCE_CHANCE` / `STATUS_CANCEL_CHANCE`).
