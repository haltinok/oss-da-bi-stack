"""Backfill simulated internet and reseller orders for a past date range in postgres_active.

The seeded AdventureWorks history (shifted forward by dbt's `date_shift_years`)
ends on 2026-06-30, and the live simulator only creates orders from the day it
first ran, which leaves an empty stretch between the two. This fills it with
orders dated inside the range and already at a final status (mostly shipped,
a few rejected or cancelled), since the simulator only advances orders from the
last day:

* internet -- built exactly like the live simulator's (`insert_sales_order`);
* reseller -- the simulator never creates these, so they are modelled here on
  the seeded reseller history: a store customer with its salesperson and
  territory, line count, quantity and product drawn from the history's own
  distributions, unit price at the history's ~59% of list, and an occasional
  special-offer discount.

Rows get `modified_date = now()`, so the incremental `postgres_active_to_postgres_aw`
pipeline picks them up on its next run like any other change.

Idempotent: a day (internet) or month (reseller, ~11 orders/month) that already
has orders of that channel is skipped, so the script can be re-run safely.
That check is made on **star-schema dates**, not the dates stored here: the
seeded history is still dated 2011-2014 in this database and dbt shifts it
forward by `date_shift_years` on the way into the star, so a day that looks
empty here may already be populated in the warehouse. The shift is read from
the dbt project (--dbt-project) rather than duplicated.

This also makes it safe to fill the gaps *inside* the seeded history, which is
sparse because the seed is a ~10% sample of AdventureWorks: 794 of the 1127 days
it spans carry orders, the rest none, and the thinning is worst in the earliest
year (47% of days populated in the first year, 99% in the last).

    # inside an Airflow container (has the driver, Faker and POSTGRES_PASSWORD)
    python /opt/airflow/scripts/backfill_adventureworks_orders.py \
        --start 2026-07-01 [--end 2026-10-01] [--channel both|internet|reseller]

    # fill the gaps in the shifted seed history (dates are post-shift)
    python /opt/airflow/scripts/backfill_adventureworks_orders.py \
        --start 2023-06-01 --end 2026-07-01

--end defaults to today (exclusive); periods already filled are skipped.
"""

import argparse
import math
import os
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import yaml

from simulate_adventureworks import (
    DUE_DATE_DAYS,
    REVISION_NUMBER,
    SHIP_DATE_DAYS,
    SHIPPED_STATUS,
    _connect,
    _next_id,
    _pick,
    insert_sales_order,
    load_keys,
)

# The dbt project whose date-shift vars have to be honoured; the compose stack
# mounts ./dbt at /opt/airflow/dbt.
DEFAULT_DBT_PROJECT = os.environ.get(
    "DBT_PROJECT_DIR", "/opt/airflow/dbt/adventureworks_dwh"
)

# Final statuses for orders that are already in the past: 5 shipped, 4 rejected,
# 6 cancelled (the live simulator's long-run mix is roughly the same).
FINAL_STATUSES = [5, 4, 6]
FINAL_WEIGHTS = [96, 2, 2]


# Average orders per day, from the seeded history (internet: the live simulator's
# default rate; reseller: 11.1 orders/month over 33 months).
DEFAULT_RATE = {"internet": 14.0, "reseller": 11.1 * 12 / 365}


def period(channel, day):
    """Idempotency unit: a day for internet, a month for the much sparser reseller."""
    return day if channel == "internet" else (day.year, day.month)


def dbt_date_shift(project_dir):
    """Read `date_shift_years` / `date_shift_cutoff` from dbt_project.yml.

    These have to match what dbt applies, so they are read from the project
    rather than duplicated here. Returns (years, cutoff_date).
    """
    path = Path(project_dir) / "dbt_project.yml"
    with path.open() as fh:
        project_vars = (yaml.safe_load(fh) or {}).get("vars") or {}
    if "date_shift_years" not in project_vars:
        raise KeyError(f"date_shift_years not found in {path}")
    years = int(project_vars["date_shift_years"])
    cutoff = project_vars.get("date_shift_cutoff", "2015-01-01")
    if isinstance(cutoff, date):
        return years, cutoff
    return years, date.fromisoformat(str(cutoff))


