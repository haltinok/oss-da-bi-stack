"""The business logic, with no database: how many order lines a day brings (growth, weekdays, bayrams, the fasting month, seasons), who orders what, at which price and discount,
when each invoice is paid (and how late), and which lines come back. Everything takes a `random.Random`, so a day made from the same seed is the same day."""
from __future__ import annotations

import datetime as dt
import math
import random
from dataclasses import dataclass, field

from . import reference as ref

ANCHOR = dt.date(2023, 1, 1)
BASE_LINES_PER_DAY = 360            # at the anchor, before growth, season and weekday
GROWTH_PER_YEAR = 1.18              # volume
LINES_PER_ORDER = 3.6
HOUR_WEIGHT = [0, 0, 0, 0, 0, 0, 0.5, 3, 8, 9, 9, 8, 6, 7, 9, 9, 8, 6, 3, 1.2, 0.4, 0.1, 0, 0]       # when orders arrive, by hour of the day
HOURS_TOTAL = sum(HOUR_WEIGHT)
SEASON = {1: 0.9, 2: 0.9, 3: 1.0, 4: 1.0, 5: 1.02, 6: 1.1, 7: 1.15, 8: 1.12, 9: 1.0, 10: 1.0, 11: 1.05, 12: 1.15}
RETURN_REASONS = {"Hasarlı ürün": 0.34, "Yanlış ürün": 0.18, "Son kullanma tarihi": 0.22, "Fazla sipariş": 0.14, "Kalite şikâyeti": 0.12}


def price_index(day: dt.date) -> float:
    """List prices follow Turkish inflation: about 3 % a month until 2025, about 2.2 % after (so a year-on-year comparison means something)."""
    months = (day.year - 2023) * 12 + (day.month - 1) + (day.day - 1) / 30
    early = min(months, 24)
    return 1.03 ** early * 1.022 ** max(0.0, months - 24)


def day_lines(day: dt.date, holidays: dict[dt.date, str] | None = None) -> float:
    """The expected number of order lines on a day."""
    years = (day - ANCHOR).days / 365
    weekday = day.weekday()
    factor = {5: 0.45, 6: 0.04}.get(weekday, 1.0)
    holiday = (holidays if holidays is not None else ref.holidays(day.year)).get(day)
    if holiday:
        factor = 0.08 if weekday < 5 else factor * 0.3
    if ref.bayram_soon(day):
        factor *= 1.6                      # stocking up before a bayram
    if ref.ramazan(day):
        factor *= 1.22
    return BASE_LINES_PER_DAY * GROWTH_PER_YEAR ** years * SEASON[day.month] * factor


def _hours(start: dt.datetime, end: dt.datetime) -> tuple[float, float]:
    """The slice as hours of the day (a slice that ends at or after midnight ends at 24)."""
    first = start.hour + start.minute / 60 + start.second / 3600
    last = 24.0 if end.date() > start.date() else end.hour + end.minute / 60 + end.second / 3600
    return first, last


def hour_share(start: dt.datetime, end: dt.datetime) -> float:
    """How much of the day's orders arrive between two moments (the second one at most at midnight after the first)."""
    def upto(h: float) -> float:
        whole = int(h)
        return sum(HOUR_WEIGHT[:whole]) + (HOUR_WEIGHT[whole] * (h - whole) if whole < 24 else 0.0)
    first, last = _hours(start, end)
    return max(0.0, (upto(last) - upto(first)) / HOURS_TOTAL)


def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam < 30:
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= limit:
                return k
            k += 1
    return max(0, round(rng.gauss(lam, math.sqrt(lam))))


def moment(rng: random.Random, start: dt.datetime, end: dt.datetime) -> dt.datetime:
    """A random moment in [start, end) weighted by the hours' order weights."""
    first, last = _hours(start, end)
    hours = [h for h in range(int(first), min(24, math.ceil(last))) if HOUR_WEIGHT[h] > 0] or [min(23, int(first))]
    h = rng.choices(hours, weights=[HOUR_WEIGHT[x] for x in hours])[0]
    t = dt.datetime.combine(start.date(), dt.time(h, rng.randrange(60), rng.randrange(60)))
    return min(max(t, start), end - dt.timedelta(seconds=1)) if end > start else start


@dataclass
class World:
    dealers: list[dict]
    items: list[dict]
    holidays: dict[dt.date, str] = field(default_factory=dict)
    _item_cum: list[float] = field(default_factory=list)

    def __post_init__(self):
        acc, self._item_cum = 0.0, []
        for i in self.items:
            acc += i["popularity"]
            self._item_cum.append(acc)

    def active_dealers(self, day: dt.date) -> tuple[list[dict], list[float]]:
        live = [d for d in self.dealers if d["opened_date"] <= day and d["is_active"]]
        cum, acc = [], 0.0
        for d in live:
            acc += d["weight"]
            cum.append(acc)
        return live, cum


