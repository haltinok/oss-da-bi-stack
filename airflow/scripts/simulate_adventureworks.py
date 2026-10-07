"""Randomly mutate the AdventureWorks2016 tables in postgres_active.

Companion to ``simulate_orders.py``: where that script keeps the small ``orders``
table moving, this one makes the AdventureWorks tables behave like a live OLTP
system. Each run performs a random mix of:

* inserts  -- a new sales order with lines, a work order, transaction history,
              product reviews and shopping-cart items (Faker-generated);
* updates  -- price/inventory/status/last-name changes, always bumping
              ``modified_date`` so an incremental consumer can follow along;
* deletes  -- leaf rows only (product reviews, shopping-cart items).

Foreign keys are not enforced in the sandbox, but inserts still reference
existing rows wherever a column points at another table, so the data stays
believable.

Intended to be invoked from an Airflow BashOperator. Connection settings are
taken from environment variables with defaults for the local stack.
"""

import os
import random
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
from faker import Faker

HOST = os.environ.get("POSTGRES_HOST", "postgres_active")
PORT = int(os.environ.get("POSTGRES_PORT", "5434"))
DB = os.environ.get("POSTGRES_DB", "active_db")
USER = os.environ.get("POSTGRES_USER", "postgres")
PASSWORD = os.environ["POSTGRES_PASSWORD"]

# AdventureWorks uses an 8 as the current revision number and small integer
# status codes (1=In process, 2=Approved, 3=Backordered, 4=Rejected, 5=Shipped,
# 6=Cancelled).
REVISION_NUMBER = 8
TRANSACTION_TYPES = ["W", "S", "P"]

# New orders start at the front of the lifecycle: mostly in process (1),
# occasionally backordered (3) or already approved (2). update_rows then moves
# them toward shipped, one step at a time.
NEW_ORDER_STATUSES = [1, 1, 1, 1, 3, 2]

# Per-run chance of creating a new order. The DAG runs every 5 min (288 runs/day),
# so 0.05 is ~14 orders/day -- visibly alive without swamping the ~2.7 orders/day
# the seeded history implies (set 0.01 to match it exactly). Override with
# SIM_ORDER_CHANCE.
ORDER_CHANCE = float(os.environ.get("SIM_ORDER_CHANCE", "0.05"))

# Per-run chance that an eligible (in-process / approved / backordered) order
# advances one step toward shipped. Small values spread the lifecycle over many
# cycles instead of shipping every order in one or two.
STATUS_ADVANCE_CHANCE = float(os.environ.get("STATUS_ADVANCE_CHANCE", "0.25"))

# Per-run chance that an in-process or backordered order is rejected (4) or
# cancelled (6) instead of advancing, so the dashboard's "exclude
# rejected/cancelled" filter applies to live data too.
STATUS_CANCEL_CHANCE = float(os.environ.get("STATUS_CANCEL_CHANCE", "0.05"))

fake = Faker()


def _connect():
    return psycopg2.connect(host=HOST, port=PORT, dbname=DB, user=USER, password=PASSWORD)


def _ids(cur, table, column):
    """All existing values of a key column, so inserts reference real rows."""
    cur.execute(f"SELECT {column} FROM public.{table}")
    return [row[0] for row in cur.fetchall()]


def _ids_where(cur, table, column, where):
    """Existing values of a key column matching a predicate."""
    cur.execute(f"SELECT {column} FROM public.{table} WHERE {where}")
    return [row[0] for row in cur.fetchall()]


def _sold_products(cur):
    """(product_id, list_price) entries for the seeded internet history's lines.

    One entry per historical line, not per distinct product, so picking with
    random.choice() weights each product by how often the history actually sold
    it -- mostly cheap accessories, rather than one bike per product.
    """
    cur.execute(
        """
        SELECT d.product_id, p.list_price
        FROM public.sales_order_detail d
        JOIN public.sales_order_header h ON h.sales_order_id = d.sales_order_id
        JOIN public.product p ON p.product_id = d.product_id
        WHERE d.modified_date < now() - interval '1 day'
          AND h.online_order_flag
        """
    )
    return [(row[0], float(row[1])) for row in cur.fetchall()]


