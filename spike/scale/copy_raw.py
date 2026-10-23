"""Copy every table and view of a schema from one StarRocks to another over the MySQL protocol.

The 250M / 500M tiers are built on the machine that has the full AdventureWorks copy (the spike stack's `raw`);
this moves that `raw` to the server that will host the demo, so nothing has to be ingested again.

  uv run --with pymysql python -I spike/scale/copy_raw.py --src 127.0.0.1:9030 --dst 127.0.0.1:19030 [--dst-schema raw_spike]

  --src / --dst        host:port of each StarRocks frontend (the demo server's through `ssh -L 19030:localhost:9030 demo`)
  --src-schema         schema to copy (default raw)
  --dst-schema         where it lands (default raw_spike, see below)
  --batch              rows per INSERT (default 5000)
  SRC_USER / DST_USER, SRC_PASSWORD / DST_PASSWORD   from the environment (default root, empty); never on the command line

Per base table: SHOW CREATE TABLE on the source, DROP and CREATE on the target, then the rows streamed with an
unbuffered cursor in batches via executemany INSERT. Views follow once every table is there (SHOW CREATE VIEW, with
the source schema's name rewritten to the target's inside the definition, e.g. recon_deleted_*). At the end it prints
source and target row counts for every table and view and exits 1 on any mismatch.

Why the default target is `raw_spike` and not `raw`: on a server that also runs the live pipeline, `raw` is the live
pipeline's schema. Dropping and recreating its tables would destroy the live data and the next 5-minute cycle would
merge postgres_active rows into the copy. The script therefore refuses `raw` on a target that already has a `raw`
holding the live pipeline's tables, unless --overwrite-live-raw is given.
"""
import argparse
import os
import re
import sys
import time

import pymysql

# Tables only the live pipeline creates (airflow/scripts/ingest_starrocks.py): their presence marks a live `raw`.
LIVE_MARKERS = {"pk_sales_order_header"}


def connect(addr: str, user: str, password: str, schema: str | None = None, stream: bool = False):
    host, _, port = addr.rpartition(":")
    return pymysql.connect(host=host or "127.0.0.1", port=int(port), user=user, password=password, database=schema, autocommit=True,
                           read_timeout=7200, write_timeout=7200, charset="utf8mb4",
                           cursorclass=pymysql.cursors.SSCursor if stream else pymysql.cursors.Cursor)


def listing(conn, schema: str) -> tuple[list[str], list[str]]:
    with conn.cursor() as cur:
        cur.execute("select table_name, table_type from information_schema.tables where table_schema = %s order by table_name", (schema,))
        rows = cur.fetchall()
    return [n for n, t in rows if t == "BASE TABLE"], [n for n, t in rows if t == "VIEW"]


def create_sql(conn, kind: str, schema: str, name: str) -> str:
    with conn.cursor() as cur:
        cur.execute(f"SHOW CREATE {kind} `{schema}`.`{name}`")
        return cur.fetchone()[1]


def retarget(ddl: str, src: str, dst: str) -> str:
    """Point a definition's `src` schema references at `dst` (a view names its tables as `raw`.`t`)."""
    return re.sub(rf"`{re.escape(src)}`\.", f"`{dst}`.", ddl) if src != dst else ddl


