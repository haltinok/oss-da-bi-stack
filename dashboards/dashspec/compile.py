"""Compile a validated spec to the JSON the renderer loads: the layout as explicit rows, plus the type of every member used."""


def compile_spec(spec, used):
    out = {k: v for k, v in spec.items() if k != "layout"}
    out["layout"] = [[{"panel": pid, "span": span} for cell in row for pid, span in cell.items()] for row in spec["layout"]]
    out["members"] = {m: used[m] for m in sorted(used)}
    return out
