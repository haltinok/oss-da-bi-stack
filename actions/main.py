"""Actions service: an approved inventory proposal becomes a row in the simulated ERP (postgres_active).

  POST /actions/purchase-orders  {idempotency_key, lines: [{product_id, qty}]}        purchasing, admin
  POST /actions/work-orders      {idempotency_key, lines: [{product_id, qty}]}        purchasing, admin
  POST /actions/campaigns        {idempotency_key, product_ids, discount_pct, days}   marketing, admin
  GET  /actions/log                                                                   the role's own kinds

Every request carries a Keycloak access token, verified like the auth service does (signature, issuer,
expiry, client). Nothing the client sends is trusted beyond the product ids and the edits a role may make
(a quantity, a discount, a length): the vendor, unit price, lead time and the product's state come from the
current mart.inventory_health row, and rules.py refuses a request that disagrees with it. All writes of one
request, and its audit row, happen in one transaction; a refused request is logged on its own. The database
user can only insert into the purchasing / offer tables and the audit log (postgres_active/init/05_actions.sh).
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
import psycopg2
import psycopg2.errors
import psycopg2.extras
import pymysql
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import rules

ISSUER = os.environ["KEYCLOAK_ISSUER"]
JWKS_URL = os.environ["KEYCLOAK_JWKS_URL"]
CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "dashboard")
ROLE_ORDER = ("admin", "purchasing", "marketing")
KINDS = {"admin": ("purchase_order", "work_order", "campaign"), "purchasing": ("purchase_order", "work_order"), "marketing": ("campaign",)}

jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=300)
app = FastAPI(title="actions")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "http://localhost:8250").split(","),
    allow_methods=["POST", "GET"],
    allow_headers=["Authorization", "Content-Type"],
)


# ----------------------------------------------------------------------------------- auth
class User(BaseModel):
    name: str
    role: str


def current_user(authorization: str = Header(default="")) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    raw = authorization.removeprefix("Bearer ")
    try:
        key = jwks.get_signing_key_from_jwt(raw).key
        claims = jwt.decode(raw, key, algorithms=["RS256"], issuer=ISSUER, options={"verify_aud": False})
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid token: {exc}") from exc
    if claims.get("azp") != CLIENT_ID:
        raise HTTPException(401, "token was not issued to the dashboard client")
    roles = claims.get("realm_access", {}).get("roles", [])
    role = next((r for r in ROLE_ORDER if r in roles), None)
    if role is None:
        raise HTTPException(403, "your role has no inventory actions")
    return User(name=claims["preferred_username"], role=role)


def need(user: User, kind: str) -> None:
    if kind not in KINDS[user.role]:
        raise HTTPException(403, f"your role cannot create a {kind.replace('_', ' ')}")


# ----------------------------------------------------------------------------------- data access
def pg():
    return psycopg2.connect(
        host=os.environ.get("ACTIONS_PG_HOST", "postgres_active"), port=int(os.environ.get("ACTIONS_PG_PORT", "5434")),
        dbname=os.environ.get("ACTIONS_PG_DB", "active_db"), user=os.environ.get("ACTIONS_PG_USER", "actions_writer"),
        password=os.environ["ACTIONS_DB_PASSWORD"], connect_timeout=5,
    )


def inventory_rows(product_ids: list[int]) -> dict[int, dict]:
    """The current mart.inventory_health rows for these products. dbt drops and recreates the table on every
    build, so for a split second it does not exist: retry that (and only that) briefly."""
    marks = ", ".join(["%s"] * len(product_ids))
    sql = ("select product_key, status, replenishment_type, vendor_id, lead_time_days, unit_cost, suggested_order_qty, "
           "min_order_qty, max_order_qty, suggested_discount_pct from mart.inventory_health "
           f"where product_key in ({marks})")
    for attempt in range(4):
        try:
            conn = pymysql.connect(
                host=os.environ.get("STARROCKS_HOST", "starrocks-fe"), port=int(os.environ.get("STARROCKS_PORT", "9030")),
                user=os.environ["ACTIONS_SR_USER"], password=os.environ["ACTIONS_SR_PASSWORD"], connect_timeout=5,
                cursorclass=pymysql.cursors.DictCursor)
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, product_ids)
                    return {int(r["product_key"]): r for r in cur.fetchall()}
            finally:
                conn.close()
        except pymysql.err.ProgrammingError as exc:
            if exc.args[0] != 5502 or attempt == 3:
                raise
            time.sleep(0.4)
    return {}


def next_id(cur, table: str, column: str, *others: tuple[str, str]) -> int:
    """max + 1 over the table and any others that can hold the same id. The seeded sample has purchase-order
    lines whose header is missing, so a new header must not reuse one of their ids."""
    parts = [f"coalesce((select max({column}) from public.{table}), 0)"]
    parts += [f"coalesce((select max({c}) from public.{t}), 0)" for t, c in others]
    cur.execute(f"select greatest({', '.join(parts)}) + 1 as next_id")
    return cur.fetchone()["next_id"]


def audit(cur, user: User, kind: str, key: str, payload: dict, outcome: str, result: dict | None, products: list[int], reason: str | None = None):
    cur.execute(
        "insert into public.actions_log (username, role, action, idempotency_key, payload, outcome, result, product_ids, reason) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (user.name, user.role, kind, key, json.dumps(payload), outcome, json.dumps(result) if result is not None else None, products, reason),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def run_action(user: User, kind: str, key: str, payload: dict, products: list[int], build):
    """Idempotency, validation, one transaction for the writes and the audit row, one log row for a refusal.
    `build(cur, rows)` validates against the inventory rows and inserts; it returns the result dict."""
    rules_error = None
    with pg() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("select username, result from public.actions_log where idempotency_key = %s and outcome = 'approved'", (key,))
        prior = cur.fetchone()
    if prior:
        if prior["username"] != user.name:
            raise HTTPException(409, "idempotency key belongs to another user")
        return {"ok": True, "idempotent": True, **prior["result"]}
    try:
        rows = inventory_rows(products)
        for attempt in range(3):
            try:
                with pg() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    result = build(cur, rows)
                    log_id = audit(cur, user, kind, key, payload, "approved", result, products)
                return {"ok": True, "idempotent": False, "log_id": log_id, **result}
            except psycopg2.errors.UniqueViolation as exc:
                if attempt == 2 or "actions_log" in str(exc):
                    raise
                # an id taken by the simulator between our read and our insert: take the next one
    except rules.Refused as exc:
        rules_error = exc.reason
    with pg() as conn, conn.cursor() as cur:
        audit(cur, user, kind, f"{key}#refused-{uuid.uuid4().hex[:8]}", payload, "refused", None, products, rules_error)
    raise HTTPException(422, rules_error)


# ----------------------------------------------------------------------------------- requests
class Line(BaseModel):
    product_id: int = Field(gt=0)
    qty: int = Field(gt=0, le=10_000_000)


class Replenish(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    lines: list[Line]


class Campaign(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    product_ids: list[int] = Field(min_length=1, max_length=rules.MAX_LINES)
    discount_pct: int = Field(ge=1, le=100)
    days: int = Field(ge=1, le=365)


def now() -> datetime:
    return datetime.now(timezone.utc)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/actions/purchase-orders")
def purchase_orders(req: Replenish, user: Annotated[User, Depends(current_user)]) -> dict:
    need(user, "purchase_order")
    checked = _lines(req)

    def build(cur, rows):
        lines = [rules.check_replenishment(rows.get(l.product_id), l.product_id, l.qty, "purchase") for l in checked]
        by_vendor: dict[int, list[dict]] = {}
        for l in lines:
            by_vendor.setdefault(int(l["vendor_id"]), []).append(l)
        cur.execute("select employee_id, ship_method_id from public.purchase_order_header order by purchase_order_id desc limit 1")
        ref = cur.fetchone() or {"employee_id": 1, "ship_method_id": 1}
        created = []
        for vendor_id, vlines in by_vendor.items():
            po_id = next_id(cur, "purchase_order_header", "purchase_order_id", ("purchase_order_detail", "purchase_order_id"))
            total = round(sum(l["qty"] * l["unit_cost"] for l in vlines), 4)
            t = now()
            # status 2 = approved: the approval is the action itself
            cur.execute(
                "insert into public.purchase_order_header (purchase_order_id, revision_number, status, employee_id, vendor_id, "
                "ship_method_id, order_date, sub_total, tax_amt, freight, total_due, modified_date) "
                "values (%s, 0, 2, %s, %s, %s, %s, %s, 0, 0, %s, %s)",
                (po_id, ref["employee_id"], vendor_id, ref["ship_method_id"], t, total, total, t))
            for n, l in enumerate(vlines, start=1):
                cur.execute(
                    "insert into public.purchase_order_detail (purchase_order_id, purchase_order_detail_id, due_date, order_qty, "
                    "product_id, unit_price, line_total, received_qty, rejected_qty, stocked_qty, modified_date) "
                    "values (%s, %s, %s, %s, %s, %s, %s, 0, 0, 0, %s)",
                    (po_id, n, t + timedelta(days=l["lead_time_days"]), l["qty"], l["product_id"], l["unit_cost"],
                     round(l["qty"] * l["unit_cost"], 4), t))
            created.append({"purchase_order_id": po_id, "vendor_id": vendor_id, "lines": len(vlines), "total": total})
        return {"action": "purchase_order", "purchase_orders": created}

    return run_action(user, "purchase_order", req.idempotency_key, req.model_dump(), [l.product_id for l in checked], build)


@app.post("/actions/work-orders")
def work_orders(req: Replenish, user: Annotated[User, Depends(current_user)]) -> dict:
    need(user, "work_order")
    checked = _lines(req)

    def build(cur, rows):
        lines = [rules.check_replenishment(rows.get(l.product_id), l.product_id, l.qty, "manufacture") for l in checked]
        created = []
        for l in lines:
            wo_id = next_id(cur, "work_order", "work_order_id")
            t = now()
            cur.execute(
                "insert into public.work_order (work_order_id, product_id, order_qty, stocked_qty, scrapped_qty, start_date, due_date, modified_date) "
                "values (%s, %s, %s, 0, 0, %s, %s, %s)",
                (wo_id, l["product_id"], l["qty"], t, t + timedelta(days=l["lead_time_days"]), t))
            created.append({"work_order_id": wo_id, "product_id": l["product_id"], "qty": l["qty"]})
        return {"action": "work_order", "work_orders": created}

    return run_action(user, "work_order", req.idempotency_key, req.model_dump(), [l.product_id for l in checked], build)


@app.post("/actions/campaigns")
def campaigns(req: Campaign, user: Annotated[User, Depends(current_user)]) -> dict:
    need(user, "campaign")
    rules.check_line_count(len(req.product_ids))

    def build(cur, rows):
        rules.check_campaign(rows, req.product_ids, req.discount_pct, req.days)
        offer_id = next_id(cur, "special_offer", "special_offer_id", ("special_offer_product", "special_offer_id"))
        t = now()
        cur.execute(
            "insert into public.special_offer (rowguid, special_offer_id, description, discount_pct, type, category, start_date, end_date, min_qty, modified_date) "
            "values (%s, %s, %s, %s, 'Excess Inventory', 'Customer', %s, %s, 1, %s)",
            (str(uuid.uuid4()), offer_id, f"Clearance {req.discount_pct}% off, {len(req.product_ids)} products", req.discount_pct / 100,
             t, t + timedelta(days=req.days), t))
        for pid in req.product_ids:
            cur.execute("insert into public.special_offer_product (rowguid, special_offer_id, product_id, modified_date) values (%s, %s, %s, %s)",
                        (str(uuid.uuid4()), offer_id, pid, t))
        return {"action": "campaign", "special_offer_id": offer_id, "products": len(req.product_ids), "discount_pct": req.discount_pct}

    return run_action(user, "campaign", req.idempotency_key, req.model_dump(), req.product_ids, build)


def _lines(req: Replenish) -> list[Line]:
    try:
        rules.check_line_count(len(req.lines))
    except rules.Refused as exc:
        raise HTTPException(422, exc.reason) from exc
    if len({l.product_id for l in req.lines}) != len(req.lines):
        raise HTTPException(422, "a product appears more than once")
    return req.lines


@app.get("/actions/log")
def log(user: Annotated[User, Depends(current_user)], limit: int = 100) -> dict:
    with pg() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "select id, ts, username, action, outcome, product_ids, result, reason from public.actions_log "
            "where action = any(%s) and outcome in ('approved', 'refused') order by id desc limit %s",
            (list(KINDS[user.role]), max(1, min(limit, 500))))
        rows = cur.fetchall()
    for r in rows:
        r["ts"] = r["ts"].isoformat()
    return {"entries": rows}