def copy_table(src_args, dst_args, src_schema: str, dst_schema: str, name: str, batch: int, attempts: int = 6) -> int:
    """One table, retried from scratch when the StarRocks it reads from runs out of query memory (a busy server, e.g.
    Cube rebuilding rollups on the source): the target table is dropped and recreated on each attempt."""
    for attempt in range(1, attempts + 1):
        try:
            return copy_table_once(src_args, dst_args, src_schema, dst_schema, name, batch)
        except pymysql.err.MySQLError as exc:
            memory = "exceed limit" in str(exc) or "Memory" in str(exc)
            if attempt == attempts or not memory:
                raise
            wait = 30 * attempt
            print(f"  table {name}: the server is short of memory, retrying in {wait}s ({attempt}/{attempts - 1})", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")


def copy_table_once(src_args, dst_args, src_schema: str, dst_schema: str, name: str, batch: int) -> int:
    src, dst = src_args["conn"], dst_args["conn"]
    ddl = create_sql(src, "TABLE", src_schema, name)
    with dst.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS `{dst_schema}`.`{name}`")
        cur.execute(f"USE `{dst_schema}`")
        cur.execute(ddl)
    total = 0
    stream = connect(src_args["addr"], src_args["user"], src_args["password"], src_schema, stream=True)
    try:
        with stream.cursor() as read, dst.cursor() as write:
            read.execute(f"SELECT * FROM `{src_schema}`.`{name}`")
            marks = ", ".join(["%s"] * len(read.description))
            sql = f"INSERT INTO `{dst_schema}`.`{name}` VALUES ({marks})"
            while rows := read.fetchmany(batch):
                write.executemany(sql, rows)
                total += len(rows)
    finally:
        stream.close()
    return total


def count(conn, schema: str, name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM `{schema}`.`{name}`")
        return cur.fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="host:port of the source StarRocks frontend")
    ap.add_argument("--dst", required=True, help="host:port of the target StarRocks frontend")
    ap.add_argument("--src-schema", default="raw")
    ap.add_argument("--dst-schema", default="raw_spike")
    ap.add_argument("--batch", type=int, default=5000)
    ap.add_argument("--overwrite-live-raw", action="store_true", help="allow --dst-schema raw on a target whose raw is the live pipeline's")
    args = ap.parse_args()

    s_cfg = {"addr": args.src, "user": os.environ.get("SRC_USER", "root"), "password": os.environ.get("SRC_PASSWORD", "")}
    d_cfg = {"addr": args.dst, "user": os.environ.get("DST_USER", "root"), "password": os.environ.get("DST_PASSWORD", "")}
    s_cfg["conn"], d_cfg["conn"] = connect(**s_cfg), connect(**d_cfg)
    tables, views = listing(s_cfg["conn"], args.src_schema)
    if not tables:
        sys.exit(f"{args.src_schema} on {args.src} has no tables")

    target_tables, _ = listing(d_cfg["conn"], args.dst_schema)
    if args.dst_schema == "raw" and LIVE_MARKERS & set(target_tables) and not args.overwrite_live_raw:
        sys.exit(f"refusing: `raw` on {args.dst} holds the live pipeline's tables ({', '.join(sorted(LIVE_MARKERS & set(target_tables)))}). "
                 "Copying into it would drop them. Use --dst-schema raw_spike (the default), or --overwrite-live-raw on a server with no live pipeline.")
    with d_cfg["conn"].cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{args.dst_schema}`")

    print(f"copying {len(tables)} tables and {len(views)} views: {args.src}/{args.src_schema} -> {args.dst}/{args.dst_schema}", flush=True)
    for name in tables:
        t0 = time.time()
        n = copy_table(s_cfg, d_cfg, args.src_schema, args.dst_schema, name, args.batch)
        print(f"  table {name:<34} {n:>10} rows  {time.time() - t0:5.1f}s", flush=True)
    with d_cfg["conn"].cursor() as cur:
        cur.execute(f"USE `{args.dst_schema}`")
        for name in views:
            ddl = retarget(create_sql(s_cfg["conn"], "VIEW", args.src_schema, name), args.src_schema, args.dst_schema)
            cur.execute(f"DROP VIEW IF EXISTS `{args.dst_schema}`.`{name}`")
            cur.execute(ddl)
            print(f"  view  {name}", flush=True)

    print("\nrow counts (source vs target):")
    bad = []
    for name in [*tables, *views]:
        a, b = count(s_cfg["conn"], args.src_schema, name), count(d_cfg["conn"], args.dst_schema, name)
        flag = "" if a == b else "   <-- MISMATCH"
        print(f"  {name:<34} {a:>10} {b:>10}{flag}")
        if a != b:
            bad.append(name)
    if bad:
        print(f"\nFAILED: {len(bad)} object(s) differ: {', '.join(bad)}", file=sys.stderr)
        return 1
    print(f"\nOK: {len(tables)} tables and {len(views)} views match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
