#!/usr/bin/env python3
"""postgres_active -> StarRocks `raw`, one ingestr run per table (incremental merge).

Run by the `postgres_active_to_starrocks` DAG every 5 minutes; also usable by hand:

    python ingest_starrocks.py [--full-refresh] [table ...]

* The tables are the ones the dbt project reads: every source in
  dbt/adventureworks_starrocks/models/staging/_sources.yml (so adding a source there adds it here).
* Primary keys and the `modified_date` cursor come from the source's own catalog, nothing is
  hard-coded. A table with both is loaded `merge` on `modified_date`, so only changed rows move;
  anything else is replaced in full.
* A merge never sees hard deletes. The live primary keys of sales_order_header are snapshotted
  (full replace) into raw.pk_sales_order_header each run; dbt's staging models drop orders whose
  key is gone (var use_pk_snapshots).
* Connection URIs reach ingestr through its environment variables, not the command line, so the
  passwords never appear in the process list. Tables load in parallel (INGEST_WORKERS, default 4).

Env: POSTGRES_PASSWORD; optional ACTIVE_HOST/PORT/DB/USER (postgres_active:5434/active_db/postgres),
STARROCKS_HOST/PORT/USER/PASSWORD (starrocks-fe:9030/root/none), STARROCKS_RAW_DB (raw).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import psycopg2
import yaml

SOURCES_YML = Path(
    os.environ.get(
        "DBT_SOURCES_YML",
        "/opt/airflow/dbt/adventureworks_starrocks/models/staging/_sources.yml",
    )
)
CURSOR = "modified_date"
# Live primary-key snapshots (full replace each run): dest table -> source query.
PK_SNAPSHOTS = {"pk_sales_order_header": "select sales_order_id from public.sales_order_header"}


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        sys.exit(f"{name} is not set")
    return value


def source_uri() -> str:
    return "postgresql://{u}:{p}@{h}:{port}/{db}".format(
        u=env("ACTIVE_USER", "postgres"),
        p=quote(env("POSTGRES_PASSWORD"), safe=""),
        h=env("ACTIVE_HOST", "postgres_active"),
        port=env("ACTIVE_PORT", "5434"),
        db=env("ACTIVE_DB", "active_db"),
    )


def dest_uri() -> str:
    password = quote(env("STARROCKS_PASSWORD", ""), safe="")
    return "starrocks://{u}:{p}@{h}:{port}/{db}".format(
        u=env("STARROCKS_USER", "root"),
        p=password,
        h=env("STARROCKS_HOST", "starrocks-fe"),
        port=env("STARROCKS_PORT", "9030"),
        db=env("STARROCKS_RAW_DB", "raw"),
    )


def dbt_source_tables() -> list[str]:
    sources = yaml.safe_load(SOURCES_YML.read_text())["sources"]
    names = [t["name"] for s in sources for t in s["tables"]]
    return [n for n in names if not n.startswith("pk_")]


def table_plan(cur, table: str) -> dict:
    """Primary key columns and whether the table has the incremental cursor."""
    cur.execute(
        """
        select a.attname
        from pg_index i
        join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey)
        where i.indrelid = %s::regclass and i.indisprimary
        order by array_position(i.indkey::int2[], a.attnum)
        """,
        (f"public.{table}",),
    )
    pk = [r[0] for r in cur.fetchall()]
    cur.execute(
        "select 1 from information_schema.columns "
        "where table_schema = 'public' and table_name = %s and column_name = %s",
        (table, CURSOR),
    )
    return {"table": table, "pk": pk, "cursor": bool(cur.fetchone())}


def plan(tables: list[str]) -> list[dict]:
    conn = psycopg2.connect(
        host=env("ACTIVE_HOST", "postgres_active"),
        port=int(env("ACTIVE_PORT", "5434")),
        dbname=env("ACTIVE_DB", "active_db"),
        user=env("ACTIVE_USER", "postgres"),
        password=env("POSTGRES_PASSWORD"),
        connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            return [table_plan(cur, t) for t in tables]
    finally:
        conn.close()


def run_ingestr(args: list[str], label: str) -> dict:
    run_env = {**os.environ, "INGESTR_SOURCE_URI": source_uri(), "INGESTR_DESTINATION_URI": dest_uri()}
    t0 = time.time()
    proc = subprocess.run(["ingestr", "ingest", *args], env=run_env, capture_output=True, text=True)
    secs = time.time() - t0
    out = (proc.stdout or "") + (proc.stderr or "")
    rows = re.search(r"Total Rows\s*[│|]\s*([\d,]+)", out)
    result = {
        "table": label,
        "ok": proc.returncode == 0 and "Ingestion completed successfully" in out,
        "seconds": round(secs, 1),
        "rows": int(rows.group(1).replace(",", "")) if rows else None,
    }
    if not result["ok"]:
        # keep any credential out of the log
        tail = "\n".join(out.strip().splitlines()[-6:])
        for secret in (env("POSTGRES_PASSWORD"), env("STARROCKS_PASSWORD", "")):
            if secret:
                tail = tail.replace(secret, "***")
        result["error"] = tail
    return result


def load_table(p: dict, full_refresh: bool) -> dict:
    t = p["table"]
    args = ["--source-table", f"public.{t}", "--dest-table", f"raw.{t}"]
    if p["pk"] and p["cursor"]:
        args += ["--incremental-strategy", "merge", "--incremental-key", CURSOR]
        for col in p["pk"]:
            args += ["--primary-key", col]
    else:
        args += ["--incremental-strategy", "replace"]
    if full_refresh:
        args.append("--full-refresh")
    return run_ingestr(args, t)


def load_pk_snapshot(dest: str, query: str) -> dict:
    return run_ingestr(
        ["--source-table", f"query:{query}", "--dest-table", f"raw.{dest}", "--incremental-strategy", "replace"],
        dest,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tables", nargs="*", help="only these tables (default: every dbt source)")
    ap.add_argument("--full-refresh", action="store_true")
    args = ap.parse_args()

    tables = args.tables or dbt_source_tables()
    plans = plan(tables)
    workers = int(env("INGEST_WORKERS", "4"))
    t0 = time.time()
    results: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(load_table, p, args.full_refresh) for p in plans]
        futures += [pool.submit(load_pk_snapshot, d, q) for d, q in PK_SNAPSHOTS.items() if not args.tables]
        for f in cf.as_completed(futures):
            r = f.result()
            results.append(r)
            print(f"{'ok  ' if r['ok'] else 'FAIL'} {r['table']:32s} {r['seconds']:6.1f}s rows={r['rows']}", flush=True)

    failed = [r for r in results if not r["ok"]]
    summary = {
        "tables": len(results),
        "failed": len(failed),
        "rows": sum(r["rows"] or 0 for r in results),
        "seconds": round(time.time() - t0, 1),
        "workers": workers,
    }
    print(json.dumps(summary), flush=True)
    for r in failed:
        print(f"--- {r['table']} failed:\n{r['error']}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
