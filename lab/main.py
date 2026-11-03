"""The SQL lab service: ad-hoc SELECTs over the semantic layer, for the people who have been given the lab.

  GET  /healthz
  GET  /info      { user, role, lab, limits }: whether this person has the lab, and the limits
  GET  /schema    the cubes, dimensions and measures this person may query (role rules and blocked cubes applied), for the schema browser
  POST /query     { sql } -> { columns: [{name, type}], rows: [[...]], row_count, truncated, ms }
  POST /export    { sql, format: csv | xlsx } -> the file (up to LAB_EXPORT_ROWS rows; header X-Lab-Truncated says when it was cut), under the same rules, limits and audit as /query
  GET|POST /queries, GET|PUT|DELETE /queries/{id}        saved queries (queries.py: private, or shared with people and groups for view or edit; in the dashboards' folders)
  POST /queries/{id}/run, GET /queries/{id}/snapshot     run one as YOU (under your own rules) and keep the result for you for LAB_SNAPSHOT_HOURS; read your own last result
  POST /transfer  { from_user, to_user }                 admin: hand every saved query of one person to another

Every call carries a Keycloak access token of the dashboard client. The lab asks the auth service for the person's Cube token (which says their role, territories, blocked cubes and whether
they have the lab), and runs the statement on Cube's SQL API (Postgres protocol) signed in as that person, with the Cube token as the password. So a statement goes through the very
same queryRewrite as a dashboard's query: role rules (no profit for a rep), row-level security (territories) and blocked cubes (datasets) apply to it, and Cube only understands
queries over the cubes (no other tables, no INSERT or DROP). The lab adds the limits: one statement, a row cap, a time limit, a few queries at a time per person, and an audit line per statement.
"""
from __future__ import annotations

import csv
import datetime
import decimal
import io
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

import httpx
import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

import queries
import sqlcheck
from store import NotFound, PgStore

ISSUER = os.environ["KEYCLOAK_ISSUER"]
JWKS_URL = os.environ["KEYCLOAK_JWKS_URL"]
CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "dashboard")
AUTH_URL = os.environ.get("AUTH_URL", "http://auth:8200").rstrip("/")
CUBE_SQL_HOST = os.environ.get("CUBE_SQL_HOST", "cube")
CUBE_SQL_PORT = int(os.environ.get("CUBE_SQL_PORT", "15432"))
ROW_LIMIT = int(os.environ.get("LAB_ROW_LIMIT", "10000"))
EXPORT_ROWS = int(os.environ.get("LAB_EXPORT_ROWS", "100000"))
TIMEOUT = float(os.environ.get("LAB_TIMEOUT", "60"))
PER_USER = int(os.environ.get("LAB_MAX_PER_USER", "2"))
MAX_CONCURRENT = int(os.environ.get("LAB_MAX_CONCURRENT", "8"))
LOG_FILE = os.environ.get("LAB_LOG_FILE", "")
SNAPSHOT_HOURS = float(os.environ.get("LAB_SNAPSHOT_HOURS", "24"))
STORE = PgStore.from_env()                                  # None when LAB_DB_PASSWORD is not set: the lab runs, but cannot save queries

jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=300)
app = FastAPI(title="lab")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("ALLOWED_ORIGINS", "http://localhost:8250").split(","),
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"], expose_headers=["Content-Disposition", "X-Lab-Truncated", "X-Lab-Rows"])
_pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT)
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
_per_user: dict[str, threading.BoundedSemaphore] = {}
_lock = threading.Lock()


class Caller(BaseModel):
    name: str
    raw: str                                                  # the Keycloak token, passed to the auth service for the Cube token


def current_caller(authorization: str = Header(default="")) -> Caller:
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
    return Caller(name=claims["preferred_username"], raw=raw)


Who = Depends(current_caller)


