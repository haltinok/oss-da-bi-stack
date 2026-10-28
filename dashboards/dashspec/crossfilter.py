"""`cross_filter` on a panel: a click on it filters the other panels, with no filter written in the file. The compiler turns it into what a click already works on: for each dimension the
clicked mark carries it adds a filter (marked `implicit`, with the panel it belongs to) and fills the panel's `on_click`. The source file is not touched, so the designer, the versions
and review only ever see `cross_filter`. An existing visible `select` filter on the same dimension is reused instead (the header select and the click then stay in step)."""
import copy

from .filters import tab_of
from .queries import cube_of, panel_measures

PREFIX = "xf_"                       # the filter ids made here; a file's own filters may not start with it (the validator says so)
CARRIERS = ("bar", "pie", "treemap", "table")


def carried(panel, used):
    """The dimensions a click on this panel carries, in the order the clicked mark names them (what `on_click.set_filter` follows)."""
    kind = panel["type"]
    if kind in ("bar", "pie"):
        return [panel["by"]]
    if kind == "treemap":
        return list(panel["group"])
    if kind == "table":
        cols = [c["member"] if isinstance(c, dict) else c for c in panel["columns"]]
        return [m for m in cols if used.get(m, {}).get("kind") != "measure"]
    return []


def _label(dimension):
    name = dimension.partition(".")[2].replace("_", " ")
    return name[:1].upper() + name[1:]


def expand(spec, used, catalog=None):
    """A copy of the (validated) spec in which every `cross_filter` has become filters and an `on_click`. A spec without one comes back as it is."""
    if not any("cross_filter" in p for p in spec["panels"]):
        return spec
    out = copy.deepcopy(spec)
    filters = out.setdefault("filters", [])
    for p in out["panels"]:
        mode = p.pop("cross_filter", None)
        if mode is None:
            continue
        ids = []
        for n, dim in enumerate(carried(p, used), 1):
            reuse = next((f for f in filters if f["dimension"] == dim and f.get("type", "select") == "select" and f.get("visible", True) is not False and f["id"] not in ids), None)
            if reuse is None:
                reuse = {"id": f"{PREFIX}{p['id']}_{n}", "dimension": dim, "label": _label(dim), "implicit": True, "source": p["id"]}
                if mode == "page":
                    reuse |= {"scope": "page", "tab": tab_of(out, p["id"])}
                filters.append(reuse)
            ids.append(reuse["id"])
        p["on_click"] = {"set_filter": ids}
    # a panel that cannot join to a made filter's dimension ignores it (written by hand, an explicit filter asks for that in `ignore_filters`; here nobody wrote one)
    if catalog is not None:
        for f in (x for x in filters if x.get("implicit")):
            for p in out["panels"]:
                measures = panel_measures(p, used)
                if measures and any(not catalog.reachable(cube_of(m), cube_of(f["dimension"])) for m in measures) and f["id"] not in p.get("ignore_filters", []):
                    p["ignore_filters"] = [*p.get("ignore_filters", []), f["id"]]
    return out
