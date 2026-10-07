-- AdventureWorks CDC landing zone.
--
-- The postgres_active AdventureWorks tables are mutated every 5 minutes by the
-- Airflow `simulate_adventureworks` DAG. Debezium streams the nine tables the
-- simulator touches into Kafka (topics `active_db.public.<table>`), and this
-- file lands those changes in ClickHouse.
--
-- Design: ONE Kafka-engine table consumes every topic (the `_topic` virtual
-- column names the source table), and ONE materialized view stores the raw
-- Debezium envelope in `cdc.aw_events`. Adding a table later is one line in
-- `kafka_topic_list` (and Debezium's `table.include.list`) -- no new DDL here.
--
-- Typed, dashboard-ready current-state tables are then built for a couple of
-- headline tables by cascading from `cdc.aw_events`, mirroring the orders
-- pattern (`cdc.orders_latest` / `cdc.orders_active`).

CREATE DATABASE IF NOT EXISTS cdc;

-- Raw Kafka queue: each message is the whole Debezium envelope as one string.
-- Multi-topic, so `_topic` identifies which table a change belongs to. As with
-- the orders queue, the table must have exactly ONE String column for
-- JSONAsString; `_raw_message`/`_error` are virtual columns supplied by
-- kafka_handle_error_mode = 'stream'.
CREATE TABLE IF NOT EXISTS cdc.aw_kafka (
    raw String
) ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'active_db.public.sales_order_header,active_db.public.sales_order_detail,active_db.public.product,active_db.public.product_inventory,active_db.public.work_order,active_db.public.transaction_history,active_db.public.product_review,active_db.public.shopping_cart_item,active_db.public.person',
    kafka_group_name = 'clickhouse_adventureworks',
    kafka_format = 'JSONAsString',
    kafka_handle_error_mode = 'stream',
    kafka_skip_broken_messages = 1;

-- Generic envelope history for every streamed table. `after`/`before` are the
-- raw JSON images, so a table can be decoded at read time without new DDL.
-- Deletes (op = 'd') have a null `after`; the primary key is in `before` (with
-- REPLICA IDENTITY DEFAULT the other columns are placeholders).
CREATE TABLE IF NOT EXISTS cdc.aw_events (
    source_table String,
    op           String,
    ts_ms        UInt64,
    -- Debezium WAL position: monotonic per change, so it beats ts_ms as the
    -- version column (an insert and its follow-up update in one transaction
    -- share ts_ms).
    lsn          UInt64,
    before       String,
    after        String,
    ingested_at  DateTime DEFAULT now()
) ENGINE = MergeTree
ORDER BY (source_table, ts_ms)
TTL ingested_at + INTERVAL 90 DAY DELETE;

CREATE MATERIALIZED VIEW IF NOT EXISTS cdc.aw_events_mv TO cdc.aw_events AS
SELECT
    _topic AS source_table,
    JSONExtractString(raw, 'op') AS op,
    JSONExtractUInt(raw, 'ts_ms') AS ts_ms,
    JSONExtractUInt(raw, 'source', 'lsn') AS lsn,
    JSONExtractRaw(raw, 'before') AS before,
    JSONExtractRaw(raw, 'after') AS after
FROM cdc.aw_kafka;

-- Anything that raised an error while being processed, so nothing disappears
-- silently. `_raw_message`/`_error` are virtual columns from handle_error_mode.
CREATE TABLE IF NOT EXISTS cdc.aw_kafka_rejected (
    raw     String,
    reason  String,
    seen_at DateTime DEFAULT now()
) ENGINE = MergeTree
ORDER BY seen_at
TTL seen_at + INTERVAL 30 DAY DELETE;

CREATE MATERIALIZED VIEW IF NOT EXISTS cdc.aw_kafka_rejected_mv TO cdc.aw_kafka_rejected AS
SELECT
    if(_error != '', _raw_message, raw) AS raw,
    if(_error != '', _error, 'unhandled message') AS reason
FROM cdc.aw_kafka
WHERE _error != '' OR JSONExtractString(raw, 'op') = '';

-- --- Typed current state: sales_order_header ------------------------------
-- ReplacingMergeTree keeps the newest version per sales_order_id (highest
-- lsn, the Debezium WAL position); a delete is a version with deleted = 1.
-- Read with FINAL.
CREATE TABLE IF NOT EXISTS cdc.sales_order_header_latest (
    sales_order_id    UInt64,
    revision_number   Nullable(Int64),
    order_date        Nullable(DateTime64(6)),
    due_date          Nullable(DateTime64(6)),
    ship_date         Nullable(DateTime64(6)),
    status            Nullable(Int64),
    online_order_flag Nullable(UInt8),
    sales_order_number Nullable(String),
    customer_id       Nullable(UInt64),
    sales_person_id   Nullable(UInt64),
    territory_id      Nullable(UInt64),
    sub_total         Nullable(Decimal(18, 4)),
    tax_amt           Nullable(Decimal(18, 4)),
    freight           Nullable(Decimal(18, 4)),
    total_due         Nullable(Decimal(18, 4)),
    modified_date     Nullable(DateTime64(6)),
    deleted           UInt8 DEFAULT 0,
    op                String,
    ts_ms             UInt64,
    lsn               UInt64
) ENGINE = ReplacingMergeTree(lsn)
ORDER BY sales_order_id;

-- Deletes have a null `after`, so the primary key comes from `before`;
-- everything else is extracted from `after`. The `> 0` guard drops messages
-- that carry neither (e.g. a tombstone for a different table).
CREATE MATERIALIZED VIEW IF NOT EXISTS cdc.sales_order_header_latest_mv TO cdc.sales_order_header_latest AS
SELECT
    JSONExtractUInt(if(op = 'd', before, after), 'sales_order_id') AS sales_order_id,
    JSONExtractInt(after, 'revision_number') AS revision_number,
    parseDateTime64BestEffortOrNull(JSONExtractString(after, 'order_date'), 6) AS order_date,
    parseDateTime64BestEffortOrNull(JSONExtractString(after, 'due_date'), 6) AS due_date,
    parseDateTime64BestEffortOrNull(JSONExtractString(after, 'ship_date'), 6) AS ship_date,
    JSONExtractInt(after, 'status') AS status,
    JSONExtractUInt(after, 'online_order_flag') AS online_order_flag,
    JSONExtractString(after, 'sales_order_number') AS sales_order_number,
    JSONExtractUInt(after, 'customer_id') AS customer_id,
    JSONExtractUInt(after, 'sales_person_id') AS sales_person_id,
    JSONExtractUInt(after, 'territory_id') AS territory_id,
    toDecimal64OrNull(JSONExtractString(after, 'sub_total'), 4) AS sub_total,
    toDecimal64OrNull(JSONExtractString(after, 'tax_amt'), 4) AS tax_amt,
    toDecimal64OrNull(JSONExtractString(after, 'freight'), 4) AS freight,
    toDecimal64OrNull(JSONExtractString(after, 'total_due'), 4) AS total_due,
    parseDateTime64BestEffortOrNull(JSONExtractString(after, 'modified_date'), 6) AS modified_date,
    if(op = 'd', 1, 0) AS deleted,
    op,
    ts_ms,
    lsn
FROM cdc.aw_events
WHERE source_table = 'active_db.public.sales_order_header'
  AND JSONExtractUInt(if(op = 'd', before, after), 'sales_order_id') > 0;

CREATE VIEW IF NOT EXISTS cdc.sales_order_header_current AS
SELECT
    sales_order_id, revision_number, order_date, due_date, ship_date, status,
    online_order_flag, sales_order_number, customer_id, sales_person_id,
    territory_id, sub_total, tax_amt, freight, total_due, modified_date, op, ts_ms
FROM cdc.sales_order_header_latest FINAL
WHERE deleted = 0;

-- --- Typed current state: product_inventory -------------------------------
-- Composite key (product_id, location_id), so both go in ORDER BY and the
-- delete key is read from `key`.
CREATE TABLE IF NOT EXISTS cdc.product_inventory_current_state (
    product_id    UInt64,
    location_id   UInt64,
    shelf         Nullable(String),
    bin           Nullable(Int64),
    quantity      Nullable(Int64),
    modified_date Nullable(DateTime64(6)),
    deleted       UInt8 DEFAULT 0,
    op            String,
    ts_ms         UInt64,
    lsn           UInt64
) ENGINE = ReplacingMergeTree(lsn)
ORDER BY (product_id, location_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS cdc.product_inventory_current_state_mv TO cdc.product_inventory_current_state AS
SELECT
    JSONExtractUInt(if(op = 'd', before, after), 'product_id') AS product_id,
    JSONExtractUInt(if(op = 'd', before, after), 'location_id') AS location_id,
    JSONExtractString(after, 'shelf') AS shelf,
    JSONExtractInt(after, 'bin') AS bin,
    JSONExtractInt(after, 'quantity') AS quantity,
    parseDateTime64BestEffortOrNull(JSONExtractString(after, 'modified_date'), 6) AS modified_date,
    if(op = 'd', 1, 0) AS deleted,
    op,
    ts_ms,
    lsn
FROM cdc.aw_events
WHERE source_table = 'active_db.public.product_inventory'
  AND JSONExtractUInt(if(op = 'd', before, after), 'product_id') > 0;

CREATE VIEW IF NOT EXISTS cdc.product_inventory_current AS
SELECT product_id, location_id, shelf, bin, quantity, modified_date, op, ts_ms
FROM cdc.product_inventory_current_state FINAL
WHERE deleted = 0;
