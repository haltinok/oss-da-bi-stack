"""The rules of saved queries: who may see, run, change, share and delete one.

- A saved query is private to its owner until the owner shares it with named people or groups (view: see and run it; edit: also change the SQL and title). A query can live in one of the
  dashboards' folders; a folder shared with someone shares what is in it with them. An admin sees every query and can delete, move or hand over any.
- **Running a saved query always runs it as the person who runs it**, under their own rules (territories, role, blocked cubes): sharing a query shares the question, never the answer.
  The last result of a query for a person (a snapshot) is that person's own copy and is never shown to anyone else.
- The SQL is checked (one SELECT) when it is saved, as it is when it is run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import sqlcheck
from store import NotFound  # noqa: F401 (re-exported)

UNSET = object()
SHARE_TYPES = ("user", "group")
SHARE_PERMISSIONS = ("view", "edit")
MAX_SHARES = 50
MAX_QUERIES = 100                                              # per owner


@dataclass
class QueryError(Exception):
    status: int
    message: str


@dataclass
class Who:
    name: str
    role: str
    groups: list[str] = field(default_factory=list)


def _level_in(shares, who: Who) -> str | None:
    best = None
    for sh in shares or []:
        if (sh["type"] == "user" and sh["principal"] == who.name) or (sh["type"] == "group" and sh["principal"] in who.groups):
            if sh["permission"] == "edit":
                return "edit"
            best = "view"
    return best


def _level(row: dict, who: Who, folders: dict) -> str | None:
    levels = {_level_in(row.get("shares"), who), _level_in((folders.get(row.get("folder_id")) or {}).get("shares"), who)}
    return "edit" if "edit" in levels else "view" if "view" in levels else None


def _clean_shares(shares) -> list[dict]:
    if not isinstance(shares, list) or len(shares) > MAX_SHARES:
        raise QueryError(422, f"share with at most {MAX_SHARES} people and groups")
    best: dict[tuple, str] = {}
    for sh in shares:
        if not isinstance(sh, dict) or sh.get("type") not in SHARE_TYPES or sh.get("permission") not in SHARE_PERMISSIONS \
                or not isinstance(sh.get("principal"), str) or not 0 < len(sh["principal"].strip()) <= 120:
            raise QueryError(422, "a share is a person or a group with view or edit")
        key = (sh["type"], sh["principal"].strip())
        if best.get(key) != "edit":
            best[key] = sh["permission"]
    return [{"type": t, "principal": p, "permission": perm} for (t, p), perm in sorted(best.items())]


def _can_see(row: dict, who: Who, folders: dict) -> bool:
    return row["owner"] == who.name or who.role == "admin" or _level(row, who, folders) is not None


def _can_edit(row: dict, who: Who, folders: dict) -> bool:
    return row["owner"] == who.name or _level(row, who, folders) == "edit"


def meta(row: dict, who: Who, folders: dict) -> dict:
    mine = row["owner"] == who.name
    manage = mine or who.role == "admin"
    folder = folders.get(row.get("folder_id"))
    out = {"id": row["id"], "title": row["title"], "description": row["description"], "sql": row["sql"], "owner": row["owner"], "mine": mine, "can_edit": _can_edit(row, who, folders), "can_manage": manage,
           "folder_id": row.get("folder_id") if folder else None, "folder_name": folder["name"] if folder else None, "shared_with_me": not mine and _level(row, who, folders) is not None,
           "created_at": row["created_at"], "updated_at": row["updated_at"]}
    if manage:
        out["shares"] = row.get("shares") or []
    return out


def _folder_for_putting(folders: dict, who: Who, folder_id: str) -> dict:
    f = folders.get(folder_id)
    if f is None or not (f["owner"] == who.name or who.role == "admin" or _level_in(f.get("shares"), who) == "edit"):
        raise QueryError(404, "There is no such folder (or it is not yours to put things in).")
    return f


def _visible(store, who: Who, id_: str, folders: dict | None = None) -> dict:
    row = store.get(id_)
    if row is None or not _can_see(row, who, folders if folders is not None else store.folders()):
        raise QueryError(404, "There is no such saved query (or it is not shared with you).")        # the same answer for both: do not reveal what exists
    return row


def _title(title) -> str:
    t = (title or "").strip()[:120]
    if not t:
        raise QueryError(422, "give the query a title")
    return t


def list_queries(store, who: Who) -> list[dict]:
    folders = store.folders()
    return [meta(r, who, folders) for r in store.list() if _can_see(r, who, folders)]


def create(store, who: Who, *, title, sql, description="", folder_id=None, shares=None) -> dict:
    try:
        sql = sqlcheck.check(sql)
    except sqlcheck.SqlRefused as e:
        raise QueryError(422, str(e)) from None
    folders = store.folders()
    if folder_id is not None:
        _folder_for_putting(folders, who, folder_id)
    if store.count_owned(who.name) >= MAX_QUERIES:
        raise QueryError(409, f"You can keep {MAX_QUERIES} saved queries; delete one first.")
    row = store.create(owner=who.name, title=_title(title), description=(description or "").strip()[:400], sql=sql, folder_id=folder_id, shares=_clean_shares(shares) if shares is not None else [])
    return meta(row, who, folders)


def get(store, who: Who, id_: str) -> dict:
    folders = store.folders()
    return meta(_visible(store, who, id_, folders), who, folders)


def update(store, who: Who, id_: str, *, title=None, description=None, sql=None, shares=UNSET, folder_id=UNSET, owner=UNSET) -> dict:
    folders = store.folders()
    row = _visible(store, who, id_, folders)
    manage = row["owner"] == who.name or who.role == "admin"
    if (title is not None or description is not None or sql is not None) and not _can_edit(row, who, folders):
        raise QueryError(403, "Only the owner, or someone it is shared with for editing, can change the query.")
    if (shares is not UNSET or folder_id is not UNSET or owner is not UNSET) and not manage:
        raise QueryError(403, "Only the owner can change how it is shared.")
    patch: dict = {}
    if title is not None:
        patch["title"] = _title(title)
    if description is not None:
        patch["description"] = description.strip()[:400]
    if sql is not None:
        try:
            patch["sql"] = sqlcheck.check(sql)
        except sqlcheck.SqlRefused as e:
            raise QueryError(422, str(e)) from None
    if shares is not UNSET:
        patch["shares"] = _clean_shares(shares)
    if folder_id is not UNSET:
        if folder_id is not None:
            _folder_for_putting(folders, who, folder_id)
        patch["folder_id"] = folder_id
    if owner is not UNSET:
        if not isinstance(owner, str) or not 0 < len(owner.strip()) <= 120:
            raise QueryError(422, "say who the new owner is")
        patch["owner"] = owner.strip()
    return meta(store.patch(id_, **patch) if patch else row, who, folders)


def delete(store, who: Who, id_: str) -> None:
    row = _visible(store, who, id_)
    if not (row["owner"] == who.name or who.role == "admin"):
        raise QueryError(403, "Only the owner can delete it.")
    store.delete(id_)


def transfer_all(store, who: Who, from_user: str, to_user: str) -> int:
    if who.role != "admin":
        raise QueryError(403, "Only an admin can hand over somebody's queries.")
    if not from_user.strip() or not to_user.strip():
        raise QueryError(422, "say from whom and to whom")
    return store.transfer(from_user.strip(), to_user.strip())


def snapshot_of(store, who: Who, id_: str) -> dict:
    """The person's OWN last result of this query (never anyone else's)."""
    _visible(store, who, id_)
    snap = store.snapshot(id_, who.name)
    if snap is None:
        raise QueryError(404, "There is no saved result of this query for you (it was never run, or it has expired).")
    return {"columns": snap["columns"], "rows": snap["rows"], "row_count": snap["row_count"], "truncated": snap["truncated"], "ms": snap["ms"], "created_at": snap["created_at"], "expires_at": snap["expires_at"]}


def list_folders(store, who: Who) -> list[dict]:
    """The dashboards' folders this person may put a query in or see one in: their own, those shared with them (can_edit says whether they may put things in), all of them for an admin."""
    out = []
    for f in store.folders().values():
        level = "edit" if f["owner"] == who.name or who.role == "admin" else _level_in(f.get("shares"), who)
        if level:
            out.append({"id": f["id"], "name": f["name"], "can_edit": level == "edit"})
    return sorted(out, key=lambda f: f["name"].lower())
