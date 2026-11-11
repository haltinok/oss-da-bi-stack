"""The rules of saved dashboards: who may see, open, change, share and delete one, and what is checked when. The store (store.py) only stores.

- A dashboard is private to its owner until the owner shares it with some roles, with everyone, or with named people and groups (view or edit). It can live in a folder, and
  a folder can be shared the same way (what is in it follows). An admin can open and delete any (and change who it is shared with). Delete moves it to a trash (30 days).
- The spec is validated when it is saved (for the owner's role) and again every time someone opens it, **for the opener's role**: sharing a dashboard with a role that cannot
  read one of its members does not leak anything, that role is told why it cannot open it. Cube's row-level security applies to what the opener sees, as on every dashboard.
- Only the owner, or someone it is shared with for **edit**, changes the YAML; only the owner (or an admin) changes how it is shared, moves it, or hands it to someone else.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from builder import changes, core
from builder.store import KEEP_VERSIONS, TRASH_DAYS, Limit, NotFound  # noqa: F401 (re-exported)

VISIBILITIES = ("private", "roles", "everyone")
_readable: dict[tuple, tuple[bool, list[str]]] = {}
_tags: dict[tuple, list[str]] = {}


@dataclass
class SavedError(Exception):
    status: int
    message: str
    problems: list[str] = field(default_factory=list)


@dataclass
class Who:
    name: str
    role: str
    groups: list[str] = field(default_factory=list)


UNSET = object()                                              # "not given", as opposed to None ("no folder")
SHARE_TYPES = ("user", "group")
SHARE_PERMISSIONS = ("view", "edit")
MAX_SHARES = 50
MAX_FOLDERS = 50                                             # per owner


def _level_in(shares, who: Who) -> str | None:
    """The best permission `shares` gives this person (directly or through a group): "edit", "view" or None."""
    best = None
    for sh in shares or []:
        if (sh["type"] == "user" and sh["principal"] == who.name) or (sh["type"] == "group" and sh["principal"] in who.groups):
            if sh["permission"] == "edit":
                return "edit"
            best = "view"
    return best


def _level(row: dict, who: Who, folders: dict) -> str | None:
    """What the dashboard's own shares and its folder's shares give this person (the owner and admins are handled by the callers)."""
    levels = {_level_in(row.get("shares"), who), _level_in((folders.get(row.get("folder_id")) or {}).get("shares"), who)}
    return "edit" if "edit" in levels else "view" if "view" in levels else None


def _folders(store) -> dict:
    return {f["id"]: f for f in store.folders()}


def _clean_shares(shares) -> list[dict]:
    if not isinstance(shares, list) or len(shares) > MAX_SHARES:
        raise SavedError(422, f"share with at most {MAX_SHARES} people and groups")
    best: dict[tuple, str] = {}
    for sh in shares:
        if not isinstance(sh, dict) or sh.get("type") not in SHARE_TYPES or sh.get("permission") not in SHARE_PERMISSIONS \
                or not isinstance(sh.get("principal"), str) or not 0 < len(sh["principal"].strip()) <= 120:
            raise SavedError(422, "a share is a person or a group with view or edit")
        key = (sh["type"], sh["principal"].strip())
        if best.get(key) != "edit":
            best[key] = sh["permission"]
    return [{"type": t, "principal": p, "permission": perm} for (t, p), perm in sorted(best.items())]


def _can_see(row: dict, who: Who, folders: dict | None = None) -> bool:
    return (row["owner"] == who.name or who.role == "admin" or row["visibility"] == "everyone"
            or (row["visibility"] == "roles" and who.role in row["shared_roles"]) or _level(row, who, folders or {}) is not None)


def _can_edit(row: dict, who: Who, folders: dict) -> bool:
    return row["owner"] == who.name or _level(row, who, folders) == "edit"


def _readable_for(row: dict, catalog, role: str) -> tuple[bool, list[str]]:
    key = (row["id"], row["version"], role, tuple(sorted(catalog.cubes)))              # the cubes the opener may read are part of the answer (datasets)
    if key not in _readable:
        if len(_readable) > 5000:
            _readable.clear()
        built, problems = core.check_submission(row["yaml"], catalog, role)
        _readable[key] = (built is not None, problems)
    return _readable[key]


def tags_of(row: dict) -> list[str]:
    """The tags of a saved dashboard, read from its YAML (cached by id and version, like the readability check). They are metadata, not data, so a
    dashboard the viewer's role cannot open still shows them. Anything odd gives fewer tags or none, never an error in a list."""
    key = (row["id"], row["version"])
    if key not in _tags:
        if len(_tags) > 5000:
            _tags.clear()
        try:
            raw = (yaml.safe_load(row["yaml"]) or {}).get("tags", [])
        except (yaml.YAMLError, AttributeError):
            raw = []
        _tags[key] = [t for t in raw if isinstance(t, str) and 0 < len(t) <= 24][:5] if isinstance(raw, list) else []
    return list(_tags[key])


