"""Randomly mutate the `public.orders` table in postgres_active.

Each run performs a random mix of:
- inserts  (new orders via faker)
- updates  (status/amount changes; updated_at is refreshed by a DB trigger)
- soft-deletes (set deleted_at = now())

Intended to be invoked from an Airflow BashOperator. Connection settings are
taken from environment variables with sensible defaults for the local stack.
"""

import os
import random

import psycopg2
from faker import Faker

HOST = os.environ.get("POSTGRES_HOST", "postgres_active")
PORT = int(os.environ.get("POSTGRES_PORT", "5434"))
DB = os.environ.get("POSTGRES_DB", "active_db")
USER = os.environ.get("POSTGRES_USER", "postgres")
PASSWORD = os.environ.get("POSTGRES_PASSWORD", "postgres")

fake = Faker()
random.seed()


def _connect():
    return psycopg2.connect(
        host=HOST, port=PORT, dbname=DB, user=USER, password=PASSWORD
    )


def insert_orders(cur, n):
    for _ in range(n):
        cur.execute(
            """
            INSERT INTO public.orders (customer_name, amount, status)
            VALUES (%s, %s, %s)
            """,
            (fake.company(), round(random.uniform(10, 5000), 2), "created"),
        )
    return n


def update_orders(cur, n):
    cur.execute(
        "SELECT id FROM public.orders WHERE deleted_at IS NULL ORDER BY random() LIMIT %s",
        (n,),
    )
    ids = [row[0] for row in cur.fetchall()]
    statuses = ["shipped", "cancelled", "created"]
    for order_id in ids:
        if random.random() < 0.5:
            cur.execute(
                "UPDATE public.orders SET status = %s WHERE id = %s",
                (random.choice(statuses), order_id),
            )
        else:
            cur.execute(
                "UPDATE public.orders SET amount = %s WHERE id = %s",
                (round(random.uniform(10, 5000), 2), order_id),
            )
    return len(ids)


def soft_delete_orders(cur, n):
    cur.execute(
        "SELECT id FROM public.orders WHERE deleted_at IS NULL ORDER BY random() LIMIT %s",
        (n,),
    )
    ids = [row[0] for row in cur.fetchall()]
    for order_id in ids:
        cur.execute(
            "UPDATE public.orders SET deleted_at = now() WHERE id = %s",
            (order_id,),
        )
    return len(ids)


def main():
    n_insert = random.randint(1, 5)
    n_update = random.randint(1, 4)
    n_delete = random.randint(1, 2)

    conn = _connect()
    try:
        with conn:
            with conn.cursor() as cur:
                inserted = insert_orders(cur, n_insert)
                updated = update_orders(cur, n_update)
                deleted = soft_delete_orders(cur, n_delete)

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM public.orders")
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM public.orders WHERE deleted_at IS NOT NULL"
            )
            deleted_total = cur.fetchone()[0]
    finally:
        conn.close()

    print(
        f"simulate_orders: inserted={inserted} updated={updated} "
        f"soft_deleted={deleted} total={total} deleted_total={deleted_total}"
    )


if __name__ == "__main__":
    main()
