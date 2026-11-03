"""Admin console service: people, groups and roles, over Keycloak.

  GET  /healthz
  GET  /roles                              the dashboard roles a person can hold
  GET  /users?search&role&group&enabled&first&max      { users: [...], total }
  POST /users                              create (a temporary password the person must change at first sign-in)
  GET|PUT /users/{id}                      read; change name, email, role, groups
  POST /users/{id}/enable | /disable       activate, or deactivate (and end their sessions)
  POST /users/{id}/password                set a password { password, temporary }
  POST /users/{id}/reset-password          email Keycloak's "update password" link ({ email: true }) or set a temporary one and return it once
  DELETE /users/{id}?confirm=<username>    delete (deactivating is what the page suggests)
  GET|POST /groups, PUT|DELETE /groups/{id}, PUT|DELETE /groups/{id}/members/{userId}
  GET  /rls/rules                          { rules, regions }: which territories each user or group may see (Postgres schema `access`)
  PUT|DELETE /rls/rules/{user|group}/{name}  set (values: [region, ...]) or remove one
  GET  /rls/preview/{username}             what that person will see now: their territories, whether the rules or the dbt seed decided, and the cubes datasets keep from them
  GET  /datasets                           { datasets, cubes, roles }: named sets of cubes and who may use each (a cube in a dataset is readable only by those with a grant)
  PUT|DELETE /datasets/{id}                create or replace one (name, description, cubes, grants: [{type: user|group|role, principal}]), or remove it

Every call needs a Keycloak access token of the dashboard client from a person with the `admin` role. The service signs in to Keycloak as its own client
(`admin-console`), so the browser never holds a Keycloak admin token. Rules kept here, not only on the page: the last active admin cannot be deactivated, deleted or
demoted, and nobody can do that to their own account. Every change writes one JSON line to stdout (who, what, to whom).
"""
from __future__ import annotations

import datetime
import json
import os
import secrets
from typing import Annotated

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import access_resolve
from access import TYPES, PgRules
from cubes import cubes as model_cubes
from keycloak import Keycloak, KeycloakError
from seed import Seed

ISSUER = os.environ["KEYCLOAK_ISSUER"]
JWKS_URL = os.environ["KEYCLOAK_JWKS_URL"]
CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "dashboard")
ROLES = ("admin", "manager", "rep", "viewer", "purchasing", "marketing")        # the dashboard roles a person holds (`agent` belongs to a service account)
MIN_PASSWORD = 10
MAX_USERS = 1000

jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=300)
app = FastAPI(title="admin")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("ALLOWED_ORIGINS", "http://localhost:8250").split(","),
                   allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])

_kc: Keycloak | None = None


def kc() -> Keycloak:
    """The Keycloak client (made on first use, so a test can replace it with a fake before that)."""
    global _kc
    if _kc is None:
        _kc = Keycloak(os.environ.get("KEYCLOAK_ADMIN_URL", "http://keycloak:8080"), os.environ.get("KEYCLOAK_REALM", "spike"),
                       os.environ.get("ADMIN_CLIENT_ID", "admin-console"), os.environ["ADMIN_CLIENT_SECRET"])
    return _kc


_rules: PgRules | None | str = "unset"
_seed: Seed | None | str = "unset"
TERRITORY_ROLES = ("admin", "manager", "rep", "viewer")       # the roles the auth service scopes by territory (the others work on inventory)


def rules() -> PgRules:
    """The rules store (made on first use, so a test can replace it); 503 when no login for it is configured."""
    global _rules
    if _rules == "unset":
        _rules = PgRules.from_env()
    if _rules is None:
        raise HTTPException(503, "row-level rules are off: set ADMIN_DB_PASSWORD and run postgres/sync-access.sh")
    return _rules


def rules_or_none():
    try:
        return rules()
    except HTTPException:
        return None


def seed() -> Seed | None:
    global _seed
    if _seed == "unset":
        _seed = Seed.from_env()
    return _seed


class Admin(BaseModel):
    id: str
    name: str


def current_admin(authorization: str = Header(default="")) -> Admin:
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
    if "admin" not in claims.get("realm_access", {}).get("roles", []):
        raise HTTPException(403, "only an admin can use the console")
    return Admin(id=claims["sub"], name=claims["preferred_username"])


Who = Annotated[Admin, Depends(current_admin)]