_models: dict = {}


def model_of(row: dict) -> str | None:
    """The model a saved dashboard says it is for (its YAML's `model:`; None: the default model), cached by id and version like the tags."""
    key = (row["id"], row["version"])
    if key not in _models:
        if len(_models) > 5000:
            _models.clear()
        try:
            named = (yaml.safe_load(row["yaml"]) or {}).get("model")
        except (yaml.YAMLError, AttributeError):
            named = None
        _models[key] = named if isinstance(named, str) else None
    return _models[key]


def meta(row: dict, who: Who, folders: dict | None = None) -> dict:
    folders = folders or {}
    mine = row["owner"] == who.name
    manage = mine or who.role == "admin"
    folder = folders.get(row.get("folder_id"))
    out = {"id": row["id"], "title": row["title"], "description": row["description"], "tags": tags_of(row), "model": model_of(row), "owner": row["owner"], "owner_role": row["owner_role"], "visibility": row["visibility"],
           "shared_roles": row["shared_roles"], "version": row["version"], "created_at": row["created_at"], "updated_at": row["updated_at"],
           "mine": mine, "can_edit": _can_edit(row, who, folders), "can_manage": manage, "folder_id": row.get("folder_id") if folder else None,
           "folder_name": folder["name"] if folder else None, "shared_with_me": not mine and _level(row, who, folders) is not None}
    if manage:
        out["shares"] = row.get("shares") or []                    # who it is shared with is for the owner and admins to see
    if row.get("deleted_at"):
        out["deleted_at"] = row["deleted_at"]
    return out


def _clean_share(visibility: str | None, shared_roles) -> tuple[str | None, list[str] | None]:
    if visibility is not None and visibility not in VISIBILITIES:
        raise SavedError(422, f"visibility must be one of {', '.join(VISIBILITIES)}")
    roles = None if shared_roles is None else sorted({r for r in shared_roles})
    if roles is not None and any(r not in core.ROLES for r in roles):
        raise SavedError(422, f"roles must be among {', '.join(core.ROLES)}")
    if visibility == "everyone":
        roles = []
    if visibility == "roles" and not roles:
        raise SavedError(422, "choose at least one role to share with")
    return visibility, roles


def _validate(yaml_text: str, catalog, who: Who, *, tags_given: bool = False) -> dict:
    built, problems = core.check_submission(yaml_text, catalog, who.role)
    if built is None:
        only_tags = tags_given and problems and all(p.startswith("dashboard: tags") for p in problems)
        raise SavedError(422, "Those tags are not valid." if only_tags else "The dashboard is not valid for your role.", problems)
    return built