def item_price(item: dict, day: dt.date) -> float:
    return round(item["base_price"] * price_index(day), 2)


def discount_pct(rng: random.Random, segment: str, day: dt.date) -> float:
    d = ref.SEGMENTS[segment]["discount"] + rng.choice([-1.0, 0.0, 0.0, 1.0, 2.0])
    if day.month in (3, 4, 11):
        d += 2.5                          # the Ramazan and the November campaigns
    if rng.random() < 0.06:
        d += 5.0                          # a promotion on a line
    return round(max(0.0, d), 2)


def new_order(rng: random.Random, world: World, dealer: dict, ts: dt.datetime, number: str) -> dict:
    """One order: the lines (with price, discount, amounts), its invoice, and what will happen later (payments, returns)."""
    seg = ref.SEGMENTS[dealer["segment"]]
    day = ts.date()
    n_lines = max(1, 1 + poisson(rng, seg["lines"] - 1))
    picked = rng.choices(range(len(world.items)), cum_weights=world._item_cum, k=n_lines * 2)
    seen, lines = set(), []
    for idx in picked:
        if idx in seen:
            continue
        seen.add(idx)
        item = world.items[idx]
        cases = rng.randint(*seg["cases"])
        qty = cases * item["case_size"]
        price = item_price(item, day)
        disc = discount_pct(rng, dealer["segment"], day)
        net = round(qty * price * (1 - disc / 100), 2)
        lines.append({"item_key": item["item_key"], "quantity": qty, "unit_price": price, "discount_pct": disc, "net_amount": net, "cost_amount": round(qty * price * item["cost_ratio"], 2), "vat": item["vat_rate"]})
        if len(lines) >= n_lines:
            break
    net = round(sum(x["net_amount"] for x in lines), 2)
    vat = round(sum(x["net_amount"] * x["vat"] / 100 for x in lines), 2)
    invoice_date = day + dt.timedelta(days=rng.choice([0, 0, 1]))
    due = invoice_date + dt.timedelta(days=dealer["payment_term_days"])
    gross = round(net + vat, 2)
    return {"number": number, "ts": ts, "dealer_key": dealer["dealer_key"], "lines": lines,
            "invoice": {"date": invoice_date, "due": due, "net": net, "vat": vat, "gross": gross},
            "payments": payment_plan(rng, dealer["segment"], due, gross),
            "returns": return_plan(rng, lines, day)}


def payment_plan(rng: random.Random, segment: str, due: dt.date, gross: float) -> list[tuple[dt.date, float, str]]:
    """When the money comes: usually around the due date, sometimes late (a tail of weeks), sometimes in two parts, rarely never."""
    seg = ref.SEGMENTS[segment]
    if rng.random() < 0.015:
        return []                                                     # never paid (it stays open and grows old)
    ontime = rng.random() < seg["ontime"]
    shift = rng.randint(-3, 3) if ontime else rng.randint(5, 80)
    first = due + dt.timedelta(days=shift)
    methods, weights = list(seg["methods"]), list(seg["methods"].values())
    method = rng.choices(methods, weights=weights)[0]
    if rng.random() < 0.88:
        return [(first, gross, method)]
    part = round(gross * rng.uniform(0.4, 0.7), 2)
    later = first + dt.timedelta(days=rng.randint(10, 45))
    return [(first, part, method), (later, round(gross - part, 2), rng.choices(methods, weights=weights)[0])]


def return_plan(rng: random.Random, lines: list[dict], day: dt.date) -> list[dict]:
    out = []
    for line in lines:
        if rng.random() < 0.025:
            qty = max(1, round(line["quantity"] * rng.uniform(0.08, 0.5)))
            out.append({"date": day + dt.timedelta(days=rng.randint(2, 20)), "item_key": line["item_key"], "quantity": qty,
                        "amount": round(qty * line["unit_price"] * (1 - line["discount_pct"] / 100), 2),
                        "reason": rng.choices(list(RETURN_REASONS), weights=list(RETURN_REASONS.values()))[0]})
    return out


def orders_for(rng: random.Random, world: World, start: dt.datetime, end: dt.datetime, first_number: int) -> list[dict]:
    """The orders placed in [start, end) of one day (a whole day for the history, a quarter of an hour for the live tick)."""
    day = start.date()
    lam = day_lines(day, world.holidays) * hour_share(start, end) / LINES_PER_ORDER
    n = poisson(rng, lam)
    dealers, cum = world.active_dealers(day)
    if not n or not dealers:
        return []
    chosen = rng.choices(dealers, cum_weights=cum, k=n)
    return [new_order(rng, world, dealer, moment(rng, start, end), f"S{day:%y%m%d}-{first_number + i:04d}") for i, dealer in enumerate(chosen)]
