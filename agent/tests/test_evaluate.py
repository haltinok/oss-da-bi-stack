from agent.evaluate import evaluate
from agent.tests.conftest import row


def wo(*lines, rationale="Restock."):
    return {"kind": "work_order", "title": "t", "rationale": rationale, "payload": {"lines": [dict(product_id=p, qty=q, **({"deviation_reason": r} if r else {})) for p, q, r in lines]}}


def test_quantities_equal_to_the_suggestion_match_and_the_rest_are_listed():
    at = [row(1), row(2), row(3, suggested_order_qty=0.0, suggested_order_value=0.0)]
    rep = evaluate([wo((1, 40, None), (2, 55, "Demand doubled this week"))], at, [])
    assert rep["order_lines"] == 2 and rep["quantity_matches_suggestion"] == 1
    assert rep["deviations"][0]["suggested"] == 40 and rep["unexplained_deviations"] == 0
    assert rep["at_risk_items_needing_an_order"] == 2                       # item 3 needs nothing
    assert rep["share_of_reorder_value_drafted"] == 1.0


def test_a_deviation_without_a_reason_is_flagged():
    rep = evaluate([wo((1, 55, None))], [row(1)], [])
    assert rep["unexplained_deviations"] == 1


def test_coverage_of_reorder_and_excess_value_and_refusals_from_the_service():
    at = [row(1, suggested_order_value=3000.0), row(2, suggested_order_value=1000.0)]
    ex = [row(10, status="overstock", suggested_discount_pct=10.0, excess_value=800.0), row(11, status="overstock", suggested_discount_pct=10.0, excess_value=200.0)]
    camp = {"kind": "campaign", "title": "c", "rationale": "r", "payload": {"product_ids": [10], "discount_pct": 10, "days": 30}}
    rep = evaluate([wo((1, 40, None)), camp], at, ex, results=[{"seq": 0, "ok": True}, {"seq": 1, "ok": False, "reason": "no"}])
    assert rep["share_of_reorder_value_drafted"] == 0.75 and rep["share_of_excess_value_in_campaigns"] == 0.8
    assert rep["refused_by_service"] == [{"seq": 1, "reason": "no"}]
