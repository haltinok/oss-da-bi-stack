"""Dashboard builder service: a request becomes a validated dashboard spec.

  GET  /healthz
  GET  /info      the mode (llm | standin), the model, the caller's role
  GET  /saved, POST /saved, GET|PUT|DELETE /saved/{id}, GET /saved/{id}/versions, POST /saved/{id}/restore   saved dashboards (private, shared with roles, or with everyone)
  GET  /usage     the caller's builds this hour and tokens today, against their limits
  GET  /catalog   the semantic layer as the caller's role may read it (cubes, measures, dimensions, descriptions, joins)
  POST /build     { prompt, current_yaml? } -> { status: ok | cannot | failed, yaml, spec, message, notes, attempts, mode, model, usage }
  POST /validate  { yaml } -> { ok, yaml, spec, notes, problems }: the same checks for a file a person edited (no model, no cost)

Every request carries a Keycloak access token (verified like the actions service does). The role from the token decides what the model is shown and
what the validator accepts; Cube still enforces access on every query the finished dashboard sends. Only member names and descriptions go to the model,
never data rows. With an API key set the model is Claude (or DeepSeek or another Anthropic-compatible server: builder/provider.py); without it a rule-based stand-in answers (a fixed set of phrases, no API calls). Each
user may build BUILDER_RATE_LIMIT times an hour and use BUILDER_DAILY_TOKENS model tokens a day; at most BUILDER_MAX_CONCURRENT builds run at once and a
model call gives up after BUILDER_TIMEOUT seconds. Every build writes one JSON line (stdout, and BUILDER_LOG_FILE if set).
"""
from __future__ import annotations

import collections
import datetime
import json
import os
import threading
import time
from typing import Annotated

import jwt
from dashspec import catalog as cat
from dashspec.semantic import catalog_json
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from builder import core, provider, saved
from builder.standin import StandInClient
from builder.store import PgStore

ISSUER = os.environ["KEYCLOAK_ISSUER"]
JWKS_URL = os.environ["KEYCLOAK_JWKS_URL"]
CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "dashboard")
CATALOG = cat.from_model(os.environ.get("BUILDER_MODEL_DIR", "/app/cube-model"))
RATE_LIMIT = int(os.environ.get("BUILDER_RATE_LIMIT", "20"))
DAILY_TOKENS = int(os.environ.get("BUILDER_DAILY_TOKENS", "300000"))           # model tokens per user per UTC day (the stand-in uses none)
MAX_CONCURRENT = int(os.environ.get("BUILDER_MAX_CONCURRENT", "4"))
TIMEOUT = float(os.environ.get("BUILDER_TIMEOUT", "120"))
LOG_FILE = os.environ.get("BUILDER_LOG_FILE", "")
MAX_SAVED = int(os.environ.get("BUILDER_MAX_SAVED", "50"))
STORE = PgStore.from_env()                                                   # None when BUILDER_DB_PASSWORD is not set: saving is off
MODE = os.environ.get("BUILDER_MODE", "auto").lower()
if MODE not in ("auto", "llm", "standin"):
    raise SystemExit(f"BUILDER_MODE must be auto, llm or standin, got {MODE!r}")


def mode() -> str:
    if MODE == "auto":
        return "llm" if provider.has_key() else "standin"
    if MODE == "llm" and not provider.has_key():
        raise HTTPException(503, "BUILDER_MODE=llm needs an API key (ANTHROPIC_API_KEY, or DEEPSEEK_API_KEY with BUILDER_PROVIDER=deepseek)")
    return MODE


def make_client(m: str, role: str):
    if m == "standin":
        return StandInClient(CATALOG, role)
    return provider.make_client(TIMEOUT)


jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=300)
app = FastAPI(title="builder")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("ALLOWED_ORIGINS", "http://localhost:8250").split(","),
                   allow_methods=["POST", "GET", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])


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
    role = next((r for r in core.ROLES if r in roles), None)
    if role is None:
        raise HTTPException(403, "your account has no dashboard role")
    return User(name=claims["preferred_username"], role=role)


_recent: dict[str, collections.deque] = collections.defaultdict(collections.deque)
_tokens: dict[str, tuple[str, int]] = {}                       # user -> (UTC date, tokens used that day); in memory, so a restart resets it
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)