def audit(who: Admin, action: str, **entry) -> None:
    print(json.dumps({"event": "admin", "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "by": who.name, "action": action, **entry}, ensure_ascii=False), flush=True)


def fail(exc: KeycloakError):
    raise HTTPException(exc.status, exc.message)


# -------------------------------------------------------------------------------------------------------------------- shaping
def role_map() -> dict[str, str]:
    """user id -> dashboard role (the highest one, as the auth service picks it); 5 calls however many people there are."""
    out: dict[str, str] = {}
    for role in reversed(ROLES):                                       # ROLES is ordered high to low, so the highest is written last and wins
        for u in kc().role_members(role):
            out[u["id"]] = role
    return out


def group_map() -> tuple[dict[str, list[dict]], list[dict]]:
    """user id -> [{id, name}], and the groups with their member counts."""
    by_user: dict[str, list[dict]] = {}
    groups = []
    for g in kc().groups():
        members = kc().group_members(g["id"])
        groups.append({"id": g["id"], "name": g["name"], "members": len(members)})
        for m in members:
            by_user.setdefault(m["id"], []).append({"id": g["id"], "name": g["name"]})
    return by_user, groups


def shape(u: dict, roles: dict[str, str], groups: dict[str, list[dict]]) -> dict:
    return {"id": u["id"], "username": u["username"], "email": u.get("email", ""), "firstName": u.get("firstName", ""), "lastName": u.get("lastName", ""),
            "enabled": u.get("enabled", True), "role": roles.get(u["id"]), "groups": sorted(groups.get(u["id"], []), key=lambda g: g["name"].lower())}


def one(uid: str) -> dict:
    try:
        return shape(kc().user(uid), role_map(), group_map()[0])
    except KeycloakError as exc:
        fail(exc)


def active_admins(excluding: str) -> int:
    return sum(1 for u in kc().role_members("admin") if u.get("enabled", True) and u["id"] != excluding)


def keep_an_admin(who: Admin, uid: str, what: str) -> None:
    """Refuse what would leave no active admin, or that an admin does to their own account."""
    if uid == who.id:
        raise HTTPException(409, f"you cannot {what} your own account")
    try:
        was_admin = any(u["id"] == uid for u in kc().role_members("admin"))
        if was_admin and active_admins(uid) == 0:
            raise HTTPException(409, f"the last active admin cannot be {what}d")
    except KeycloakError as exc:
        fail(exc)


# -------------------------------------------------------------------------------------------------------------------- requests
class NewUser(BaseModel):
    username: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9._@-]+$")
    email: str = Field(default="", max_length=200)
    firstName: str = Field(default="", max_length=100)
    lastName: str = Field(default="", max_length=100)
    role: str
    groups: list[str] = []
    password: str = Field(min_length=MIN_PASSWORD, max_length=200)
    temporary: bool = True


class UserEdit(BaseModel):
    email: str | None = Field(default=None, max_length=200)
    firstName: str | None = Field(default=None, max_length=100)
    lastName: str | None = Field(default=None, max_length=100)
    role: str | None = None
    groups: list[str] | None = None


class PasswordRequest(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD, max_length=200)
    temporary: bool = True


class ResetRequest(BaseModel):
    email: bool = False


class GroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def need_role(role: str) -> None:
    if role not in ROLES:
        raise HTTPException(400, f"role must be one of {', '.join(ROLES)}")


def apply_groups(uid: str, wanted: list[str]) -> None:
    current = {g["id"] for g in kc().groups() if any(m["id"] == uid for m in kc().group_members(g["id"]))}
    known = {g["id"] for g in kc().groups()}
    unknown = [g for g in wanted if g not in known]
    if unknown:
        raise HTTPException(400, f"no such group: {unknown[0]}")
    for gid in set(wanted) - current:
        kc().add_to_group(uid, gid)
    for gid in current - set(wanted):
        kc().remove_from_group(uid, gid)


def apply_role(uid: str, role: str) -> None:
    held = {r for r in ROLES if any(u["id"] == uid for u in kc().role_members(r))}
    for r in held - {role}:
        kc().remove_role(uid, r)
    if role not in held:
        kc().add_role(uid, role)


# -------------------------------------------------------------------------------------------------------------------- routes
@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/roles")
def roles(_: Who) -> dict:
    return {"roles": list(ROLES)}


@app.get("/users")
def list_users(_: Who, search: str = "", role: str = "", group: str = "", enabled: bool | None = None, first: int = 0, max: int = 50) -> dict:
    try:
        raw = kc().users(search=search, enabled=enabled, limit=MAX_USERS)
        roles_, (groups_, _all) = role_map(), group_map()
    except KeycloakError as exc:
        fail(exc)
    rows = [shape(u, roles_, groups_) for u in raw]
    if role:
        rows = [r for r in rows if r["role"] == role]
    if group:
        rows = [r for r in rows if any(g["id"] == group for g in r["groups"])]
    rows.sort(key=lambda r: r["username"].lower())
    max = min(max, 200)
    return {"users": rows[first:first + max], "total": len(rows)}


@app.post("/users", status_code=201)
def create_user(req: NewUser, who: Who) -> dict:
    need_role(req.role)
    try:
        uid = kc().create_user({"username": req.username, "email": req.email or None, "firstName": req.firstName, "lastName": req.lastName, "enabled": True,
                                "emailVerified": bool(req.email), "requiredActions": ["UPDATE_PASSWORD"] if req.temporary else []})
        kc().set_password(uid, req.password, req.temporary)
        apply_role(uid, req.role)
        apply_groups(uid, req.groups)
    except KeycloakError as exc:
        fail(exc)
    audit(who, "create_user", user=req.username, role=req.role, groups=req.groups)
    return one(uid)


@app.get("/users/{uid}")
def get_user(uid: str, _: Who) -> dict:
    return one(uid)


@app.put("/users/{uid}")
def edit_user(uid: str, req: UserEdit, who: Who) -> dict:
    if req.role is not None:
        need_role(req.role)
    try:
        current = kc().user(uid)
        if req.role is not None and req.role != "admin":
            keep_an_admin(who, uid, "demote")
        rep = {**current, **{k: v for k, v in {"email": req.email, "firstName": req.firstName, "lastName": req.lastName}.items() if v is not None}}
        kc().update_user(uid, rep)
        if req.role is not None:
            apply_role(uid, req.role)
        if req.groups is not None:
            apply_groups(uid, req.groups)
    except KeycloakError as exc:
        fail(exc)
    audit(who, "edit_user", user=current["username"], **{k: v for k, v in req.model_dump().items() if v is not None})
    return one(uid)


@app.post("/users/{uid}/disable")
def disable(uid: str, who: Who) -> dict:
    keep_an_admin(who, uid, "deactivate")
    try:
        u = kc().user(uid)
        kc().update_user(uid, {**u, "enabled": False})
        kc().logout(uid)                                                # their Keycloak sessions end now; a Cube token already issued lives out its few minutes
    except KeycloakError as exc:
        fail(exc)
    audit(who, "deactivate_user", user=u["username"])
    return one(uid)


@app.post("/users/{uid}/enable")
def enable(uid: str, who: Who) -> dict:
    try:
        u = kc().user(uid)
        kc().update_user(uid, {**u, "enabled": True})
    except KeycloakError as exc:
        fail(exc)
    audit(who, "activate_user", user=u["username"])
    return one(uid)


@app.post("/users/{uid}/password")
def set_password(uid: str, req: PasswordRequest, who: Who) -> dict:
    try:
        u = kc().user(uid)
        kc().set_password(uid, req.password, req.temporary)
    except KeycloakError as exc:
        fail(exc)
    audit(who, "set_password", user=u["username"], temporary=req.temporary)               # the password itself is never logged
    return {"ok": True}


@app.post("/users/{uid}/reset-password")
def reset_password(uid: str, who: Who, req: ResetRequest | None = None) -> dict:
    by_email = bool(req and req.email)
    try:
        u = kc().user(uid)
        if by_email:
            if not u.get("email"):
                raise HTTPException(400, "this person has no email address")
            kc().email_update_password(uid)
            audit(who, "reset_password", user=u["username"], by="email")
            return {"ok": True, "emailed": True}
        temp = secrets.token_urlsafe(12)
        kc().set_password(uid, temp, True)
    except KeycloakError as exc:
        fail(exc)
    audit(who, "reset_password", user=u["username"], by="temporary")
    return {"ok": True, "emailed": False, "temporary_password": temp}                    # shown once; the person must change it at the next sign-in


@app.delete("/users/{uid}", status_code=204, response_class=Response)
def delete_user(uid: str, who: Who, confirm: str = ""):
    try:
        u = kc().user(uid)
        if confirm != u["username"]:
            raise HTTPException(400, "type the username to confirm the deletion")
        keep_an_admin(who, uid, "delete")
        if rules_or_none():
            rules().delete("user", u["username"])                                     # a new person with the same username must not inherit them
            rules().drop_grants("user", u["username"])
        kc().delete_user(uid)
    except KeycloakError as exc:
        fail(exc)
    audit(who, "delete_user", user=u["username"])


@app.get("/groups")
def list_groups(_: Who) -> dict:
    try:
        return {"groups": sorted(group_map()[1], key=lambda g: g["name"].lower())}
    except KeycloakError as exc:
        fail(exc)


@app.post("/groups", status_code=201)
def create_group(req: GroupRequest, who: Who) -> dict:
    try:
        gid = kc().create_group(req.name.strip())
    except KeycloakError as exc:
        fail(exc)
    audit(who, "create_group", group=req.name)
    return {"id": gid, "name": req.name.strip(), "members": 0}


@app.put("/groups/{gid}")
def rename_group(gid: str, req: GroupRequest, who: Who) -> dict:
    try:
        old = next((g["name"] for g in kc().groups() if g["id"] == gid), None)
        kc().rename_group(gid, req.name.strip())
        if old and old != req.name.strip() and rules_or_none():
            rules().rename("group", old, req.name.strip())                          # a rule and a grant follow their group's name
            rules().rename_grants("group", old, req.name.strip())
    except KeycloakError as exc:
        fail(exc)
    audit(who, "rename_group", group=req.name, id=gid)
    return {"id": gid, "name": req.name.strip()}


@app.delete("/groups/{gid}", status_code=204, response_class=Response)
def delete_group(gid: str, who: Who):
    try:
        old = next((g["name"] for g in kc().groups() if g["id"] == gid), None)
        if old and rules_or_none():
            rules().delete("group", old)                                              # no rule or grant outlives its group
            rules().drop_grants("group", old)
        kc().delete_group(gid)
    except KeycloakError as exc:
        fail(exc)
    audit(who, "delete_group", id=gid)


@app.put("/groups/{gid}/members/{uid}", status_code=204, response_class=Response)
def add_member(gid: str, uid: str, who: Who):
    try:
        kc().add_to_group(uid, gid)
    except KeycloakError as exc:
        fail(exc)
    audit(who, "add_to_group", id=gid, user_id=uid)


@app.delete("/groups/{gid}/members/{uid}", status_code=204, response_class=Response)
def remove_member(gid: str, uid: str, who: Who):
    try:
        kc().remove_from_group(uid, gid)
    except KeycloakError as exc:
        fail(exc)
    audit(who, "remove_from_group", id=gid, user_id=uid)


# -------------------------------------------------------------------------------------------------------------------- row-level rules
class RuleRequest(BaseModel):
    values: list[str] = Field(min_length=1, max_length=200)


def known_regions() -> list[str] | None:
    sd = seed()
    return sd.regions() if sd else None


@app.get("/rls/rules")
def list_rules(_: Who) -> dict:
    return {"rules": rules().list(), "regions": known_regions() or []}


@app.put("/rls/rules/{type_}/{principal}")
def put_rule(type_: str, principal: str, req: RuleRequest, who: Who) -> dict:
    if type_ not in TYPES:
        raise HTTPException(400, "a rule is for a user or a group")
    store = rules()
    try:
        if type_ == "user":
            if not any(u["username"] == principal for u in kc().users(search=principal)):
                raise HTTPException(404, f"no user '{principal}'")
        elif not any(g["name"] == principal for g in kc().groups()):
            raise HTTPException(404, f"no group '{principal}'")
    except KeycloakError as exc:
        fail(exc)
    regions = known_regions()
    values = sorted(set(req.values))
    if regions is not None:
        unknown = [v for v in values if v not in regions]
        if unknown:
            raise HTTPException(400, f"unknown territory: {unknown[0]} (known: {', '.join(regions)})")
    row = store.put(type_, principal, values, who.name)
    audit(who, "set_rule", type=type_, principal=principal, values=values)
    return row


@app.delete("/rls/rules/{type_}/{principal}", status_code=204, response_class=Response)
def delete_rule(type_: str, principal: str, who: Who):
    if type_ not in TYPES:
        raise HTTPException(400, "a rule is for a user or a group")
    if not rules().delete(type_, principal):
        raise HTTPException(404, "no such rule")
    audit(who, "delete_rule", type=type_, principal=principal)


@app.get("/rls/preview/{username}")
def preview(username: str, _: Who) -> dict:
    """What the auth service will give this person at their next sign-in: the union of the rules for them and their groups, else the dbt seed."""
    store = rules()
    try:
        person = next((u for u in kc().users(search=username) if u["username"] == username), None)
        if person is None:
            raise HTTPException(404, f"no user '{username}'")
        shaped = shape(person, role_map(), group_map()[0])
    except KeycloakError as exc:
        fail(exc)
    names = [g["name"] for g in shaped["groups"]]
    applying = [r for r in store.list() if (r["type"] == "user" and r["principal"] == username) or (r["type"] == "group" and r["principal"] in names)]
    datasets, grants = store.resolve_input()
    out = {"username": username, "role": shaped["role"], "groups": names, "applies": shaped["role"] in TERRITORY_ROLES,
           "rules": [{"type": r["type"], "principal": r["principal"], "values": r["values"]} for r in applying],
           "blocked_cubes": access_resolve.blocked_cubes(datasets, grants, username, shaped["role"] or "", names),
           "blocked_members": access_resolve.blocked_members(datasets, grants, username, shaped["role"] or "", names),
           "lab": access_resolve.lab_allowed(grants, username, shaped["role"] or "", names)}
    if applying:
        return {**out, "territories": sorted({v for r in applying for v in r["values"]}), "source": "rules"}
    sd = seed()
    seeded = sd.regions_of(username) if sd else None
    if seeded is None:
        return {**out, "territories": [], "source": "unknown"}
    return {**out, "territories": seeded, "source": "seed" if seeded else "none"}


# -------------------------------------------------------------------------------------------------------------------- datasets
GRANT_ROLES = (*ROLES, "agent")


class GrantIn(BaseModel):
    type: str
    principal: str = Field(min_length=1, max_length=120)
    permission: str = "view"                                  # view: read the dataset's cubes; lab: also use the SQL lab


class DatasetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=400)
    cubes: list[str] = Field(default=[], max_length=100)                       # whole cubes that need a grant
    members: list[str] = Field(default=[], max_length=300)                     # single fields (cube.member) that need a grant
    grants: list[GrantIn] = Field(default=[], max_length=500)


@app.get("/datasets")
def list_datasets(_: Who) -> dict:
    return {"datasets": rules().datasets(), "cubes": model_cubes(), "roles": list(GRANT_ROLES)}


@app.put("/datasets/{dataset_id}")
def put_dataset(dataset_id: str, req: DatasetRequest, who: Who) -> dict:
    import re
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", dataset_id):
        raise HTTPException(400, "the id is lowercase letters, digits, - and _ (at most 40 characters)")
    store = rules()
    if not req.cubes and not req.members:
        raise HTTPException(422, "a dataset holds at least one cube or one field")
    known = {c["name"] for c in model_cubes()}
    if known:
        unknown = [c for c in req.cubes if c not in known]
        if unknown:
            raise HTTPException(400, f"no such cube: {unknown[0]}")
        fields = {f"{c['name']}.{f['name']}" for c in model_cubes() for f in c.get("fields", [])}
        bad = [m for m in req.members if m not in fields]
        if bad:
            raise HTTPException(400, f"no such field: {bad[0]} (write cube.field, e.g. internet_sales.gross_profit)")
    grants, seen = [], {}
    try:
        users, groups = None, None
        for g in req.grants:
            if g.type not in ("user", "group", "role"):
                raise HTTPException(400, "a grant is for a user, a group or a role")
            if g.permission not in ("view", "lab"):
                raise HTTPException(400, "a grant is view or lab")
            if (g.type, g.principal) in seen:
                if g.permission == "lab":                                                   # the same person twice: lab includes view
                    seen[(g.type, g.principal)]["permission"] = "lab"
                continue
            if g.type == "role" and g.principal not in GRANT_ROLES:
                raise HTTPException(400, f"no such role: {g.principal}")
            if g.type == "user":
                users = users if users is not None else {u["username"] for u in kc().users(limit=MAX_USERS)}
                if g.principal not in users:
                    raise HTTPException(404, f"no user '{g.principal}'")
            if g.type == "group":
                groups = groups if groups is not None else {x["name"] for x in kc().groups()}
                if g.principal not in groups:
                    raise HTTPException(404, f"no group '{g.principal}'")
            grants.append({"type": g.type, "principal": g.principal, "permission": g.permission})
            seen[(g.type, g.principal)] = grants[-1]
    except KeycloakError as exc:
        fail(exc)
    row = store.put_dataset(dataset_id, req.name.strip(), req.description.strip(), sorted(set(req.cubes)), grants, who.name, members=sorted(set(req.members)))
    audit(who, "set_dataset", id=dataset_id, cubes=row["cubes"], members=row["members"], grants=grants)
    return row


@app.delete("/datasets/{dataset_id}", status_code=204, response_class=Response)
def delete_dataset(dataset_id: str, who: Who):
    if not rules().delete_dataset(dataset_id):
        raise HTTPException(404, "no such dataset")
    audit(who, "delete_dataset", id=dataset_id)
