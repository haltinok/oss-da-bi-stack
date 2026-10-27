"""The Cube queries each panel sends: a Python mirror of the builders in dashboard/static/render/plan.js (the renderer's source of truth).
`dashspec lint` asks Cube about these, so they must be the queries the page really sends; dashboards/tests runs the JS builders and
compares, on every checked-in dashboard and several filter states."""

DEFAULT_LIMIT = {"bar": 10, "table": 100}
PIVOT_LIMIT = {"rows": 25, "columns": 12}
PIVOT_MAX_ROWS = 200
PIVOT_CELLS = 50000


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
    if kind == "pie":
        return list(panel["sum"]) if "sum" in panel else [panel["measure"]]
    if kind == "treemap":
        return [panel["measure"]]
    if kind == "table":
        return table_parts(panel, members)[0]
    if kind == "pivot":
        return [m["member"] for m in panel["measures"]]
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


def pivot_column(panel):
    """A pivot's columns are a dimension or { member, granularity } -> { member, granularity? }."""
    cols = panel["columns"]
    return {"member": cols} if isinstance(cols, str) else cols


def pivot_queries(spec, panel, values):
    """Every query a pivot sends, shapes only (mirror of pivotQueryList in render/plan.js: the axes of wave 1, then the values of wave 2)."""
    measures = [m["member"] for m in panel["measures"]]
    lead = measures[0]
    rows, totals = panel["rows"], panel.get("totals", "both")
    col = pivot_column(panel)["member"]
    gran = pivot_column(panel).get("granularity")
    lim = {**PIVOT_LIMIT, **panel.get("limit", {})}
    by = panel.get("order", {}).get("by", "total")
    direction = panel.get("order", {}).get("dir", "asc" if by == "label" else "desc")
    base = active_filters(spec, values, panel)

    def lead_query(query):
        return follow_period(spec, panel, values, [{"cube": cube_of(lead), "query": {"measures": [lead], "filters": base, **query}}])

    def shape(row_dims, with_col):
        """The grouping by these rows and, with with_col, the column: a time column is a timeDimension at its granularity (mirror of `shape` in plan.js)."""
        dims = [*row_dims, col] if with_col and not gran else list(row_dims)
        out = {"dimensions": dims} if dims else {}
        if with_col and gran:
            out["timeDimensions"] = [{"dimension": col, "granularity": gran}]
        return out

    dims_asc = {d: "asc" for d in rows}
    out = lead_query({**shape(rows, False), "order": {lead: direction, **dims_asc} if by == "total" else {d: direction for d in rows}, "limit": lim["rows"] + 1})
    if len(rows) > 1:
        out += lead_query({**shape([rows[0]], False), "order": {lead: direction, rows[0]: "asc"} if by == "total" else {rows[0]: direction}, "limit": PIVOT_MAX_ROWS})
    out += lead_query({**shape([], True), "order": {col: "asc"}, "limit": lim["columns"] + 1})

    def per(row_dims, with_col):
        grouping = shape(row_dims, with_col)
        return follow_period(spec, panel, values, per_cube(measures, {"filters": base, **grouping, **({"limit": PIVOT_CELLS} if grouping else {})}))

    row_total, col_total, anything = totals in ("both", "rows"), totals in ("both", "columns"), totals != "none"
    out += per(rows, True)
    out += per([rows[0]], True) if len(rows) > 1 and anything else []
    out += per(rows, False) if row_total else []
    out += per([rows[0]], False) if len(rows) > 1 and row_total else []
    out += per([], True) if col_total else []
    out += per([], False) if anything else []
    return out


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
        qs = per_cube(panel_measures(panel, spec["members"]), {"dimensions": [panel["by"]], "filters": filters, "limit": 100})
        return follow_period(spec, panel, values, [{**q, "query": {**q["query"], "order": {q["query"]["measures"][0]: "desc"}}} for q in qs])
    if kind == "treemap":
        return follow_period(spec, panel, values, per_cube([panel["measure"]], {"dimensions": panel["group"], "filters": filters}))
    if kind == "pivot":
        return pivot_queries(spec, panel, values)
    if kind == "table":
        measures, dims = table_parts(panel, spec["members"])
        order = dict(panel.get("order") or {}) or {d: "asc" for d in dims}   # the author's order, else every dimension ascending
        limit = panel.get("limit", DEFAULT_LIMIT["table"])
        base = {"dimensions": dims, "filters": filters}
        if not measures:
            return [{"cube": "", "query": {**base, "order": order, "limit": limit}}]
        single = len({cube_of(m) for m in measures}) <= 1
        rows = follow_period(spec, panel, values, per_cube(measures, {**base, **({"order": order, "limit": limit} if single else {})}))
        total = follow_period(spec, panel, values, per_cube(measures, {"filters": filters})) if panel.get("totals") else []
        return rows + total
    return []
