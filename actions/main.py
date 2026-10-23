"""Actions service: an approved inventory proposal becomes a row in the simulated ERP (postgres_active).

  POST /actions/purchase-orders  {idempotency_key, lines: [{product_id, qty}]}        purchasing, admin
  POST /actions/work-orders      {idempotency_key, lines: [{product_id, qty}]}        purchasing, admin
  POST /actions/campaigns        {idempotency_key, product_ids, discount_pct, days}   marketing, admin
  GET  /actions/log                                                                   the role's own kinds

  POST /proposals                {run_id, proposals: [...]}                           the proposal agent only
  GET  /proposals                                                                     open proposals of the role's kinds
  POST /proposals/{id}/dismiss                                                        the role's kinds
  (an action request may carry proposal_id: approving it marks the proposal approved)

The proposal agent (a Keycloak service account of its own client) can only draft: every proposal is validated
by the same rules as an action before it is stored, and it cannot create, approve or dismiss anything. A person
turns a proposal into an action through the normal endpoints, with whatever edits the rules allow.

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
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal

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
AGENT_CLIENT_ID = os.environ.get("KEYCLOAK_AGENT_CLIENT_ID", "inventory-agent")
ROLE_ORDER = ("admin", "purchasing", "marketing")
# What each role may create. The agent creates none: it only drafts proposals.
KINDS = {"admin": ("purchase_order", "work_order", "campaign"), "purchasing": ("purchase_order", "work_order"),
         "marketing": ("campaign",), "agent": ()}

# DATASET=live (default): the live mart and the live ERP. Anything else (250m): a scaled benchmark copy that has no ERP behind it.
# It reads that dataset's mart for validation but refuses every write, and shows no proposals or log: approved actions go to
# postgres_active, which only feeds the live mart, so they would be nonsense for products of another dataset.
DATASET = os.environ.get("DATASET", "live").lower()
if not re.fullmatch(r"[a-z0-9]+", DATASET):
    raise SystemExit(f"DATASET must be letters and digits, got {DATASET!r}")
# `both` (the live Cube and a 250m Cube side by side): the actions service stays the live one; the dashboard never calls it
# while the 250m dataset is shown.
MART = "mart" if DATASET in ("live", "both") else f"mart_{DATASET}"
READ_ONLY = DATASET not in ("live", "both")
READ_ONLY_MESSAGE = (f"Read-only: this deployment serves the {DATASET} dataset, a scaled copy with no ERP behind it. Approved actions are written to "
                     "postgres_active, which only feeds the live mart. Set DATASET=live to approve.")


def writable() -> None:
    if READ_ONLY:
        raise HTTPException(409, READ_ONLY_MESSAGE)


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
    azp = claims.get("azp")
    roles = claims.get("realm_access", {}).get("roles", [])
    if azp == AGENT_CLIENT_ID:
        role = "agent" if "agent" in roles else None     # the agent client can only ever be the agent
    elif azp == CLIENT_ID:
        role = next((r for r in ROLE_ORDER if r in roles), None)
    else:
        raise HTTPException(401, "token was not issued to a known client")
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
    sql = ("select product_key, product_name, status, replenishment_type, vendor_id, vendor_name, lead_time_days, unit_cost, "
           "suggested_order_qty, min_order_qty, max_order_qty, suggested_discount_pct, on_hand, on_order, daily_demand, "
           f"days_of_cover, excess_units, excess_value, reason from {MART}.inventory_health "
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


def open_proposal(cur, proposal_id: int, kind: str) -> None:
    """Lock the proposal this action approves; it must still be open and of the same kind."""
    cur.execute("select kind, status from public.proposals where id = %s for update", (proposal_id,))
    row = cur.fetchone()
    if row is None or row["status"] != "proposed" or row["kind"] != kind:
        raise rules.Refused(f"proposal {proposal_id} is not an open {kind.replace('_', ' ')} proposal")


def run_action(user: User, kind: str, key: str, payload: dict, products: list[int], build, proposal_id: int | None = None):
    """Idempotency, validation, one transaction for the writes and the audit row, one log row for a refusal.
    `build(cur, rows)` validates against the inventory rows and inserts; it returns the result dict.
    With a proposal_id the same transaction marks that proposal approved."""
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
                    if proposal_id is not None:
                        open_proposal(cur, proposal_id, kind)
                    result = build(cur, rows)
                    log_id = audit(cur, user, kind, key, payload, "approved", result, products)
                    if proposal_id is not None:
                        cur.execute("update public.proposals set status = 'approved', decided_by = %s, decided_at = now(), action_log_id = %s "
                                    "where id = %s", (user.name, log_id, proposal_id))
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
    proposal_id: int | None = Field(default=None, gt=0)    # the proposal this approves, if any


class Campaign(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    product_ids: list[int] = Field(min_length=1, max_length=rules.MAX_LINES)
    discount_pct: int = Field(ge=1, le=100)
    days: int = Field(ge=1, le=365)
    proposal_id: int | None = Field(default=None, gt=0)


def now() -> datetime:
    return datetime.now(timezone.utc)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/actions/purchase-orders")
def purchase_orders(req: Replenish, user: Annotated[User, Depends(current_user)]) -> dict:
    writable()
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

    return run_action(user, "purchase_order", req.idempotency_key, req.model_dump(), [l.product_id for l in checked], build, req.proposal_id)


@app.post("/actions/work-orders")
def work_orders(req: Replenish, user: Annotated[User, Depends(current_user)]) -> dict:
    writable()
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

    return run_action(user, "work_order", req.idempotency_key, req.model_dump(), [l.product_id for l in checked], build, req.proposal_id)


@app.post("/actions/campaigns")
def campaigns(req: Campaign, user: Annotated[User, Depends(current_user)]) -> dict:
    writable()
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

    return run_action(user, "campaign", req.idempotency_key, req.model_dump(), req.product_ids, build, req.proposal_id)


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
    if READ_ONLY:
        return {"entries": []}
    with pg() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "select id, ts, username, action, outcome, product_ids, result, reason from public.actions_log "
            "where action = any(%s) and outcome in ('approved', 'refused') order by id desc limit %s",
            (list(KINDS[user.role]), max(1, min(limit, 500))))
        rows = cur.fetchall()
    for r in rows:
        r["ts"] = r["ts"].isoformat()
    return {"entries": rows}


# ----------------------------------------------------------------------------------- proposals
class ProposalIn(BaseModel):
    kind: Literal["purchase_order", "work_order", "campaign"]
    title: str = Field(min_length=3, max_length=200)
    rationale: str = Field(min_length=10, max_length=2000)
    payload: dict


class ProposalBatch(BaseModel):
    run_id: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    proposals: list[ProposalIn] = Field(min_length=1, max_length=50)


class LinesPayload(BaseModel):
    lines: list[Line]


class CampaignPayload(BaseModel):
    product_ids: list[int] = Field(min_length=1, max_length=rules.MAX_LINES)
    discount_pct: int = Field(ge=1, le=100)
    days: int = Field(ge=1, le=365)


def snapshot(row: dict, **extra) -> dict:
    """The numbers behind a proposal, as the mart showed them when it was drafted."""
    keys = ("product_name", "status", "replenishment_type", "vendor_name", "on_hand", "on_order", "daily_demand", "days_of_cover",
            "lead_time_days", "suggested_order_qty", "excess_units", "excess_value", "suggested_discount_pct", "reason")
    return {**{k: (float(row[k]) if isinstance(row[k], Decimal) else row[k]) for k in keys if k in row}, **extra}


def validate_proposal(p: ProposalIn, rows: dict[int, dict]) -> tuple[dict, list[int]]:
    """Run the action rules on a drafted proposal; returns (numbers, product ids) or raises Refused."""
    if p.kind == "campaign":
        c = CampaignPayload(**p.payload)
        rules.check_line_count(len(c.product_ids))
        rules.check_campaign(rows, c.product_ids, c.discount_pct, c.days)
        return {"products": [snapshot(rows[i], product_id=i) for i in c.product_ids]}, c.product_ids
    lines = LinesPayload(**p.payload).lines
    rules.check_line_count(len(lines))
    if len({l.product_id for l in lines}) != len(lines):
        raise rules.Refused("a product appears more than once")
    kind = "purchase" if p.kind == "purchase_order" else "manufacture"
    checked = [rules.check_replenishment(rows.get(l.product_id), l.product_id, l.qty, kind) for l in lines]
    if kind == "purchase" and len({c["vendor_id"] for c in checked}) != 1:
        raise rules.Refused("a purchase-order proposal covers one vendor")
    return {"products": [snapshot(rows[l.product_id], product_id=l.product_id, proposed_qty=l.qty) for l in lines]}, [l.product_id for l in lines]


@app.post("/proposals")
def create_proposals(batch: ProposalBatch, user: Annotated[User, Depends(current_user)]) -> dict:
    writable()
    if user.role != "agent":
        raise HTTPException(403, "only the proposal agent drafts proposals")
    wanted: list[int] = []
    malformed: set[int] = set()
    for seq, p in enumerate(batch.proposals):
        try:
            wanted += _payload_products(p)
        except (ValueError, TypeError, KeyError):
            malformed.add(seq)
    rows = inventory_rows(sorted(set(wanted))) if wanted else {}
    results, accepted = [], []
    for seq, p in enumerate(batch.proposals):
        try:
            if seq in malformed:
                raise ValueError("malformed")
            numbers, products = validate_proposal(p, rows)
        except rules.Refused as exc:
            results.append({"seq": seq, "ok": False, "reason": exc.reason})
        except (ValueError, TypeError, KeyError):
            results.append({"seq": seq, "ok": False, "reason": "payload is malformed"})
        else:
            accepted.append((seq, p, numbers, products))
    with pg() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for seq, p, numbers, _ in accepted:
            cur.execute(
                "insert into public.proposals (run_id, seq, created_by, kind, title, rationale, payload, numbers) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s) on conflict (run_id, seq) do nothing returning id",
                (batch.run_id, seq, user.name, p.kind, p.title, p.rationale, json.dumps(p.payload), json.dumps(numbers, default=str)))
            row = cur.fetchone()
            results.append({"seq": seq, "ok": True, "id": row["id"], "duplicate": False} if row else {"seq": seq, "ok": True, "duplicate": True})
        audit(cur, user, "proposal", f"{batch.run_id}#drafted-{uuid.uuid4().hex[:8]}", {"run_id": batch.run_id, "count": len(batch.proposals)},
              "drafted", {"results": sorted(results, key=lambda r: r["seq"])}, sorted({i for *_, ids in accepted for i in ids}))
    return {"run_id": batch.run_id, "results": sorted(results, key=lambda r: r["seq"])}


def _payload_products(p: ProposalIn) -> list[int]:
    if p.kind == "campaign":
        return CampaignPayload(**p.payload).product_ids
    return [l.product_id for l in LinesPayload(**p.payload).lines]


READ_KINDS = {**KINDS, "agent": ("purchase_order", "work_order", "campaign")}


@app.get("/proposals")
def list_proposals(user: Annotated[User, Depends(current_user)], status: str = "proposed", limit: int = 100) -> dict:
    if status not in ("proposed", "approved", "dismissed", "all"):
        raise HTTPException(422, "status must be proposed, approved, dismissed or all")
    if READ_ONLY:
        return {"proposals": []}
    with pg() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "select id, created_at, run_id, seq, created_by, kind, title, rationale, payload, numbers, status, decided_by, decided_at "
            "from public.proposals where kind = any(%s) and (%s = 'all' or status = %s) order by id desc limit %s",
            (list(READ_KINDS[user.role]), status, status, max(1, min(limit, 500))))
        rows = cur.fetchall()
    for r in rows:
        for k in ("created_at", "decided_at"):
            r[k] = r[k].isoformat() if r[k] else None
    return {"proposals": rows}


@app.post("/proposals/{proposal_id}/dismiss")
def dismiss(proposal_id: int, user: Annotated[User, Depends(current_user)]) -> dict:
    writable()
    with pg() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("select kind, status from public.proposals where id = %s", (proposal_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "no such proposal")
        need(user, row["kind"])
        cur.execute("update public.proposals set status = 'dismissed', decided_by = %s, decided_at = now() where id = %s and status = 'proposed'",
                    (user.name, proposal_id))
        if cur.rowcount == 0:
            raise HTTPException(409, f"proposal is already {row['status']}")
    return {"ok": True, "id": proposal_id, "status": "dismissed"}
