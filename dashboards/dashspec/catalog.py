"""The catalog of Cube members a spec may use: read from the model files, or from a running Cube's /v1/meta."""
import json
import pathlib
import urllib.request

import yaml


class Catalog:
    """cubes: {cube: {"measures": {name: type}, "dimensions": {name: type}, "joins": set | None, "description": str, "docs": {name: str}}}.
    joins is None when the source does not say (Cube's /v1/meta), which turns the join check off. `docs` holds the description of each member."""

    def __init__(self, cubes):
        self.cubes = cubes

    def lookup(self, member):
        """-> (kind, type) for 'cube.name', or None when the cube or the member does not exist."""
        cube, _, name = member.partition(".")
        c = self.cubes.get(cube)
        if c is None:
            return None
        if name in c["measures"]:
            return "measure", c["measures"][name]
        if name in c["dimensions"]:
            return "dimension", c["dimensions"][name]
        return None

    def sort_by(self, member):
        """The dimension (as 'cube.name') a text dimension is sorted by, from its `meta.sort_by` in the Cube model; None for most."""
        cube, _, name = member.partition(".")
        key = self.cubes.get(cube, {}).get("sort_by", {}).get(name)
        return f"{cube}.{key}" if key else None

    def reachable(self, src, dst):
        """Can a query on cube `src` use dimensions of cube `dst`? Cube follows join paths, so this is graph reachability."""
        if src == dst or self.cubes.get(src, {}).get("joins") is None:
            return True
        seen, todo = {src}, [src]
        while todo:
            for nxt in self.cubes.get(todo.pop(), {}).get("joins") or ():
                if nxt == dst:
                    return True
                if nxt not in seen and nxt in self.cubes:
                    seen.add(nxt)
                    todo.append(nxt)
        return False

    def suggest(self, member):
        """A hint for an unknown member: the members of that cube, or the cubes that exist."""
        cube = member.partition(".")[0]
        c = self.cubes.get(cube)
        if c is None:
            return f"cubes: {', '.join(sorted(self.cubes))}"
        return f"{cube} has: {', '.join(sorted([*c['measures'], *c['dimensions']]))}"


def from_model(model_dir):
    """Read every cube in a Cube model directory (cube/model). Only names, types and joins are needed, so the SQL is ignored."""
    cubes = {}
    for path in sorted(pathlib.Path(model_dir).rglob("*.y*ml")):
        for cube in (yaml.safe_load(path.read_text()) or {}).get("cubes", []):
            members = [*cube.get("measures", []), *cube.get("dimensions", [])]
            cubes[cube["name"]] = {
                "measures": {m["name"]: m["type"] for m in cube.get("measures", [])},
                "dimensions": {d["name"]: d["type"] for d in cube.get("dimensions", [])},
                "joins": {j["name"] for j in cube.get("joins", [])},
                "primary_key": next((d["name"] for d in cube.get("dimensions", []) if d.get("primary_key")), None),         # what tells one row of the cube from another
                "sort_by": {d["name"]: d["meta"]["sort_by"] for d in cube.get("dimensions", []) if (d.get("meta") or {}).get("sort_by")},          # a text dimension that sorts by another (month name by month number)
                "description": cube.get("description", ""),
                "docs": {m["name"]: m["description"] for m in members if m.get("description")},
            }
    if not cubes:
        raise SystemExit(f"no cubes found under {model_dir}")
    return Catalog(cubes)


def from_cube(url, token):
    """Read a running Cube's catalog (GET <url>/cubejs-api/v1/meta). The token is a Cube JWT (never put it on the command line)."""
    req = urllib.request.Request(url.rstrip("/") + "/cubejs-api/v1/meta", headers={"Authorization": token})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (a URL the operator passed)
        meta = json.load(r)
    cubes = {}
    for c in meta["cubes"]:
        short = lambda m: m["name"].partition(".")[2]  # noqa: E731
        cubes[c["name"]] = {
            "measures": {short(m): m["type"] for m in c["measures"]},
            "dimensions": {short(d): d["type"] for d in c["dimensions"]},
            "joins": None,
            "primary_key": next((short(d) for d in c["dimensions"] if d.get("primaryKey")), None),
            "sort_by": {short(d): d["meta"]["sort_by"] for d in c["dimensions"] if (d.get("meta") or {}).get("sort_by")},
            "description": c.get("description", ""),
            "docs": {short(m): m["description"] for m in [*c["measures"], *c["dimensions"]] if m.get("description")},
        }
    return Catalog(cubes)
