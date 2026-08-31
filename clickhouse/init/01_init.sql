-- CDC landing zone: consumes the Debezium change stream for active_db.public.orders
-- from Kafka and lands it into a MergeTree table (full history per (id, ts_ms)).

CREATE DATABASE IF NOT EXISTS cdc;

-- Raw Kafka queue: each message is the whole Debezium envelope as a single string.
CREATE TABLE cdc.orders_kafka (
    raw String
) ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'active_db.public.orders',
    kafka_group_name = 'clickhouse_orders',
    kafka_format = 'JSONAsString';

-- Target table: full CDC history, every version of a row kept.
CREATE TABLE cdc.orders (
    id            UInt64,
    customer_name String,
    amount        Decimal(12, 2),
    status        String,
    created_at    DateTime64(6),
    updated_at    DateTime64(6),
    deleted_at    Nullable(DateTime64(6)),
    op            String,
    ts_ms         UInt64
) ENGINE = MergeTree
ORDER BY (id, ts_ms);

-- Parse the Debezium envelope and land it into MergeTree.
-- parseDateTime64BestEffortOrNull: returns NULL instead of throwing on empty/unparseable
-- values (deleted_at is an empty string when the row is not soft-deleted).
CREATE MATERIALIZED VIEW cdc.orders_mv TO cdc.orders AS
SELECT
    JSONExtractUInt(raw, 'after', 'id') AS id,
    JSONExtractString(raw, 'after', 'customer_name') AS customer_name,
    toDecimal64(JSONExtractString(raw, 'after', 'amount'), 2) AS amount,
    JSONExtractString(raw, 'after', 'status') AS status,
    parseDateTime64BestEffortOrNull(JSONExtractString(raw, 'after', 'created_at'), 6) AS created_at,
    parseDateTime64BestEffortOrNull(JSONExtractString(raw, 'after', 'updated_at'), 6) AS updated_at,
    parseDateTime64BestEffortOrNull(JSONExtractString(raw, 'after', 'deleted_at'), 6) AS deleted_at,
    JSONExtractString(raw, 'op') AS op,
    JSONExtractUInt(raw, 'ts_ms') AS ts_ms
FROM cdc.orders_kafka
WHERE JSONExtractString(raw, 'op') IN ('r', 'c', 'u');