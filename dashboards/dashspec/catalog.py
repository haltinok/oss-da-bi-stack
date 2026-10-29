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

    def label(self, member):
        """The name a report shows for a field of a role-playing cube ("Ship month name": the role in front); None when the cube has no role prefix, and the page makes the name itself."""
        cube, _, name = member.partition(".")
        prefix = self.cubes.get(cube, {}).get("label_prefix")
        return f"{prefix} {name.replace('_', ' ')}" if prefix and name else None

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


def sort_by_problems(catalog):
    """What is wrong with the `meta.sort_by` declarations of a model: the sort field must be another dimension of the same cube, a number or a time (something that orders),
    and must not itself sort by another field (no chains). Returns [message]."""
    out = []
    for cube, c in sorted(catalog.cubes.items()):
        for name, key in sorted(c.get("sort_by", {}).items()):
            where = f"{cube}.{name}: sort_by '{key}'"
            if key == name:
                out.append(f"{where} is the field itself")
            elif key not in c["dimensions"]:
                out.append(f"{where} is not a dimension of the cube {cube}")
            elif c["dimensions"][key] not in ("number", "time"):
                out.append(f"{where} is a {c['dimensions'][key]} dimension; it must be a number or a time to order by")
            elif key in c["sort_by"]:
                out.append(f"{where} itself sorts by '{c['sort_by'][key]}': no chains")
    return out


def _by_name(base, own):
    """Members of a cube that `extends` another: the base's, then its own, an own member replacing the base's of the same name."""
    merged = {m["name"]: m for m in base}
    merged.update({m["name"]: m for m in own})
    return list(merged.values())


def from_model(model_dir):
    """Read every cube in a Cube model directory (cube/model). Only names, types and joins are needed, so the SQL is ignored.
    A cube that `extends` another (a role of the date dimension: `ship_dates` extends `dates`) has the base's members, joins and key as well as its own."""
    raw = {}
    for path in sorted(pathlib.Path(model_dir).rglob("*.y*ml")):
        for cube in (yaml.safe_load(path.read_text()) or {}).get("cubes", []):
            raw[cube["name"]] = cube
    cubes = {}
    for name, cube in raw.items():
        base = raw.get(cube.get("extends"), {})
        measures = _by_name(base.get("measures", []), cube.get("measures", []))
        dimensions = _by_name(base.get("dimensions", []), cube.get("dimensions", []))
        members = [*measures, *dimensions]
        cubes[name] = {
            "measures": {m["name"]: m["type"] for m in measures},
            "dimensions": {d["name"]: d["type"] for d in dimensions},
            "joins": {j["name"] for j in [*base.get("joins", []), *cube.get("joins", [])]},
            "primary_key": next((d["name"] for d in dimensions if d.get("primary_key")), None),         # what tells one row of the cube from another
            "sort_by": {d["name"]: d["meta"]["sort_by"] for d in dimensions if (d.get("meta") or {}).get("sort_by")},          # a text dimension that sorts by another (month name by month number)
            "label_prefix": (cube.get("meta") or {}).get("label_prefix"),                                                      # the role of a role-playing cube ("Ship"), put in front of its fields' names
            "extends": cube.get("extends"),
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
            "label_prefix": (c.get("meta") or {}).get("label_prefix"),
            "extends": None,
            "description": c.get("description", ""),
            "docs": {short(m): m["description"] for m in [*c["measures"], *c["dimensions"]] if m.get("description")},
        }
    return Catalog(cubes)
