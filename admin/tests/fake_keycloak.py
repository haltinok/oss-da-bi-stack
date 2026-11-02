"""An in-memory stand-in for keycloak.Keycloak: users, realm roles and groups, with the same method names and the same refusals for what the tests care about."""
from __future__ import annotations

import itertools

from keycloak import KeycloakError


class FakeKeycloak:
    def __init__(self):
        self.n = itertools.count(1)
        self.users_: dict[str, dict] = {}
        self.roles_: dict[str, set[str]] = {r: set() for r in ("admin", "manager", "rep", "purchasing", "marketing", "agent")}
        self.groups_: dict[str, dict] = {}
        self.passwords: dict[str, tuple[str, bool]] = {}
        self.emailed: list[str] = []
        self.logged_out: list[str] = []

    def add(self, username, role=None, enabled=True, **extra) -> str:
        uid = f"u{next(self.n)}"
        self.users_[uid] = {"id": uid, "username": username, "enabled": enabled, **extra}
        if role:
            self.roles_[role].add(uid)
        return uid

    # users
    def users(self, search="", enabled=None, limit=1000):
        return [dict(u) for u in self.users_.values() if (not search or search.lower() in u["username"].lower() or search.lower() in u.get("email", "").lower())
                and (enabled is None or u["enabled"] == enabled)][:limit]

    def user(self, uid):
        if uid not in self.users_:
            raise KeycloakError(404, "User not found")
        return dict(self.users_[uid])

    def create_user(self, rep):
        if any(u["username"] == rep["username"] for u in self.users_.values()):
            raise KeycloakError(409, "User exists with same username")
        uid = self.add(rep["username"], email=rep.get("email") or "", firstName=rep.get("firstName", ""), lastName=rep.get("lastName", ""), enabled=rep.get("enabled", True))
        return uid

    def update_user(self, uid, rep):
        self.user(uid)
        self.users_[uid] = {**rep, "id": uid}

    def delete_user(self, uid):
        self.user(uid)
        del self.users_[uid]
        for s in self.roles_.values():
            s.discard(uid)
        for g in self.groups_.values():
            g["members"].discard(uid)

    def logout(self, uid):
        self.logged_out.append(uid)

    def set_password(self, uid, password, temporary):
        self.user(uid)
        self.passwords[uid] = (password, temporary)

    def email_update_password(self, uid):
        self.emailed.append(uid)

    # roles
    def role(self, name):
        return {"name": name}

    def role_members(self, name):
        return [dict(self.users_[u]) for u in self.roles_[name] if u in self.users_]

    def add_role(self, uid, name):
        self.roles_[name].add(uid)

    def remove_role(self, uid, name):
        self.roles_[name].discard(uid)

    # groups
    def groups(self):
        return [{"id": g["id"], "name": g["name"]} for g in self.groups_.values()]

    def group_members(self, gid):
        return [dict(self.users_[u]) for u in self.groups_[gid]["members"] if u in self.users_]

    def create_group(self, name):
        if any(g["name"] == name for g in self.groups_.values()):
            raise KeycloakError(409, "Top level group named '%s' already exists." % name)
        gid = f"g{next(self.n)}"
        self.groups_[gid] = {"id": gid, "name": name, "members": set()}
        return gid

    def rename_group(self, gid, name):
        self.groups_[gid]["name"] = name

    def delete_group(self, gid):
        if gid not in self.groups_:
            raise KeycloakError(404, "Could not find group by id")
        del self.groups_[gid]

    def add_to_group(self, uid, gid):
        self.groups_[gid]["members"].add(uid)

    def remove_from_group(self, uid, gid):
        self.groups_[gid]["members"].discard(uid)
