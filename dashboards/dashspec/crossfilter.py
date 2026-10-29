"""`cross_filter` on a panel: a click on it filters the other panels, with no filter written in the file. The compiler turns it into what a click already works on: for each dimension the
clicked mark carries it adds a filter (marked `implicit`, with the panel it belongs to) and fills the panel's `on_click`. The source file is not touched, so the designer, the versions
and review only ever see `cross_filter`. An existing visible `select` filter on the same dimension is reused instead (the header select and the click then stay in step)."""
import copy

from .filters import tab_of
from .queries import cube_of, panel_measures

PREFIX = "xf_"                       # the filter ids made here; a file's own filters may not start with it (the validator says so)
CARRIERS = ("bar", "pie", "treemap", "table", "pivot", "timeseries")
DEFAULT_OFF = ("table",)             # a table does not filter the others unless it says so (its rows are details to read; a click can carry order numbers no other panel can join to)
DEFAULT = "page"                     # a panel that says nothing cross-filters the panels of its page (its tab; the whole dashboard when there are no tabs)


def carried(panel, used, catalog=None, time_dim=None):
    """The dimensions a click on this panel carries, in the order the clicked mark names them (what `on_click.set_filter` follows): a bar's or pie's `by`, a treemap's groups, a table row's
    group columns, a pivot's rows and plain column, a time chart's year (needs the catalog and the dashboard's time field)."""
    kind = panel["type"]
    if kind in ("bar", "pie"):
        return [panel["by"]]
    if kind == "treemap":
        return list(panel["group"])
    if kind == "table":
        cols = [c if isinstance(c, dict) else {"member": c} for c in panel["columns"]]
        return [c["member"] for c in cols if used.get(c["member"], {}).get("kind") != "measure" and "aggregate" not in c]          # an aggregated field is a value, not a key
    if kind == "pivot":
        return [*panel["rows"], *([panel["columns"]] if isinstance(panel["columns"], str) else [])]
    if kind == "timeseries" and catalog is not None and time_dim:
        cube = cube_of(panel.get("time_dimension") or time_dim)
        return [f"{cube}.fiscal_year"] if "fiscal_year" in catalog.cubes.get(cube, {}).get("dimensions", {}) else []
    return []


def _default_dims(panel, used, catalog, time_dim):
    """What a panel that did not say anything cross-filters by: all the dimension values of the clicked mark (every group column of a table, every row and the plain column of a pivot),
    but not for a time chart that drills down: its click opens the next level."""
    if panel["type"] == "timeseries" and "drill" in panel:
        return []
    return carried(panel, used, catalog, time_dim)


def _label(dimension):
    name = dimension.partition(".")[2].replace("_", " ")
    return name[:1].upper() + name[1:]


def expand(spec, used, catalog=None):
    """A copy of the (validated) spec in which the cross-filtering of every panel has become filters and an `on_click`: `cross_filter: true | page` as written, and, for a panel that says
    nothing (and has no `on_click` of its own), the default (`page`). `cross_filter: false` or an `on_click` turns it off."""
    out = copy.deepcopy(spec)
    filters = out.setdefault("filters", [])
    tabbed = "tabs" in out
    time_dim = out["time"]["dimension"]
    for p in out["panels"]:
        explicit = "cross_filter" in p
        mode = p.pop("cross_filter", DEFAULT)
        if mode is False or "on_click" in p or (not explicit and p["type"] in DEFAULT_OFF):
            continue
        dims = carried(p, used, catalog, time_dim) if explicit else _default_dims(p, used, catalog, time_dim)
        ids = []
        for n, dim in enumerate(dims, 1):
            reuse = next((f for f in filters if f["dimension"] == dim and f.get("type", "select") == "select" and f.get("visible", True) is not False and f["id"] not in ids), None)
            if reuse is None:
                reuse = {"id": f"{PREFIX}{p['id']}_{n}", "dimension": dim, "label": _label(dim), "implicit": True, "source": p["id"]}
                if mode == "page" and tabbed:
                    reuse |= {"scope": "page", "tab": tab_of(out, p["id"])}
                filters.append(reuse)
            ids.append(reuse["id"])
        if ids:
            p["on_click"] = {"set_filter": ids}
    if not filters:
        del out["filters"]
    # a panel that cannot join to a made filter's dimension ignores it (written by hand, an explicit filter asks for that in `ignore_filters`; here nobody wrote one)
    if catalog is not None:
        for f in (x for x in filters if x.get("implicit")):
            for p in out["panels"]:
                measures = panel_measures(p, used)
                if measures and any(not catalog.reachable(cube_of(m), cube_of(f["dimension"])) for m in measures) and f["id"] not in p.get("ignore_filters", []):
                    p["ignore_filters"] = [*p.get("ignore_filters", []), f["id"]]
    return out