def retag(yaml_text: str, tags: list[str]) -> str:
    """The YAML with its `tags` set to `tags` (none removes the key): the page's Tags field is applied here, on the server, so the same validator that
    checks every other field checks the tags, the page never edits YAML text, and a bad tag is refused before anything is stored. Tags go after the
    description (or the title). The text is returned untouched when it is not a mapping (the validator then says what is wrong) or when the tags are
    already these, so asking for the tags a dashboard has is not a change."""
    try:
        spec = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return yaml_text
    if not isinstance(spec, dict) or spec.get("tags", []) == list(tags):
        return yaml_text
    anchor = "description" if "description" in spec else "title"
    out: dict = {}
    for key, value in spec.items():
        if key == "tags":
            continue
        out[key] = value
        if key == anchor and tags:
            out["tags"] = list(tags)
    if tags and "tags" not in out:
        out["tags"] = list(tags)
    return yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=140)


def readable_by(yaml_text: str, catalog) -> list[str]:
    """The roles that can open this YAML. A role no longer decides what data a person may read (datasets, grants and rules do, per person), so every role can open it; what a given
    reader may not read shows as Cube's refusal in that panel, or as 'your role cannot open this one' when the spec is checked against their own catalog."""
    return list(core.ROLES)


def list_saved(store, catalog, who: Who, *, everything: bool = False) -> list[dict]:
    out = []
    folders = _folders(store)
    for row in store.list():
        if not (_can_see(row, who, folders) if not (everything and who.role == "admin") else True):
            continue
        item = meta(row, who, folders)
        ok, problems = _readable_for(row, catalog, who.role)
        out.append({**item, "readable": ok, "problems": [] if ok else problems[:3]})
    return out


def save_new(store, catalog, who: Who, yaml_text: str, *, title=None, visibility="private", shared_roles=(), tags=None, max_saved=50, folder_id=None, shares=None) -> dict:
    """`tags` (a list, or None to keep what the YAML has) is written into the dashboard and checked with it."""
    visibility, roles = _clean_share(visibility, list(shared_roles))
    clean = _clean_shares(shares) if shares is not None else []
    folders = _folders(store)
    if folder_id is not None:
        _folder_for_putting(folders, who, folder_id)
    if tags is not None:
        yaml_text = retag(yaml_text, tags)
    built = _validate(yaml_text, catalog, who, tags_given=tags is not None)
    spec = built["spec"]
    name = (title or spec["title"]).strip()[:120] or "Untitled"
    try:
        row = store.create(owner=who.name, owner_role=who.role, title=name, description=(spec.get("description") or "")[:300], yaml=built["yaml"], visibility=visibility or "private",
                           shared_roles=roles or [], max_saved=max_saved)
    except Limit as e:
        raise SavedError(409, str(e)) from None
    if clean or folder_id is not None:
        row = store.patch(row["id"], shares=clean, folder_id=folder_id)
    return {**meta(row, who, folders), "readable_by": readable_by(row["yaml"], catalog)}


def _folder_for_putting(folders: dict, who: Who, folder_id: str) -> dict:
    """A folder a dashboard may be put in: the person's own, one shared with them for edit, or any for an admin."""
    f = folders.get(folder_id)
    if f is None or not (f["owner"] == who.name or who.role == "admin" or _level_in(f.get("shares"), who) == "edit"):
        raise SavedError(404, "There is no such folder (or it is not yours to put things in).")
    return f


def _get_visible(store, who: Who, id_: str, folders: dict | None = None) -> dict:
    row = store.get(id_)
    if row is None or row.get("deleted_at") or not _can_see(row, who, folders if folders is not None else _folders(store)):
        raise SavedError(404, "There is no such dashboard (or it is not shared with you).")     # the same answer for both: do not reveal what exists
    return row


def open_saved(store, catalog, who: Who, id_: str, version: int | None = None) -> dict:
    folders = _folders(store)
    row = _get_visible(store, who, id_, folders)
    if version is not None:
        if row["owner"] != who.name:
            raise SavedError(403, "Only the owner can open earlier versions.")
        old = store.get_version(id_, version)
        if old is None:
            raise SavedError(404, f"There is no version {version} (the last {KEEP_VERSIONS} are kept).")
        row = {**row, "yaml": old["yaml"], "title": old["title"], "version": old["version"]}
    built, problems = core.check_submission(row["yaml"], catalog, who.role)            # for the opener's role, every time
    if built is None:
        raise SavedError(422, "Your role cannot open this dashboard.", problems)
    out = {"meta": meta(row, who, folders), "yaml": built["yaml"], "spec": built["spec"], "notes": built["notes"]}
    if row["owner"] == who.name or who.role == "admin":
        out["readable_by"] = readable_by(row["yaml"], catalog)
    return out