def _next_id(cur, table, column):
    cur.execute(f"SELECT coalesce(max({column}), 0) + 1 FROM public.{table}")
    return cur.fetchone()[0]


def _pick_distinct_products(pool, n):
    """n distinct (product_id, list_price) from the frequency-weighted pool.

    The pool holds one entry per historical line, so popular products repeat;
    shuffling and keeping the first n distinct ids preserves that frequency
    weighting while guaranteeing no product repeats within an order.
    """
    shuffled = pool[:]
    random.shuffle(shuffled)
    chosen, seen = [], set()
    for item in shuffled:
        if item[0] not in seen:
            seen.add(item[0])
            chosen.append(item)
            if len(chosen) == n:
                break
    return chosen


def _pick(values, default=None):
    return random.choice(values) if values else default


def insert_sales_order(cur, keys):
    """Insert one sales order with its lines. Returns (order_id, line_ids).

    The lines are computed first, so the header is written once with the real
    sub_total/tax/freight/total_due. It used to insert the header with zero
    totals and UPDATE it afterwards; both changes then carried the same source
    timestamp, which could make ClickHouse's ReplacingMergeTree keep the zero row.
    """
    order_id = _next_id(cur, "sales_order_header", "sales_order_id")
    now = datetime.now(timezone.utc)
    order_date = now
    due_date = now + timedelta(days=14)
    ship_date = now + timedelta(days=7)
    customer_id = _pick(keys["individual_customer_id"])
    bill_to = _pick(keys["address_id"])
    ship_to = _pick(keys["address_id"], bill_to)

    # 1-3 lines per order (the seeded history averages 2.16), each a distinct
    # product drawn from the frequency-weighted catalogue.
    chosen = _pick_distinct_products(keys["sold_product"], random.randint(1, 3))
    lines = []
    sub_total = 0.0
    for line_no, (product_id, list_price) in enumerate(chosen, start=1):
        # Sell at the product's list price, quantity 1, so simulated orders stay
        # in the same range as the seeded history.
        unit_price = round(list_price, 4)
        discount = round(random.choice([0, 0, 0, 0.02, 0.05, 0.1, 0.2]), 4)
        qty = 1
        line_total = round(unit_price * qty * (1 - discount), 4)
        sub_total += line_total
        lines.append((line_no, product_id, unit_price, discount, qty, line_total))

    tax = round(sub_total * 0.08, 4)
    freight = round(random.uniform(0, 50), 4)
    total_due = round(sub_total + tax + freight, 4)

    cur.execute(
        """
        INSERT INTO public.sales_order_header (
            rowguid, sales_order_id, revision_number, order_date, due_date, ship_date,
            status, online_order_flag, sales_order_number, customer_id,
            sales_person_id, territory_id, bill_to_address_id, ship_to_address_id,
            ship_method_id, credit_card_id, sub_total, tax_amt, freight, total_due,
            modified_date
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s
        )
        """,
        (
            str(uuid.uuid4()), order_id, REVISION_NUMBER, order_date, due_date, ship_date,
            _pick(NEW_ORDER_STATUSES), True, f"SO{order_id:05d}", customer_id,
            # Online orders carry no salesperson in AdventureWorks.
            None, _pick(keys["territory_id"]), bill_to, ship_to,
            _pick(keys["ship_method_id"]), _pick(keys["credit_card_id"]),
            sub_total, tax, freight, total_due,
            now,
        ),
    )

    line_ids = []
    for line_no, product_id, unit_price, discount, qty, line_total in lines:
        cur.execute(
            """
            INSERT INTO public.sales_order_detail (
                rowguid, sales_order_id, sales_order_detail_id, order_qty,
                product_id, special_offer_id, unit_price, unit_price_discount,
                line_total, modified_date
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(uuid.uuid4()), order_id, line_no, qty,
                product_id, _pick(keys["special_offer_id"], 1), unit_price, discount,
                line_total, now,
            ),
        )
        line_ids.append(line_no)

    return order_id, line_ids


def insert_work_order(cur, keys):
    work_order_id = _next_id(cur, "work_order", "work_order_id")
    now = datetime.now(timezone.utc)
    order_qty = random.randint(1, 100)
    cur.execute(
        """
        INSERT INTO public.work_order (
            work_order_id, product_id, order_qty, stocked_qty, scrapped_qty,
            start_date, due_date, scrap_reason_id, modified_date
        ) VALUES (%s, %s, %s, 0, 0, %s, %s, %s, %s)
        """,
        (
            work_order_id, _pick(keys["product_id"]), order_qty, now,
            now + timedelta(days=7), _pick(keys["scrap_reason_id"]), now,
        ),
    )
    return work_order_id


def insert_transaction_history(cur, keys, order_id, line_ids):
    transaction_id = _next_id(cur, "transaction_history", "transaction_id")
    now = datetime.now(timezone.utc)
    qty = random.randint(1, 10)
    cur.execute(
        """
        INSERT INTO public.transaction_history (
            transaction_id, product_id, reference_order_id, reference_order_line_id,
            transaction_date, transaction_type, quantity, actual_cost, modified_date
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            transaction_id, _pick(keys["product_id"]), order_id, _pick(line_ids, 1),
            now, _pick(TRANSACTION_TYPES), qty, round(qty * random.uniform(5, 500), 4), now,
        ),
    )
    return transaction_id


