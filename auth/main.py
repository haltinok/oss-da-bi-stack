"""Auth service: Keycloak access token in, short-lived Cube JWT out.

POST /token   Authorization: Bearer <Keycloak access token>
  1. verify the token's signature, issuer, expiry and client (azp) against Keycloak's JWKS
  2. map the Keycloak realm role to a Cube role (admin > purchasing > marketing > manager > rep)
  3. look the user's territories up in mart.dim_user_territory (a dbt seed); purchasing and marketing have none
  4. mint a Cube JWT {user_id, role, territories} signed with CUBEJS_API_SECRET, 15 min

Cube re-verifies that signature and applies the territory filter in queryRewrite
(cube/cube.js), so a client can neither widen its territories nor extend the token.
"""
import os
import re
import time

import jwt
import pymysql
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

CUBE_SECRET = os.environ["CUBEJS_API_SECRET"]  # fail at startup, not at first request
TTL = int(os.environ.get("CUBE_JWT_TTL_SECONDS", "900"))
ISSUER = os.environ["KEYCLOAK_ISSUER"]                 # as it appears in tokens (public URL)
JWKS_URL = os.environ["KEYCLOAK_JWKS_URL"]             # reachable from this container
CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "dashboard")
ROLE_ORDER = ("admin", "purchasing", "marketing", "manager", "rep")
# The proposal agent is a Keycloak service account (client-credentials grant) of its own client: it may only
# ever be the `agent` role, and the dashboard client may never be. Neither can borrow the other's roles.
AGENT_CLIENT_ID = os.environ.get("KEYCLOAK_AGENT_CLIENT_ID", "inventory-agent")
# Only these roles are scoped by territory. purchasing and marketing work on inventory, which is not
# territory-bound; cube/cube.js keeps them away from the sales cubes.
TERRITORY_ROLES = ("admin", "manager", "rep")   # the agent has none either
# DATASET picks the schema the territories come from: rls (live) or rls_<dataset> (e.g. rls_250m, built by dbt with
# mart_suffix _250m). AUTH_REGIONS_TABLE overrides it. Operator-set, not user input, and checked before it reaches SQL.
DATASET = os.environ.get("DATASET", "live").lower()
if not re.fullmatch(r"[a-z0-9]+", DATASET):
    raise SystemExit(f"DATASET must be letters and digits, got {DATASET!r}")
# `both` (the live Cube and a 250m Cube side by side): this deployment's users and territories are the live ones for both.
DATASET_SUFFIX = "" if DATASET in ("live", "both") else f"_{DATASET}"
REGIONS_TABLE = os.environ.get("AUTH_REGIONS_TABLE") or f"rls{DATASET_SUFFIX}.user_regions"

jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=300)
app = FastAPI(title="spike-auth")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "http://localhost:8250").split(","),
    allow_methods=["POST", "GET"],
    allow_headers=["Authorization"],
)


def territories_for(username: str) -> list[str]:
    # dbt drops and recreates the table on every build: for a split second it does not exist.
    # Retry that (and only that) briefly instead of failing a login.
    for attempt in range(4):
        try:
            return _territories_for(username)
        except pymysql.err.ProgrammingError as exc:
            if exc.args[0] != 5502 or attempt == 3:  # 5502: unknown table
                raise
            time.sleep(0.4)
    return []


def _territories_for(username: str) -> list[str]:
    conn = pymysql.connect(
        host=os.environ.get("STARROCKS_HOST", "starrocks"),
        port=int(os.environ.get("STARROCKS_PORT", "9030")),
        user=os.environ["AUTH_DB_USER"],
        password=os.environ["AUTH_DB_PASSWORD"],
        connect_timeout=5,
    )
    try:
        with conn.cursor() as cur:
            if REGIONS_TABLE:
                # e.g. rls.user_regions (username, region): a schema with a wildcard grant, so it
                # stays readable while dbt rebuilds the mart.
                cur.execute(f"select region from {REGIONS_TABLE} where username = %s order by 1", (username,))
            else:
                cur.execute(
                    "select t.sales_territory_region from mart.dim_user_territory u "
                    "join mart.dim_sales_territory t on t.sales_territory_key = u.sales_territory_key "
                    "where u.username = %s order by 1",
                    (username,),
                )
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/token")
def token(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    raw = authorization.removeprefix("Bearer ")
    try:
        key = jwks.get_signing_key_from_jwt(raw).key
        claims = jwt.decode(raw, key, algorithms=["RS256"], issuer=ISSUER, options={"verify_aud": False})
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid token: {exc}") from exc
    azp = claims.get("azp")
    if azp not in (CLIENT_ID, AGENT_CLIENT_ID):
        raise HTTPException(401, "token was not issued to a known client")

    roles = claims.get("realm_access", {}).get("roles", [])
    if azp == AGENT_CLIENT_ID:
        role = "agent" if "agent" in roles else None
    else:
        role = next((r for r in ROLE_ORDER if r in roles), None)
    if role is None:
        raise HTTPException(403, "no dashboard role")
    user = claims["preferred_username"]
    territories = territories_for(user) if role in TERRITORY_ROLES else []
    if role in TERRITORY_ROLES and not territories:
        raise HTTPException(403, "no territories assigned")

    now = int(time.time())
    cube_token = jwt.encode(
        {"user_id": user, "role": role, "territories": territories, "iat": now, "exp": now + TTL},
        CUBE_SECRET,
        algorithm="HS256",
    )
    return {"token": cube_token, "expires_in": TTL, "user": user, "role": role, "territories": territories}
