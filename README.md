# Open-Source Data & Analytics Stack

An end-to-end ELT/CDC demo stack orchestrated by Airflow, built from open-source tools:

- **Postgres `postgres_active`** (an AdventureWorks OLTP sandbox kept live by a Faker simulator) → (**ingestr**, every 5 min, Airflow) → **StarRocks** `raw` → (**dbt-core**) → `mart` → **Cube** (semantic layer, pre-aggregations, row-level security) → the **live sales dashboard** behind Keycloak sign-in: KPIs, cross-filtering and Excel export. See [StarRocks + Cube serving path](#starrocks--cube-serving-path-starrocks-profile) and [Live sales dashboard](#live-sales-dashboard).
- **Postgres CDC source** (`postgres_active`) → (Debezium) → Kafka topic → **ClickHouse** (real-time OLAP): an independent path, see [Kafka / Debezium CDC](#kafka--debezium-cdc)
- **SQL Server** (`AdventureWorks2016`) → (dlt) → Postgres `analytics.raw`: an optional one-time load
- **AdventureWorks2016 OLTP sandbox** in `postgres_active` — a ~10% sample of the AdventureWorks tables, kept live by the `simulate_adventureworks` simulator, so you can practise against a churning OLTP database without the real SQL Server

## Stack

| Layer                | Tool                              |
|----------------------|-----------------------------------|
| Orchestration        | Airflow 3.3.2 (LocalExecutor)     |
| Ingestion            | ingestr (live AdventureWorks → StarRocks); dlt (orders, optional SQL Server load) |
| Streaming / CDC      | Kafka (KRaft) + Kafka Connect + Debezium |
| Transformation       | dbt-core + dbt-starrocks          |
| Warehouse / serving store | StarRocks 3.3                |
| Semantic layer       | Cube (+ Cube Store pre-aggregations) |
| Sign-in / row-level security | Keycloak + a small auth service + `cube/cube.js` |
| Dashboard            | the live sales dashboard (`dashboard/static`, served by nginx) |
| Real-time OLAP (CDC) | ClickHouse 25.8                   |
| Kafka UI             | provectuslabs/kafka-ui            |
| Data simulation      | Faker (Python)                    |
| Change-data-capture source | Postgres 16 (`wal_level=logical`) |

## Databases & containers

Two Postgres containers:

**`postgres`** (host port `5433`) — the metadata and small-warehouse instance:
- `airflow` — Airflow's own metadata (implementation detail)
- `analytics` — `raw` (dlt lands the optional SQL Server load and `orders` here). The star schema is no longer built here: it lives in StarRocks (see below). The empty `stage` / `mart` schemas and the old tables are left over from the retired Postgres serving path.

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

**StarRocks, Cube, Keycloak** (the `starrocks` profile) — the serving path: see
[StarRocks + Cube serving path](#starrocks--cube-serving-path-starrocks-profile).

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
              cdc.orders  → queries over HTTP (http://localhost:8123, database cdc)
```

Containers:
- **`kafka`** — single-node broker, KRaft combined mode (`confluentinc/cp-kafka:8.3.2`)
- **`kafka-connect`** — Debezium source connector host (`cp-kafka-connect:8.3.2` + `debezium-connector-postgresql:3.2.6`), REST on port `8083`
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

## Retired: the Postgres serving path

The star schema used to be built in Postgres (`analytics.mart`, dbt-postgres), copied into ClickHouse, and read
by Superset, Metabase and a Postgres-backed dashboard, with a MetricFlow semantic layer on top. All of that was
replaced by the StarRocks + Cube path above once the two marts agreed to the cent (the check was
`scripts/parity_check.py`). Removed: Superset (and its MCP server), Metabase, `dashboard/app.py`, the
ClickHouse `mart` copy, the dbt-postgres project `dbt/adventureworks_dwh` (including its 25 MetricFlow metrics;
Cube measures in `cube/model` replace them), the `postgres_active_to_postgres_aw` DAG and its dlt pipeline.
They are all in git history before the "retire the old BI path" commit. The CDC → Kafka → ClickHouse path and the
simulators were not part of it and are unchanged.

## Pipelines

| Pipeline | Direction | Strategy | DAG / schedule |
|----------|-----------|----------|----------------|
| `sqlserver_to_postgres` | SQL Server `AdventureWorks2016` (all 71 tables) → `analytics.raw` | full refresh (`replace`), loaded **once** (static source) | `sqlserver_to_postgres_elt` / manual |
| `postgres_active_to_postgres` | `postgres_active.active_db.orders` → `analytics.raw.orders` | incremental on `updated_at` + `merge` (upsert by `id`) | `postgres_active_to_postgres` / every 15 min |
| `simulate_orders` | mutates `orders` (insert/update/soft-delete) with Faker | — | `simulate_orders` / every 5 min |
| `simulate_adventureworks` | mutates the AdventureWorks OLTP tables (insert/update/delete) with Faker | — | `simulate_adventureworks` / every 5 min |
| `postgres_active_to_starrocks` | `postgres_active` AdventureWorks tables → StarRocks `raw` → dbt star in `mart` | ingestr incremental on `modified_date` + `merge` (upsert by primary key), then `dbt build` | `postgres_active_to_starrocks` / every 5 min |

The AdventureWorks source is a static demo database, so `sqlserver_to_postgres_elt` is
not scheduled: trigger it once from the UI and the dlt step skips itself on later runs
(pass `--force` to reload).

The star schema is built by `postgres_active_to_starrocks` from the live `postgres_active` tables
(see [StarRocks + Cube serving path](#starrocks--cube-serving-path-starrocks-profile)). The static
`analytics.raw` SQL Server load and the `sqlserver_to_postgres` pipeline remain available as an optional
one-time load into Postgres; see [AdventureWorks OLTP sandbox](#adventureworks-oltp-sandbox).

The `simulate_orders` DAG generates a steady stream of changes in `active_db.orders`.
Two consumers replicate it in parallel: the `postgres_active_to_postgres` dlt pipeline
(→ Postgres `analytics.raw.orders`) and the Debezium connector (→ Kafka topic).

The `simulate_adventureworks` DAG is the OLTP-sandbox counterpart: it keeps the
AdventureWorks tables in `active_db` moving. Two consumers read them: the
`postgres_active_to_starrocks` pipeline (→ StarRocks → the dashboard), and the Debezium
CDC stream (→ ClickHouse).

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
  order with probability `SIM_ORDER_CHANCE` — by default derived from the seeded
  history's last 365 days (~0.017, 4.8 orders/day) so the live series continues the
  history rather than stepping off it; set it to pin a livelier rate (0.05 ≈ 14
  orders/day) — inserts transaction history,
  reviews and cart items; takes sold units out of inventory; receives approved purchase
  orders and open work orders once their lead time has passed (a lead time of N days
  takes N × `SIM_LEAD_TIME_MINUTES_PER_DAY` = 2 real minutes, at most `SIM_RECEIPTS_PER_RUN` = 25
  receipts per run), adding the quantity to inventory; advances order statuses forward through the lifecycle
  (in process → approved → shipped, with occasional backordered / rejected /
  cancelled); updates prices and names; and deletes leaf rows — always
  bumping `modified_date`. The old random work orders and ±5 stock drift are off by default
  (`SIM_RANDOM_WORK_ORDERS=1`, `SIM_INVENTORY_DRIFT=<span>` bring them back): they made every stockout
  look already on order, so an approved action had nothing to change.
- **CDC** — the nine tables the simulator touches are also streamed through
  Debezium → Kafka → ClickHouse; see
  [AdventureWorks CDC stream](#adventureworks-cdc-stream).
- **Warehouse** — `postgres_active_to_starrocks` ingests the tables into StarRocks `raw`, and
  `dbt/adventureworks_starrocks` builds the star schema from the live source. The seed is
  **referentially consistent** (10% of the driver tables expanded along the foreign-key
  graph), so the star's `relationships` tests pass.

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

## Live sales dashboard

`dashboard/static` is a small, dependency-light web app over the star: revenue,
gross profit and margin, orders, average order value and units (each with a
sparkline and a change vs the prior fiscal year), monthly revenue by channel,
a product-mix treemap (one hue per category, a shade per subcategory, margin in
each tile's label and tooltip), the top 10 products, revenue by territory and a
live feed of the latest orders. It is served by the `dashboard-cube` service
(http://localhost:8250) and reads everything through Cube.

- **Sign-in and row-level security:** users sign in through Keycloak; each sees only their own
  territories, and roles that may not see profit get no profit or margin figures (the tiles, columns
  and chart are hidden, not zeroed).
- **Live:** the page polls every 30 s. New orders appear within one pipeline cycle plus about a
  minute (see *Freshness* above).
- **Panels load independently:** each panel runs its own query and redraws when its answer arrives, with a
  spinner and a seconds counter while it waits and "✓ 1.4s" once it has landed. Under a product filter the
  exact order count is the slow figure, so those panels draw first and Orders / Average order value fill in
  later. Changing a filter cancels the unfinished requests.
- **Cross-filtering:** channel, fiscal year, territory group/region and product
  category in one filter row; clicking a month, treemap tile or territory
  applies the same filters. A selection is marked with an outline/check rather
  than by fading everything else. Clicking a region (or subcategory) also sets
  its group (or category); clicking it again undoes both, restoring whatever
  group/category you had picked before. The filters are kept in the URL, so a
  view can be bookmarked.
- **Accessible:** every chart has a table view, keyboard-focusable marks with
  tooltips, and light/dark themes.
- **Excel export:** every chart has an *Excel* button, and *Export all* writes
  one workbook with a sheet per chart plus the key figures. Cells are typed
  (currency, %, counts, dates), each sheet has a frozen header and autofilter
  and states the filters it was exported with (and any the panel deliberately
  ignores), and the rows are the same ones the chart's table view shows. The
  `.xlsx` is generated in the browser by `static/xlsx.js` (no dependency).
- **Data source:** `static/app.js` asks `window.dashboardData` for `/api/meta` and `/api/dashboard`. The
  Cube adapter (`dashboard/cube/cube-source.mjs`, injected by nginx in front of `app.js`) answers them
  with Cube queries; the page itself knows nothing about Cube.

**Continuous dates.** The AdventureWorks sample's business dates end in mid-2014,
while the simulator stamps new orders with `now()`. dbt therefore shifts the
historical dates forward by the `date_shift_years` var (default `12`, see
`dbt/adventureworks_starrocks/macros/shift_history_date.sql`): order/due/ship dates, cost history, special
offers, quotas, currency rates and inventory movements, but only values before
`date_shift_cutoff` (`2015-01-01`), so live rows pass through unchanged. History
then runs 2023-05 .. 2026-06 and meets the live orders. Build on the original
calendar with `--vars '{date_shift_years: 0}'`.

The stretch between the end of the shifted history (2026-06-30) and the day the
simulator first ran is filled by `airflow/scripts/backfill_adventureworks_orders.py`:
internet orders built like the simulator's and reseller orders modelled on the
seeded reseller history (Faker; the simulator itself only creates internet orders).
It skips days (internet) / months (reseller) that already have orders, so re-run it
after Airflow has been down to close the hole:

```bash
docker compose exec airflow-scheduler \
  python /opt/airflow/scripts/backfill_adventureworks_orders.py --start 2026-07-01
```

## StarRocks + Cube serving path (`starrocks` profile)

The serving path: what end users read. It was proven in [`spike/`](spike/) (results, benchmarks and the
go/no-go in [`spike/results.md`](spike/results.md)) and runs here fed by the live simulator. It replaced the
earlier Postgres mart (see [Retired](#retired-the-postgres-serving-path)).

```
postgres_active --(ingestr, every 5 min, Airflow)--> StarRocks raw --(dbt-starrocks)--> mart
   mart --> Cube (+ Cube Store rollups, row-level security) --> dashboard, behind Keycloak sign-in
```

| Service | Role |
|---|---|
| `starrocks-fe`, `starrocks-be`, `starrocks-init` | StarRocks (separate frontend and backend; the init job registers the backend by hostname, creates the schemas and the read-only users) |
| `cube`, `cubestore`, `cubestore-worker` | the semantic layer (`cube/`), pre-aggregations, and row-level security in `cube/cube.js` |
| `keycloak`, `auth` | sign-in (demo realm in `keycloak/`; the realm is still named `spike`, renaming it would orphan existing Keycloak volumes), and the service (`auth/`) that turns a Keycloak login into a 15-minute Cube token carrying the user's territories |
| `dashboard-cube` | the same dashboard UI as `dashboard`, with the Cube data source injected in front of `app.js` |

```bash
docker compose --profile starrocks up -d --build
# unpause the pipeline once (new DAGs start paused), plus the simulators if they are not running:
docker compose exec airflow-scheduler airflow dags unpause postgres_active_to_starrocks
open http://localhost:8250        # users: admin, na_manager, de_rep -- password: TEST_USER_PASSWORD in .env
                                  # buyer (purchasing) and marketer (marketing) get the inventory view only
```

An older `.env` needs the secrets this profile uses (`CUBEJS_API_SECRET`, `CUBE_DB_PASSWORD`, `AUTH_DB_PASSWORD`,
`KEYCLOAK_ADMIN_PASSWORD`, `TEST_USER_PASSWORD`; see `.env.example`), because Compose requires every
secret. `./scripts/generate-env.sh --force` writes a complete `.env` (and replaces your other secrets). The CDC
-> Kafka -> ClickHouse path (`--profile cdc`) is independent of this profile.

**Pipeline** (`airflow/dags/postgres_active_to_starrocks_dag.py`, every 5 minutes, one minute after the
simulator): `airflow/scripts/ingest_starrocks.py` loads each table dbt reads with ingestr (incremental
merge on `modified_date`, primary keys read from the source catalog, four tables at a time) and snapshots
the live order keys; then `dbt build` (in its own virtualenv, `dbt/adventureworks_starrocks`) rebuilds and
tests the star. A merge load never sees hard deletes, so the staging models drop orders whose key left
the snapshot. A cycle takes about 35 seconds at this volume; if one overruns, the next waits.

**Freshness.** A change in `postgres_active` is on the dashboard within one cycle plus about a minute:
the last step of every build rewrites `mart.data_version`, which Cube's rollup refresh keys watch (checked
every minute). Measured end to end with `spike/bench/freshness.py` (random insert times over 6 cycles):
median 126 s, fastest 86 s, slowest 276 s, none missed (a small sample; the design
bound is one 5-minute cycle + ~35 s of pipeline + ~1 min for Cube, about 6.5 minutes).

**Incremental facts.** `fact_internet_sales` and `fact_reseller_sales` are primary-key tables
(`order_date`, `sales_order_number`, `sales_order_line_number`) upserted each cycle. A run rebuilds only the
orders whose header or line `modified_date` is at or after the fact's own watermark (`max(source_modified_date)`
minus a 60-minute lookback, `incremental_lookback_minutes`), so the line-number window and joins scan a few
orders, not every line. A post-hook deletes fact rows whose order left staging (hard deletes, via the PK
snapshot). Known limits: a line deleted from a surviving order, or an order whose `order_date` changes, is not
removed until `dbt build --full-refresh`; and the 500M-row effect is not measured yet (the full rebuild was
~22 min per fact). Changing a fact's columns needs a one-off `--full-refresh`.

**Inventory health** (`mart.inventory_health`, one row per stocked, sold or on-order product; plan in
`docs/inventory-actions-plan.md`, Phase 1.1-1.3). The pipeline now also ingests vendors, product-vendor,
purchase orders, work orders, offers and inventory. Status (first match wins): `discontinued`, `not_stocked`
(no inventory record), `stockout` (nothing on hand, demand), `reorder_now` (stock projected for the end of the
lead time is down to the safety stock), `dead_stock` (stock, no sale in 90 days), `overstock` (cover above 120
days), `healthy`. Reorder quantity = demand over lead time plus review period, plus safety stock, less on
hand and on order, within the vendor's minimum and maximum. Demand is the trailing 28-day (else 90-day)
average, anchored on the data's newest order (`int_as_of_date`), not today. Thresholds are dbt vars in
`dbt_project.yml`. AdventureWorks' stored safety stock is static and unrelated to its sales, so it is capped at
30 days of demand. Open purchase orders count only when their header is present and pending/approved.
To develop against a scaled tier without touching the live schemas:
`dbt build --vars '{aw_source_schema: scale_25m, date_shift_years: 0, mart_suffix: _25m, apply_ro_grants: false}'`
(`mart_suffix` now suffixes the stage, mart, rls and default schemas).

**Inventory access** (Cube cubes `inventory_health` and `offer_performance`; not territory-bound, so gated by role in
`cube/cube.js`): `admin` sees everything; `purchasing` (user `buyer`) sees `inventory_health` including vendors,
unit costs and order quantities, but no sales, offers or customers; `marketing` (user `marketer`) sees stock,
excess and discount tiers plus offer performance, but no vendor, unit cost, lead time or order-size member,
whether asked for, filtered on or only used to order the result; managers and reps see no inventory at all,
even joined to a sales cube. A Keycloak that already imported the realm keeps its old users: run
`keycloak/sync-users.sh` to add the two roles and users. `offer_performance` is descriptive evidence (units per
day during an offer versus the 28 days before): no control group, and one offer with a tiny baseline can show an
enormous lift, so treat it as "what happened", not "what the discount did".

**Inventory panels** (dashboard, below the sales charts): three KPI tiles (items at stockout risk, suggested
reorders, capital tied in excess stock), a reorder list (admin, purchasing) and an overstock / dead-stock list with
a suggested discount and what past offers of that depth did (admin, marketing), each with an Excel export. They
ignore every sales filter and a filter change never re-queries them; they load with the page, on Refresh and on
the 30-second poll (re-drawn only if the data changed). `buyer` and `marketer` see the inventory view only and
the page never sends them a sales query. The "past offers" figure is the median lift (units per day during an
offer over the 28 days before) of past offers in that discount band: descriptive, no control group, and with few
offers it can be large.

**Inventory actions service** (`actions/`, port `ACTIONS_PORT`, profile `starrocks`; Phase 2 of
`docs/inventory-actions-plan.md`). An approved proposal becomes a row in the simulated ERP:
`POST /actions/purchase-orders` and `/actions/work-orders` (purchasing, admin) create approved purchase orders
(one per vendor) and work orders; `POST /actions/campaigns` (marketing, admin) creates a special offer;
`GET /actions/log` lists the role's own kinds. Each call carries the user's Keycloak token. Nothing but the
product ids and the edits a role may make (a quantity, a discount, a length) comes from the client: vendor,
unit price, lead time and the product's state are read from the current `mart.inventory_health` row, and a
request that disagrees is refused with 422: only stockout / reorder_now products can be replenished (by the
kind they are replenished by), a quantity must lie between the vendor minimum and the lower of the vendor
maximum and twice the suggestion, a campaign needs overstock or dead stock, a discount of 1% up to twice the
suggestion (at most 50%) and 7-90 days. Every approval and every refusal is written to `actions_log` (who,
role, payload, outcome, result); the writes of one request and its audit row share a transaction, and an
`idempotency_key` makes a retry return the first result (another user's key gets 409). The database login
`actions_writer` can only read and INSERT into those tables: no UPDATE or DELETE, so the log is append-only
for it. On an existing `postgres_active` volume run `postgres_active/sync-actions.sh` once (init scripts run
only on a fresh volume); `starrocks-init` creates the read-only `actions_ro`. A new purchase-order id is the
maximum over header and detail ids, because the sample has lines whose header is missing. The closed loop is
the simulator receiving an approved order after its lead time (a day of lead time = 2 minutes) and the next
pipeline cycle updating `inventory_health`: `actions/tests/loop_e2e.py` times it (a stocked-out product was no
longer a stockout 295 s after approval, one run). Campaigns create the offer rows only: simulated sales do not
yet pick offers up, so a campaign's effect on sales is not modelled. The dashboard's lists have an
Approve flow on top: tick rows (and edit a quantity, or a campaign's discount and length), confirm, and the page
posts to the service; an approved row shows "approved … by …" until the pipeline moves it. In this data no
purchased component ever has demand (only finished goods are sold), so only in-house work orders come up; the
purchase-order path is covered by the unit tests. `scripts/demo_stock_scenario.py` lowers the stock of a dozen
best-selling in-house products so the reorder list has something to approve (stock covers ~1000 days otherwise,
and an approved order empties the list again).

**Things that cost a day to find** (all fixed in the code, noted so they are not undone):
- The all-in-one StarRocks image advertises its backend as `127.0.0.1`, so Stream Load from another
  container fails; hence separate FE/BE containers.
- dbt drops and recreates tables on every build, and StarRocks drops table-level grants with the table.
  Read access is therefore a wildcard grant on a schema (`ALL TABLES IN DATABASE`), and the auth service
  reads its own small `rls` schema.
- Cube answers from whichever rollup partitions are built, so a rollup whose partitions are all rebuilt
  (a SQL refresh key, or a changed definition) returns incomplete totals while it rebuilds. The live
  rollups are therefore partitioned with a time-based incremental refresh: `every: 5 minute`,
  `update_window: 5 week`, so each tick rebuilds only the partitions touching the last 5 weeks (year
  partitions for `monthly` and `monthly_product`, month for `daily`) and older partitions are never
  rescanned. A SQL refresh key such as `mart.data_version` cannot be combined with `incremental`, so
  rollup freshness is now clock-driven (see the measured lag below). Orders changed more than 5 weeks
  ago are not picked up until a full rebuild of the rollup. The four non-additive `orders_mix*` rollups
  stay unpartitioned and rebuild hourly (raise this at 500M: each is a whole-table distinct count).

  Two consequences of the incremental window. (1) A partition outside it is built once and never again,
  so after a `dbt build --full-refresh`, a backfill or a correction to old orders, rebuild the rollups:
  set `CUBE_PREAGG_SCHEMA` in `.env` to a new name and `docker compose --profile starrocks up -d cube` (a new
  schema name makes Cube build every partition from scratch; keep it set, because going back to an old name
  serves that schema's stale partitions again). Until a
  fresh build finishes, Cube can answer from the partitions built so far (incomplete totals). (2) Cube
  bounds a partition's build range by `max(order_date)` truncated to milliseconds, which silently
  dropped the newest order when it carried microseconds, so the facts now store `order_date` in whole
  seconds (a one-off `--full-refresh` is needed when upgrading, as the key changed).

**Partitioned rollups at ~500M lines** (248.8M internet + 251M reseller lines, run against a copy of the
live model on the old spike stack's data; one 22-minute run): the first full build of
the monthly rollup took 64-138 s, rollup-served queries answered in 20-50 ms, and over 22 minutes with a
marker order inserted every 150 s (the update window forced to cover the 2021 partition so a real
14M-line year partition was rebuilt each tick) the total, polled every ~2 s, never dipped (9 inserts) and each insert became visible 15-205 s later. That lag is Cube's refresh only; add the pipeline
cycle for the end-to-end figure. Caveat: the tick rebuilt one real year partition, not the production
volume of a year of 500M data.

**Checks** (the 29 security tests, and every role in a real browser):

```bash
# with CUBE_URL / KEYCLOAK_URL / AUTH_URL / STARROCKS_MYSQL_PORT pointing at this stack (see spike/README.md):
uv run --with pytest --with requests --with pymysql --with pyjwt python -I -m pytest cube/tests
uv run --with playwright python -I dashboard/cube/tests/e2e.py                      # each role, in a real browser
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
│   └── apply-adventureworks-cdc.sh   # wire the AW tables into CDC on a running stack
├── .pre-commit-config.yaml   # gitleaks, private-key detection, ruff
├── ruff.toml
├── tests/
│   └── test_dag_integrity.py # every DAG imports cleanly (CI `dags` job)
├── SECURITY.md               # how secrets are handled, guard rails, reporting
├── skills/                   # agent skills for working with this stack
├── docs/
│   └── adventureworks claude dashboard app.png
├── .github/
│   ├── dependabot.yml          # monthly grouped updates: actions, pip, Docker images
│   └── workflows/
│       └── ci.yml              # gitleaks, pre-commit, DAG import, orders pipeline, dbt-starrocks parse, compose config, images, CDC smoke
├── airflow/
│   ├── Dockerfile            # apache/airflow:3.3.2 + dlt + pyodbc + faker + ingestr + a dbt-starrocks virtualenv
│   ├── requirements.txt
│   ├── requirements-dbt-starrocks.txt
│   ├── dags/
│   │   ├── sqlserver_to_postgres_dag.py
│   │   ├── postgres_active_to_postgres_dag.py
│   │   ├── postgres_active_to_starrocks_dag.py   # every 5 min: ingestr -> dbt-starrocks
│   │   ├── simulate_orders_dag.py
│   │   └── simulate_adventureworks_dag.py
│   └── scripts/
│       ├── simulate_orders.py
│       ├── simulate_adventureworks.py
│       ├── ingest_starrocks.py                # ingestr runner used by the DAG
│       └── backfill_adventureworks_orders.py  # fill past date ranges (both channels)
├── dlt/
│   └── pipelines/
│       ├── stack_credentials.py      # shared Postgres credentials (password from .env)
│       ├── sqlserver_to_postgres/
│       │   ├── sqlserver_pipeline.py
│       │   └── .dlt/
│       │       ├── config.toml           # non-secret settings
│       │       └── secrets.toml.example  # copy to secrets.toml (git-ignored)
│       └── postgres_active_to_postgres/
│           ├── orders_pipeline.py
│           └── .dlt/
│               └── config.toml           # source + destination; no secrets file needed
├── dbt/
│   └── adventureworks_starrocks/         # the star schema on StarRocks (see its README)
│       ├── dbt_project.yml
│       ├── profiles.yml                  # connection from DBT_SR_* env vars
│       ├── macros/                       # shift_history_date.sql moves seeded history onto live dates
│       ├── seeds/dim_user_territory.csv  # which territories each user may see
│       ├── tests/
│       └── models/{staging,intermediate,marts,rls}/
├── cube/
│   ├── cube.js                   # dialect fix, sign-in check, row-level security (queryRewrite)
│   └── model/cubes/              # dims, facts, measures, pre-aggregations
├── starrocks/
│   └── init.sh                   # registers the backend, creates schemas, read-only users, settings
├── postgres/
│   └── init/
│       └── 01_init.sql           # airflow + analytics databases
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
├── dashboard/
│   └── static/               # index.html, app.js (inline-SVG charts), xlsx.js (Excel export), style.css
├── spike/                    # the StarRocks + Cube spike: benchmarks, results, and the pieces
│   ├── results.md            #   not yet moved out: auth/, keycloak/, dashboard/ (Cube data source)
│   └── ...
```

## Setup

1. **Create `.env` with real secrets:**
   ```bash
   ./scripts/generate-env.sh
   ```
   This writes strong random values for the Postgres, Debezium, ClickHouse, Airflow
   and StarRocks/Cube/Keycloak secrets (mode `0600`). If you prefer to do it by hand, copy
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
   | `cdc` | `kafka`, `kafka-connect`, `kafka-ui`, `debezium-register`, `clickhouse` (independent of the serving path) |
   | `starrocks` | `starrocks-fe`, `starrocks-be`, `starrocks-init`, `cube`, `cubestore`, `cubestore-worker`, `keycloak`, `auth`, `dashboard-cube` |

   ```bash
   # everything (the StarRocks serving path + CDC)
   docker compose --profile starrocks --profile cdc up -d --build

   # or just Postgres + Airflow
   docker compose up -d --build
   ```
   First run builds images and runs `airflow-init` / `starrocks-init`.

   Every published host port is overridable from `.env` (see `.env.example`),
   so this stack can run next to another one on the same machine:

   ```bash
   # e.g. if 5434 and 8080 are already taken by another stack
   POSTGRES_ACTIVE_PORT=5444 AIRFLOW_PORT=8090 docker compose --profile starrocks --profile cdc up -d --build
   ```

3. **Access:**
   - Airflow UI: http://localhost:8080 (user/pass from `.env`)
   - Live sales dashboard: http://localhost:8250 (`starrocks` profile; sign in as `admin`, `na_manager` or `de_rep` with `TEST_USER_PASSWORD` from `.env`; see [Live sales dashboard](#live-sales-dashboard))
   - Cube API: http://localhost:4000; Keycloak: http://localhost:8180; StarRocks (MySQL protocol): `localhost:9030`, user `root`, no password (local demo only)
   - Kafka UI: http://localhost:8081
   - Kafka Connect REST: http://localhost:8083
   - ClickHouse HTTP: http://localhost:8123 (user `clickhouse`, password from `.env`)
   - Warehouse Postgres: `localhost:5433`, db `analytics`, user `postgres`, password from `.env`
   - CDC source Postgres: `localhost:5434`, db `active_db`, user `postgres` / Debezium user `debezium`, passwords from `.env`

4. **Run the DAGs:**
   - Unpause `postgres_active_to_starrocks`, `postgres_active_to_postgres`, `simulate_orders`
     and `simulate_adventureworks` (they run on a schedule). `postgres_active_to_starrocks` ingests
     the sandbox into StarRocks and runs `dbt build` (models, the product-version log and all tests).
   - `sqlserver_to_postgres_elt` is unscheduled: trigger it once if you want the
     static SQL Server load in Postgres `analytics.raw` (it only loads).
   - The AdventureWorks tables in `postgres_active` are seeded automatically on first
     start; see [AdventureWorks OLTP sandbox](#adventureworks-oltp-sandbox) for an
     existing volume.

5. **Debezium registration is automatic.** The `debezium-register` Compose service
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
- **Confluent 8.3+ images** no longer ship `cub` or `curl`, and their `python3` is older than 3.10, so the `kafka` health check uses Kafka's own `kafka-broker-api-versions`, the `kafka-connect` one a plain bash `/dev/tcp` HTTP request, and `register_connector.py` uses `from __future__ import annotations`.
- **Kafka is single-node KRaft** (broker+controller combined), no ZooKeeper — the current Confluent recommendation for new deployments.
- **ClickHouse ingestion**: the Kafka-engine table consumes the Debezium topic as `JSONAsString`; the materialized view parses the envelope with `JSONExtract*` and `parseDateTime64BestEffortOrNull` (the `OrNull` variant is important — `parseDateTime64BestEffort('')` throws instead of returning NULL for JSON-null `deleted_at`). ClickHouse must be **25.x** — 24.8's bundled librdkafka doesn't support the Kafka 4.0 protocol ("Required feature not supported by broker"). `clickhouse/config.d/kafka.xml` lowers librdkafka's topic metadata refresh to 10 s: Debezium creates the AdventureWorks topics during its snapshot, after ClickHouse has subscribed, and with the 300 s default most of them reached `cdc.aw_events` up to 5 minutes late on a fresh stack.
- **ClickHouse current state**: `cdc.orders` keeps full history (90-day TTL). A cascading materialized view feeds `cdc.orders_latest` (`ReplacingMergeTree(ts_ms)`, one row per `id`), and `cdc.orders_current` / `cdc.orders_active` read that with `FINAL`. This replaced a view that ran `row_number()` over the entire history on every query.
- **Incremental + merge**: `postgres_active_to_postgres` uses `dlt.sources.incremental("updated_at")` with `write_disposition="merge"`, keyed on the reflected primary key `id`. It only fetches rows changed since the last run and upserts them, so `raw.orders` mirrors the current source state (soft-deleted rows remain, flagged by `deleted_at`).
- **Airflow 3** runs four services (api-server, scheduler, dag-processor, triggerer). FAB auth manager is enabled to keep env-var admin-user provisioning.
- **dlt normalize race**: `[normalize] workers = 1` is set in each pipeline's `.dlt/config.toml` to avoid a process-pool race condition observed when loading many small tables.
- **Init containers fail loudly**: `airflow-init` runs with `set -euo pipefail`, so a failed `airflow db migrate` stops the stack instead of starting services on a half-migrated schema.
- **One-time SQL Server load**: `sqlserver_to_postgres` treats AdventureWorks2016 as a static source. `sqlserver_pipeline.py` checks for a load marker (`raw.customer`) and skips when present; `--force` reloads. The DAG is therefore unscheduled.
- **Secrets come from `.env`**: Compose requires each secret (`${VAR:?}`) and fails fast rather than falling back to a placeholder. `scripts/generate-env.sh` creates them. The Debezium connector and ClickHouse user read their passwords from the same file, so nothing sensitive lives in a tracked file.
- **Pinned versions**: base images are pinned (`provectuslabs/kafka-ui:v0.7.2`, `clickhouse/clickhouse-server:25.8`, `postgres:16`, Confluent 8.3.2), as are the Airflow requirements (`dlt[postgres]==1.30.0`, `faker`), ingestr (`v1.1.73`), dbt (`dbt-core==1.12.6` + `dbt-starrocks==1.12.2` in their own virtualenv) and the Debezium connector (`debezium-connector-postgresql:3.2.6` — the newest 3.x on Confluent Hub). Bump and rebuild deliberately; Dependabot handles minor/patch bumps, majors stay manual.
- **AdventureWorks OLTP sandbox**: `postgres_active` holds a generated, seeded copy of the AdventureWorks tables (see [AdventureWorks OLTP sandbox](#adventureworks-oltp-sandbox)). The schema and seed are **generated files** — edit `scripts/gen_adventureworks_schema.py` / `scripts/gen_adventureworks_seed.py`, not the SQL. Primary keys are restored; foreign keys are not enforced, but the seed is **referentially consistent** (10% of the driver tables expanded along the FK graph), so joins resolve. `simulate_adventureworks` mutates the tables every 5 min.
- **Star schema source**: `dbt/adventureworks_starrocks` reads StarRocks `raw`, fed by the `postgres_active_to_starrocks` DAG. `dim_date` runs to 2040 because the simulator stamps new rows with `now()`.
- **Hard deletes**: a merge load cannot see hard deletes. The StarRocks pipeline snapshots the live order keys each cycle and drops deleted orders in staging; other tables (e.g. deleted `product_review` rows, which the star does not use) keep them, while the Debezium/ClickHouse path records them as `op='d'`. A production feed would add a soft-delete column (like `orders.deleted_at`) or CDC for those tables.
- **dlt incremental cursor**: `modified_date` is often a date at midnight, so many rows share the cursor value; dlt warns about it but `merge` on the primary key keeps the load correct.
- **Pre-commit**: `.pre-commit-config.yaml` runs gitleaks, private-key detection and `ruff check` (config in `ruff.toml`); run `pre-commit install` once after cloning.
- **Dependabot** (`.github/dependabot.yml`): monthly grouped PRs (on the 1st) for the SHA-pinned Actions, `airflow/requirements*.txt` and the Docker base images (major image bumps are skipped; those need code changes). Each PR goes through CI, including the `images`, `dwh` and `cdc-smoke` jobs; merge only once they are green on the current `main`. Security fixes don't wait for the schedule (Dependabot alerts / security updates).
- **CI** (`.github/workflows/ci.yml`): besides gitleaks, pre-commit and `docker compose config`, the `dags` job imports every DAG under the Airflow version from `airflow/Dockerfile`, the `dwh` job loads the committed `postgres_active` schema + seed into a Postgres service and runs the orders dlt pipeline, the `dbt-starrocks` job parses the StarRocks dbt project, and the `images` job builds the Airflow image and checks ingestr and the dbt-starrocks virtualenv in it.
