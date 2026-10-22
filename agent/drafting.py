"""Rule-based drafting: the weekly proposal built from the mart's own suggestions, no model involved.

It is the baseline the LLM mode is judged against and the fallback when no API key is set. Work orders group by
product category, purchase orders by vendor, campaigns by category and suggested discount; each proposal says
what it covers in one line, and the numbers behind it are stored by the actions service.
"""
from __future__ import annotations

from collections import defaultdict

MAX_LINES = 25            # lines per work or purchase order proposal
MAX_CAMPAIGN_PRODUCTS = 25
MIN_EXCESS_VALUE = 500.0  # ignore excess too small to be worth a campaign
CAMPAIGN_DAYS = 30


def money(v: float) -> str:
    return f"${v:,.0f}"


def reorder_bounds(row: dict) -> tuple[int, int]:
    """Mirror of actions/rules.py reorder_bounds (the service stays the authority)."""
    suggested = int(row.get("suggested_order_qty") or 0)
    low = max(1, int(row.get("min_order_qty") or 0))
    high = max(2 * suggested, low)
    cap = int(row.get("max_order_qty") or 0)
    if cap > 0:
        high = min(high, cap)
        low = min(low, cap)
    return low, high


def line_qty(row: dict) -> int:
    """The quantity the mart suggests, raised to the vendor minimum for purchased items."""
    qty = int(row.get("suggested_order_qty") or 0)
    if row.get("replenishment_type") == "purchase":
        low, high = reorder_bounds(row)
        qty = min(max(qty, low), high)
    return qty


def urgent(rows: list[dict]) -> str:
    r = min(rows, key=lambda x: (x.get("days_of_cover") if x.get("days_of_cover") is not None else 0))
    return f"most urgent: {r['product_name']} ({r['on_hand']:.0f} on hand, {r['daily_demand']:.1f}/day, {r['lead_time_days']:.0f}-day lead time)"


def work_order_proposals(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["replenishment_type"] == "manufacture" and line_qty(r) > 0:
            groups[r["category"]].append(r)
    out = []
    for category, rs in groups.items():
        rs = sorted(rs, key=lambda x: -(x["suggested_order_value"] or 0))[:MAX_LINES]
        units = sum(line_qty(r) for r in rs)
        value = sum(line_qty(r) * (r["unit_cost"] or 0) for r in rs)
        out.append({
            "kind": "work_order",
            "title": f"Restock {len(rs)} in-house {category} item{'s' if len(rs) != 1 else ''}",
            "rationale": f"{len(rs)} {category} item{'s' if len(rs) != 1 else ''} {'are' if len(rs) != 1 else 'is'} out of stock or about to run out; {units} units to make (about {money(value)} at cost). {urgent(rs)}.",
            "payload": {"lines": [{"product_id": int(r["key"]), "qty": line_qty(r)} for r in rs]},
            "_value": value,
        })
    return out


def purchase_order_proposals(rows: list[dict]) -> list[dict]:
    groups: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        if r["replenishment_type"] == "purchase" and r["vendor_id"] and line_qty(r) > 0:
            groups[int(r["vendor_id"])].append(r)
    out = []
    for _, rs in groups.items():
        rs = sorted(rs, key=lambda x: -(x["suggested_order_value"] or 0))[:MAX_LINES]
        units = sum(line_qty(r) for r in rs)
        value = sum(line_qty(r) * (r["unit_cost"] or 0) for r in rs)
        vendor = rs[0]["vendor_name"] or f"vendor {rs[0]['vendor_id']:.0f}"
        out.append({
            "kind": "purchase_order",
            "title": f"Order {len(rs)} item{'s' if len(rs) != 1 else ''} from {vendor}",
            "rationale": f"{len(rs)} purchased item{'s' if len(rs) != 1 else ''} from {vendor} {'are' if len(rs) != 1 else 'is'} out of stock or about to run out; {units} units, about {money(value)} at the vendor's price. {urgent(rs)}.",
            "payload": {"lines": [{"product_id": int(r["key"]), "qty": line_qty(r)} for r in rs]},
            "_value": value,
        })
    return out


def campaign_proposals(rows: list[dict], evidence: dict) -> list[dict]:
    bands = {10: "1-10%", 20: "11-20%", 30: "21-30%", 40: "over 30%"}
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in rows:
        pct = int(r["suggested_discount_pct"] or 0)
        if pct > 0 and (r["excess_value"] or 0) >= MIN_EXCESS_VALUE:
            groups[(r["category"], pct)].append(r)
    out = []
    for (category, pct), rs in groups.items():
        rs = sorted(rs, key=lambda x: -(x["excess_value"] or 0))[:MAX_CAMPAIGN_PRODUCTS]
        excess = sum(r["excess_value"] for r in rs)
        ev = evidence.get(bands.get(pct, ""))
        past = (f" Past offers at this depth: median {ev['median_lift']:.1f}x units/day over {ev['offers_with_baseline']} offers (descriptive, no control group)."
                if ev else " No past offer at this depth to compare with.")
        out.append({
            "kind": "campaign",
            "title": f"{pct}% clearance on {len(rs)} {category} item{'s' if len(rs) != 1 else ''}",
            "rationale": f"{len(rs)} {category} item{'s' if len(rs) != 1 else ''} {'hold' if len(rs) != 1 else 'holds'} {money(excess)} of excess stock (stock beyond 60 days of demand or no recent sale).{past}",
            "payload": {"product_ids": [int(r["key"]) for r in rs], "discount_pct": pct, "days": CAMPAIGN_DAYS},
            "_value": excess,
        })
    return out


def draft(at_risk: list[dict], excess: list[dict], evidence: dict, max_proposals: int = 12) -> list[dict]:
    """The week's proposals, most valuable first, capped."""
    proposals = work_order_proposals(at_risk) + purchase_order_proposals(at_risk) + campaign_proposals(excess, evidence)
    proposals.sort(key=lambda p: -p["_value"])
    return proposals[:max_proposals]


def strip_private(proposals: list[dict]) -> list[dict]:
    return [{k: v for k, v in p.items() if not k.startswith("_")} for p in proposals]
