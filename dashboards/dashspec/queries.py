"""The Cube queries each panel sends: a Python mirror of the builders in dashboard/static/render/plan.js (the renderer's source of truth).
`dashspec lint` asks Cube about these, so they must be the queries the page really sends; dashboards/tests runs the JS builders and
compares, on every checked-in dashboard and several filter states."""

DEFAULT_LIMIT = {"bar": 10, "table": 100}


def cube_of(member):
    return member.split(".")[0]


def active_filters(spec, values, panel):
    clicked = panel.get("on_click", {}).get("set_filter")
    own = [] if clicked is None else [clicked] if isinstance(clicked, str) else list(clicked)
    ignored = set(panel.get("ignore_filters", [])) | set(own)
    return [{"member": f["dimension"], "operator": "equals", "values": [str(values[f["id"]])]}
            for f in spec.get("filters", []) if values.get(f["id"]) not in (None, "") and f["id"] not in ignored]


def term_members(m):
    if "member" in m:
        return [m["member"]]
    if "sum" in m:
        return list(m["sum"])
    return list(dict.fromkeys([*m["ratio"]["num"], *m["ratio"]["den"]]))


def per_cube(measures, base=None):
    """One query per cube that owns some of the measures, in first-seen order: [{ cube, query }]."""
    groups = {}
    for m in measures:
        members = groups.setdefault(cube_of(m), [])
        if m not in members:
            members.append(m)
    return [{"cube": c, "query": {**(base or {}), "measures": ms}} for c, ms in groups.items()]


def table_parts(panel, members):
    cols = [c["member"] if isinstance(c, dict) else c for c in panel["columns"]]
    return ([m for m in cols if members.get(m, {}).get("kind") == "measure"], [m for m in cols if members.get(m, {}).get("kind") != "measure"])


PERIOD = "_period"


def parse_period(v):
    import re
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", v or "")
    return [m.group(1), m.group(2)] if m else None


def panel_measures(panel, members):
    kind = panel["type"]
    if kind == "kpi":
        return [x for m in panel["measures"] for x in term_members(m)]
    if kind == "timeseries":
        return [x for s in panel["series"] for x in term_members(s)]
    if kind == "bar":
        return [s["member"] for s in panel["stack"]] if "stack" in panel else [panel["measure"]]
    if kind in ("pie", "treemap"):
        return [panel["measure"]]
    if kind == "table":
        return table_parts(panel, members)[0]
    return []


def _reaches(spec, src, dst):
    cubes = spec.get("cubes")
    if src == dst or not cubes:
        return True
    seen, todo = {src}, [src]
    while todo:
        for nxt in cubes.get(todo.pop(), {}).get("joins", []):
            if nxt == dst:
                return True
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return False


def applies_period(spec, panel):
    """Does the page's period narrow this panel? (mirror of appliesPeriod in render/plan.js)"""
    if panel["type"] == "text" or "drill" in panel or "period" in panel.get("ignore_filters", []):
        return False
    measures = panel_measures(panel, spec["members"])
    time_cube = cube_of(spec["time"]["dimension"])
    return bool(measures) and all(_reaches(spec, cube_of(m), time_cube) for m in measures)


def with_range(spec, query, rng):
    dim = spec["time"]["dimension"]
    td = query.get("timeDimensions", [])
    if any(t["dimension"] == dim for t in td):
        td = [{**t, "dateRange": rng} if t["dimension"] == dim else t for t in td]
    else:
        td = [*td, {"dimension": dim, "dateRange": rng}]
    return {**query, "timeDimensions": td}


def follow_period(spec, panel, values, queries):
    rng = parse_period(values.get(PERIOD))
    return [{**q, "query": with_range(spec, q["query"], rng)} for q in queries] if rng and applies_period(spec, panel) else queries


def panel_queries(spec, panel, values):
    """Every query the panel sends for these filter values, at its default granularity (a KPI's tiles and sparklines included)."""
    filters = active_filters(spec, values, panel)
    kind = panel["type"]
    if kind == "kpi":
        out = []
        for m in panel["measures"]:
            members = term_members(m)
            out += follow_period(spec, panel, values, per_cube(members, {"filters": filters}))
            if "sparkline" in panel:
                out += follow_period(spec, panel, values, per_cube(members, {"filters": filters, "timeDimensions": [{"dimension": spec["time"]["dimension"], "granularity": panel["sparkline"]["granularity"]}]}))
        return out
    if kind == "timeseries":
        members = list(dict.fromkeys(x for s in panel["series"] for x in term_members(s)))
        return follow_period(spec, panel, values, per_cube(members, {"timeDimensions": [{"dimension": spec["time"]["dimension"], "granularity": panel["granularity"]}], "filters": filters}))
    if kind == "bar":
        measures = [s["member"] for s in panel["stack"]] if "stack" in panel else [panel["measure"]]
        single = "stack" not in panel and "split" not in panel
        base = {"dimensions": [panel["by"], *([panel["split"]] if "split" in panel else [])], "filters": filters}
        if single:
            base |= {"order": {panel["measure"]: panel.get("sort", "desc")}, "limit": panel.get("limit", DEFAULT_LIMIT["bar"])}
        return follow_period(spec, panel, values, per_cube(measures, base))
    if kind == "pie":
        return follow_period(spec, panel, values, per_cube([panel["measure"]], {"dimensions": [panel["by"]], "filters": filters, "order": {panel["measure"]: "desc"}, "limit": 100}))
    if kind == "treemap":
        return follow_period(spec, panel, values, per_cube([panel["measure"]], {"dimensions": panel["group"], "filters": filters}))
    if kind == "table":
        measures, dims = table_parts(panel, spec["members"])
        order, limit = dict(panel.get("order", {})), panel.get("limit", DEFAULT_LIMIT["table"])
        base = {"dimensions": dims, "filters": filters}
        if not measures:
            return [{"cube": "", "query": {**base, "order": order, "limit": limit}}]
        single = len({cube_of(m) for m in measures}) <= 1
        return follow_period(spec, panel, values, per_cube(measures, {**base, **({"order": order, "limit": limit} if single else {})}))
    return []