def update_saved(store, catalog, who: Who, id_: str, *, yaml_text=None, title=None, visibility=None, shared_roles=None, tags=None, shares=UNSET, folder_id=UNSET, owner=UNSET) -> dict:
    """`tags` (a list, or None to leave them) changes the tags of the saved YAML (or of `yaml_text`, when it is given): a change to the YAML, so a new version; the same tags again are not a change.
    The YAML and the title are for the owner and anyone it is shared with for edit; how it is shared, which folder it is in and who owns it are for the owner and admins."""
    folders = _folders(store)
    row = _get_visible(store, who, id_, folders)
    is_owner = row["owner"] == who.name
    can_edit = _can_edit(row, who, folders)
    manage = is_owner or who.role == "admin"
    if (yaml_text is not None or tags is not None) and not can_edit:
        raise SavedError(403, "Only the owner, or someone it is shared with for editing, can change the dashboard.")
    if tags is not None:
        yaml_text = retag(yaml_text if yaml_text is not None else row["yaml"], tags)
    if title is not None and not (manage or can_edit):
        raise SavedError(403, "Only the owner can rename it.")
    if (visibility is not None or shared_roles is not None or shares is not UNSET or folder_id is not UNSET or owner is not UNSET) and not manage:
        raise SavedError(403, "Only the owner can change how it is shared.")
    visibility, roles = _clean_share(visibility, shared_roles)
    if visibility is None and roles is not None:
        visibility = row["visibility"]
        if visibility == "roles" and not roles:
            raise SavedError(422, "choose at least one role to share with")
    built = _validate(yaml_text, catalog, who, tags_given=tags is not None) if yaml_text is not None else None
    patch: dict = {}
    if shares is not UNSET:
        patch["shares"] = _clean_shares(shares)
    if folder_id is not UNSET:
        if folder_id is not None:
            _folder_for_putting(folders, who, folder_id)
        patch["folder_id"] = folder_id
    if owner is not UNSET:
        if not isinstance(owner, str) or not 0 < len(owner.strip()) <= 120:
            raise SavedError(422, "say who the new owner is")
        patch["owner"] = owner.strip()
    new = store.update(id_, by=who.name, title=(title or None) and title.strip()[:120], description=(built["spec"].get("description") or "")[:300] if built else None,
                       yaml=built["yaml"] if built else None, visibility=visibility, shared_roles=roles, owner_role=who.role if built and is_owner else None)
    if patch:
        new = store.patch(id_, **patch)
    return {**meta(new, who, folders), "readable_by": readable_by(new["yaml"], catalog)}


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def delete_saved(store, who: Who, id_: str) -> None:
    """Moves it to the trash (kept 30 days: list_trash, restore_trash, delete_forever)."""
    row = _get_visible(store, who, id_)
    if not (row["owner"] == who.name or who.role == "admin"):
        raise SavedError(403, "Only the owner can delete it.")
    store.patch(id_, deleted_at=_now_iso())


def list_trash(store, catalog, who: Who) -> list[dict]:
    import datetime
    store.purge((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=TRASH_DAYS)).isoformat(timespec="seconds"))
    return [meta(r, who) for r in store.list(deleted=True) if r["owner"] == who.name or who.role == "admin"]


def _get_trashed(store, who: Who, id_: str) -> dict:
    row = store.get(id_)
    if row is None or not row.get("deleted_at") or not (row["owner"] == who.name or who.role == "admin"):
        raise SavedError(404, "There is nothing like that in the trash.")
    return row