def periods_with_orders(cur, channel, start, end, shift_years, shift_cutoff):
    """Periods already carrying orders of this channel, in star-schema dates.

    The comparison has to happen on the date the warehouse will show, not the
    one stored here, because two different vintages live in this table:

    * rows the simulator or an earlier backfill wrote, already current-dated and
      past the cutoff, which dbt passes through unchanged;
    * the seeded AdventureWorks history, still dated 2011-2014, which dbt's
      shift_history_date macro moves forward by `date_shift_years`.

    Matching on the stored date made every seeded day look empty -- a backfill
    over the shifted history's window would have filled all ~1127 days of it,
    doubling the volume on the ~794 that already had orders.
    """
    cur.execute(
        """
        SELECT DISTINCT star_date FROM (
            SELECT CASE
                       WHEN order_date < %(cutoff)s
                           THEN (order_date + make_interval(years => %(years)s))::date
                       ELSE order_date::date
                   END AS star_date
            FROM public.sales_order_header
            WHERE online_order_flag = %(online)s
        ) shifted
        WHERE star_date >= %(start)s AND star_date < %(end)s
        """,
        {
            "cutoff": shift_cutoff,
            "years": shift_years,
            "online": channel == "internet",
            "start": start,
            "end": end,
        },
    )
    return {period(channel, row[0]) for row in cur.fetchall()}


def poisson(lam):
    """Knuth's method; fine for the small daily rates used here."""
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= random.random()
        if p <= limit:
            return k
        k += 1


def load_reseller_keys(cur):
    """Empirical distributions of the seeded reseller history, plus valid stores."""
    hist = "SELECT sales_order_id FROM public.sales_order_header WHERE NOT online_order_flag"
    cur.execute(
        f"SELECT d.product_id, p.list_price, d.order_qty FROM public.sales_order_detail d "
        f"JOIN public.product p USING (product_id) WHERE d.sales_order_id IN ({hist})"
    )
    lines = [(r[0], float(r[1]), r[2]) for r in cur.fetchall()]
    cur.execute(
        f"SELECT count(*) FROM public.sales_order_detail WHERE sales_order_id IN ({hist}) "
        "GROUP BY sales_order_id"
    )
    line_counts = [r[0] for r in cur.fetchall()]
    # Order customer = the store's contact row (person set); the DWH resolves the
    # reseller through the store's own customer row (person null), so require both.
    # Salesperson: the store's, else any salesperson in the customer's territory.
    cur.execute(
        """
        SELECT c.customer_id, c.territory_id, coalesce(s.sales_person_id, (
                   SELECT sp.business_entity_id FROM public.sales_person sp
                   WHERE sp.territory_id = c.territory_id LIMIT 1))
        FROM public.customer c
        JOIN public.store s ON s.business_entity_id = c.store_id
        WHERE c.person_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM public.customer sc
                      WHERE sc.store_id = c.store_id AND sc.person_id IS NULL)
        """
    )
    stores = [r for r in cur.fetchall() if r[2] is not None]
    cur.execute(
        "SELECT special_offer_id, discount_pct FROM public.special_offer "
        "WHERE special_offer_id <> 1 AND discount_pct > 0"
    )
    offers = [(r[0], float(r[1])) for r in cur.fetchall()]
    return {"lines": lines, "line_counts": line_counts, "stores": stores, "offers": offers}