def insert_product_review(cur, keys):
    review_id = _next_id(cur, "product_review", "product_review_id")
    now = datetime.now(timezone.utc)
    cur.execute(
        """
        INSERT INTO public.product_review (
            product_review_id, product_id, reviewer_name, review_date,
            email_address, rating, comments, modified_date
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            review_id, _pick(keys["product_id"]), fake.name(), now,
            fake.email(), random.randint(1, 5), fake.sentence(), now,
        ),
    )
    return review_id


def insert_shopping_cart_item(cur, keys):
    item_id = _next_id(cur, "shopping_cart_item", "shopping_cart_item_id")
    now = datetime.now(timezone.utc)
    cur.execute(
        """
        INSERT INTO public.shopping_cart_item (
            shopping_cart_item_id, shopping_cart_id, quantity, product_id,
            date_created, modified_date
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (item_id, str(uuid.uuid4()), random.randint(1, 5), _pick(keys["product_id"]), now, now),
    )
    return item_id


def update_rows(cur, exclude_ids=None):
    """Touch a handful of rows and always refresh modified_date."""
    now = datetime.now(timezone.utc)
    changed = 0

    cur.execute(
        """
        UPDATE public.product
        SET list_price = round((list_price * (1 + (random() * 0.1 - 0.05)))::numeric, 4),
            modified_date = %s
        WHERE product_id IN (SELECT product_id FROM public.product ORDER BY random() LIMIT 5)
        """,
        (now,),
    )
    changed += cur.rowcount

    cur.execute(
        """
        UPDATE public.product_inventory
        SET quantity = greatest(0, quantity + (random() * 10 - 5)::int),
            modified_date = %s
        WHERE (product_id, location_id) IN (
            SELECT product_id, location_id FROM public.product_inventory
            ORDER BY random() LIMIT 5
        )
        """,
        (now,),
    )
    changed += cur.rowcount

    # Forward-only, probabilistic lifecycle for orders the simulator created
    # (recent order_date). Only in-process (1), approved (2) and backordered (3)
    # orders are eligible, and each advances -- or is cancelled -- with a small
    # per-run chance, so orders take many cycles to ship and never regress.
    # ship_date is set only on the transition to shipped (5); shipped orders are
    # excluded from the pick, so an already-shipped order is never rewritten.
    cur.execute(
        """
        UPDATE public.sales_order_header h
        SET status = s.new_status,
            ship_date = CASE WHEN s.new_status = 5 THEN now() ELSE h.ship_date END,
            modified_date = %(now)s
        FROM (
            SELECT sales_order_id,
                   CASE
                       WHEN status = 1 AND random() < %(cancel)s
                           THEN (array[4, 6])[1 + floor(random() * 2)::int]
                       WHEN status = 3 AND random() < %(cancel)s THEN 6
                       WHEN status = 1 THEN (array[2, 2, 5])[1 + floor(random() * 3)::int]
                       WHEN status = 3 THEN 2
                       WHEN status = 2 THEN 5
                       ELSE status
                   END AS new_status
            FROM public.sales_order_header
            WHERE order_date > now() - interval '1 day'
              AND status IN (1, 2, 3)
              AND random() < %(advance)s
              -- Orders created earlier in this very run stay untouched for at
              -- least one cycle, so a new order is never shipped at birth.
              AND sales_order_id <> ALL(%(exclude)s::bigint[])
            ORDER BY random() LIMIT 5
        ) s
        WHERE h.sales_order_id = s.sales_order_id
        """,
        {"now": now, "advance": STATUS_ADVANCE_CHANCE, "cancel": STATUS_CANCEL_CHANCE,
         "exclude": exclude_ids or []},
    )
    changed += cur.rowcount

    cur.execute(
        """
        UPDATE public.work_order
        SET stocked_qty = least(order_qty, stocked_qty + (random() * 5)::int),
            modified_date = %s
        WHERE work_order_id IN (
            SELECT work_order_id FROM public.work_order ORDER BY random() LIMIT 5
        )
        """,
        (now,),
    )
    changed += cur.rowcount

    cur.execute(
        """
        UPDATE public.person
        SET last_name = %s, modified_date = %s
        WHERE business_entity_id IN (
            SELECT business_entity_id FROM public.person ORDER BY random() LIMIT 5
        )
        """,
        (fake.last_name(), now),
    )
    changed += cur.rowcount

    return changed


def delete_leaf_rows(cur):
    deleted = 0
    cur.execute(
        "DELETE FROM public.product_review WHERE product_review_id IN "
        "(SELECT product_review_id FROM public.product_review ORDER BY random() LIMIT 2)"
    )
    deleted += cur.rowcount
    cur.execute(
        "DELETE FROM public.shopping_cart_item WHERE shopping_cart_item_id IN "
        "(SELECT shopping_cart_item_id FROM public.shopping_cart_item ORDER BY random() LIMIT 2)"
    )
    deleted += cur.rowcount
    return deleted


def main():
    conn = _connect()
    try:
        with conn:
            with conn.cursor() as cur:
                keys = {
                    # Online orders must use individual customers: the DWH's
                    # dim_customer only holds customers with no store_id
                    # (resellers live in dim_reseller).
                    "individual_customer_id": _ids_where(cur, "customer", "customer_id", "store_id is null"),
                    "address_id": _ids(cur, "address", "address_id"),
                    "product_id": _ids(cur, "product", "product_id"),
                    "sold_product": _sold_products(cur),
                    "ship_method_id": _ids(cur, "ship_method", "ship_method_id"),
                    "currency_rate_id": _ids(cur, "currency_rate", "currency_rate_id"),
                    "territory_id": _ids(cur, "sales_territory", "territory_id"),
                    "special_offer_id": _ids(cur, "special_offer", "special_offer_id"),
                    "scrap_reason_id": _ids(cur, "scrap_reason", "scrap_reason_id"),
                    "credit_card_id": _ids(cur, "credit_card", "credit_card_id"),
                }
                if not keys["sold_product"] or not keys["individual_customer_id"]:
                    print("simulate_adventureworks: tables look empty, nothing to do")
                    return

                inserted = 0
                created_order_ids = []
                if random.random() < ORDER_CHANCE:
                    order_id, line_ids = insert_sales_order(cur, keys)
                    insert_transaction_history(cur, keys, order_id, line_ids)
                    inserted += 1 + len(line_ids)
                    created_order_ids.append(order_id)
                for _ in range(random.randint(0, 2)):
                    insert_work_order(cur, keys)
                    inserted += 1
                for _ in range(random.randint(1, 3)):
                    insert_product_review(cur, keys)
                    insert_shopping_cart_item(cur, keys)
                    inserted += 2

                updated = update_rows(cur, exclude_ids=created_order_ids)
                deleted = delete_leaf_rows(cur)

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM public.sales_order_header")
            orders = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM public.product")
            products = cur.fetchone()[0]
    finally:
        conn.close()

    print(
        f"simulate_adventureworks: inserted={inserted} updated={updated} "
        f"deleted={deleted} sales_orders={orders} products={products}"
    )


if __name__ == "__main__":
    main()
