"""LLM mode: Claude reads the inventory through read-only tools and drafts proposals through propose_* tools.

The model never talks to the actions service. The harness collects what it proposes, checks it, and submits the
batch itself, where the service runs the same rules as for an action. Nothing here can approve, dismiss or create
anything: the tools only read, or record a draft. Every request, tool call and result goes into the run log.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable

from agent.drafting import line_qty, reorder_bounds

MODEL = os.environ.get("AGENT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("AGENT_EFFORT", "medium")
MAX_TURNS = int(os.environ.get("AGENT_MAX_TURNS", "15"))
MAX_TOKENS = 16000

SYSTEM = """You prepare the weekly inventory proposals for a purchasing manager and a marketing manager. The data is a simulated \
AdventureWorks company; nothing you do touches a real system. A person reviews and approves every proposal: you cannot approve, \
create or change anything, only draft.

Work from the tools, never from memory or assumption:
- list_at_risk shows items that are out of stock or about to run out, with the quantity the mart suggests, the lead time, the \
vendor limits and what is already on order. list_excess shows overstock and dead stock with a suggested discount. \
get_offer_evidence shows what past offers did (units per day during an offer over the 28 days before; descriptive, no control group, \
so describe it as what happened, never as what a discount causes). list_open_proposals shows drafts still waiting, so do not repeat them.
- Draft with propose_work_order (in-house items, replenishment_type manufacture), propose_purchase_order (purchased items, one vendor \
per proposal) and propose_campaign (overstock or dead stock, one discount for the products it names, 7-90 days).
- Use each item's suggested_order_qty as the quantity. Change it only for a reason you can state in deviation_reason (for example \
the vendor minimum or a clearly different demand picture in the data), otherwise the draft is refused. Items whose suggested quantity \
is 0 are already covered by open orders: leave them out.
- Group sensibly: work orders by product category, purchase orders by vendor, campaigns by category and discount depth. Put the \
most valuable groups first and stop at about {max_proposals} proposals.
- Each proposal needs a title and a rationale of one or two sentences with the numbers that justify it (item count, units, value, \
the most urgent item). Do not invent figures; use the ones the tools returned.
When you are done, reply with a two-sentence summary of what you drafted and what you left out and why."""

TOOLS = [
    {"name": "list_at_risk", "description": "Items that are out of stock or about to run out, most valuable first. Read-only.",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False}},
    {"name": "list_excess", "description": "Overstock and dead-stock items with a suggested discount, largest excess first. Read-only.",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False}},
    {"name": "get_offer_evidence", "description": "Median lift of past offers per discount band. Descriptive only. Read-only.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "list_open_proposals", "description": "Proposals already drafted and still waiting for a decision. Read-only.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
]
_LINES = {"type": "array", "minItems": 1, "maxItems": 25, "items": {"type": "object", "required": ["product_id", "qty"], "additionalProperties": False, "properties": {
    "product_id": {"type": "integer"}, "qty": {"type": "integer", "minimum": 1},
    "deviation_reason": {"type": "string", "description": "Required when qty differs from the item's suggested_order_qty"}}}}
for _name, _desc in (("propose_work_order", "Draft a work order for in-house items."), ("propose_purchase_order", "Draft a purchase order: all items from one vendor.")):
    TOOLS.append({"name": _name, "description": _desc + " Records a draft for a person to review; it creates nothing.",
                  "input_schema": {"type": "object", "required": ["title", "rationale", "lines"], "additionalProperties": False,
                                   "properties": {"title": {"type": "string"}, "rationale": {"type": "string"}, "lines": _LINES}}})
TOOLS.append({"name": "propose_campaign", "description": "Draft a discount campaign for overstock or dead-stock products. Records a draft; it creates nothing.",
              "input_schema": {"type": "object", "required": ["title", "rationale", "product_ids", "discount_pct", "days"], "additionalProperties": False,
                               "properties": {"title": {"type": "string"}, "rationale": {"type": "string"},
                                              "product_ids": {"type": "array", "minItems": 1, "maxItems": 25, "items": {"type": "integer"}},
                                              "discount_pct": {"type": "integer", "minimum": 1, "maximum": 50}, "days": {"type": "integer", "minimum": 7, "maximum": 90}}}})

SHOW = ("key", "product_name", "category", "status", "replenishment_type", "vendor_id", "vendor_name", "on_hand", "on_order", "daily_demand",
        "days_of_cover", "lead_time_days", "unit_cost", "suggested_order_qty", "suggested_order_value", "min_order_qty", "max_order_qty",
        "excess_units", "excess_value", "suggested_discount_pct")


def compact(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        row = {k: r[k] for k in SHOW if r.get(k) is not None}
        for k, v in row.items():
            if isinstance(v, float):
                row[k] = round(v, 2)
        out.append(row)
    return out


def to_dict(block) -> dict:
    return block.model_dump() if hasattr(block, "model_dump") else dict(vars(block))


class Session:
    """The tools' state for one run: what the model has seen, and what it has proposed."""

    def __init__(self, api, log: Callable[[str, dict], None]):
        self.api, self.log = api, log
        self.seen: dict[int, dict] = {}
        self.proposals: list[dict] = []
        self.read_at_risk: list[dict] = []
        self.read_excess: list[dict] = []

    def call(self, name: str, args: dict) -> dict:
        try:
            return getattr(self, f"tool_{name}")(**args)
        except TypeError as exc:
            return {"error": f"bad arguments: {exc}"}

    def tool_list_at_risk(self, limit: int = 40) -> dict:
        self.read_at_risk = self.api.at_risk(min(max(limit, 1), 100))
        self.seen.update({int(r["key"]): r for r in self.read_at_risk})
        return {"items": compact(self.read_at_risk)}

    def tool_list_excess(self, limit: int = 40) -> dict:
        self.read_excess = self.api.excess(min(max(limit, 1), 100))
        self.seen.update({int(r["key"]): r for r in self.read_excess})
        return {"items": compact(self.read_excess)}

    def tool_get_offer_evidence(self) -> dict:
        return {"bands": self.api.offer_evidence()}

    def tool_list_open_proposals(self) -> dict:
        return {"proposals": [{"id": p["id"], "kind": p["kind"], "title": p["title"],
                               "products": p["payload"].get("product_ids") or [l["product_id"] for l in p["payload"].get("lines", [])]}
                              for p in self.api.open_proposals()]}

    # ---- drafting: checked here so the model can correct itself; the service checks again on submit ----
    def _lines(self, kind: str, title: str, rationale: str, lines: list[dict]) -> dict:
        want = "purchase" if kind == "purchase_order" else "manufacture"
        notes, out, vendors = [], [], set()
        for line in lines:
            row = self.seen.get(int(line["product_id"]))
            if row is None:
                return {"accepted": False, "reason": f"product {line['product_id']} was not in a list you read"}
            if row["status"] not in ("stockout", "reorder_now") or row["replenishment_type"] != want:
                return {"accepted": False, "reason": f"{row['product_name']} is {row['status']} / {row['replenishment_type']}, not an at-risk {want} item"}
            suggested = line_qty(row)
            if suggested <= 0:
                return {"accepted": False, "reason": f"{row['product_name']} needs nothing: open orders already cover it"}
            qty = int(line["qty"])
            if want == "purchase":
                lo, hi = reorder_bounds(row)
                if not lo <= qty <= hi:
                    return {"accepted": False, "reason": f"{row['product_name']}: quantity must be {lo}-{hi}"}
                vendors.add(row["vendor_id"])
            if qty != suggested:
                reason = (line.get("deviation_reason") or "").strip()
                if not reason:
                    return {"accepted": False, "reason": f"{row['product_name']}: {qty} differs from the suggested {suggested:.0f}; give a deviation_reason or use {suggested:.0f}"}
                notes.append(f"Deviation for {row['product_name']} ({qty} instead of {suggested:.0f}): {reason}")
            out.append({"product_id": int(line["product_id"]), "qty": qty})
        if len({int(l["product_id"]) for l in lines}) != len(lines):
            return {"accepted": False, "reason": "a product appears twice"}
        if len(vendors) > 1:
            return {"accepted": False, "reason": "a purchase order covers one vendor"}
        proposal = {"kind": kind, "title": title.strip(), "rationale": " ".join([rationale.strip(), *notes]), "payload": {"lines": out}}
        self.proposals.append(proposal)
        return {"accepted": True, "proposal_number": len(self.proposals)}

    def tool_propose_work_order(self, title: str, rationale: str, lines: list[dict]) -> dict:
        return self._lines("work_order", title, rationale, lines)

    def tool_propose_purchase_order(self, title: str, rationale: str, lines: list[dict]) -> dict:
        return self._lines("purchase_order", title, rationale, lines)

    def tool_propose_campaign(self, title: str, rationale: str, product_ids: list[int], discount_pct: int, days: int) -> dict:
        rows = []
        for pid in product_ids:
            row = self.seen.get(int(pid))
            if row is None or row["status"] not in ("overstock", "dead_stock"):
                return {"accepted": False, "reason": f"product {pid} is not an overstock or dead-stock item you read"}
            rows.append(row)
        top = max(int(r["suggested_discount_pct"] or 0) for r in rows)
        if not 1 <= discount_pct <= min(50, max(2 * top, 5)):
            return {"accepted": False, "reason": f"discount must be 1-{min(50, max(2 * top, 5))}% for these products"}
        self.proposals.append({"kind": "campaign", "title": title.strip(), "rationale": rationale.strip(),
                               "payload": {"product_ids": [int(p) for p in product_ids], "discount_pct": discount_pct, "days": days}})
        return {"accepted": True, "proposal_number": len(self.proposals)}


