"""The distributor simulator's engine without a database: the same seed gives the same business, the shape is a distributor's (weekdays, Ramazan, prices follow inflation),
and an order's money adds up (lines to invoice, payments to what is owed)."""
import datetime as dt
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from faker import Faker  # noqa: E402

from distributor_sim import engine as eng, reference as ref  # noqa: E402

TODAY = dt.date(2026, 11, 11)


def world(seed=1):
    rng, fake = random.Random(seed), Faker("tr_TR")
    Faker.seed(seed)
    reps = ref.build_reps(rng, fake)
    dealers = ref.build_dealers(rng, fake, reps, 60, TODAY, 3)
    return eng.World(dealers=dealers, items=ref.build_items(rng), holidays={**ref.holidays(2025), **ref.holidays(2026)})


def day_orders(w, day, seed=7):
    return eng.orders_for(random.Random(seed), w, dt.datetime.combine(day, dt.time()), dt.datetime.combine(day, dt.time()) + dt.timedelta(days=1), 1)


def test_same_seed_same_business():
    a, b = world(), world()
    assert [d["dealer_name"] for d in a.dealers] == [d["dealer_name"] for d in b.dealers]
    day = dt.date(2026, 10, 14)
    oa, ob = day_orders(a, day), day_orders(b, day)
    assert oa and [(o["number"], o["invoice"]["gross"]) for o in oa] == [(o["number"], o["invoice"]["gross"]) for o in ob]


def test_weekends_are_quieter_than_weekdays():
    w = world()
    wd = sum(eng.day_lines(dt.date(2026, 10, 5) + dt.timedelta(days=i), w.holidays) for i in range(5))
    we = sum(eng.day_lines(dt.date(2026, 10, 10) + dt.timedelta(days=i), w.holidays) for i in range(2))
    assert we / 2 < wd / 5 * 0.7


def test_prices_follow_inflation():
    assert eng.price_index(dt.date(2026, 11, 1)) > eng.price_index(dt.date(2023, 11, 1)) * 1.5


def test_an_order_adds_up():
    w = world()
    orders = [o for d in range(10) for o in day_orders(w, dt.date(2026, 10, 1) + dt.timedelta(days=d), seed=d)]
    assert len(orders) > 20
    for o in orders:
        inv = o["invoice"]
        assert o["lines"] and all(x["quantity"] > 0 and x["net_amount"] > 0 for x in o["lines"])
        assert abs(sum(x["net_amount"] for x in o["lines"]) - inv["net"]) < 0.02
        assert abs(inv["net"] + inv["vat"] - inv["gross"]) < 0.02
        assert inv["due"] >= inv["date"]
        assert sum(p[1] for p in o["payments"]) <= inv["gross"] + 0.01          # never collects more than was invoiced
        assert all(p[0] >= o["ts"].date() for p in o["payments"])
        assert all(x["cost_amount"] < x["net_amount"] * 1.5 for x in o["lines"])


def test_a_quarter_of_an_hour_at_night_is_empty():
    w = world()
    night = dt.datetime(2026, 10, 14, 3, 0)
    assert eng.orders_for(random.Random(3), w, night, night + dt.timedelta(minutes=15), 1) == []


def test_reference_data_is_turkish_and_complete():
    rng = random.Random(1)
    reps = ref.build_reps(rng, Faker("tr_TR"))
    assert {r["region"] for r in reps} == {"Marmara", "Ege", "İç Anadolu", "Akdeniz", "Karadeniz", "Doğu Anadolu", "Güneydoğu Anadolu"}
    assert {"marmara_temsilci", "ege_temsilci"} <= {r["rep_username"] for r in reps}
    items = ref.build_items(rng)
    assert 300 <= len(items) <= 450 and {i["category"] for i in items} == {"Gıda", "İçecek", "Atıştırmalık", "Temizlik", "Kişisel Bakım"}
    assert dt.date(2026, 10, 29) in ref.holidays(2026)                           # Cumhuriyet Bayramı
