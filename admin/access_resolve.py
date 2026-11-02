"""Which cubes a person may NOT read because of datasets. The same file is in auth/, builder/ and admin/ (a test keeps the three identical).

A cube in at least one dataset is governed: readable only with a grant (to the person, one of their groups, or their role) on a dataset that contains it. Admins can read everything.
A cube in no dataset is not governed. So without datasets nothing is blocked, and a grant can only narrow what the role rules already allow.
"""
from __future__ import annotations


def blocked_cubes(datasets: list[dict], grants: list[dict], user: str, role: str, groups: list[str]) -> list[str]:
    """datasets: [{id, cubes}]; grants: [{object_id, principal_type, principal}] (dataset grants only). -> the governed cubes this person has no grant for."""
    if role == "admin":
        return []
    mine = {g["object_id"] for g in grants
            if (g["principal_type"] == "user" and g["principal"] == user) or (g["principal_type"] == "role" and g["principal"] == role)
            or (g["principal_type"] == "group" and g["principal"] in groups)}
    governed = {c for d in datasets for c in d["cubes"]}
    allowed = {c for d in datasets if d["id"] in mine for c in d["cubes"]}
    return sorted(governed - allowed)


def load(cur) -> tuple[list[dict], list[dict]]:
    """Read the datasets and their grants with a plain psycopg2 cursor (rows are tuples, columns selected by position)."""
    cur.execute("select id, cubes from access.dataset")
    datasets = [{"id": r[0], "cubes": list(r[1])} for r in cur.fetchall()]
    cur.execute("select object_id, principal_type, principal from access.\"grant\" where object_type = 'dataset'")
    grants = [{"object_id": r[0], "principal_type": r[1], "principal": r[2]} for r in cur.fetchall()]
    return datasets, grants
