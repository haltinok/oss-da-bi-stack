"""Compile a validated spec to the JSON the renderer loads: the layout as explicit rows, plus the type of every member used."""
import copy


def compile_spec(spec, used, catalog=None):
    out = copy.deepcopy({k: v for k, v in spec.items() if k != "layout"})
    for panel in out["panels"]:
        if panel["type"] == "table":     # every column as { member, label?, format? }, so the renderer reads one shape
            panel["columns"] = [{"member": col} if isinstance(col, str) else col for col in panel["columns"]]
    out["layout"] = [[{"panel": pid, "span": span} for cell in row for pid, span in cell.items()] for row in spec["layout"]]
    out["members"] = {m: used[m] for m in sorted(used)}
    if catalog is not None:
        # which cubes each cube joins to: the renderer applies a drill-down's period only to panels that can reach the time dimension
        cubes = {m.partition(".")[0] for m in used} | {spec["time"]["dimension"].partition(".")[0]}
        out["cubes"] = {c: {"joins": sorted(catalog.cubes[c]["joins"])} for c in sorted(cubes)
                        if c in catalog.cubes and catalog.cubes[c]["joins"] is not None}
    return out
