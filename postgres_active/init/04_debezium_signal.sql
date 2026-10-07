-- Debezium incremental-snapshot signalling table (source channel).
--
-- The connector's initial snapshot only runs once, at connector start. Tables
-- added to `table.include.list` afterwards start *streaming* from the current
-- WAL position but are not backfilled. Inserting an `execute-snapshot` row here
-- asks Debezium to snapshot them on demand, without re-snapshotting orders.
--
-- Read by Debezium over JDBC (signal.enabled.channels=source); the `debezium`
-- role already has SELECT on it through the ALTER DEFAULT PRIVILEGES in
-- 01_init.sql. Not part of the CDC stream itself.
CREATE TABLE IF NOT EXISTS public.debezium_signal (
    id   varchar(42) PRIMARY KEY,
    type varchar(32) NOT NULL,
    data varchar(2048)
);

-- The incremental snapshot writes its `open`/`close` window signals back into
-- this table, so `debezium` needs more than the SELECT that the schema-wide
-- default privileges grant it.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.debezium_signal TO debezium;
