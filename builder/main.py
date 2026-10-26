"""Dashboard builder service: a request becomes a validated dashboard spec.

  GET  /healthz
  GET  /info      the mode (llm | standin), the model, the caller's role
  GET  /catalog   the semantic layer as the caller's role may read it (cubes, measures, dimensions, descriptions, joins)
  POST /build     { prompt, current_yaml? } -> { status: ok | cannot | failed, yaml, spec, message, notes, attempts, mode, model, usage }
  POST /validate  { yaml } -> { ok, yaml, spec, notes, problems }: the same checks for a file a person edited (no model, no cost)

Every request carries a Keycloak access token (verified like the actions service does). The role from the token decides what the model is shown and
what the validator accepts; Cube still enforces access on every query the finished dashboard sends. Only member names and descriptions go to the model,
never data rows. With ANTHROPIC_API_KEY set the model is Claude; without it a rule-based stand-in answers (a fixed set of phrases, no API calls). Each
user may build BUILDER_RATE_LIMIT times an hour.
"""
from __future__ import annotations

import collections
import json
import os
import time
from typing import Annotated

import jwt
from dashspec import catalog as cat
from dashspec.semantic import catalog_json
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from builder import core
from builder.standin import StandInClient

ISSUER = os.environ["KEYCLOAK_ISSUER"]
JWKS_URL = os.environ["KEYCLOAK_JWKS_URL"]
CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "dashboard")
CATALOG = cat.from_model(os.environ.get("BUILDER_MODEL_DIR", "/app/cube-model"))
RATE_LIMIT = int(os.environ.get("BUILDER_RATE_LIMIT", "20"))
MODE = os.environ.get("BUILDER_MODE", "auto").lower()
if MODE not in ("auto", "llm", "standin"):
    raise SystemExit(f"BUILDER_MODE must be auto, llm or standin, got {MODE!r}")


def mode() -> str:
    if MODE == "auto":
        return "llm" if os.environ.get("ANTHROPIC_API_KEY") else "standin"
    if MODE == "llm" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "BUILDER_MODE=llm needs ANTHROPIC_API_KEY")
    return MODE


def make_client(m: str, role: str):
    if m == "standin":
        return StandInClient(CATALOG, role)
    import anthropic
    return anthropic.Anthropic()


jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=300)
app = FastAPI(title="builder")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("ALLOWED_ORIGINS", "http://localhost:8250").split(","),
                   allow_methods=["POST", "GET"], allow_headers=["Authorization", "Content-Type"])


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


def rate_limit(user: User) -> None:
    now, q = time.time(), _recent[user.name]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(429, f"You can build {RATE_LIMIT} dashboards an hour; try again in {int((3600 - (now - q[0])) / 60) + 1} minutes.")
    q.append(now)


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
    return {"mode": m, "model": core.MODEL if m == "llm" else "rule-based stand-in", "role": user.role, "user": user.name, "rate_limit_per_hour": RATE_LIMIT, "examples": core.examples_for(user.role),
            "note": "A language model reads your request." if m == "llm" else "A rule-based stand-in answers: it understands a fixed set of phrases, not free text."}


@app.get("/catalog")
def catalog(user: User_) -> list[dict]:
    return catalog_json(CATALOG, user.role)


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
    t0 = time.time()
    result = core.run_build(make_client(m, user.role), CATALOG, user.role, req.prompt, req.current_yaml, mode=m)
    # one line per build, for the operator: who, what role, how it went and what it cost (the prompt is kept short)
    print(json.dumps({"event": "build", "user": user.name, "role": user.role, "mode": m, "status": result["status"], "attempts": result["attempts"],
                      "seconds": round(time.time() - t0, 1), "usage": result["usage"], "prompt": req.prompt[:160]}), flush=True)
    return result
