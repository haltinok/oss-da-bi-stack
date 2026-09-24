-- CDC landing zone: consumes the Debezium change stream for active_db.public.orders
-- from Kafka and lands it into a MergeTree table (full history per (id, ts_ms)).
--
-- `cdc.orders` is append-only history -- one row per change event, so every
-- version of a row is kept and a consumer that does not de-duplicate will
-- double-count. Use the current-state views below for reporting.

CREATE DATABASE IF NOT EXISTS cdc;

-- Raw Kafka queue: each message is the whole Debezium envelope as a single string.
--
-- The table must have exactly ONE column: the JSONAsString input format only
-- accepts a single String column, and declaring _error/_raw_message as real
-- columns makes ClickHouse reject every message with
-- "This input format is only suitable for tables with a single column of type
-- String or Object, but the number of columns is 3". With
-- kafka_handle_error_mode = 'stream' those two names are exposed as *virtual*
-- columns instead, which is why the rejected-message view below can select them.
CREATE TABLE cdc.orders_kafka (
    raw String
) ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'active_db.public.orders',
    kafka_group_name = 'clickhouse_orders',
    kafka_format = 'JSONAsString',
    kafka_handle_error_mode = 'stream',
    kafka_skip_broken_messages = 1;

-- Target table: full CDC history, every version of a row kept.
-- amount/created_at/updated_at are Nullable because the *OrNull extraction below
-- can legitimately fail (a tombstone has no `after` block at all); the previous
-- non-Nullable columns plus toDecimal64() made one bad message throw and stall
-- the materialized view.
CREATE TABLE cdc.orders (
    id            UInt64,
    customer_name String,
    amount        Nullable(Decimal(12, 2)),
    status        String,
    created_at    Nullable(DateTime64(6)),
    updated_at    Nullable(DateTime64(6)),
    deleted_at    Nullable(DateTime64(6)),
    op            String,
    ts_ms         UInt64
) ENGINE = MergeTree
ORDER BY (id, ts_ms);

-- Messages that were not landed, so that nothing disappears without a trace.
CREATE TABLE cdc.orders_kafka_rejected (
    raw     String,
    reason  String,
    seen_at DateTime DEFAULT now()
) ENGINE = MergeTree
ORDER BY seen_at;

-- Parse the Debezium envelope and land it into MergeTree.
-- *OrNull extraction: returns NULL instead of throwing on empty/unparseable
-- values (deleted_at is an empty string when the row is not soft-deleted, and
-- `after` is absent entirely for hard deletes).
--
-- Only 'r' (snapshot read), 'c' (insert) and 'u' (update) are landed. Hard
-- deletes ('d') are deliberately NOT landed: they carry no `after` image, and
-- the simulated workload only ever soft-deletes (sets `deleted_at`), which
-- arrives as an 'u'. They are not dropped silently -- the view below routes
-- them to cdc.orders_kafka_rejected. Capturing them properly would need
-- REPLICA IDENTITY FULL on the source table (see
-- postgres_active/init/01_init.sql).
CREATE MATERIALIZED VIEW cdc.orders_mv TO cdc.orders AS
SELECT
    JSONExtractUInt(raw, 'after', 'id') AS id,
    JSONExtractString(raw, 'after', 'customer_name') AS customer_name,
    toDecimal64OrNull(JSONExtractString(raw, 'after', 'amount'), 2) AS amount,
    JSONExtractString(raw, 'after', 'status') AS status,
    parseDateTime64BestEffortOrNull(JSONExtractString(raw, 'after', 'created_at'), 6) AS created_at,
    parseDateTime64BestEffortOrNull(JSONExtractString(raw, 'after', 'updated_at'), 6) AS updated_at,
    parseDateTime64BestEffortOrNull(JSONExtractString(raw, 'after', 'deleted_at'), 6) AS deleted_at,
    JSONExtractString(raw, 'op') AS op,
    JSONExtractUInt(raw, 'ts_ms') AS ts_ms
FROM cdc.orders_kafka
WHERE JSONExtractString(raw, 'op') IN ('r', 'c', 'u');

-- Anything that is NOT landed: an error raised while processing the message
-- (_error), or a payload whose op code is not one of r/c/u (hard deletes,
-- truncated payloads, non-JSON noise). Without this, those messages vanish
-- without any signal. _raw_message/_error are virtual columns supplied by
-- kafka_handle_error_mode = 'stream'.
CREATE MATERIALIZED VIEW cdc.orders_kafka_rejected_mv TO cdc.orders_kafka_rejected AS
SELECT
    if(_error != '', _raw_message, raw) AS raw,
    if(
        _error != '',
        _error,
        concat('unhandled op code: ', JSONExtractString(raw, 'op'))
    ) AS reason
FROM cdc.orders_kafka
WHERE _error != '' OR JSONExtractString(raw, 'op') NOT IN ('r', 'c', 'u');

-- Current state: the newest version of each order. This is what reporting should
-- read -- querying cdc.orders directly returns every historical version.
CREATE VIEW cdc.orders_current AS
SELECT
    id,
    customer_name,
    amount,
    status,
    created_at,
    updated_at,
    deleted_at,
    op,
    ts_ms
FROM (
    SELECT
        *,
        row_number() OVER (PARTITION BY id ORDER BY ts_ms DESC) AS version_rank
    FROM cdc.orders
)
WHERE version_rank = 1;

-- Current state excluding soft-deleted orders (the dashboard-ready view).
CREATE VIEW cdc.orders_active AS
SELECT
    id,
    customer_name,
    amount,
    status,
    created_at,
    updated_at,
    op,
    ts_ms
FROM cdc.orders_current
WHERE deleted_at IS NULL;