def _builds_last_hour(user: User) -> int:
    now, q = time.time(), _recent[user.name]
    while q and now - q[0] > 3600:
        q.popleft()
    return len(q)


def _tokens_today(user: User) -> int:
    day, used = _tokens.get(user.name, ("", 0))
    return used if day == datetime.datetime.now(datetime.timezone.utc).date().isoformat() else 0


def rate_limit(user: User) -> None:
    if _builds_last_hour(user) >= RATE_LIMIT:
        wait = int((3600 - (time.time() - _recent[user.name][0])) / 60) + 1
        raise HTTPException(429, f"You can build {RATE_LIMIT} dashboards an hour; try again in {wait} minutes.")
    if _tokens_today(user) >= DAILY_TOKENS:
        raise HTTPException(429, f"Today's model budget ({DAILY_TOKENS:,} tokens) is used up; it resets at midnight UTC.")
    _recent[user.name].append(time.time())


def spend(user: User, usage: dict) -> None:
    day = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    _tokens[user.name] = (day, _tokens_today(user) + int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)))


def audit(entry: dict, event: str = "build") -> None:
    """One line per build or saved-dashboard change: who, what role, how it went and what it cost (the prompt is kept short). To stdout and, if BUILDER_LOG_FILE is set, to that file."""
    line = json.dumps({"event": event, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), **entry}, ensure_ascii=False)
    print(line, flush=True)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            print(json.dumps({"event": "log_file_failed", "error": str(exc)}), flush=True)


def clean(text: str) -> str:
    """The prompt without control characters (a newline and a tab are fine)."""
    return "".join(ch for ch in text if ch >= " " or ch in "\n\t")


class BuildRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=core.MAX_PROMPT)
    current_yaml: str | None = Field(default=None, max_length=core.MAX_YAML)


User_ = Annotated[User, Depends(current_user)]


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/info")
def info(user: User_) -> dict:
    m = mode()
    return {"mode": m, "model": provider.model() if m == "llm" else "rule-based stand-in", "provider": provider.label() if m == "llm" else "stand-in", "role": user.role, "user": user.name, "rate_limit_per_hour": RATE_LIMIT, "builds_left": max(0, RATE_LIMIT - _builds_last_hour(user)), "examples": core.examples_for(user.role), "saving": STORE is not None,
            "note": f"A language model ({provider.label()}, {provider.model()}) reads your request." if m == "llm" else "A rule-based stand-in answers: it understands a fixed set of phrases, not free text."}


@app.get("/usage")
def usage(user: User_) -> dict:
    return {"builds_last_hour": _builds_last_hour(user), "builds_per_hour": RATE_LIMIT, "tokens_today": _tokens_today(user), "tokens_per_day": DAILY_TOKENS,
            "concurrent": MAX_CONCURRENT, "mode": mode(), "saving": STORE is not None}


@app.get("/catalog")
def catalog(user: User_) -> list[dict]:
    return catalog_json(CATALOG, user.role)


def need_store():
    if STORE is None:
        raise HTTPException(503, "Saving is not set up on this server (BUILDER_DB_PASSWORD is empty).")
    return STORE


def who(user: User) -> saved.Who:
    return saved.Who(name=user.name, role=user.role)


def saved_call(fn, *args, **kw):
    """Run a saved-dashboards rule and turn its refusals into HTTP errors (a refusal carries the validator's problems when there are some)."""
    try:
        return fn(*args, **kw)
    except saved.SavedError as e:
        detail = {"message": e.message, "problems": e.problems} if e.problems else e.message
        raise HTTPException(e.status, detail) from None
    except saved.NotFound:
        raise HTTPException(404, "There is no such dashboard.") from None


class SaveRequest(BaseModel):
    yaml: str = Field(min_length=1, max_length=core.MAX_YAML)
    title: str | None = Field(default=None, max_length=120)
    visibility: str = "private"
    shared_roles: list[str] = []
    tags: list[Annotated[str, Field(max_length=100)]] | None = Field(default=None, max_length=10)      # the validator says what a tag may be; this only bounds the request


class UpdateRequest(BaseModel):
    yaml: str | None = Field(default=None, min_length=1, max_length=core.MAX_YAML)
    title: str | None = Field(default=None, max_length=120)
    visibility: str | None = None
    shared_roles: list[str] | None = None
    tags: list[Annotated[str, Field(max_length=100)]] | None = Field(default=None, max_length=10)


