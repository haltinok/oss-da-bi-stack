"""Judging a draft against what the mart suggested, so a run can be reviewed (and compared across modes).

The check the plan asks for: a drafted quantity must equal the mart's `suggested_order_qty` unless the proposal
explains the deviation. Raising a purchased item to the vendor minimum or capping it at the vendor maximum is not
a deviation, it is the rule; anything else is listed with its stated reason, or flagged when there is none.
"""
from __future__ import annotations

from agent.drafting import line_qty


def evaluate(proposals: list[dict], at_risk: list[dict], excess: list[dict], results: list[dict] | None = None) -> dict:
    by_id = {int(r["key"]): r for r in at_risk + excess}
    lines = matches = 0
    deviations: list[dict] = []
    covered_at_risk: set[int] = set()
    covered_excess: set[int] = set()
    for p in proposals:
        payload = p["payload"]
        if p["kind"] == "campaign":
            covered_excess.update(int(i) for i in payload["product_ids"])
            continue
        for line in payload["lines"]:
            pid, qty = int(line["product_id"]), int(line["qty"])
            row = by_id.get(pid)
            lines += 1
            covered_at_risk.add(pid)
            if row is None:
                deviations.append({"product_id": pid, "qty": qty, "suggested": None, "reason": "not in the lists the agent read", "explained": False})
            elif qty == line_qty(row):
                matches += 1
            else:
                reason = line.get("deviation_reason") or ""
                deviations.append({"product_id": pid, "name": row["product_name"], "qty": qty, "suggested": line_qty(row),
                                   "reason": reason, "explained": bool(reason.strip()) or "Deviation" in p.get("rationale", "")})
    needed = [r for r in at_risk if line_qty(r) > 0]
    needed_value = sum(r["suggested_order_value"] or 0 for r in needed)
    drafted_value = sum(r["suggested_order_value"] or 0 for r in needed if int(r["key"]) in covered_at_risk)
    campaign_pool = [r for r in excess if (r["suggested_discount_pct"] or 0) > 0 and (r["excess_value"] or 0) > 0]
    pool_value = sum(r["excess_value"] for r in campaign_pool)
    out = {
        "proposals": len(proposals),
        "order_lines": lines,
        "quantity_matches_suggestion": matches,
        "deviations": deviations,
        "unexplained_deviations": sum(1 for d in deviations if not d["explained"]),
        "at_risk_items_needing_an_order": len(needed),
        "share_of_reorder_value_drafted": round(drafted_value / needed_value, 3) if needed_value else None,
        "share_of_excess_value_in_campaigns": round(sum(r["excess_value"] for r in campaign_pool if int(r["key"]) in covered_excess) / pool_value, 3) if pool_value else None,
    }
    if results is not None:
        out["refused_by_service"] = [{"seq": r["seq"], "reason": r["reason"]} for r in results if not r["ok"]]
    return out
