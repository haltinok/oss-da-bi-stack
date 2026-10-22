"""Unit tests for the validation rules (no services needed).

  uv run --with pytest python -I -m pytest actions/tests/test_rules.py
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import rules  # noqa: E402


def row(**kw):
    base = {"status": "stockout", "replenishment_type": "purchase", "vendor_id": 7, "lead_time_days": 10, "unit_cost": 2.5,
            "suggested_order_qty": 100, "min_order_qty": 20, "max_order_qty": 150, "suggested_discount_pct": 0}
    return {**base, **kw}


def test_reorder_bounds_follow_vendor_limits_and_twice_the_suggestion():
    assert rules.reorder_bounds(row()) == (20, 150)                                  # 2x100 capped by the vendor max
    assert rules.reorder_bounds(row(max_order_qty=0)) == (20, 200)                   # no vendor max
    assert rules.reorder_bounds(row(suggested_order_qty=0, min_order_qty=50)) == (50, 50)
    assert rules.reorder_bounds(row(suggested_order_qty=0, min_order_qty=0, max_order_qty=0)) == (1, 1)
    low, high = rules.reorder_bounds(row(min_order_qty=500, max_order_qty=100))      # vendor max below its min
    assert low <= high


@pytest.mark.parametrize("qty", [20, 100, 150])
def test_quantity_inside_bounds_is_accepted(qty):
    out = rules.check_replenishment(row(), 5, qty, "purchase")
    assert out["qty"] == qty and out["vendor_id"] == 7 and out["unit_cost"] == 2.5 and out["lead_time_days"] == 10


@pytest.mark.parametrize("qty", [0, 19, 151, 10_000])
def test_quantity_outside_bounds_is_refused(qty):
    with pytest.raises(rules.Refused):
        rules.check_replenishment(row(), 5, qty, "purchase")


@pytest.mark.parametrize("status", ["healthy", "overstock", "dead_stock", "discontinued", "not_stocked"])
def test_only_stockout_and_reorder_now_can_be_replenished(status):
    with pytest.raises(rules.Refused):
        rules.check_replenishment(row(status=status), 5, 50, "purchase")
    assert rules.check_replenishment(row(status="reorder_now"), 5, 50, "purchase")


def test_replenishment_kind_must_match_the_product():
    with pytest.raises(rules.Refused):
        rules.check_replenishment(row(replenishment_type="manufacture", vendor_id=None), 5, 50, "purchase")
    with pytest.raises(rules.Refused):
        rules.check_replenishment(row(replenishment_type="purchase"), 5, 50, "manufacture")
    with pytest.raises(rules.Refused):
        rules.check_replenishment(row(vendor_id=None), 5, 50, "purchase")


def test_unknown_product_is_refused():
    with pytest.raises(rules.Refused):
        rules.check_replenishment(None, 5, 50, "purchase")


def test_work_order_quantity_is_capped_at_twice_the_suggestion():
    wo = row(replenishment_type="manufacture", vendor_id=None, suggested_order_qty=40)
    assert rules.check_replenishment(wo, 5, 80, "manufacture")["qty"] == 80
    with pytest.raises(rules.Refused):
        rules.check_replenishment(wo, 5, 81, "manufacture")
    with pytest.raises(rules.Refused):
        rules.check_replenishment(wo, 5, 0, "manufacture")


def excess(**kw):
    return {"status": "overstock", "suggested_discount_pct": 10, **kw}


def test_campaign_discount_range_scales_with_the_suggestion_and_caps_at_50():
    assert rules.discount_bounds([excess()]) == (1, 20)
    assert rules.discount_bounds([excess(suggested_discount_pct=0)]) == (1, 5)
    assert rules.discount_bounds([excess(suggested_discount_pct=40)]) == (1, 50)
    assert rules.discount_bounds([excess(suggested_discount_pct=10), excess(suggested_discount_pct=30)]) == (1, 50)


def test_campaign_rules():
    rows = {1: excess(), 2: excess(status="dead_stock", suggested_discount_pct=30), 3: {"status": "healthy", "suggested_discount_pct": 0}}
    rules.check_campaign(rows, [1, 2], 30, 30)
    for args in (([1, 3], 10, 30),          # a healthy product
                 ([1, 2], 51, 30),           # deeper than allowed
                 ([1, 2], 0, 30),            # no discount
                 ([1, 2], 10, 6),            # too short
                 ([1, 2], 10, 91),           # too long
                 ([], 10, 30),               # nothing selected
                 ([1, 1], 10, 30),           # duplicate product
                 ([1, 99], 10, 30)):         # unknown product
        with pytest.raises(rules.Refused):
            rules.check_campaign(rows, *args)


def test_line_count_limits():
    rules.check_line_count(1)
    rules.check_line_count(rules.MAX_LINES)
    for n in (0, rules.MAX_LINES + 1):
        with pytest.raises(rules.Refused):
            rules.check_line_count(n)