class RestoreRequest(BaseModel):
    version: int


@app.get("/saved")
def saved_list(user: User_, everything: bool = False) -> list[dict]:
    return saved_call(saved.list_saved, need_store(), CATALOG, who(user), everything=everything)


@app.post("/saved", status_code=201)
def saved_create(req: SaveRequest, user: User_) -> dict:
    out = saved_call(saved.save_new, need_store(), CATALOG, who(user), req.yaml, title=req.title, visibility=req.visibility, shared_roles=req.shared_roles, tags=req.tags, max_saved=MAX_SAVED)
    audit({"user": user.name, "role": user.role, "id": out["id"], "visibility": out["visibility"], "shared_roles": out["shared_roles"], "title": out["title"][:80]}, "saved")
    return out


@app.get("/saved/{id}")
def saved_open(id: str, user: User_, version: int | None = None) -> dict:
    return saved_call(saved.open_saved, need_store(), CATALOG, who(user), id, version)


@app.put("/saved/{id}")
def saved_update(id: str, req: UpdateRequest, user: User_) -> dict:
    out = saved_call(saved.update_saved, need_store(), CATALOG, who(user), id, yaml_text=req.yaml, title=req.title, visibility=req.visibility, shared_roles=req.shared_roles, tags=req.tags)
    audit({"user": user.name, "role": user.role, "id": id, "version": out["version"], "visibility": out["visibility"], "shared_roles": out["shared_roles"]}, "saved_update")
    return out


@app.delete("/saved/{id}", status_code=204, response_class=Response)
def saved_delete(id: str, user: User_) -> Response:
    saved_call(saved.delete_saved, need_store(), who(user), id)
    audit({"user": user.name, "role": user.role, "id": id}, "saved_delete")
    return Response(status_code=204)


@app.get("/saved/{id}/versions")
def saved_versions(id: str, user: User_) -> list[dict]:
    return saved_call(saved.versions, need_store(), who(user), id)


@app.post("/saved/{id}/restore")
def saved_restore(id: str, req: RestoreRequest, user: User_) -> dict:
    out = saved_call(saved.restore, need_store(), CATALOG, who(user), id, req.version)
    audit({"user": user.name, "role": user.role, "id": id, "restored": req.version, "version": out["version"]}, "saved_restore")
    return out


class ValidateRequest(BaseModel):
    yaml: str = Field(min_length=1, max_length=core.MAX_YAML)


@app.post("/validate")
def validate(req: ValidateRequest, user: User_) -> dict:
    built, problems = core.check_submission(req.yaml, CATALOG, user.role)
    return {"ok": built is not None, "yaml": built and built["yaml"], "spec": built and built["spec"], "notes": built["notes"] if built else [], "problems": problems}


@app.post("/build")
def build(req: BuildRequest, user: User_) -> dict:
    m = mode()
    rate_limit(user)
    if not _slots.acquire(blocking=False):
        _recent[user.name].pop()                                  # a refused request does not count against the user
        raise HTTPException(503, "The builder is busy with other requests; try again in a moment.")
    t0, prompt = time.time(), clean(req.prompt)
    try:
        result = core.run_build(make_client(m, user.role), CATALOG, user.role, prompt, req.current_yaml, mode=m)
    except HTTPException:
        raise
    except Exception as exc:  # the model API: a key that is rejected, a timeout, an outage. Never echo anything but the kind of failure.
        status = getattr(exc, "status_code", None)
        audit({"user": user.name, "role": user.role, "mode": m, "status": "error", "error": f"{type(exc).__name__} {status or ''}".strip(), "seconds": round(time.time() - t0, 1), "prompt": prompt[:160]})
        why = "the API key was rejected" if status in (401, 403) else "the model took too long" if "Timeout" in type(exc).__name__ else "the model is not reachable right now"
        raise HTTPException(502, f"The dashboard could not be built: {why}.") from None
    finally:
        _slots.release()
    spend(user, result["usage"])
    audit({"user": user.name, "role": user.role, "mode": m, "status": result["status"], "attempts": result["attempts"], "seconds": round(time.time() - t0, 1),
           "usage": result["usage"], "refine": bool(req.current_yaml), "prompt": prompt[:160]})
    return result
