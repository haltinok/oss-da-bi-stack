"""The rules of saved dashboards: who may see, open, change, share and delete one, and what is checked when. The store (store.py) only stores.

- A dashboard is private to its owner until the owner shares it with some roles or with everyone. An admin can open and delete any (and change who it is shared with).
- The spec is validated when it is saved (for the owner's role) and again every time someone opens it, **for the opener's role**: sharing a dashboard with a role that cannot
  read one of its members does not leak anything, that role is told why it cannot open it. Cube's row-level security applies to what the opener sees, as on every dashboard.
- Only the owner changes the YAML.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from builder import changes, core
from builder.store import KEEP_VERSIONS, Limit, NotFound  # noqa: F401 (re-exported)

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


def _can_see(row: dict, who: Who) -> bool:
    return (row["owner"] == who.name or who.role == "admin" or row["visibility"] == "everyone"
            or (row["visibility"] == "roles" and who.role in row["shared_roles"]))


def _readable_for(row: dict, catalog, role: str) -> tuple[bool, list[str]]:
    key = (row["id"], row["version"], role)
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


def meta(row: dict, who: Who) -> dict:
    mine = row["owner"] == who.name
    return {"id": row["id"], "title": row["title"], "description": row["description"], "tags": tags_of(row), "owner": row["owner"], "owner_role": row["owner_role"], "visibility": row["visibility"],
            "shared_roles": row["shared_roles"], "version": row["version"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "mine": mine, "can_edit": mine, "can_manage": mine or who.role == "admin"}


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
    """The roles that can open this YAML (every member readable by them): shown to the owner who is about to share it."""
    return [r for r in core.ROLES if core.check_submission(yaml_text, catalog, r)[0] is not None]


def list_saved(store, catalog, who: Who, *, everything: bool = False) -> list[dict]:
    out = []
    for row in store.list():
        if not (_can_see(row, who) if not (everything and who.role == "admin") else True):
            continue
        item = meta(row, who)
        ok, problems = _readable_for(row, catalog, who.role)
        out.append({**item, "readable": ok, "problems": [] if ok else problems[:3]})
    return out


def save_new(store, catalog, who: Who, yaml_text: str, *, title=None, visibility="private", shared_roles=(), tags=None, max_saved=50) -> dict:
    """`tags` (a list, or None to keep what the YAML has) is written into the dashboard and checked with it."""
    visibility, roles = _clean_share(visibility, list(shared_roles))
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
    return {**meta(row, who), "readable_by": readable_by(row["yaml"], catalog)}


def _get_visible(store, who: Who, id_: str) -> dict:
    row = store.get(id_)
    if row is None or not _can_see(row, who):
        raise SavedError(404, "There is no such dashboard (or it is not shared with you).")     # the same answer for both: do not reveal what exists
    return row


def open_saved(store, catalog, who: Who, id_: str, version: int | None = None) -> dict:
    row = _get_visible(store, who, id_)
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
    out = {"meta": meta(row, who), "yaml": built["yaml"], "spec": built["spec"], "notes": built["notes"]}
    if row["owner"] == who.name or who.role == "admin":
        out["readable_by"] = readable_by(row["yaml"], catalog)
    return out


def update_saved(store, catalog, who: Who, id_: str, *, yaml_text=None, title=None, visibility=None, shared_roles=None, tags=None) -> dict:
    """`tags` (a list, or None to leave them) changes the tags of the saved YAML (or of `yaml_text`, when it is given): a change to the YAML, so the owner's
    alone and a new version; the same tags again are not a change."""
    row = _get_visible(store, who, id_)
    is_owner = row["owner"] == who.name
    if (yaml_text is not None or tags is not None) and not is_owner:
        raise SavedError(403, "Only the owner can change the dashboard.")
    if tags is not None:
        yaml_text = retag(yaml_text if yaml_text is not None else row["yaml"], tags)
    if (visibility is not None or shared_roles is not None or title is not None) and not (is_owner or who.role == "admin"):
        raise SavedError(403, "Only the owner can change how it is shared.")
    visibility, roles = _clean_share(visibility, shared_roles)
    if visibility is None and roles is not None:
        visibility = row["visibility"]
        if visibility == "roles" and not roles:
            raise SavedError(422, "choose at least one role to share with")
    built = _validate(yaml_text, catalog, who, tags_given=tags is not None) if yaml_text is not None else None
    new = store.update(id_, by=who.name, title=(title or None) and title.strip()[:120], description=(built["spec"].get("description") or "")[:300] if built else None,
                       yaml=built["yaml"] if built else None, visibility=visibility, shared_roles=roles, owner_role=who.role if built else None)
    return {**meta(new, who), "readable_by": readable_by(new["yaml"], catalog)}


def delete_saved(store, who: Who, id_: str) -> None:
    row = _get_visible(store, who, id_)
    if not (row["owner"] == who.name or who.role == "admin"):
        raise SavedError(403, "Only the owner can delete it.")
    store.delete(id_)


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
