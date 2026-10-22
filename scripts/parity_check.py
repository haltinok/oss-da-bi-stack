#!/usr/bin/env python3
"""Parity of the old Postgres mart and the new StarRocks mart (run before retiring the old path).

    uv run --with psycopg2-binary --with pymysql python -I scripts/parity_check.py [--env .env]

Both marts are built from the same postgres_active data. Compares, per fact (internet, reseller),
the line count and the sums of sales_amount and total_product_cost for every fiscal year x
territory, plus the row counts of the shared dimensions. Exit code 1 when anything differs.
Amounts must agree to the cent. Connection settings come from .env (published host ports).
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

import psycopg2
import pymysql

FACTS = ("fact_internet_sales", "fact_reseller_sales")
DIMS = ("dim_product", "dim_customer", "dim_geography", "dim_sales_territory", "dim_date")
BY_YEAR_TERRITORY = """
select d.fiscal_year, f.sales_territory_key, count(*),
       round(sum(f.sales_amount), 2), round(sum(coalesce(f.total_product_cost, 0)), 2)
from mart.{fact} f join mart.dim_date d on d.date_key = f.order_date_key
group by 1, 2
"""


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def rows(cursor, sql: str) -> list[tuple]:
    cursor.execute(sql)
    return cursor.fetchall()


def norm(row: tuple) -> tuple:
    return tuple(Decimal(str(v)).quantize(Decimal("0.01")) if isinstance(v, Decimal | float) else v for v in row)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=".env")
    args = ap.parse_args()
    env = read_env(Path(args.env))

    pg = psycopg2.connect(host="localhost", port=int(env.get("POSTGRES_PORT", "5433")), user="postgres",
                          password=env["POSTGRES_PASSWORD"], dbname=env.get("POSTGRES_DB", "analytics")).cursor()
    sr = pymysql.connect(host="127.0.0.1", port=int(env.get("STARROCKS_MYSQL_PORT", "9030")), user="root").cursor()

    bad = 0
    for fact in FACTS:
        old = {(r[0], r[1]): norm(r[2:]) for r in rows(pg, BY_YEAR_TERRITORY.format(fact=fact))}
        new = {(r[0], r[1]): norm(r[2:]) for r in rows(sr, BY_YEAR_TERRITORY.format(fact=fact))}
        diff = sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))
        n_old, n_new = sum(v[0] for v in old.values()), sum(v[0] for v in new.values())
        print(f"{'OK  ' if not diff else 'DIFF'} {fact}: {n_old} vs {n_new} lines, {len(old)} vs {len(new)} year x territory cells")
        for k in diff[:10]:
            print(f"       FY{k[0]} territory {k[1]}: postgres={old.get(k)} starrocks={new.get(k)}")
        bad += len(diff)
    for dim in DIMS:
        a = rows(pg, f"select count(*) from mart.{dim}")[0][0]
        b = rows(sr, f"select count(*) from mart.{dim}")[0][0]
        print(f"{'OK  ' if a == b else 'DIFF'} {dim}: {a} vs {b}")
        bad += a != b
    print("\nparity: " + ("PASS" if not bad else f"FAIL ({bad} differences)"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
