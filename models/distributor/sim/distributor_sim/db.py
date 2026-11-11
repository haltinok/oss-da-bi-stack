"""Everything that touches the database: the reference tables, the facts, what comes due (payments, returns), the stock snapshots."""
from __future__ import annotations

import datetime as dt
import json

import psycopg2.extras

from . import engine as eng
from . import reference as ref

PAGE = 5000


def key(day: dt.date) -> int:
    return int(day.strftime("%Y%m%d"))


def meta_get(cur, name: str) -> str | None:
    cur.execute("SELECT value FROM dist.meta WHERE key = %s", (name,))
    row = cur.fetchone()
    return row[0] if row else None


def meta_set(cur, name: str, value: str) -> None:
    cur.execute("INSERT INTO dist.meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (name, value))


def put_calendar(cur, start: dt.date, end: dt.date) -> None:
    psycopg2.extras.execute_values(cur, "INSERT INTO dist.dim_calendar VALUES %s ON CONFLICT (date_key) DO NOTHING", ref.calendar_rows(start, end), page_size=PAGE)


def put_reference(cur, reps: list[dict], dealers: list[dict], items: list[dict], today: dt.date) -> None:
    psycopg2.extras.execute_values(cur, "INSERT INTO dist.dim_rep VALUES %s", [(r["rep_key"], r["rep_username"], r["rep_name"], r["region"]) for r in reps])
    psycopg2.extras.execute_values(cur, "INSERT INTO dist.dim_dealer VALUES %s", [(d["dealer_key"], d["dealer_code"], d["dealer_name"], d["region"], d["province"], d["segment"], d["rep_key"], d["rep_username"],
                                                                                   d["credit_limit"], d["payment_term_days"], d["opened_date"], d["is_active"], round(d["weight"], 4)) for d in dealers])
    idx = eng.price_index(today)
    psycopg2.extras.execute_values(cur, "INSERT INTO dist.dim_item VALUES %s", [(i["item_key"], i["sku"], i["item_name"], i["category"], i["subcategory"], i["brand"], round(i["base_price"] * idx, 2),
                                                                                round(i["base_price"] * idx * i["cost_ratio"], 2), i["case_size"], i["vat_rate"], round(i["popularity"], 6),
                                                                                i["base_price"], round(i["cost_ratio"], 4)) for i in items])


def load_world(cur) -> eng.World:
    """The company as the database has it (the live ticks work on this, not on a fresh draw)."""
    cur.execute("SELECT dealer_key, region, segment, payment_term_days, opened_date, is_active, order_weight FROM dist.dim_dealer")
    dealers = [{"dealer_key": k, "region": r, "segment": s, "payment_term_days": t, "opened_date": o, "is_active": a, "weight": float(w)} for k, r, s, t, o, a, w in cur.fetchall()]
    cur.execute("SELECT item_key, base_price, cost_ratio, case_size, vat_rate, popularity FROM dist.dim_item ORDER BY item_key")
    items = [{"item_key": k, "base_price": float(b), "cost_ratio": float(c), "case_size": cs, "vat_rate": float(v), "popularity": float(p)} for k, b, c, cs, v, p in cur.fetchall()]
    years = range(dt.date.today().year - 4, dt.date.today().year + 3)
    holidays: dict[dt.date, str] = {}
    for y in years:
        holidays |= ref.holidays(y)
    return eng.World(dealers, items, holidays)


def next_number(cur, day: dt.date) -> int:
    cur.execute("SELECT count(DISTINCT order_number) FROM dist.fact_order_line WHERE order_date = %s", (day,))
    return cur.fetchone()[0] + 1


def put_orders(cur, orders: list[dict]) -> None:
    lines, invoices, plans = [], [], []
    for o in orders:
        day = o["ts"].date()
        for ln in o["lines"]:
            lines.append((o["number"], o["ts"], day, key(day), o["dealer_key"], ln["item_key"], ln["quantity"], ln["unit_price"], ln["discount_pct"], ln["net_amount"], ln["cost_amount"]))
        inv = o["invoice"]
        number = "F" + o["number"][1:]
        invoices.append((number, o["number"], inv["date"], key(inv["date"]), inv["due"], key(inv["due"]), o["dealer_key"], inv["net"], inv["vat"], inv["gross"]))
        for when, amount, method in o["payments"]:
            plans.append(("payment", when, number, json.dumps({"amount": amount, "method": method})))
        for r in o["returns"]:
            plans.append(("return", r["date"], o["number"], json.dumps({"dealer_key": o["dealer_key"], "item_key": r["item_key"], "quantity": r["quantity"], "amount": r["amount"], "reason": r["reason"]})))
    psycopg2.extras.execute_values(cur, "INSERT INTO dist.fact_order_line (order_number, order_ts, order_date, order_date_key, dealer_key, item_key, quantity, unit_price, discount_pct, net_amount, cost_amount) VALUES %s", lines, page_size=PAGE)
    psycopg2.extras.execute_values(cur, "INSERT INTO dist.fact_invoice (invoice_number, order_number, invoice_date, invoice_date_key, due_date, due_date_key, dealer_key, net_amount, vat_amount, gross_amount) VALUES %s", invoices, page_size=PAGE)
    psycopg2.extras.execute_values(cur, "INSERT INTO dist.plan (kind, due_date, ref, payload) VALUES %s", plans, page_size=PAGE)


def process_due(cur, today: dt.date) -> tuple[int, int]:
    """Moves what has come due into the facts: payments (and the invoices' paid amount) and returns. -> (payments, returns)."""
    cur.execute("ANALYZE dist.plan")                                  # a table just filled has no statistics: without them the planner joins the wrong way round
    cur.execute("ANALYZE dist.fact_invoice")
    cur.execute("""
        WITH due AS (DELETE FROM dist.plan WHERE kind = 'payment' AND due_date <= %(d)s RETURNING due_date, ref, payload),
        paid AS (
            INSERT INTO dist.fact_payment (invoice_id, dealer_key, paid_date, paid_date_key, amount, method)
            SELECT i.invoice_id, i.dealer_key, due.due_date, to_char(due.due_date, 'YYYYMMDD')::int, (due.payload->>'amount')::numeric, due.payload->>'method'
            FROM due JOIN dist.fact_invoice i ON i.invoice_number = due.ref
            RETURNING invoice_id, amount
        ),
        sums AS (SELECT invoice_id, sum(amount) AS amount FROM paid GROUP BY 1),
        moved AS (UPDATE dist.fact_invoice i SET paid_amount = i.paid_amount + sums.amount FROM sums WHERE i.invoice_id = sums.invoice_id RETURNING 1)
        SELECT (SELECT count(*) FROM paid)""", {"d": today})
    payments = cur.fetchone()[0]
    cur.execute("""
        WITH due AS (DELETE FROM dist.plan WHERE kind = 'return' AND due_date <= %(d)s RETURNING due_date, ref, payload),
        made AS (
            INSERT INTO dist.fact_return (order_number, item_key, dealer_key, return_date, return_date_key, quantity, amount, reason)
            SELECT ref, (payload->>'item_key')::int, (payload->>'dealer_key')::int, due_date, to_char(due_date, 'YYYYMMDD')::int,
                   (payload->>'quantity')::int, (payload->>'amount')::numeric, payload->>'reason' FROM due RETURNING 1
        )
        SELECT count(*) FROM made""", {"d": today})
    return payments, cur.fetchone()[0]


def snapshot_stock(cur, day: dt.date) -> None:
    """Stock on a day, per item: what is on hand and when it would run out, from the last 30 days' sales (a few items are out of stock)."""
    cur.execute("DELETE FROM dist.fact_stock WHERE snapshot_date = %s", (day,))
    cur.execute("""
        WITH s AS MATERIALIZED (SELECT item_key, sum(quantity)::numeric / 30 AS daily FROM dist.fact_order_line WHERE order_date > %(d)s - 30 AND order_date <= %(d)s GROUP BY 1)
        INSERT INTO dist.fact_stock (snapshot_date, snapshot_date_key, item_key, on_hand, reorder_point, cover_days, stock_value)
        SELECT %(d)s, %(k)s, i.item_key, q.on_hand, q.reorder, CASE WHEN h.daily > 0 THEN round(q.on_hand / h.daily, 1) ELSE 0 END, q.on_hand * i.base_price * i.cost_ratio * %(idx)s
        FROM dist.dim_item i
        LEFT JOIN s USING (item_key)
        CROSS JOIN LATERAL (SELECT coalesce(s.daily, 1) AS daily, (abs(hashtext(i.item_key::text || %(d)s::text)) %% 1000) / 1000.0 AS r) h
        CROSS JOIN LATERAL (SELECT CASE WHEN h.r < 0.03 THEN 0 ELSE round(h.daily * (4 + 56 * power(h.r, 1.4)))::int END AS on_hand, round(h.daily * 14 + 5)::int AS reorder) q""",
                {"d": day, "k": key(day), "idx": eng.price_index(day)})


def update_prices(cur, day: dt.date) -> None:
    """List prices follow the inflation index: refreshed on the first run of each month."""
    if meta_get(cur, "price_month") == f"{day:%Y-%m}":
        return
    idx = eng.price_index(day)
    cur.execute("UPDATE dist.dim_item SET unit_price = round(base_price * %s, 2), unit_cost = round(base_price * cost_ratio * %s, 2)", (idx, idx))
    meta_set(cur, "price_month", f"{day:%Y-%m}")
