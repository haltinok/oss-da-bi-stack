"""Which cubes a person may NOT read because of datasets. The same file is in auth/, builder/ and admin/ (a test keeps the three identical).

A cube in at least one dataset is governed: readable only with a grant (to the person, one of their groups, or their role) on a dataset that contains it. Admins can read everything.
A cube in no dataset is not governed. So without datasets nothing is blocked, and a grant can only narrow what the role rules already allow.
"""
from __future__ import annotations


def _mine(grants: list[dict], user: str, role: str, groups: list[str]) -> set[str]:
    return {g["object_id"] for g in grants
            if (g["principal_type"] == "user" and g["principal"] == user) or (g["principal_type"] == "role" and g["principal"] == role)
            or (g["principal_type"] == "group" and g["principal"] in groups)}


def blocked_cubes(datasets: list[dict], grants: list[dict], user: str, role: str, groups: list[str]) -> list[str]:
    """datasets: [{id, cubes, members?}]; grants: [{object_id, principal_type, principal}] (dataset grants only). -> the governed cubes this person has no grant for."""
    if role == "admin":
        return []
    mine = _mine(grants, user, role, groups)
    governed = {c for d in datasets for c in d["cubes"]}
    allowed = {c for d in datasets if d["id"] in mine for c in d["cubes"]}
    return sorted(governed - allowed)


def blocked_members(datasets: list[dict], grants: list[dict], user: str, role: str, groups: list[str]) -> list[str]:
    """The governed single fields (cube.member) this person has no grant for: a field in a dataset needs a grant on a dataset that holds it, whether or not its cube is open."""
    if role == "admin":
        return []
    mine = _mine(grants, user, role, groups)
    governed = {m for d in datasets for m in d.get("members", [])}
    allowed = {m for d in datasets if d["id"] in mine for m in d.get("members", [])}
    return sorted(governed - allowed)


def load(cur) -> tuple[list[dict], list[dict]]:
    """Read the datasets and their grants with a plain psycopg2 cursor (rows are tuples, columns selected by position)."""
    cur.execute("select id, cubes, members from access.dataset")
    datasets = [{"id": r[0], "cubes": list(r[1]), "members": list(r[2])} for r in cur.fetchall()]
    cur.execute("select object_id, principal_type, principal, permission from access.\"grant\" where object_type = 'dataset'")
    grants = [{"object_id": r[0], "principal_type": r[1], "principal": r[2], "permission": r[3]} for r in cur.fetchall()]
    return datasets, grants

def lab_allowed(grants: list[dict], user: str, role: str, groups: list[str]) -> bool:
    """May this person use the SQL lab? Admins always; anyone else needs a grant with permission `lab` (to them, one of their groups, or their role) on any dataset.
    What they can read in the lab is exactly what the dashboards let them read: the lab runs through Cube, which applies the role rules, territories and blocked cubes."""
    if role == "admin":
        return True
    if role == "viewer":                                         # a viewer only views dashboards: no SQL lab, whatever they are granted
        return False
    return any(g.get("permission") == "lab" and ((g["principal_type"] == "user" and g["principal"] == user) or (g["principal_type"] == "role" and g["principal"] == role)
                                                  or (g["principal_type"] == "group" and g["principal"] in groups)) for g in grants)
