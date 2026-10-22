"""Validation rules for the actions service, kept free of I/O so they can be unit-tested.

A request names products and, where the role may edit them, a quantity or a discount. Nothing else comes
from the client: vendor, unit price, lead time and the product's state are read from the current
mart.inventory_health row, and a request that disagrees with that row is refused.
"""
from __future__ import annotations

AT_RISK = ("stockout", "reorder_now")
EXCESS = ("overstock", "dead_stock")
MAX_LINES = 200
MAX_DISCOUNT_PCT = 50
MIN_CAMPAIGN_DAYS, MAX_CAMPAIGN_DAYS = 7, 90


class Refused(Exception):
    """The request breaks a rule; `reason` is safe to show to the caller."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _need(row: dict | None, product_id: int) -> dict:
    if row is None:
        raise Refused(f"product {product_id} is not in the inventory list")
    return row


def reorder_bounds(row: dict) -> tuple[int, int]:
    """Quantity a user may order: at least the vendor minimum (and 1), at most twice the suggestion and never
    above the vendor maximum. The suggestion can be 0 when what is on order already covers the need; then
    the minimum is the only quantity on offer. A vendor maximum below the minimum wins (the vendor will
    not take more), so the range is never empty."""
    suggested = int(row.get("suggested_order_qty") or 0)
    low = max(1, int(row.get("min_order_qty") or 0))
    high = max(2 * suggested, low)
    cap = int(row.get("max_order_qty") or 0)
    if cap > 0:
        high = min(high, cap)
        low = min(low, cap)
    return low, high


def check_replenishment(row: dict | None, product_id: int, qty: int, kind: str) -> dict:
    """`kind` is 'purchase' or 'manufacture'. Returns what the caller needs to write."""
    row = _need(row, product_id)
    if row["status"] not in AT_RISK:
        raise Refused(f"product {product_id} is not stocked out or due for reorder (it is {row['status']})")
    if row["replenishment_type"] != kind:
        raise Refused(f"product {product_id} is replenished by {row['replenishment_type']}, not {kind}")
    if kind == "purchase" and not row.get("vendor_id"):
        raise Refused(f"product {product_id} has no vendor")
    low, high = reorder_bounds(row) if kind == "purchase" else (1, max(1, 2 * int(row.get("suggested_order_qty") or 0)))
    if not low <= qty <= high:
        raise Refused(f"quantity {qty} for product {product_id} is outside the allowed range {low}-{high}")
    return {
        "product_id": product_id, "qty": qty, "vendor_id": row.get("vendor_id"), "unit_cost": float(row.get("unit_cost") or 0),
        "lead_time_days": max(1, int(row.get("lead_time_days") or 1)),
    }


def discount_bounds(rows: list[dict]) -> tuple[int, int]:
    """Allowed discount (whole percent) for a campaign: 1 up to twice the deepest suggestion, at most 50."""
    suggested = max((int(r.get("suggested_discount_pct") or 0) for r in rows), default=0)
    return 1, min(MAX_DISCOUNT_PCT, max(2 * suggested, 5))


def check_campaign(rows: dict[int, dict], product_ids: list[int], discount_pct: int, days: int) -> None:
    if not product_ids:
        raise Refused("no products selected")
    if len(set(product_ids)) != len(product_ids):
        raise Refused("a product appears more than once")
    chosen = []
    for pid in product_ids:
        row = _need(rows.get(pid), pid)
        if row["status"] not in EXCESS:
            raise Refused(f"product {pid} is not overstock or dead stock (it is {row['status']})")
        chosen.append(row)
    low, high = discount_bounds(chosen)
    if not low <= discount_pct <= high:
        raise Refused(f"discount {discount_pct}% is outside the allowed range {low}-{high}%")
    if not MIN_CAMPAIGN_DAYS <= days <= MAX_CAMPAIGN_DAYS:
        raise Refused(f"campaign length must be {MIN_CAMPAIGN_DAYS}-{MAX_CAMPAIGN_DAYS} days")


def check_line_count(n: int) -> None:
    if n < 1:
        raise Refused("no lines")
    if n > MAX_LINES:
        raise Refused(f"at most {MAX_LINES} lines per request")

