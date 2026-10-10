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

    # inside an Airflow container (has the driver, Faker and POSTGRES_PASSWORD)
    python /opt/airflow/scripts/backfill_adventureworks_orders.py \
        --start 2026-07-01 [--end 2026-10-01] [--channel both|internet|reseller]

--end defaults to today (exclusive); days the simulator already filled are skipped.
"""

import argparse
import math
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone

from simulate_adventureworks import (
    REVISION_NUMBER,
    _connect,
    _next_id,
    _pick,
    insert_sales_order,
    load_keys,
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


def periods_with_orders(cur, channel, start, end):
    cur.execute(
        """
        SELECT DISTINCT order_date::date FROM public.sales_order_header
        WHERE order_date >= %s AND order_date < %s AND online_order_flag = %s
        """,
        (start, end, channel == "internet"),
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
            order_date + timedelta(days=12), order_date + timedelta(days=7),
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
    args = parser.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

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
                done = periods_with_orders(cur, channel, args.start, end)
                orders = 0
                day = args.start
                while day < end:
                    if period(channel, day) not in done:
                        for _ in range(poisson(DEFAULT_RATE[channel])):
                            at = datetime.combine(day, time(), timezone.utc) + timedelta(
                                seconds=random.randint(0, 86_399)
                            )
                            status = random.choices(FINAL_STATUSES, FINAL_WEIGHTS)[0]
                            if channel == "internet":
                                insert_sales_order(cur, keys, order_date=at, status=status)
                            else:
                                insert_reseller_order(cur, keys, rkeys, at, status)
                            orders += 1
                    day += timedelta(days=1)
                print(f"backfill {channel}: {orders} orders over {args.start}..{end} (exclusive), "
                      f"{len(done)} {'days' if channel == 'internet' else 'months'} already present")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
