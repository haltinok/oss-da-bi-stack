"""Auth service: Keycloak access token in, short-lived Cube JWT out.

POST /token   Authorization: Bearer <Keycloak access token>
  1. verify the token's signature, issuer, expiry and client (azp) against Keycloak's JWKS
  2. map the Keycloak realm role to a Cube role (admin > purchasing > marketing > manager > rep)
  3. read the person's row rules (access.rls_rule: for them and their groups) for each row-level dimension of the registry, and their datasets and grants
  4. mint a Cube JWT {user_id, role, rls: {dimension: values}, ...} signed with CUBEJS_API_SECRET, 15 min

Cube re-verifies that signature and applies the row filters in queryRewrite
(cube/cube.js), so a client can neither widen its values nor extend the token.
"""
import os
import time

import jwt

import access_resolve
import rls_registry
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

CUBE_SECRET = os.environ["CUBEJS_API_SECRET"]  # fail at startup, not at first request
TTL = int(os.environ.get("CUBE_JWT_TTL_SECONDS", "900"))
ISSUER = os.environ["KEYCLOAK_ISSUER"]                 # as it appears in tokens (public URL)
JWKS_URL = os.environ["KEYCLOAK_JWKS_URL"]             # reachable from this container
CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "dashboard")
# A role says what a person may DO in the app (admin: everything; editor: build, change and share dashboards; viewer: only view them). What data they may read is not a role matter:
# it comes from datasets, grants and row rules (the access schema), which this service puts in the Cube token. The old data roles (manager, rep, purchasing, marketing) are
# not recognised: a person who still has only one of them must be moved to editor plus a group first (keycloak/migrate-roles.sh), or their sign-in is refused.
ROLE_ORDER = ("admin", "editor", "viewer")
# The proposal agent is a Keycloak service account (client-credentials grant) of its own client: it may only
# ever be the `agent` role, and the dashboard client may never be. Neither can borrow the other's roles.
AGENT_CLIENT_ID = os.environ.get("KEYCLOAK_AGENT_CLIENT_ID", "inventory-agent")
# Row-level rules the admin console edits (Postgres, schema `access`, read-only login `access_auth`): a person's values per dimension are the union of the rules for them and their
# groups. Without AUTH_PG_PASSWORD there are no rules (nobody has a value, so a `deny` dimension gives everyone but an admin nothing). With it, a rules database that cannot be read
# fails the sign-in (503).
PG = {"host": os.environ.get("AUTH_PG_HOST", "postgres"), "port": int(os.environ.get("AUTH_PG_PORT", "5432")), "dbname": os.environ.get("AUTH_PG_DB", "postgres"),
      "user": os.environ.get("AUTH_PG_USER", "access_auth"), "password": os.environ.get("AUTH_PG_PASSWORD", "")}
RULES_ON = bool(PG["password"]) and PG["password"] != "REPLACE_ME"



def _access_db():
    import psycopg2
    return psycopg2.connect(connect_timeout=5, **PG)


# The row-level dimensions (territory, ...): access.rls_dimension, read once now, at startup (rls_registry.py; the default file rls_dimensions.json when there is no
# access database). A registry that cannot be read or is not valid stops the service. Cube adds the filters; here the values of each are worked out, and the token
# carries the registry's version so Cube refuses tokens made from a different list (one of the two was not restarted after a change).
DIMENSIONS, REGISTRY_SOURCE = rls_registry.load(_access_db if RULES_ON else None, wait=float(os.environ.get("RLS_REGISTRY_WAIT", "60")))
RLS_VERSION = rls_registry.version(DIMENSIONS)

jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=300)
app = FastAPI(title="spike-auth")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "http://localhost:8250").split(","),
    allow_methods=["POST", "GET"],
    allow_headers=["Authorization"],
)


def read_access(username: str, role: str, groups: list[str]) -> tuple[dict[str, list[str]], list[str], bool, list[str]]:
    """From the access schema: the values the rules give this person for each dimension (union over the rules for them and for their groups; a dimension with no rule is absent), the cubes
    they may not read because of datasets (access_resolve.blocked_cubes), and whether they may use the SQL lab (access_resolve.lab_allowed)."""
    import psycopg2
    conn = psycopg2.connect(connect_timeout=5, **PG)
    try:
        with conn.cursor() as cur:
            cur.execute("select dimension, \"values\" from access.rls_rule where ((principal_type = 'user' and principal = %s) "
                        "or (principal_type = 'group' and principal = any(%s)))", (username, groups))
            ruled: dict[str, set[str]] = {}
            for dim, vals in cur.fetchall():
                ruled.setdefault(dim, set()).update(vals)
            known = {d["id"] for d in DIMENSIONS}
            territories = {d: sorted(v) for d, v in ruled.items() if d in known}
            datasets, grants = access_resolve.load(cur)
        return (territories, access_resolve.blocked_cubes(datasets, grants, username, role, groups), access_resolve.lab_allowed(grants, username, role, groups),
                access_resolve.blocked_members(datasets, grants, username, role, groups))
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
    groups = sorted(g.strip("/") for g in claims.get("groups", []) if isinstance(g, str))       # Keycloak's group-membership mapper (the `dashboard` client)
    ruled: dict[str, list[str]] = {}
    blocked: list[str] = []
    blocked_fields: list[str] = []
    lab = role == "admin"                                                                            # without the access database only admins have the SQL lab
    if RULES_ON:
        try:
            ruled, blocked, lab, blocked_fields = read_access(user, role, groups)
        except Exception as exc:                                                                  # noqa: BLE001 (any failure to read the rules fails the sign-in)
            raise HTTPException(503, "the access rules cannot be read right now") from exc
    rls: dict[str, list[str]] = {}
    if role != "agent":                                                                              # the agent works on inventory, which is not row-bound
        for dim in DIMENSIONS:
            rls[dim["id"]] = ruled.get(dim["id"], [])                                                 # the rules for this person or their groups; none is fine (cube.js denies or allows by `when_empty`)

    now = int(time.time())
    cube_token = jwt.encode(
        {"user_id": user, "role": role, "rls": rls, "rls_version": RLS_VERSION, "groups": groups, "blocked_cubes": blocked, "blocked_members": blocked_fields, "lab": lab, "iat": now, "exp": now + TTL},
        CUBE_SECRET,
        algorithm="HS256",
    )
    return {"token": cube_token, "expires_in": TTL, "user": user, "role": role, "rls": rls, "groups": groups, "blocked_cubes": blocked, "blocked_members": blocked_fields, "lab": lab}
