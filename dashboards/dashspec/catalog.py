"""The catalog of Cube members a spec may use: read from the model files, or from a running Cube's /v1/meta."""
import json
import pathlib
import urllib.request

import yaml


class Catalog:
    """cubes: {cube: {"measures": {name: type}, "dimensions": {name: type}, "joins": set | None, "description": str, "docs": {name: str}}}.
    joins is None when the source does not say (Cube's /v1/meta), which turns the join check off. `docs` holds the description of each member."""

    def __init__(self, cubes, config=None):
        self.cubes = cubes
        self.config = config or {}              # what the model ships in model.config.yml (see PLAN-decouple.md)

    def year_fields(self):
        """The year fields a comparison with the previous year moves, from `time.year_fields` of the model's config: { "fiscal": [members], "calendar": [members] } (a key is left out
        when the model has none). A cube that `extends` the one that holds the field (a role of the calendar) has it too."""
        out = {}
        for kind, member in (self.config.get("time", {}).get("year_fields") or {}).items():
            cube, _, name = str(member).partition(".")
            roles = [c for c, v in self.cubes.items() if v.get("extends") == cube and name in v["dimensions"]]
            out[kind] = [str(member), *(f"{c}.{name}" for c in sorted(roles))]
        return out

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

    def extra(self, member):
        """What the compiled spec keeps about a member beyond its kind and type (a calculation: its formula); nothing for a model member."""
        return {}

    def label(self, member):
        """The name a report shows for a field of a role-playing cube ("Ship month name": the role in front); None when the cube has no role prefix, and the page makes the name itself."""
        cube, _, name = member.partition(".")
        prefix = self.cubes.get(cube, {}).get("label_prefix")
        return f"{prefix} {name.replace('_', ' ')}" if prefix and name else None

    def kind(self, cube):
        """"fact" or "dimension": what the model says in the cube's `meta.kind` ("dimension" when it says nothing)."""
        return "fact" if (self.cubes.get(cube) or {}).get("kind") == "fact" else "dimension"

    def facts(self):
        """The fact cubes, in name order."""
        return sorted(n for n in self.cubes if self.kind(n) == "fact")

    def series(self, cube):
        """How a fact is named when facts are shown side by side (`meta.series`), else None; and the theme colour it takes by default (`meta.color`)."""
        c = self.cubes.get(cube) or {}
        return c.get("series"), c.get("color")

    def measure_meta(self, member):
        """A measure's `meta` ({"format": "money", "primary": True}); {} when it has none."""
        cube, _, name = member.partition(".")
        return (self.cubes.get(cube) or {}).get("measure_meta", {}).get(name, {})

    def primary(self, cube):
        """The measure a KPI row or chart picks first (`meta.primary: true`), else the cube's first measure; None when it has none."""
        c = self.cubes.get(cube) or {}
        ranked = sorted((rank(m.get("primary")), n) for n, m in c.get("measure_meta", {}).items() if m.get("primary"))
        return (ranked[0][1] if ranked else (list(c.get("measures", {})) or [None])[0])

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


def rank(primary):
    """`primary: true` or `primary: 2`: the order a model prefers its measures in (true is 1)."""
    return 1 if primary is True else primary if isinstance(primary, (int, float)) else 1


def _cube_meta(meta, measures):
    """What the model says about a cube and its measures in `meta:` (the same keys whether read from the files or from /v1/meta): kind, series, color, and each measure's meta."""
    meta = meta or {}
    return {"kind": meta.get("kind"), "series": meta.get("series"), "color": meta.get("color"),
            "measure_meta": {m["name"].rpartition(".")[2]: dict(m["meta"]) for m in measures if m.get("meta")}}


def _by_name(base, own):
    """Members of a cube that `extends` another: the base's, then its own, an own member replacing the base's of the same name."""
    merged = {m["name"]: m for m in base}
    merged.update({m["name"]: m for m in own})
    return list(merged.values())


def _rollup_dimensions(name, cube):
    """Every dimension (cube.field) any pre-aggregation of the cube groups by; a field written bare or as CUBE.field is the cube's own."""
    out = set()
    for pa in cube.get("pre_aggregations") or []:
        for d in pa.get("dimensions") or []:
            d = str(d)
            out.add(f"{name}.{d.partition('.')[2]}" if d.startswith("CUBE.") else d if "." in d else f"{name}.{d}")
    return sorted(out)


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
            **_cube_meta(cube.get("meta"), measures),
            "rollup_dimensions": _rollup_dimensions(name, cube),          # the fields its pre-aggregations group by: a query by any other field reads the raw data
        }
    if not cubes:
        raise SystemExit(f"no cubes found under {model_dir}")
    config_file = pathlib.Path(model_dir).parent / "model.config.yml"          # the model's own settings sit beside its cube folder
    return Catalog(cubes, yaml.safe_load(config_file.read_text()) if config_file.exists() else None)


def from_cube(url, token):
    """Read a running Cube's catalog (GET <url>/cubejs-api/v1/meta). The token is a Cube JWT (never put it on the command line)."""
    req = urllib.request.Request(url.rstrip("/") + "/cubejs-api/v1/meta", headers={"Authorization": token})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (a URL the operator passed)
        return from_meta(json.load(r))


def from_meta(meta):
    """The catalog of a /v1/meta answer."""
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
            **_cube_meta(c.get("meta"), c["measures"]),
        }
    return Catalog(cubes)
