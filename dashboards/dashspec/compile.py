"""Compile a validated spec to the JSON the renderer loads: the layout (or each tab's) as explicit rows, plus the type of every member used."""
import copy

from .crossfilter import expand


def compile_spec(spec, used, catalog=None):
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
        cubes = {m.partition(".")[0] for m in used} | {spec["time"]["dimension"].partition(".")[0]}
        out["cubes"] = {c: {"joins": sorted(catalog.cubes[c]["joins"])} for c in sorted(cubes)
                        if c in catalog.cubes and catalog.cubes[c]["joins"] is not None}
    return out
