"""Copy the warehouse star schema (``analytics.mart``) into ClickHouse.

The star (``dim_*`` / ``fact_*``) is built by dbt in Postgres. This script mirrors
each table into a ClickHouse database ``mart`` so the same tables can be browsed
and queried in ClickHouse (fast OLAP), exactly like ``cdc.aw_events`` is.

It uses ClickHouse's built-in ``postgresql()`` table function -- no extra driver
and no staging: each run does ``CREATE OR REPLACE TABLE mart.<t> AS SELECT * FROM
postgresql(...)``. The star is small (dimensions hundreds of rows, facts a few
thousand), so a full rebuild every run is cheap and always matches the latest
``dbt build``.

The Postgres password travels in the query text, so ``log_queries=0`` is set on
the ClickHouse session to keep it out of ``system.query_log``.

Run it as the last task of the ``postgres_active_to_postgres_aw`` DAG, right after
``dbt build``. If ClickHouse is not running (the ``cdc``/``bi`` profiles are not
active) it skips instead of failing.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import psycopg2

# ClickHouse HTTP interface.
CH_URL = os.environ.get("CLICKHOUSE_URL", "http://clickhouse:8123")
CH_USER = os.environ.get("CLICKHOUSE_USER", "clickhouse")
CH_PASSWORD = os.environ["CLICKHOUSE_PASSWORD"]
CH_DATABASE = os.environ.get("CLICKHOUSE_MART_DATABASE", "mart")

# Warehouse Postgres (the dbt target).
PG_HOST = os.environ.get("DBT_PG_HOST", "postgres")
PG_PORT = os.environ.get("DBT_PG_PORT", "5432")
PG_DATABASE = os.environ.get("DBT_PG_DATABASE", "analytics")
# Read the mart as the read-only BI role (`bi_ro`), not the postgres superuser.
PG_USER = os.environ.get("BI_DB_USER", "bi_ro")
PG_PASSWORD = os.environ["BI_READONLY_PASSWORD"]
PG_SCHEMA = "mart"


class ClickHouseUnavailable(Exception):
    """ClickHouse is not running/reachable (e.g. the cdc/bi profile is off)."""


def ch_query(sql: str) -> str:
    """Run one statement over the ClickHouse HTTP interface and return the body."""
    # Credentials go in headers, not the URL: URLs end up in proxy/access logs.
    params = urllib.parse.urlencode({"log_queries": "0"})
    request = urllib.request.Request(
        f"{CH_URL}/?{params}",
        data=sql.encode(),
        method="POST",
        headers={"X-ClickHouse-User": CH_USER, "X-ClickHouse-Key": CH_PASSWORD},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.read().decode()
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"ClickHouse error ({exc.code}): {exc.read().decode()}"
        ) from exc
    except urllib.error.URLError as exc:
        # Not running / DNS failure: the cdc|bi profile is off. Caller decides.
        raise ClickHouseUnavailable(str(exc)) from exc


def mart_tables() -> list[str]:
    """The base tables in the warehouse `mart` schema, from Postgres itself."""
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DATABASE, user=PG_USER, password=PG_PASSWORD
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select table_name from information_schema.tables
                where table_schema = %s and table_type = 'BASE TABLE'
                order by table_name
                """,
                (PG_SCHEMA,),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def sql_string(value: str) -> str:
    """Quote `value` as a ClickHouse string literal (escapes backslash and quote)."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def copy_table(table: str) -> int:
    args = ", ".join(
        sql_string(v)
        for v in (f"{PG_HOST}:{PG_PORT}", PG_DATABASE, table, PG_USER, PG_PASSWORD, PG_SCHEMA)
    )
    source = f"postgresql({args})"
    ch_query(
        f"CREATE OR REPLACE TABLE {CH_DATABASE}.{table} "
        f"ENGINE = MergeTree ORDER BY tuple() AS SELECT * FROM {source}"
    )
    return int(ch_query(f"SELECT count() FROM {CH_DATABASE}.{table}").strip())


def _sync() -> None:
    ch_query(f"CREATE DATABASE IF NOT EXISTS {CH_DATABASE}")
    tables = mart_tables()
    if not tables:
        print("sync_mart_to_clickhouse: no tables in mart schema", file=sys.stderr)
        sys.exit(1)
    total = 0
    for table in tables:
        rows = copy_table(table)
        total += rows
        print(f"{table}: {rows} rows")
    print(f"sync_mart_to_clickhouse: copied {len(tables)} tables, {total} rows into {CH_DATABASE}")


def main() -> None:
    try:
        _sync()
    except ClickHouseUnavailable as exc:
        # A core-only stack (no cdc/bi profile) has no ClickHouse. Exit 99 so the
        # DAG's BashOperator (skip_on_exit_code=99) marks the task SKIPPED rather
        # than SUCCESS: a ClickHouse that is down by accident must not look like
        # a clean skip.
        print(
            "sync_mart_to_clickhouse: ClickHouse not reachable, skipping the mart copy "
            f"(start it with --profile cdc or --profile bi). [{exc}]"
        )
        sys.exit(99)


if __name__ == "__main__":
    main()
