---
name: oss-da-bi-stack
description: >-
  Work with the OSS data & analytics stack in this repository: the dlt/dbt ELT into
  Postgres, the Debezium → Kafka → ClickHouse CDC path, the AdventureWorks OLTP
  sandbox in postgres_active, its simulators, and the Airflow orchestration. Use when
  regenerating the AdventureWorks sandbox, applying init scripts, running or debugging
  a pipeline/DAG, querying the warehouse/CDC databases, or extending the stack.
---

# OSS data & analytics stack

An Airflow-orchestrated ELT/CDC demo. Read `README.md` first for the full picture;
this skill is the operator's shortcut for the common tasks.

## Architecture in one breath

- **Warehouse** `postgres` (`localhost:5433`, db `analytics`, schemas `raw`/`stage`/`mart`).
- **CDC source / OLTP sandbox** `postgres_active` (`localhost:5434`, db `active_db`).
- **Streaming** Debezium → Kafka (`localhost:8081` UI) → ClickHouse (`localhost:8123`, db `cdc`).
- **Orchestration** Airflow (`localhost:8080`).
- **BI** Superset (`localhost:8089`) and Metabase (`localhost:3001`).

Three data paths: SQL Server → `analytics.raw` (dlt, one-time static load, now a
fallback); `postgres_active.orders` → Kafka → ClickHouse and → `analytics.raw.orders`
(dlt); AdventureWorks sandbox in `postgres_active` → `analytics.raw_active` (dlt) → the
`adventureworks_dwh` star, and the nine mutated tables → Kafka → ClickHouse.

## Rules of engagement

- **Never commit secrets.** Everything sensitive is in `.env` (git-ignored). Copy
  `scripts/generate-env.sh` output; never paste values into tracked files.
- **`docker compose down -v` is destructive and forbidden here.** It wipes the
  warehouse and ClickHouse volumes, and the AdventureWorks SQL Server source is not
  reachable, so `analytics.raw` cannot be rebuilt. Apply schema changes in place.
- The container-internal port for `postgres_active` is **5434**, not 5432. Use
  `-p 5434` for `psql` inside that container.
- The AdventureWorks sandbox files (`postgres_active/init/02_*.sql`, `03_*.sql.gz`) are
  **generated**; edit the generator scripts, not the output.

## Common tasks

Load the env first:

```bash
set -a && . ./.env && set +a
```

**Regenerate the AdventureWorks sandbox** (from the warehouse `analytics.raw`):

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
psql "postgresql://postgres:$POSTGRES_PASSWORD@localhost:5433/analytics" -c 'select count(*) from raw.sales_order_header'
docker exec clickhouse clickhouse-client --password "$CLICKHOUSE_PASSWORD" -q 'select count() from cdc.orders'
```

**dbt** (runs in the Airflow image; project at `/opt/airflow/dbt/adventureworks_dwh`):

```bash
docker exec oss_airflow_scheduler dbt build \
  --project-dir /opt/airflow/dbt/adventureworks_dwh \
  --profiles-dir /opt/airflow/dbt/adventureworks_dwh
```

**Airflow DAGs:** `sqlserver_to_postgres_elt` (manual, dlt load only), `postgres_active_to_postgres`
(orders, 15 min), `postgres_active_to_postgres_aw` (AdventureWorks → `raw_active`, `dbt source freshness`,
`dbt build` (incl. the product snapshot), then the star → ClickHouse; 15 min),
`simulate_orders` (5 min), `simulate_adventureworks` (5 min).

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

## ClickHouse mart (star copy)

The dbt star is copied into ClickHouse `mart` by `airflow/scripts/sync_mart_to_clickhouse.py`
(the last task of the `postgres_active_to_postgres_aw` DAG) using ClickHouse's
`postgresql()` table function — a full `CREATE OR REPLACE TABLE … AS SELECT` per table.
It reads the mart as the read-only `bi_ro` role. Query it like Postgres:

```bash
docker exec clickhouse clickhouse-client --password "$CLICKHOUSE_PASSWORD" -q \
  "select p.product_category_name, round(sum(f.sales_amount),2) revenue \
   from mart.fact_internet_sales f join mart.dim_product p on f.product_key=p.product_key \
   group by 1 order by revenue desc"
```

Refresh by hand: `docker exec oss_airflow_scheduler python /opt/airflow/scripts/sync_mart_to_clickhouse.py`.
Note: dlt's ClickHouse destination works on dlt 1.30 (re-tested — loads fine via native
port 9000 + `http_port` 8123; the dlt 1.4.1 staging-table quoting bug is gone). The mart
sync still uses the `postgresql()` script, which predates the upgrade.

## Warehouse DWH (fed live from the sandbox)

The dbt project `adventureworks_dwh` reads **`analytics.raw_active`**, not the static
`analytics.raw`. The pipeline `postgres_active_to_postgres_aw`
(`dlt/pipelines/postgres_active_to_postgres_aw/aw_pipeline.py`, DAG
`postgres_active_to_postgres_aw`, every 15 min) replicates every sandbox table into
`raw_active` (incremental on `modified_date` + `merge` on the reflected PKs) and then
runs `dbt build`.

- **Repoint the source:** the `aw_source_schema` dbt var (default `raw_active`).
  `dbt build --vars '{aw_source_schema: raw}'` builds from the static SQL Server load.
- **Regenerate `raw_active` from scratch** (e.g. after re-seeding the sandbox): drop
  the schema and re-run the pipeline —
  `psql ... -c "drop schema if exists raw_active cascade"` then
  `docker exec -w /opt/airflow/dlt/pipelines/postgres_active_to_postgres_aw oss_airflow_scheduler python aw_pipeline.py`.
  dlt's cursor lives in the dropped schema, so this also resets the incremental state.
- **`dim_date` runs to 2040** because the simulator stamps new rows with `now()`.
- The seed is referentially consistent, so `dbt build` should pass 168/168. If a
  relationship test fails, check `scripts/gen_adventureworks_seed.py`'s closure
  (`SELECTION_SETS` / `TABLE_PREDICATES`) rather than the dbt models.

## Extending the sandbox

- **Add a table to the DWH:** append it to `TABLE_PREDICATES` in
  `scripts/gen_adventureworks_seed.py` (closure) or let it default to a 10% sample,
  regenerate the seed, re-apply, and re-run the pipeline. dlt picks up new sandbox
  tables automatically; only `_sources.yml` + a staging model need adding.

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