def audit(entry: dict) -> None:
    line = json.dumps({"event": "lab", "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), **entry}, ensure_ascii=False)         # an entry's own "event" wins
    print(line, flush=True)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            print(json.dumps({"event": "lab", "warning": f"could not write {LOG_FILE}: {exc}"}), flush=True)


def cube_session(caller: Caller) -> dict:
    """The person's Cube token and claims, from the auth service (it applies the access rules); a refusal there is a refusal here."""
    try:
        r = httpx.post(f"{AUTH_URL}/token", headers={"Authorization": f"Bearer {caller.raw}"}, timeout=10)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"the auth service is not reachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(r.status_code if r.status_code in (401, 403, 503) else 502, r.json().get("detail", "the auth service refused") if r.headers.get("content-type", "").startswith("application/json") else "the auth service refused")
    return r.json()


def need_lab(session: dict) -> dict:
    if not session.get("lab"):
        raise HTTPException(403, "You have not been given the SQL lab. Ask an admin to give a dataset you use the SQL lab permission.")
    return session


# -------------------------------------------------------------------------------------------------------------------- schema
_catalog = None


def catalog():
    global _catalog
    if _catalog is None:
        try:
            from dashspec import catalog as cat
            _catalog = cat.from_model(os.environ.get("LAB_MODEL_DIR", "/app/cube-model"))
        except (ImportError, SystemExit, OSError):
            _catalog = False
    return _catalog or None


def schema_for(session: dict) -> list[dict]:
    """The cubes and members this person may query: what the role rules and the blocked cubes leave (the same rules Cube enforces; this only keeps the browser from listing what would be refused)."""
    cat = catalog()
    if cat is None:
        return []
    from dashspec.validate import denied
    role, blocked, fields = session.get("role", ""), set(session.get("blocked_cubes") or []), set(session.get("blocked_members") or [])
    out = []
    for name, c in sorted(cat.cubes.items()):
        if name in blocked:
            continue
        dims = [{"name": d, "type": t, "description": c.get("docs", {}).get(d, "")} for d, t in sorted(c["dimensions"].items()) if denied(role, f"{name}.{d}") is None and f"{name}.{d}" not in fields]
        meas = [{"name": m, "type": t, "description": c.get("docs", {}).get(m, "")} for m, t in sorted(c["measures"].items()) if denied(role, f"{name}.{m}") is None and f"{name}.{m}" not in fields]
        if dims or meas:
            out.append({"name": name, "description": c.get("description", ""), "dimensions": dims, "measures": meas, "joins": sorted(j for j in (c["joins"] or ()) if j not in blocked)})
    return out


# -------------------------------------------------------------------------------------------------------------------- running a statement
_NUMERIC = {20, 21, 23, 700, 701, 1700, 26}
_TIME = {1082, 1114, 1184, 1083}


def kind_of(type_code: int) -> str:
    return "number" if type_code in _NUMERIC else "time" if type_code in _TIME else "boolean" if type_code == 16 else "string"


def plain(v):
    """A value as JSON can carry it."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, decimal.Decimal):
        return float(v) if v.is_finite() else str(v)
    if isinstance(v, float):
        return v if v == v and v not in (float("inf"), float("-inf")) else str(v)
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, (bytes, memoryview)):
        return bytes(v).hex()
    return str(v)


def execute(user: str, token: str, sql: str, limit: int) -> dict:
    """Run one statement on Cube's SQL API as `user` (the Cube token is the password). Blocking: called in a worker thread."""
    import psycopg2
    conn = psycopg2.connect(host=CUBE_SQL_HOST, port=CUBE_SQL_PORT, dbname="db", user=user, password=token, connect_timeout=5, sslmode="disable")
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [{"name": d.name, "type": kind_of(d.type_code)} for d in (cur.description or [])]
            rows = cur.fetchmany(limit + 1) if cur.description else []
        truncated = len(rows) > limit
        return {"columns": cols, "rows": [[plain(v) for v in r] for r in rows[:limit]], "row_count": min(len(rows), limit), "truncated": truncated}
    finally:
        try:
            conn.close()
        except Exception:                                      # noqa: BLE001
            pass


def user_slot(user: str) -> threading.BoundedSemaphore:
    with _lock:
        return _per_user.setdefault(user, threading.BoundedSemaphore(PER_USER))


def run_limited(caller: Caller, session: dict, sql: str, *, limit: int | None = None, timeout: float | None = None, event: str = "lab") -> dict:
    mine, anyone = user_slot(caller.name), _slots
    if not mine.acquire(blocking=False):
        raise HTTPException(429, f"You already have {PER_USER} queries running; wait for one to finish.")
    if not anyone.acquire(blocking=False):
        mine.release()
        raise HTTPException(503, "The SQL lab is busy; try again in a moment.")
    t0 = time.time()
    future = _pool.submit(execute, caller.name, session["token"], sql, limit or ROW_LIMIT)
    future.add_done_callback(lambda _f: (mine.release(), anyone.release()))        # the slots are held until Cube is really done, even if we stopped waiting
    try:
        out = future.result(timeout=timeout or TIMEOUT)
    except FutureTimeout:
        audit({"event": event, "user": caller.name, "role": session.get("role"), "sql": sql[:500], "error": "timeout", "ms": int((time.time() - t0) * 1000)})
        raise HTTPException(504, f"The query took longer than {int(timeout or TIMEOUT)} seconds and was given up on. Narrow it (a filter, fewer rows) and try again.") from None
    except Exception as exc:                                   # noqa: BLE001 (Cube's refusals and errors, in its words)
        audit({"event": event, "user": caller.name, "role": session.get("role"), "sql": sql[:500], "error": str(exc)[:200], "ms": int((time.time() - t0) * 1000)})
        raise HTTPException(400, clean_error(exc)) from None
    out["ms"] = int((time.time() - t0) * 1000)
    audit({"event": event, "user": caller.name, "role": session.get("role"), "sql": sql[:500], "rows": out["row_count"], "truncated": out["truncated"], "ms": out["ms"]})
    return out


def clean_error(exc: Exception) -> str:
    """Cube's message without the echo of the statement and the connection details."""
    msg = str(exc).split("\nQUERY:")[0].strip()
    for prefix in ("Database Execution Error: ", "Internal Error: ", "Planning Error: ", "User Error: ", "Unsupported Error: ", "Rewrite Error: "):
        msg = msg.removeprefix("ERROR:  ").removeprefix(prefix)
    if "password authentication failed" in msg or "could not connect" in msg:
        return "The SQL lab could not reach the data service right now."
    return msg[:400] or "The query failed."


# -------------------------------------------------------------------------------------------------------------------- routes
class QueryRequest(BaseModel):
    sql: str = Field(max_length=sqlcheck.MAX_SQL + 1000)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


def limits() -> dict:
    return {"row_limit": ROW_LIMIT, "export_rows": EXPORT_ROWS, "timeout_seconds": int(TIMEOUT), "per_user": PER_USER, "max_sql": sqlcheck.MAX_SQL}


@app.get("/info")
def info(caller: Caller = Who) -> dict:
    s = cube_session(caller)
    return {"user": caller.name, "role": s.get("role"), "lab": bool(s.get("lab")), "saving": STORE is not None, "limits": limits()}


@app.get("/schema")
def schema(caller: Caller = Who) -> dict:
    s = need_lab(cube_session(caller))
    return {"cubes": schema_for(s)}


@app.post("/query")
def query(req: QueryRequest, caller: Caller = Who) -> dict:
    s = need_lab(cube_session(caller))
    try:
        sql = sqlcheck.check(req.sql)
    except sqlcheck.SqlRefused as exc:
        raise HTTPException(400, str(exc)) from None
    return run_limited(caller, s, sql)


# -------------------------------------------------------------------------------------------------------------------- export
_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(v, kind: str):
    """A cell for a CSV file. A text that starts like a formula would be run by a spreadsheet that opens the file, so it is made plain text with a leading apostrophe."""
    if v is None:
        return ""
    if isinstance(v, str) and kind != "number" and v.startswith(_DANGEROUS):
        return "'" + v
    return v


def csv_bytes(columns: list[dict], rows: list[list]):
    """The CSV as chunks of bytes: UTF-8 with a byte-order mark (Excel then reads Turkish letters right), a header row, quoted as needed."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    yield "\ufeff".encode()
    w.writerow([csv_cell(c["name"], "string") for c in columns])
    for i, row in enumerate(rows, 1):
        w.writerow([csv_cell(v, columns[j]["type"]) for j, v in enumerate(row)])
        if i % 2000 == 0:
            yield buf.getvalue().encode()
            buf.seek(0)
            buf.truncate()
    yield buf.getvalue().encode()


def xlsx_bytes(columns: list[dict], rows: list[list]) -> bytes:
    """The Excel file: numbers as numbers, everything else as text (written as text, so nothing is ever read as a formula), a bold header, the header row frozen."""
    import xlsxwriter
    out = io.BytesIO()
    wb = xlsxwriter.Workbook(out, {"in_memory": True, "strings_to_formulas": False, "strings_to_numbers": False, "strings_to_urls": False, "nan_inf_to_errors": True})
    ws = wb.add_worksheet("Result")
    bold = wb.add_format({"bold": True})
    for j, c in enumerate(columns):
        ws.write_string(0, j, str(c["name"]), bold)
    for i, row in enumerate(rows, 1):
        for j, v in enumerate(row):
            kind = columns[j]["type"]
            if v is None:
                continue
            if kind == "number" and isinstance(v, (int, float)) and not isinstance(v, bool):
                ws.write_number(i, j, v)
            elif isinstance(v, bool):
                ws.write_boolean(i, j, v)
            else:
                ws.write_string(i, j, str(v))
    ws.freeze_panes(1, 0)
    ws.set_column(0, max(len(columns) - 1, 0), 18)
    wb.close()
    return out.getvalue()


class ExportRequest(BaseModel):
    sql: str = Field(max_length=sqlcheck.MAX_SQL + 1000)
    format: str = "csv"


@app.post("/export")
def export(req: ExportRequest, caller: Caller = Who):
    s = need_lab(cube_session(caller))
    if req.format not in ("csv", "xlsx"):
        raise HTTPException(400, "format is csv or xlsx")
    try:
        sql = sqlcheck.check(req.sql)
    except sqlcheck.SqlRefused as exc:
        raise HTTPException(400, str(exc)) from None
    out = run_limited(caller, s, sql, limit=EXPORT_ROWS, timeout=TIMEOUT * 2, event="lab_export")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    headers = {"Content-Disposition": f'attachment; filename="lab-{stamp}.{req.format}"', "X-Lab-Truncated": "true" if out["truncated"] else "false", "X-Lab-Rows": str(out["row_count"])}
    if req.format == "csv":
        return StreamingResponse(csv_bytes(out["columns"], out["rows"]), media_type="text/csv; charset=utf-8", headers=headers)
    return Response(xlsx_bytes(out["columns"], out["rows"]), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)


# -------------------------------------------------------------------------------------------------------------------- saved queries
def need_store():
    if STORE is None:
        raise HTTPException(503, "Saving queries is off: set LAB_DB_PASSWORD and run postgres/sync-lab.sh.")
    return STORE


def who_of(s: dict, caller: Caller) -> queries.Who:
    return queries.Who(name=caller.name, role=s.get("role", ""), groups=list(s.get("groups") or []))


def qcall(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except queries.QueryError as e:
        raise HTTPException(e.status, e.message) from None
    except NotFound:
        raise HTTPException(404, "There is no such saved query.") from None


class QueryIn(BaseModel):
    title: str = Field(max_length=120)
    sql: str = Field(max_length=sqlcheck.MAX_SQL + 1000)
    description: str = Field(default="", max_length=400)
    folder_id: str | None = Field(default=None, max_length=60)
    shares: list[dict] | None = Field(default=None, max_length=60)


class QueryPatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    sql: str | None = Field(default=None, max_length=sqlcheck.MAX_SQL + 1000)
    description: str | None = Field(default=None, max_length=400)
    shares: list[dict] | None = Field(default=None, max_length=60)
    folder_id: str | None = Field(default=None, max_length=60)                  # given as null: out of any folder
    owner: str | None = Field(default=None, max_length=120)


class TransferRequest(BaseModel):
    from_user: str = Field(min_length=1, max_length=120)
    to_user: str = Field(min_length=1, max_length=120)


@app.get("/query-folders")
def query_folders(caller: Caller = Who) -> list[dict]:
    s = need_lab(cube_session(caller))
    return qcall(queries.list_folders, need_store(), who_of(s, caller))


@app.get("/queries")
def queries_list(caller: Caller = Who) -> list[dict]:
    s = need_lab(cube_session(caller))
    store = need_store()
    store.purge()
    return qcall(queries.list_queries, store, who_of(s, caller))


@app.post("/queries", status_code=201)
def queries_create(req: QueryIn, caller: Caller = Who) -> dict:
    s = need_lab(cube_session(caller))
    out = qcall(queries.create, need_store(), who_of(s, caller), title=req.title, sql=req.sql, description=req.description, folder_id=req.folder_id, shares=req.shares)
    audit({"event": "lab_query_save", "user": caller.name, "id": out["id"], "title": out["title"][:80]})
    return out


@app.get("/queries/{id}")
def queries_get(id: str, caller: Caller = Who) -> dict:
    s = need_lab(cube_session(caller))
    return qcall(queries.get, need_store(), who_of(s, caller), id)


@app.put("/queries/{id}")
def queries_update(id: str, req: QueryPatch, caller: Caller = Who) -> dict:
    s = need_lab(cube_session(caller))
    given = req.model_fields_set
    extra: dict = {}
    if "shares" in given:
        extra["shares"] = req.shares if req.shares is not None else []
    if "folder_id" in given:
        extra["folder_id"] = req.folder_id
    if "owner" in given and req.owner is not None:
        extra["owner"] = req.owner
    out = qcall(queries.update, need_store(), who_of(s, caller), id, title=req.title, description=req.description, sql=req.sql, **extra)
    audit({"event": "lab_query_update", "user": caller.name, "id": id, **({"shares": extra["shares"]} if "shares" in extra else {}), **({"new_owner": extra["owner"]} if "owner" in extra else {})})
    return out


@app.delete("/queries/{id}", status_code=204, response_class=Response)
def queries_delete(id: str, caller: Caller = Who):
    s = need_lab(cube_session(caller))
    qcall(queries.delete, need_store(), who_of(s, caller), id)
    audit({"event": "lab_query_delete", "user": caller.name, "id": id})


@app.post("/queries/{id}/run")
def queries_run(id: str, caller: Caller = Who) -> dict:
    """Run a saved query as the caller (their own Cube token, so their own rules) and keep the result as the caller's own snapshot."""
    s = need_lab(cube_session(caller))
    store, who = need_store(), who_of(s, caller)
    q = qcall(queries.get, store, who, id)
    out = run_limited(caller, s, q["sql"])
    snap = store.put_snapshot(id, caller.name, out, SNAPSHOT_HOURS)
    return {**out, "snapshot": {"created_at": snap["created_at"], "expires_at": snap["expires_at"]}}


@app.get("/queries/{id}/snapshot")
def queries_snapshot(id: str, caller: Caller = Who) -> dict:
    s = need_lab(cube_session(caller))
    return qcall(queries.snapshot_of, need_store(), who_of(s, caller), id)


@app.post("/transfer")
def transfer(req: TransferRequest, caller: Caller = Who) -> dict:
    s = cube_session(caller)
    n = qcall(queries.transfer_all, need_store(), who_of(s, caller), req.from_user, req.to_user)
    audit({"event": "lab_transfer", "user": caller.name, "from": req.from_user, "to": req.to_user, "count": n})
    return {"transferred": n}
