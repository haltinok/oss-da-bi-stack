import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


def row(key, **kw):
    base = {"key": float(key), "product_name": f"Item {key}", "category": "Bikes", "status": "stockout", "replenishment_type": "manufacture",
            "vendor_id": None, "vendor_name": None, "on_hand": 0.0, "on_order": 0.0, "daily_demand": 2.0, "days_of_cover": 0.0,
            "lead_time_days": 4.0, "unit_cost": 100.0, "suggested_order_qty": 40.0, "suggested_order_value": 4000.0, "min_order_qty": None,
            "max_order_qty": None, "excess_units": 0.0, "excess_value": 0.0, "suggested_discount_pct": 0.0, "reason": "x"}
    return {**base, **kw}


class FakeApi:
    def __init__(self, at_risk=(), excess=(), evidence=None, open_proposals=()):
        self._at, self._ex, self._ev, self._open = list(at_risk), list(excess), evidence or {}, list(open_proposals)
        self.submitted = None

    def at_risk(self, limit=60):
        return self._at[:limit]

    def excess(self, limit=60):
        return self._ex[:limit]

    def offer_evidence(self):
        return self._ev

    def open_proposals(self):
        return self._open

    def recently_approved(self, hours=24):
        return []

    def submit(self, run_id, proposals):
        self.submitted = (run_id, proposals)
        return {"run_id": run_id, "results": [{"seq": i, "ok": True, "id": i + 1} for i in range(len(proposals))]}
