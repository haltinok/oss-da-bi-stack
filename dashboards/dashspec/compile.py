"""Compile a validated spec to the JSON the renderer loads: the layout as explicit rows, plus the type of every member used."""
import copy


def compile_spec(spec, used):
    out = copy.deepcopy({k: v for k, v in spec.items() if k != "layout"})
    for panel in out["panels"]:
        if panel["type"] == "table":     # every column as { member, label?, format? }, so the renderer reads one shape
            panel["columns"] = [{"member": col} if isinstance(col, str) else col for col in panel["columns"]]
    out["layout"] = [[{"panel": pid, "span": span} for cell in row for pid, span in cell.items()] for row in spec["layout"]]
    out["members"] = {m: used[m] for m in sorted(used)}
    return out
