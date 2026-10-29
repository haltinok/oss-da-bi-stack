"""The Cube queries each panel sends: a Python mirror of the builders in dashboard/static/render/plan.js (the renderer's source of truth).
`dashspec lint` asks Cube about these, so they must be the queries the page really sends; dashboards/tests runs the JS builders and
compares, on every checked-in dashboard and several filter states."""

from .filters import applies, default_env, effective_value, to_cube

DEFAULT_LIMIT = {"bar": 10, "table": 100}
PIVOT_LIMIT = {"rows": 25, "columns": 12}
PIVOT_MAX_ROWS = 200
PIVOT_CELLS = 50000


def cube_of(member):
    return member.split(".")[0]


def active_filters(spec, values, panel, env=None):
    clicked = panel.get("on_click", {}).get("set_filter")
    own = [] if clicked is None else [clicked] if isinstance(clicked, str) else list(clicked)
    ignored = set(panel.get("ignore_filters", [])) | set(own)
    env = env or default_env(spec)
    return [c for f in spec.get("filters", []) if f["id"] not in ignored and applies(spec, f, panel.get("id")) and effective_value(f, values) not in (None, "")
            for c in to_cube(f, effective_value(f, values), env)]


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


def sort_key_of(spec, member):
    """The dimension a text dimension sorts by (a month's name by its number), from the compiled `members`; None for most."""
    return spec.get("members", {}).get(member, {}).get("sort_by")


def with_sort_keys(spec, dims):
    """`dims` plus the sort keys of the ones that have one, after them, each once (a query that orders by a field must ask for it)."""
    return list(dict.fromkeys([*dims, *[k for d in dims if (k := sort_key_of(spec, d))]]))


def sorted_by(spec, order):
    """An order by dimensions, with the sort key standing in for the dimension that has one."""
    return {sort_key_of(spec, k) or k: v for k, v in order.items()}


AGGREGATE_LIMIT = 20000            # rows fetched to aggregate a table's value fields client-side; the page says so when it hit this


def table_parts(panel, members):
    """(measures, key dimensions) of a table. A dimension column with `aggregate` is a value, not a key: see table_values."""
    cols = [c if isinstance(c, dict) else {"member": c} for c in panel["columns"]]
    keys = [c["member"] for c in cols if members.get(c["member"], {}).get("kind") != "measure" and "aggregate" not in c]
    return ([c["member"] for c in cols if members.get(c["member"], {}).get("kind") == "measure"], keys)


def table_values(panel):
    """The aggregated dimension columns of a table: [(member, aggregate)]."""
    return [(c["member"], c["aggregate"]) for c in panel["columns"] if isinstance(c, dict) and "aggregate" in c]


PERIOD = "_period"


def parse_period(v):
    import re
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", v or "")
    return [m.group(1), m.group(2)] if m else None


def option_measures(spec, flt, nested=False):
    """One measure per cube among the panels this filter narrows: what a filter's (or a slicer's) option query can use. A slicer has no data of its own: a pane filter on a slicer
    narrows that slicer's options, so it uses the measures its slicer's filter uses (`nested` stops it there)."""
    per = {}
    for p in spec["panels"]:
        if flt["id"] in p.get("ignore_filters", []) or not applies(spec, flt, p["id"]):
            continue
        if p["type"] == "slicer":
            inner = next((f for f in spec.get("filters", []) if f["id"] == p["filter"]), None)
            members = [] if nested or inner is None or inner["id"] == flt["id"] else option_measures(spec, inner, True)
        else:
            members = panel_measures(p, spec.get("members", {}))
        for m in members:
            per.setdefault(cube_of(m), m)
    return list(per.values())


def slicer_queries(spec, panel, values):
    """The queries behind a slicer's options (mirror of slicerQueries in render/plan.js): its filter's dimension, narrowed by every other filter that applies to the slicer."""
    flt = next((f for f in spec.get("filters", []) if f["id"] == panel["filter"]), None)
    if flt is None:
        return []
    measures = option_measures(spec, flt)
    own = {**panel, "ignore_filters": [*panel.get("ignore_filters", []), flt["id"]], "optionMeasures": measures}
    dims = with_sort_keys(spec, [*([flt["parent"]] if "parent" in flt else []), flt["dimension"]])
    return follow_period(spec, own, values, per_cube(measures, {"dimensions": dims, "filters": active_filters(spec, values, own)}))


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
    if kind == "slicer":
        return panel.get("optionMeasures", [])                 # set by slicer_queries
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

    def axis(sh, order, limit):
        """An axis is read in the order of its labels: a field that sorts by another (a month's name by its number) asks for that one and orders by it."""
        return {**({**sh, "dimensions": with_sort_keys(spec, sh["dimensions"])} if "dimensions" in sh else sh), "order": sorted_by(spec, order), "limit": limit}

    out = lead_query(axis(shape(rows, False), {lead: direction, **dims_asc} if by == "total" else {d: direction for d in rows}, lim["rows"] + 1))
    if len(rows) > 1:
        out += lead_query(axis(shape([rows[0]], False), {lead: direction, rows[0]: "asc"} if by == "total" else {rows[0]: direction}, PIVOT_MAX_ROWS))
    out += lead_query(axis(shape([], True), {col: "asc"}, lim["columns"] + 1))

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
    kind = panel["type"]
    if kind == "slicer":
        return slicer_queries(spec, panel, values)
    filters = active_filters(spec, values, panel)
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
        agg = table_values(panel)
        order = dict(panel.get("order") or {}) or {d: "asc" for d in dims}   # the author's order, else every dimension ascending
        limit = panel.get("limit", DEFAULT_LIMIT["table"])
        order = sorted_by(spec, order)
        base = {"dimensions": with_sort_keys(spec, dims), "filters": filters}
        out = []
        if measures:
            single = len({cube_of(m) for m in measures}) <= 1 and not agg           # with aggregated fields the rows are merged and ordered here, not in Cube
            out += follow_period(spec, panel, values, per_cube(measures, {**base, **({"order": order, "limit": limit} if single else {})}))
        elif not agg:
            return [{"cube": "", "query": {**base, "order": order, "limit": limit}}]
        if agg:                                                                   # the rows the value fields are aggregated over: one per row of their cube, tagged `agg:<cube>`
            cube = cube_of(agg[0][0])
            key = spec["rowKeys"][cube]
            fields = list(dict.fromkeys(m for m, _ in agg))
            out.append({"cube": f"agg:{cube}", "query": {"dimensions": [*with_sort_keys(spec, dims), key, *fields], "filters": filters, "order": {key: "asc"}, "limit": AGGREGATE_LIMIT}})
        if panel.get("totals") and measures:
            out += follow_period(spec, panel, values, per_cube(measures, {"filters": filters}))
        return out
    return []
