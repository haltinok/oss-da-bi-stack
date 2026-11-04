"""A slicer on a field (`dimension:` on a slicer panel, PLAN-slicer-fields.md): the compiler turns it into what a slicer already draws, a filter, so the page and the query mirrors
(render/plan.js, queries.py) only ever see slicers that point at a filter. The source file is not touched: the designer, versions and review see `dimension`.

The made filter is a visible `select` with the id `sl_<panel id>` (also its key in the address), narrowing only the panels of the slicer's own tab (the whole dashboard when there
are no tabs). A panel of that tab that cannot join to the field ignores it. This runs before the cross-filter expansion, so a click on a bar by the same field reuses the slicer's
filter and the slicer shows what was clicked."""
import copy

from . import calculations
from .filters import tab_of

PREFIX = "sl_"                       # the filter ids made here; a file's own filters may not start with it (the validator says so)
DATA_LESS = ("text", "slicer")


def label_of(dimension):
    name = dimension.partition(".")[2].replace("_", " ")
    return name[:1].upper() + name[1:]


def field_slicers(spec):
    return [p for p in spec["panels"] if p["type"] == "slicer" and "dimension" in p]


def scope_panels(spec, slicer):
    """The data panels a field slicer narrows: those of its tab (every panel when there are no tabs)."""
    tab = tab_of(spec, slicer["id"]) if "tabs" in spec else None
    return [p for p in spec["panels"] if p["type"] not in DATA_LESS and (tab is None or tab_of(spec, p["id"]) == tab)]


def measures_of(panel, catalog):
    """The cube measures a panel reads (a calculation as the measures it reads), from the catalog: the validator's view, before anything is compiled."""
    from .validate import _panel_members              # here, not at the top: validate imports this module
    found = [m for _, m, _ in _panel_members(panel) if (catalog.lookup(m) or ("",))[0] == "measure"]
    return calculations.real_members(getattr(catalog, "calcs", {}), found)


def joins(catalog, panel, dimension):
    """Can this panel be filtered by the field? Every measure it reads must reach the field's cube; a panel of dimensions only (a list table) goes by its fields."""
    from .validate import _panel_members
    members = measures_of(panel, catalog) or [m for _, m, _ in _panel_members(panel) if catalog.lookup(m) is not None]
    cube = dimension.partition(".")[0]
    return bool(members) and all(catalog.reachable(m.partition(".")[0], cube) for m in members)


def made_filter(spec, slicer):
    f = {"id": f"{PREFIX}{slicer['id']}", "dimension": slicer["dimension"], "label": slicer.get("label") or label_of(slicer["dimension"]), "source": slicer["id"]}
    tab = tab_of(spec, slicer["id"]) if "tabs" in spec else None
    if tab is not None:
        f |= {"scope": "page", "tab": tab}
    return f


def expand(spec, catalog=None):
    """A copy of the spec in which every field slicer points at a filter made for it. With the catalog, the panels of its tab that cannot join to the field ignore that filter."""
    if not field_slicers(spec):
        return spec
    out = copy.deepcopy(spec)
    filters = out.setdefault("filters", [])
    for p in field_slicers(out):
        f = made_filter(out, p)
        filters.append(f)
        if catalog is not None:
            for q in scope_panels(out, p):
                if not joins(catalog, q, f["dimension"]) and f["id"] not in q.get("ignore_filters", []):
                    q["ignore_filters"] = [*q.get("ignore_filters", []), f["id"]]
        p["filter"] = f["id"]
        p.pop("dimension")
        p.pop("label", None)
    return out
