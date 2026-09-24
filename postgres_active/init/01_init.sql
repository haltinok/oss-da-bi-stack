-- Debezium replication user (least privilege: replication + select for initial snapshot)
CREATE USER debezium WITH REPLICATION LOGIN PASSWORD 'debezium';

-- Sample table so Debezium has something to stream immediately.
-- id: auto-incrementing (BIGSERIAL) primary key.
CREATE TABLE public.orders (
    id BIGSERIAL PRIMARY KEY,
    customer_name TEXT NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

-- The dlt pipeline reads incrementally on `updated_at` (`WHERE updated_at > $cursor`),
-- which is a sequential scan without this index.
CREATE INDEX IF NOT EXISTS orders_updated_at_idx ON public.orders (updated_at);

-- REPLICA IDENTITY is left at its DEFAULT (primary key only) on purpose: the only
-- consumer of the `before` image is delete handling, and ClickHouse drops the
-- 'd' op (the workload soft-deletes instead). Setting REPLICA IDENTITY FULL would
-- roughly double the WAL for every update for no benefit here. To capture hard
-- deletes, set it and stop filtering 'd' in clickhouse/init/01_init.sql:
--   ALTER TABLE public.orders REPLICA IDENTITY FULL;

-- Keep updated_at in sync on every row update.
CREATE OR REPLACE FUNCTION public.touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER orders_touch_updated_at
    BEFORE UPDATE ON public.orders
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_updated_at();

INSERT INTO public.orders (customer_name, amount, status) VALUES
    ('Acme Corp', 1500.00, 'created'),
    ('Globex', 2300.50, 'created'),
    ('Initech', 450.00, 'created');

-- Grant Debezium the access it needs
GRANT CONNECT ON DATABASE active_db TO debezium;
GRANT USAGE ON SCHEMA public TO debezium;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO debezium;

-- GRANT ... ON ALL TABLES only covers tables that exist now; without this, the
-- initial snapshot fails as soon as someone adds a table to public.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO debezium;

-- pgoutput publication (built-in logical decoding plugin, no extension required)
CREATE PUBLICATION dbz_publication FOR ALL TABLES;
