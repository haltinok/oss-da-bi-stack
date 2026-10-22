from agent import drafting
from agent.tests.conftest import row


def test_work_orders_group_by_category_and_use_the_suggested_quantity():
    rows = [row(1, category="Bikes"), row(2, category="Bikes", suggested_order_qty=10.0, suggested_order_value=1000.0), row(3, category="Frames")]
    props = drafting.work_order_proposals(rows)
    assert {p["title"] for p in props} == {"Restock 2 in-house Bikes items", "Restock 1 in-house Frames item"}
    bikes = next(p for p in props if "Bikes" in p["title"])
    assert bikes["payload"]["lines"] == [{"product_id": 1, "qty": 40}, {"product_id": 2, "qty": 10}]      # most valuable first
    assert "50 units" in bikes["rationale"] and "most urgent" in bikes["rationale"]


def test_items_already_covered_by_open_orders_are_left_out():
    assert drafting.work_order_proposals([row(1, suggested_order_qty=0.0, suggested_order_value=0.0)]) == []


def test_purchase_orders_group_by_vendor_and_respect_vendor_limits():
    rows = [row(1, replenishment_type="purchase", vendor_id=7.0, vendor_name="Acme", suggested_order_qty=5.0, min_order_qty=20.0, max_order_qty=150.0),
            row(2, replenishment_type="purchase", vendor_id=7.0, vendor_name="Acme", suggested_order_qty=400.0, max_order_qty=150.0),
            row(3, replenishment_type="purchase", vendor_id=8.0, vendor_name="Bolt")]
    props = drafting.purchase_order_proposals(rows)
    acme = next(p for p in props if "Acme" in p["title"])
    assert acme["payload"]["lines"] == [{"product_id": 2, "qty": 150}, {"product_id": 1, "qty": 20}] or acme["payload"]["lines"] == [{"product_id": 1, "qty": 20}, {"product_id": 2, "qty": 150}]
    assert len(props) == 2


def test_campaigns_group_by_category_and_depth_and_cite_the_evidence():
    ex = [row(i, status="overstock", category="Bikes", suggested_discount_pct=20.0, excess_value=1000.0 * i) for i in (1, 2)]
    ex += [row(3, status="dead_stock", category="Bikes", suggested_discount_pct=30.0, excess_value=900.0),
           row(4, status="overstock", category="Bikes", suggested_discount_pct=20.0, excess_value=10.0)]   # too small to matter
    props = drafting.campaign_proposals(ex, {"11-20%": {"median_lift": 1.4, "offers_with_baseline": 3}})
    by = {p["payload"]["discount_pct"]: p for p in props}
    assert set(by) == {20, 30}
    assert by[20]["payload"]["product_ids"] == [2, 1]                                       # largest excess first, tiny one dropped
    assert "median 1.4x" in by[20]["rationale"] and "no control group" in by[20]["rationale"]
    assert "No past offer" in by[30]["rationale"]


def test_draft_is_capped_and_most_valuable_first_and_private_fields_are_stripped():
    rows = [row(i, category=f"C{i}", suggested_order_value=float(i * 100)) for i in range(1, 20)]
    props = drafting.draft(rows, [], {}, max_proposals=5)
    assert len(props) == 5 and props[0]["_value"] >= props[-1]["_value"]
    assert all(not k.startswith("_") for p in drafting.strip_private(props) for k in p)
