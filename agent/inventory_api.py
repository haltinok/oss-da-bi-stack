"""What the agent can reach: inventory through Cube (read-only) and the actions service (draft proposals).

The agent signs in as the Keycloak service account `inventory-agent` (client-credentials grant). The auth
service turns that token into a Cube token with the role `agent`, which cube/cube.js limits to the two inventory
cubes; the actions service lets the same token draft proposals and do nothing else. No password, no sales data.
"""
from __future__ import annotations

import os
import time

import requests

INV = "inventory_health"


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise SystemExit(f"{name} is not set")
    return value


class InventoryApi:
    def __init__(self):
        self.keycloak = env("KEYCLOAK_TOKEN_URL", "http://keycloak:8080/realms/spike/protocol/openid-connect/token")
        self.auth = env("AUTH_URL", "http://auth:8200")
        self.cube = env("CUBE_URL", "http://cube:4000/cubejs-api/v1/load")
        self.actions = env("ACTIONS_URL", "http://actions:8300")
        self._kc = self._cube = None
        self._at = 0.0

    # -- tokens (refreshed every 10 minutes: the Cube token lives 15) --
    def _tokens(self) -> tuple[str, str]:
        if self._kc is None or time.time() - self._at > 600:
            kc = requests.post(self.keycloak, timeout=30, data={
                "grant_type": "client_credentials", "client_id": "inventory-agent", "client_secret": env("AGENT_CLIENT_SECRET")})
            kc.raise_for_status()
            self._kc = kc.json()["access_token"]
            cube = requests.post(f"{self.auth}/token", headers={"Authorization": f"Bearer {self._kc}"}, timeout=30)
            cube.raise_for_status()
            self._cube = cube.json()["token"]
            self._at = time.time()
        return self._kc, self._cube

    def load(self, query: dict) -> list[dict]:
        _, cube = self._tokens()
        for _ in range(120):
            r = requests.post(self.cube, json={"query": query}, headers={"Authorization": cube}, timeout=300)
            body = r.json()
            if body.get("error") == "Continue wait":
                time.sleep(1)
                continue
            r.raise_for_status()
            return body["data"]
        raise TimeoutError("Cube did not answer")

    def items(self, statuses: list[str], limit: int, order_by: str, direction: str = "desc") -> list[dict]:
        """Inventory rows with these statuses, as plain dicts with the Cube prefixes removed."""
        dims = ["key", "product_name", "status", "replenishment_type", "vendor_id", "vendor_name", "on_hand", "on_order", "daily_demand",
                "days_of_cover", "lead_time_days", "unit_cost", "suggested_order_qty", "suggested_order_value", "min_order_qty",
                "max_order_qty", "excess_units", "excess_value", "suggested_discount_pct", "reason"]
        rows = self.load({
            "dimensions": [f"{INV}.{d}" for d in dims] + ["products.category"],
            "filters": [{"member": f"{INV}.status", "operator": "equals", "values": statuses}],
            "order": [[f"{INV}.{order_by}", direction]], "limit": limit,
        })
        out = []
        for r in rows:
            row = {k.split(".", 1)[1]: v for k, v in r.items()}
            for k in ("key", "vendor_id", "on_hand", "on_order", "daily_demand", "days_of_cover", "lead_time_days", "unit_cost",
                      "suggested_order_qty", "suggested_order_value", "min_order_qty", "max_order_qty", "excess_units", "excess_value",
                      "suggested_discount_pct"):
                row[k] = None if row.get(k) is None else float(row[k])
            row["category"] = row.pop("category", None) or "Uncategorized"
            out.append(row)
        return out

    def at_risk(self, limit: int = 60) -> list[dict]:
        return self.items(["stockout", "reorder_now"], limit, "suggested_order_value")

    def excess(self, limit: int = 60) -> list[dict]:
        return self.items(["overstock", "dead_stock"], limit, "excess_value")

    def offer_evidence(self) -> dict:
        """Median lift per discount band: units/day during past offers over the 28 days before (descriptive only)."""
        rows = self.load({"dimensions": ["offer_performance.key", "offer_performance.discount_band", "offer_performance.lift"], "limit": 500})
        by: dict[str, list[float]] = {}
        for r in rows:
            if r["offer_performance.lift"] is not None:
                by.setdefault(r["offer_performance.discount_band"], []).append(float(r["offer_performance.lift"]))
        out = {}
        for band, lifts in by.items():
            lifts.sort()
            m = len(lifts) // 2
            out[band] = {"offers_with_baseline": len(lifts), "median_lift": lifts[m] if len(lifts) % 2 else (lifts[m - 1] + lifts[m]) / 2}
        return out

    # -- actions service --
    def _auth_header(self) -> dict:
        kc, _ = self._tokens()
        return {"Authorization": f"Bearer {kc}"}

    def open_proposals(self) -> list[dict]:
        r = requests.get(f"{self.actions}/proposals", headers=self._auth_header(), timeout=30)
        r.raise_for_status()
        return r.json()["proposals"]

    def submit(self, run_id: str, proposals: list[dict]) -> dict:
        r = requests.post(f"{self.actions}/proposals", json={"run_id": run_id, "proposals": proposals}, headers=self._auth_header(), timeout=60)
        r.raise_for_status()
        return r.json()