def restore_trash(store, who: Who, id_: str) -> dict:
    row = _get_trashed(store, who, id_)
    return meta(store.patch(row["id"], deleted_at=None), who, _folders(store))


def delete_forever(store, who: Who, id_: str) -> None:
    row = _get_trashed(store, who, id_)
    store.delete(row["id"])


def transfer_all(store, who: Who, from_user: str, to_user: str) -> int:
    """Hands every dashboard (and trashed one) of a person to another: for an admin who is about to delete the person."""
    if who.role != "admin":
        raise SavedError(403, "Only an admin can hand over somebody's dashboards.")
    if not from_user.strip() or not to_user.strip():
        raise SavedError(422, "say from whom and to whom")
    return store.transfer(from_user.strip(), to_user.strip())


# ------------------------------------------------------------------------------------------------------------------ folders
def folder_meta(f: dict, who: Who) -> dict:
    mine = f["owner"] == who.name
    manage = mine or who.role == "admin"
    out = {"id": f["id"], "name": f["name"], "owner": f["owner"], "mine": mine, "can_manage": manage, "can_edit": manage or _level_in(f.get("shares"), who) == "edit"}
    if manage:
        out["shares"] = f.get("shares") or []
    return out


def list_folders(store, who: Who) -> list[dict]:
    return [folder_meta(f, who) for f in store.folders() if f["owner"] == who.name or who.role == "admin" or _level_in(f.get("shares"), who) is not None]


def create_folder(store, who: Who, name: str) -> dict:
    name = (name or "").strip()[:80]
    if not name:
        raise SavedError(422, "give the folder a name")
    if sum(1 for f in store.folders() if f["owner"] == who.name) >= MAX_FOLDERS:
        raise SavedError(409, f"You can keep {MAX_FOLDERS} folders; delete one first.")
    return folder_meta(store.create_folder(owner=who.name, name=name), who)


def _own_folder(store, who: Who, id_: str) -> dict:
    f = store.folder(id_)
    if f is None or not (f["owner"] == who.name or who.role == "admin" or _level_in(f.get("shares"), who) is not None):
        raise SavedError(404, "There is no such folder (or it is not shared with you).")
    if not (f["owner"] == who.name or who.role == "admin"):
        raise SavedError(403, "Only the owner of a folder can change it.")
    return f


def update_folder(store, who: Who, id_: str, *, name=None, shares=UNSET) -> dict:
    _own_folder(store, who, id_)
    clean = _clean_shares(shares) if shares is not UNSET else None
    new_name = None
    if name is not None:
        new_name = name.strip()[:80]
        if not new_name:
            raise SavedError(422, "give the folder a name")
    return folder_meta(store.patch_folder(id_, name=new_name, shares=clean), who)


def delete_folder(store, who: Who, id_: str) -> None:
    """What was in it stays, outside any folder."""
    _own_folder(store, who, id_)
    store.delete_folder(id_)
def versions(store, who: Who, id_: str) -> list[dict]:
    """The kept versions, newest first, each with `changes` (see changes.py): what it did to the version before it."""
    row = _get_visible(store, who, id_)
    if row["owner"] != who.name:
        raise SavedError(403, "Only the owner can see earlier versions.")
    out = store.list_versions(id_)
    yamls = {v["version"]: (store.get_version(id_, v["version"]) or {}).get("yaml") for v in out}
    for v in out:
        new = yamls.get(v["version"])
        before = yamls.get(v["version"] - 1)
        v["changes"] = changes.describe(before, new) if new and (before or v["version"] == 1) else [{"kind": "unknown"}]       # an older version that is no longer kept has no "before"
    return out


def restore(store, catalog, who: Who, id_: str, version: int) -> dict:
    row = _get_visible(store, who, id_)
    if row["owner"] != who.name:
        raise SavedError(403, "Only the owner can restore a version.")
    old = store.get_version(id_, version)
    if old is None:
        raise SavedError(404, f"There is no version {version} (the last {KEEP_VERSIONS} are kept).")
    return update_saved(store, catalog, who, id_, yaml_text=old["yaml"])