def run_llm(client, api, log: Callable[[str, dict], None], max_proposals: int = 12) -> tuple[list[dict], dict, Session]:
    """Run the tool-use loop; returns (proposals, info, session). `client` is an anthropic.Anthropic (or a stand-in)."""
    session = Session(api, log)
    system = SYSTEM.format(max_proposals=max_proposals)
    messages = [{"role": "user", "content": "Prepare this week's proposals."}]
    log("request", {"model": MODEL, "effort": EFFORT, "system": system, "tools": [t["name"] for t in TOOLS], "messages": messages})
    usage = {"input_tokens": 0, "output_tokens": 0, "turns": 0}
    summary, stop = "", "max_turns"
    for turn in range(MAX_TURNS):
        response = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=system, tools=TOOLS, messages=messages,
                                          output_config={"effort": EFFORT})
        usage["turns"] += 1
        usage["input_tokens"] += getattr(response.usage, "input_tokens", 0) or 0
        usage["output_tokens"] += getattr(response.usage, "output_tokens", 0) or 0
        log("assistant", {"turn": turn, "stop_reason": response.stop_reason, "content": [to_dict(b) for b in response.content]})
        if response.stop_reason in ("refusal", "max_tokens"):
            stop = response.stop_reason
            break
        if response.stop_reason != "tool_use":
            summary = next((b.text for b in response.content if b.type == "text"), "")
            stop = response.stop_reason
            break
        messages.append({"role": "assistant", "content": response.content})   # thinking blocks go back unchanged
        results = []
        for block in (b for b in response.content if b.type == "tool_use"):
            out = session.call(block.name, dict(block.input))
            log("tool", {"name": block.name, "input": dict(block.input), "result": out})
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out, default=str), **({"is_error": True} if "error" in out else {})})
        messages.append({"role": "user", "content": results})
    return session.proposals[:max_proposals], {"stop": stop, "summary": summary, "usage": usage, "model": MODEL}, session
