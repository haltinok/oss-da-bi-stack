"""Compile a validated spec to the JSON the renderer loads: the layout (or each tab's) as explicit rows, plus the type of every member used."""
import copy

from .calculations import with_calculations
from .crossfilter import expand


def _calculation_formats(panel, members):
    """A calculation's own `format` is the format wherever a panel uses it and does not say otherwise (a bar, a pie or a treemap has one format for its measure)."""
    fmt = lambda m: members.get(m, {}).get("format") if isinstance(m, str) and m.startswith("calc.") else None  # noqa: E731
    for key in ("measures", "series", "columns"):
        for item in panel.get(key, []) if isinstance(panel.get(key), list) else []:
            if isinstance(item, dict) and "format" not in item and fmt(item.get("member")):
                item["format"] = fmt(item["member"])
    if panel["type"] in ("bar", "pie", "treemap") and "format" not in panel:
        first = panel.get("measure") or (panel["stack"][0]["member"] if panel.get("stack") else None)
        if fmt(first):
            panel["format"] = fmt(first)


def compile_spec(spec, used, catalog=None):
    catalog = with_calculations(catalog, spec) if catalog is not None else None
    spec = expand(spec, used, catalog)            # `cross_filter` on a panel becomes filters and an `on_click` (dashspec/crossfilter.py)
    out = copy.deepcopy({k: v for k, v in spec.items() if k not in ("layout", "tabs")})
    for panel in out["panels"]:
        if panel["type"] == "table":     # every column as { member, label?, format? }, so the renderer reads one shape
            panel["columns"] = [{"member": col} if isinstance(col, str) else col for col in panel["columns"]]
        if panel["type"] == "pivot":     # every measure as { member, label?, format? }
            panel["measures"] = [{"member": m} if isinstance(m, str) else m for m in panel["measures"]]
    def rows(layout):                  # the rows as explicit cells, so the renderer reads one shape
        return [[{"panel": pid, "span": span} for cell in row for pid, span in cell.items()] for row in layout]

    if "tabs" in spec:                 # a tabbed file has `tabs` and no `layout`; the renderer treats a plain `layout` as one untitled tab
        out["tabs"] = [{"id": t["id"], "title": t["title"], "layout": rows(t["layout"])} for t in spec["tabs"]]
    else:
        out["layout"] = rows(spec["layout"])
    out["members"] = {m: used[m] for m in sorted(used)}
    for panel in out["panels"]:
        _calculation_formats(panel, out["members"])
    if catalog is not None:
        # a table that aggregates dimension fields needs to tell the rows of their cube apart: the cube's primary key (the renderer asks for it with those fields)
        keys = {}
        for p in spec["panels"]:
            if p["type"] == "table":
                for c in p["columns"]:
                    if isinstance(c, dict) and "aggregate" in c:
                        cube = c["member"].partition(".")[0]
                        pk = catalog.cubes.get(cube, {}).get("primary_key")
                        if pk:
                            keys[cube] = f"{cube}.{pk}"
        if keys:
            out["rowKeys"] = keys
    if catalog is not None:
        # which cubes each cube joins to: the renderer applies a drill-down's period only to panels that can reach the time dimension
        cubes = {m.partition(".")[0] for m in used if not m.startswith("calc.")} | {x.partition(".")[0] for u in used.values() for x in u.get("calc", {}).get("members", [])} | {spec["time"]["dimension"].partition(".")[0]} | {p["time_dimension"].partition(".")[0] for p in spec["panels"] if "time_dimension" in p}
        out["cubes"] = {c: {"joins": sorted(catalog.cubes[c]["joins"])} for c in sorted(cubes)
                        if c in catalog.cubes and catalog.cubes[c]["joins"] is not None}
    return out
