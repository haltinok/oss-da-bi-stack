"""The tool-use loop against a scripted stand-in for the Anthropic client (no network, no key)."""
from types import SimpleNamespace as NS

from agent import llm
from agent.tests.conftest import FakeApi, row


def tool_use(i, name, **inp):
    return NS(type="tool_use", id=f"tu_{i}", name=name, input=inp)


def reply(stop, *content, out=100):
    return NS(stop_reason=stop, content=list(content), usage=NS(input_tokens=1000, output_tokens=out))


class FakeClient:
    def __init__(self, turns):
        self.turns, self.requests = list(turns), []
        self.messages = NS(create=self._create)

    def _create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})   # the loop appends to the same list afterwards
        return self.turns.pop(0)


def events():
    seen = []
    return seen, lambda event, payload: seen.append((event, payload))


def test_loop_reads_then_drafts_and_the_model_can_correct_a_refused_draft():
    api = FakeApi(at_risk=[row(1), row(2), row(3, replenishment_type="purchase", vendor_id=7.0, vendor_name="Acme", suggested_order_qty=30.0),
                          row(4, replenishment_type="purchase", vendor_id=8.0, vendor_name="Bolt", suggested_order_qty=30.0)],
                  excess=[row(10, status="overstock", suggested_discount_pct=20.0, excess_value=900.0)])
    thinking = NS(type="thinking", thinking="", signature="sig")
    client = FakeClient([
        reply("tool_use", thinking, tool_use(1, "list_at_risk"), tool_use(2, "list_excess")),
        reply("tool_use", tool_use(3, "propose_work_order", title="Restock bikes", rationale="Two items are out of stock.", lines=[{"product_id": 1, "qty": 39}, {"product_id": 2, "qty": 40}]),
              tool_use(4, "propose_purchase_order", title="Mixed", rationale="r", lines=[{"product_id": 3, "qty": 30}, {"product_id": 4, "qty": 30}]),
              tool_use(5, "propose_campaign", title="Clear", rationale="Excess.", product_ids=[10], discount_pct=20, days=30)),
        reply("tool_use", tool_use(6, "propose_work_order", title="Restock bikes", rationale="Two items are out of stock.",
                                    lines=[{"product_id": 1, "qty": 39, "deviation_reason": "demand fell"}, {"product_id": 2, "qty": 40}])),
        reply("end_turn", NS(type="text", text="Drafted two proposals.")),
    ])
    seen, log = events()
    proposals, info, session = llm.run_llm(client, api, log)
    kinds = [p["kind"] for p in proposals]
    assert kinds == ["campaign", "work_order"]
    wo = proposals[1]
    assert wo["payload"]["lines"][0] == {"product_id": 1, "qty": 39} and "Deviation for Item 1 (39 instead of 40): demand fell" in wo["rationale"]
    assert info["stop"] == "end_turn" and info["summary"] == "Drafted two proposals." and info["usage"]["turns"] == 4
    # the rejected drafts were reported back to the model with a reason, not raised
    results = [e[1]["result"] for e in seen if e[0] == "tool" and e[1]["name"].startswith("propose")]
    assert results[0]["accepted"] is False and "deviation_reason" in results[0]["reason"]
    assert results[1]["accepted"] is False and "one vendor" in results[1]["reason"]
    # parallel tool results go back in ONE user message, and the thinking block is passed back unchanged
    second = client.requests[1]["messages"]
    assert second[-1]["role"] == "user" and [r["tool_use_id"] for r in second[-1]["content"]] == ["tu_1", "tu_2"]
    assert second[-2]["content"][0] is thinking
    assert client.requests[0]["output_config"] == {"effort": llm.EFFORT} and "tool_choice" not in client.requests[0]


def test_drafts_must_come_from_items_the_model_has_read():
    s = llm.Session(FakeApi(at_risk=[row(1)]), lambda *_: None)
    assert s.call("propose_work_order", {"title": "t", "rationale": "r", "lines": [{"product_id": 1, "qty": 40}]})["accepted"] is False   # not read yet
    s.call("list_at_risk", {})
    assert s.call("propose_work_order", {"title": "t", "rationale": "r", "lines": [{"product_id": 1, "qty": 40}]})["accepted"] is True
    assert s.call("propose_purchase_order", {"title": "t", "rationale": "r", "lines": [{"product_id": 1, "qty": 40}]})["accepted"] is False  # wrong kind
    assert "error" in s.call("propose_work_order", {"title": "t"})                                                                       # malformed


def test_items_covered_by_open_orders_and_deep_discounts_are_refused():
    s = llm.Session(FakeApi(at_risk=[row(1, suggested_order_qty=0.0)], excess=[row(10, status="overstock", suggested_discount_pct=10.0)]), lambda *_: None)
    s.call("list_at_risk", {}); s.call("list_excess", {})
    assert "already cover" in s.call("propose_work_order", {"title": "t", "rationale": "r", "lines": [{"product_id": 1, "qty": 1}]})["reason"]
    assert s.call("propose_campaign", {"title": "t", "rationale": "r", "product_ids": [10], "discount_pct": 21, "days": 30})["accepted"] is False
    assert s.call("propose_campaign", {"title": "t", "rationale": "r", "product_ids": [10], "discount_pct": 20, "days": 30})["accepted"] is True


def test_refusal_and_turn_limit_stop_the_loop_without_proposals(monkeypatch):
    seen, log = events()
    _, info, _ = llm.run_llm(FakeClient([reply("refusal")]), FakeApi(), log)
    assert info["stop"] == "refusal"
    monkeypatch.setattr(llm, "MAX_TURNS", 2)
    loop = FakeClient([reply("tool_use", tool_use(i, "list_at_risk")) for i in range(5)])
    proposals, info, _ = llm.run_llm(loop, FakeApi(at_risk=[row(1)]), log)
    assert proposals == [] and info["stop"] == "max_turns" and info["usage"]["turns"] == 2


def test_the_model_has_no_tool_that_approves_or_writes():
    names = {t["name"] for t in llm.TOOLS}
    assert names == {"list_at_risk", "list_excess", "get_offer_evidence", "list_open_proposals", "propose_work_order", "propose_purchase_order", "propose_campaign"}