def insert_reseller_order(cur, keys, rkeys, order_date, status):
    order_id = _next_id(cur, "sales_order_header", "sales_order_id")
    now = datetime.now(timezone.utc)
    customer_id, territory_id, sales_person_id = random.choice(rkeys["stores"])
    n_lines = random.choice(rkeys["line_counts"])
    lines, seen, sub_total = [], set(), 0.0
    while len(lines) < n_lines and len(seen) < len(rkeys["lines"]):
        product_id, list_price, qty = random.choice(rkeys["lines"])
        if product_id in seen:
            continue
        seen.add(product_id)
        unit_price = round(list_price * 0.59, 4)
        offer_id, discount = 1, 0.0
        if rkeys["offers"] and random.random() < 0.063:
            offer_id, discount = random.choice(rkeys["offers"])
        line_total = round(unit_price * qty * (1 - discount), 4)
        sub_total += line_total
        lines.append((len(lines) + 1, product_id, offer_id, unit_price, discount, qty, line_total))

    tax = round(sub_total * 0.08, 4)
    freight = round(sub_total * 0.025, 4)  # AdventureWorks charges 2.5% of sub_total
    cur.execute(
        """
        INSERT INTO public.sales_order_header (
            rowguid, sales_order_id, revision_number, order_date, due_date, ship_date,
            status, online_order_flag, sales_order_number, purchase_order_number,
            customer_id, sales_person_id, territory_id, bill_to_address_id,
            ship_to_address_id, ship_method_id, sub_total, tax_amt, freight,
            total_due, modified_date
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, false, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s)
        """,
        (
            str(uuid.uuid4()), order_id, REVISION_NUMBER, order_date,
            order_date + timedelta(days=DUE_DATE_DAYS),
            # Same rule as the internet path: a ship date only on a shipped order.
            (order_date + timedelta(days=SHIP_DATE_DAYS)
             if status == SHIPPED_STATUS else None),
            status, f"SO{order_id:05d}", f"PO{random.randint(10**9, 10**10 - 1)}",
            customer_id, sales_person_id, territory_id, _pick(keys["address_id"]),
            _pick(keys["address_id"]), _pick(keys["ship_method_id"]),
            sub_total, tax, freight, round(sub_total + tax + freight, 4), now,
        ),
    )
    for line_no, product_id, offer_id, unit_price, discount, qty, line_total in lines:
        cur.execute(
            """
            INSERT INTO public.sales_order_detail (
                rowguid, sales_order_id, sales_order_detail_id, order_qty, product_id,
                special_offer_id, unit_price, unit_price_discount, line_total, modified_date
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (str(uuid.uuid4()), order_id, line_no, qty, product_id, offer_id,
             unit_price, discount, line_total, now),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, help="exclusive; default: today")
    parser.add_argument("--channel", choices=["both", "internet", "reseller"], default="both")
    parser.add_argument("--seed", type=int, help="random seed, for a reproducible backfill")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report the periods that would be filled, write nothing",
    )
    parser.add_argument(
        "--dbt-project", default=DEFAULT_DBT_PROJECT,
        help="dbt project to read date_shift_years/date_shift_cutoff from "
             f"(default: {DEFAULT_DBT_PROJECT})",
    )
    args = parser.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    shift_years, shift_cutoff = dbt_date_shift(args.dbt_project)
    # The dates written here are literal, so a range reaching below the cutoff
    # would itself be shifted forward by dbt and land somewhere else entirely.
    if shift_years and args.start < shift_cutoff:
        parser.error(
            f"--start {args.start} is before the dbt date_shift_cutoff "
            f"{shift_cutoff}: dbt would shift these rows forward by "
            f"{shift_years} years. Backfill at the shifted dates instead."
        )

    conn = _connect()
    try:
        with conn, conn.cursor() as cur:
            end = args.end or datetime.now(timezone.utc).date()
            if end <= args.start:
                print(f"backfill: nothing to do (start={args.start}, end={end})")
                return
            keys = load_keys(cur)
            channels = ["internet", "reseller"] if args.channel == "both" else [args.channel]
            rkeys = load_reseller_keys(cur) if "reseller" in channels else None
            for channel in channels:
                done = periods_with_orders(
                    cur, channel, args.start, end, shift_years, shift_cutoff
                )
                orders, filled = 0, set()
                day = args.start
                while day < end:
                    if period(channel, day) not in done:
                        filled.add(period(channel, day))
                        for _ in range(poisson(DEFAULT_RATE[channel])):
                            at = datetime.combine(day, time(), timezone.utc) + timedelta(
                                seconds=random.randint(0, 86_399)
                            )
                            status = random.choices(FINAL_STATUSES, FINAL_WEIGHTS)[0]
                            if args.dry_run:
                                pass
                            elif channel == "internet":
                                insert_sales_order(cur, keys, order_date=at, status=status)
                            else:
                                insert_reseller_order(cur, keys, rkeys, at, status)
                            orders += 1
                    day += timedelta(days=1)
                unit = "days" if channel == "internet" else "months"
                print(f"backfill{' (dry run)' if args.dry_run else ''} {channel}: "
                      f"{orders} orders over {args.start}..{end} (exclusive) into "
                      f"{len(filled)} empty {unit}, {len(done)} {unit} already present")
            if args.dry_run:
                conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
