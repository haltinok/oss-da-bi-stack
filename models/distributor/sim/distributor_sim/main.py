"""distributor-sim: `init` writes the history, `run` does that if the database is empty and then adds new business every SIM_INTERVAL_SECONDS (900), catching up after downtime."""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import random
import time

import psycopg2
from faker import Faker

from . import db, engine as eng, reference as ref

SEED = int(os.environ.get("SIM_SEED", "20231111"))
HISTORY_YEARS = int(os.environ.get("SIM_HISTORY_YEARS", "3"))
DEALERS = int(os.environ.get("SIM_DEALERS", "220"))
INTERVAL = float(os.environ.get("SIM_INTERVAL_SECONDS", "900"))
READY = pathlib.Path(os.environ.get("SIM_READY_FILE", "/tmp/ready"))


def connect():
    last = None
    for _ in range(60):
        try:
            return psycopg2.connect(host=os.environ.get("DISTRIBUTOR_DB_HOST", "distributor-db"), port=int(os.environ.get("DISTRIBUTOR_DB_PORT", "5432")), dbname=os.environ.get("DISTRIBUTOR_DB_NAME", "distributor"),
                                    user=os.environ.get("DISTRIBUTOR_DB_USER", "distributor"), password=os.environ["DISTRIBUTOR_DB_PASSWORD"], connect_timeout=5)
        except psycopg2.OperationalError as exc:
            last = exc
            time.sleep(2)
    raise SystemExit(f"cannot reach the database: {last}")


def say(msg: str) -> None:
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def init(conn, now: dt.datetime) -> bool:
    """Writes the company and three years of history up to `now`, once. -> whether it did anything."""
    with conn, conn.cursor() as cur:
        if db.meta_get(cur, "history_from"):
            return False
        today = now.date()
        start = today - dt.timedelta(days=365 * HISTORY_YEARS)
        rng = random.Random(SEED)
        fake = Faker("tr_TR")
        Faker.seed(SEED)
        reps = ref.build_reps(rng, fake)
        dealers = ref.build_dealers(rng, fake, reps, DEALERS, today, HISTORY_YEARS)
        items = ref.build_items(rng)
        say(f"company: {len(reps)} reps, {len(dealers)} dealers, {len(items)} items; history from {start}")
        db.put_calendar(cur, start - dt.timedelta(days=30), today + dt.timedelta(days=400))
        db.put_reference(cur, reps, dealers, items, today)
        holidays = {}
        for y in range(start.year, today.year + 2):
            holidays |= ref.holidays(y)
        world = eng.World(dealers, items, holidays)
        day, total, chunk = start, 0, []
        while day <= today:
            s = dt.datetime.combine(day, dt.time())
            e = now if day == today else s + dt.timedelta(days=1)
            chunk += eng.orders_for(random.Random(f"{SEED}:{day}"), world, s, e, 1)
            if len(chunk) > 4000 or day == today:
                db.put_orders(cur, chunk)
                total += len(chunk)
                say(f"  orders to {day}: {total}")
                chunk = []
            day += dt.timedelta(days=1)
        cur.execute("ANALYZE dist.fact_order_line")                    # a table just filled has no statistics; the stock queries below read it by date
        payments, returns = db.process_due(cur, today)
        say(f"payments {payments}, returns {returns}")
        d = (start.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        while d <= today:
            db.snapshot_stock(cur, d - dt.timedelta(days=1))                     # the last day of each month
            d = (d + dt.timedelta(days=32)).replace(day=1)
        db.snapshot_stock(cur, today)
        db.meta_set(cur, "history_from", str(start))
        db.meta_set(cur, "price_month", f"{today:%Y-%m}")
        db.meta_set(cur, "last_tick", now.isoformat())
    say("history written")
    return True


def tick(conn, now: dt.datetime) -> dict:
    """Adds the business of the time since the last run (days of it, after downtime), what has come due, today's stock and, on a new month, the new prices."""
    with conn, conn.cursor() as cur:
        last = dt.datetime.fromisoformat(db.meta_get(cur, "last_tick") or (now - dt.timedelta(minutes=15)).isoformat())
        if last >= now:
            return {"orders": 0}
        world = db.load_world(cur)
        orders, day = [], last.date()
        while day <= now.date():
            s = max(last, dt.datetime.combine(day, dt.time()))
            e = min(now, dt.datetime.combine(day, dt.time()) + dt.timedelta(days=1))
            if e > s:
                orders += eng.orders_for(random.Random(f"live:{s.isoformat()}"), world, s, e, db.next_number(cur, day) + sum(1 for o in orders if o["ts"].date() == day))
            day += dt.timedelta(days=1)
        if orders:
            db.put_orders(cur, orders)
        payments, returns = db.process_due(cur, now.date())
        db.put_calendar(cur, now.date(), now.date() + dt.timedelta(days=400))
        db.update_prices(cur, now.date())
        db.snapshot_stock(cur, now.date())
        db.meta_set(cur, "last_tick", now.isoformat())
    return {"orders": len(orders), "payments": payments, "returns": returns}


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "run"
    conn = connect()
    now = dt.datetime.now().replace(microsecond=0)
    if command == "init":
        init(conn, now)
        return 0
    if command == "once":
        init(conn, now)
        say(str(tick(conn, dt.datetime.now().replace(microsecond=0))))
        return 0
    init(conn, now)
    READY.touch()
    say(f"ready; adding business every {INTERVAL:g} s")
    while True:
        time.sleep(INTERVAL)
        try:
            say(str(tick(conn, dt.datetime.now().replace(microsecond=0))))
        except psycopg2.Error as exc:
            say(f"tick failed: {exc}")
            conn.rollback()
            conn = connect()
