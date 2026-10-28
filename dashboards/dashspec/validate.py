"""Schema and member checks. Every message names the panel (or filter) and the field, so a broken file points at its own line."""
import json
import pathlib

from jsonschema import Draft202012Validator

SCHEMA = json.loads((pathlib.Path(__file__).parent.parent / "schema" / "dashboard.schema.json").read_text())
_VALIDATOR = Draft202012Validator(SCHEMA)


def _field(path):
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out or "(file)"


def _where(spec, path):
    """-> ("panel 'trend' (timeseries)", "series[1].member") for a path into the spec."""
    path = list(path)
    if len(path) >= 2 and path[0] in ("panels", "filters") and isinstance(path[1], int):
        items = spec.get(path[0]) if isinstance(spec, dict) else None
        item = items[path[1]] if isinstance(items, list) and path[1] < len(items) else None
        ident = item.get("id", f"#{path[1]}") if isinstance(item, dict) else f"#{path[1]}"
        if path[0] == "panels":
            kind = f" ({item['type']})" if isinstance(item, dict) and isinstance(item.get("type"), str) else ""
            return f"panel '{ident}'{kind}", _field(path[2:])
        return f"filter '{ident}'", _field(path[2:])
    return "dashboard", _field(path)


def _schema_message(err):
    if err.validator in ("minItems", "maxItems") and list(err.absolute_path) == ["tabs"]:
        return f"a dashboard has 2 to 8 tabs, this one has {len(err.instance)} (use `layout` for a single page)"
    if err.validator == "oneOf" and isinstance(err.validator_value, list) and all(isinstance(a, dict) and set(a) == {"required"} for a in err.validator_value):
        names = [n for a in err.validator_value for n in a["required"]]                  # none of them matched, or more than one did
        if "member" in names:
            return "needs a 'member' (or a 'sum' / 'ratio' of measures, with a 'label')"
        return "needs exactly one of: " + ", ".join(dict.fromkeys(names))
    has_object = err.validator == "oneOf" and any(isinstance(b, dict) and b.get("type") == "object" for b in err.validator_value)
    if has_object and isinstance(err.instance, dict):
        branch = next(i for i, b in enumerate(err.validator_value) if isinstance(b, dict) and b.get("type") == "object")      # a { ... } where a string or an object may go
        why = [c.message for c in err.context if c.schema_path and c.schema_path[0] == branch]
        return "; ".join(why) or err.message
    if has_object and isinstance(err.instance, str):
        return "must be a member ('cube.name') or an object { member, granularity }"
    if err.validator == "oneOf":
        return "must be a filter id or a list of one or two filter ids"
    if err.validator == "required" and "sum" in err.message:
        return err.message
    return err.message


def _allowed_panel_keys(ptype):
    panel = SCHEMA["$defs"]["panel"]
    keys = set(panel["properties"])
    for branch in panel["allOf"]:
        if branch["if"]["properties"]["type"]["const"] == ptype:
            keys |= set(branch["then"]["properties"])
    return keys


def _unknown_keys(spec, path):
    """unevaluatedProperties also fires on every key of a panel whose branch failed for another reason; name only the keys that really are unknown."""
    node = spec
    for p in path:
        node = node[p]
    if len(path) == 2 and path[0] == "panels" and isinstance(node, dict) and node.get("type") in SCHEMA["$defs"]["panel"]["properties"]["type"]["enum"]:
        return sorted(set(node) - _allowed_panel_keys(node["type"]))
    return None


def schema_errors(spec):
    errors = sorted(_VALIDATOR.iter_errors(spec), key=lambda e: [str(x) for x in e.absolute_path])
    # a bad panel type makes every other key look unexpected; report the type only
    bad_type = {tuple(e.absolute_path)[:2] for e in errors if tuple(e.absolute_path)[:1] == ("panels",) and tuple(e.absolute_path)[2:] == ("type",)}
    out = []
    for e in errors:
        path = tuple(e.absolute_path)
        if path[:2] in bad_type and path[2:] != ("type",):
            continue
        where, field = _where(spec, path)
        if e.validator == "unevaluatedProperties":
            unknown = _unknown_keys(spec, path)
            if unknown is not None:
                out.extend(f"{where}: {k}: '{k}' is not a field of a {spec['panels'][path[1]]['type']} panel" for k in unknown)
                continue
        out.append(f"{where}: {field}: {_schema_message(e)}")
    return out


def column_member(c):
    """A table column is a member string or { member, label, format }."""
    return c if isinstance(c, str) else c["member"]


def pivot_column_member(p):
    """A pivot's `columns` is a dimension member or { member, granularity }."""
    return p["columns"] if isinstance(p["columns"], str) else p["columns"]["member"]


def _measure_members(prefix, m):
    """The members of a measure definition: { member } | { sum: [...] } | { ratio: { num, den } }."""
    if "member" in m:
        yield f"{prefix}.member", m["member"], "measure"
    for j, s in enumerate(m.get("sum", [])):
        yield f"{prefix}.sum[{j}]", s, "measure"
    for part in ("num", "den"):
        for j, s in enumerate(m.get("ratio", {}).get(part, [])):
            yield f"{prefix}.ratio.{part}[{j}]", s, "measure"


def _panel_members(p):
    """(field, member, wanted kind) for every Cube member a panel names; wanted is measure | dimension | any."""
    t = p["type"]
    if t == "kpi":
        for i, m in enumerate(p["measures"]):
            yield from _measure_members(f"measures[{i}]", m)
    elif t == "timeseries":
        for i, s in enumerate(p["series"]):
            yield from _measure_members(f"series[{i}]", s)
    elif t == "bar":
        if "measure" in p:
            yield "measure", p["measure"], "measure"
        for i, s in enumerate(p.get("stack", [])):
            yield f"stack[{i}].member", s["member"], "measure"
        yield "by", p["by"], "dimension"
        if "split" in p:
            yield "split", p["split"], "dimension"
    elif t == "pie":
        if "measure" in p:
            yield "measure", p["measure"], "measure"
        for j, m in enumerate(p.get("sum", [])):
            yield f"sum[{j}]", m, "measure"
        yield "by", p["by"], "dimension"
    elif t == "treemap":
        yield "measure", p["measure"], "measure"
        for i, g in enumerate(p["group"]):
            yield f"group[{i}]", g, "dimension"
    elif t == "table":
        for i, c in enumerate(p["columns"]):
            yield f"columns[{i}]", column_member(c), "any"
    elif t == "pivot":
        for i, r in enumerate(p["rows"]):
            yield f"rows[{i}]", r, "dimension"
        yield "columns" if isinstance(p["columns"], str) else "columns.member", pivot_column_member(p), "dimension"
        for i, m in enumerate(p["measures"]):
            yield f"measures[{i}]", column_member(m), "measure"


def semantic_errors(spec, catalog):
    errs = []
    used = {}  # member -> (kind, type), for the compiler

    def check(where, field, member, want, time=False):
        found = catalog.lookup(member)
        if found is None:
            errs.append(f"{where}: {field}: '{member}' is not in the Cube model ({catalog.suggest(member)})")
            return None
        kind, typ = found
        if want in ("measure", "dimension") and kind != want:
            errs.append(f"{where}: {field}: '{member}' is a {kind}, a {want} is needed here")
            return None
        if time and typ != "time":
            errs.append(f"{where}: {field}: '{member}' is a {typ} dimension, a time dimension is needed")
            return None
        used[member] = {"kind": kind, "type": typ}
        return kind

    check("dashboard", "time.dimension", spec["time"]["dimension"], "dimension", time=True)

    filters = spec.get("filters", [])
    filter_ids = [f["id"] for f in filters]
    for dup in sorted({i for i in filter_ids if filter_ids.count(i) > 1}):
        errs.append(f"dashboard: filters: id '{dup}' is used by more than one filter")
    for f in filters:
        w = f"filter '{f['id']}'"
        check(w, "dimension", f["dimension"], "dimension")
        if "parent" in f:
            check(w, "parent", f["parent"], "dimension")
            if f["parent"] == f["dimension"]:
                errs.append(f"{w}: parent: a filter cannot be its own parent")

    for i, tag in enumerate(spec.get("tags", [])):
        why = tag_problem(tag)
        if why:
            errs.append(f"dashboard: tags[{i}]: '{tag}' {why}")

    panel_ids = [p["id"] for p in spec["panels"]]
    for dup in sorted({i for i in panel_ids if panel_ids.count(i) > 1}):
        errs.append(f"dashboard: panels: id '{dup}' is used by more than one panel")

    for p in spec["panels"]:
        w = f"panel '{p['id']}' ({p['type']})"
        kinds = {}
        for field, member, want in _panel_members(p):
            kinds[member] = check(w, field, member, want)
        for fid in p.get("ignore_filters", []):
            if fid not in filter_ids and fid != PERIOD:
                errs.append(f"{w}: ignore_filters: no filter with id '{fid}'")
        click = p.get("on_click", {}).get("set_filter")
        if click is not None:
            ids = [click] if isinstance(click, str) else click
            for fid in ids:
                if fid not in filter_ids:
                    errs.append(f"{w}: on_click.set_filter: no filter with id '{fid}'")
            _click_errors(p, w, ids, filters, catalog, errs)
        if p["type"] == "timeseries" and "drill" in p:
            _drill_errors(p, w, errs)
        if p["type"] == "timeseries" and p.get("granularities") and p["granularity"] not in p["granularities"]:
            errs.append(f"{w}: granularities: must include the default granularity '{p['granularity']}'")
        if p["type"] == "bar" and "stack" in p and "split" in p:
            errs.append(f"{w}: split: a bar that is stacked by measures (stack) cannot also be split by a dimension")
        if p["type"] == "table":
            shown = [column_member(c) for c in p["columns"]]
            for col in p.get("order", {}):
                if col not in shown:
                    errs.append(f"{w}: order.{col}: not one of the table's columns")
            for c in p["columns"]:
                if isinstance(c, dict) and "rules" in c and (catalog.lookup(c["member"]) or ("",))[0] != "measure":
                    errs.append(f"{w}: columns: '{c['member']}' has `rules`, which colour a measure column; it is not a measure")
            if "totals" in p and not any((catalog.lookup(m) or ("",))[0] == "measure" for m in shown):
                errs.append(f"{w}: totals: a total row needs at least one measure column")
        if p["type"] == "pivot":
            for m in p["measures"]:
                if isinstance(m, dict) and "rules" in m:
                    errs.append(f"{w}: measures: '{m['member']}' has `rules`; a pivot is coloured by `heat`, and `rules` are for key figures and tables")
            col = pivot_column_member(p)
            if col in p["rows"]:
                errs.append(f"{w}: columns: '{col}' is also in `rows`; a dimension is either down the side or across the top")
            if isinstance(p["columns"], dict) and kinds.get(col) == "dimension" and used.get(col, {}).get("type") != "time":
                errs.append(f"{w}: columns.member: '{col}' is a {used[col]['type']} dimension, a time dimension is needed to group the columns by a granularity (or write `columns: {col}`)")
            share = p.get("show", "value")
            if share != "value":
                needs = {"share_of_row": ("rows", ("both", "rows"), "a total for every row"), "share_of_column": ("columns", ("both", "columns"), "a total for every column"),
                         "share_of_total": ("any", ("both", "rows", "columns"), "a grand total")}[share]
                if p.get("totals", "both") not in needs[1]:
                    errs.append(f"{w}: show: '{share}' divides by {needs[2]}, but totals: '{p.get('totals', 'both')}' does not ask for it (use {' or '.join(repr(t) for t in needs[1])})")
                for i, m in enumerate(p["measures"]):
                    typ = used.get(column_member(m), {}).get("type")
                    if typ is not None and typ not in ADDITIVE:
                        errs.append(f"{w}: measures[{i}]: '{column_member(m)}' is a {typ} measure, which does not add up across rows and columns, so a share of it means nothing: use `show: value` or a `sum` or `count` measure")
            if "heat" in p and p["heat"]["measure"] not in [column_member(m) for m in p["measures"]]:
                errs.append(f"{w}: heat.measure: '{p['heat']['measure']}' is not one of the pivot's measures")
        _join_errors(spec, p, w, catalog, errs)

    _layout_errors(spec, panel_ids, errs)
    _role_errors(spec, errs)
    return errs, used


def tag_problem(tag):
    """Why `tag` is not a good tag, or None. A tag is a short plain word or two: lower case, letters (of any language), digits, single spaces and
    hyphens, trimmed. Nothing is fixed silently, so two spellings of one word cannot sneak in ('Sales' is an error that says 'sales')."""
    if tag != tag.strip() or "  " in tag:
        return "has spaces at its ends or two in a row; write it trimmed, with single spaces"
    if tag != tag.lower():
        return f"is not lower case; write '{tag.lower()}'" if tag.isascii() else "is not lower case; write it in lower case"
    bad = sorted({c for c in tag if not (c.isalnum() or c in " -")})
    if bad:
        return f"contains {' '.join(repr(c) for c in bad)}; a tag is letters, digits, spaces and hyphens"
    if not tag[0].isalnum():
        return "must start with a letter or a digit"
    return None


TIME_FILTERS = ("fiscal_year", "calendar_year")
ADDITIVE = ("sum", "count")      # measure types whose cells add up to their totals: only those can be shown as a share
PERIOD = "period"            # the reserved filter id of the date range a drill-down sets; a panel lists it in ignore_filters to opt out
FINENESS = ["year", "quarter", "month", "week", "day", "hour"]


def _drill_errors(p, w, errs):
    levels = p["drill"]
    order = [FINENESS.index(g) for g in levels]
    if order != sorted(order) or len(set(order)) != len(order):
        errs.append(f"{w}: drill: the levels must go from coarse to fine ({', '.join(FINENESS)}), got {levels}")
    if p["granularity"] != levels[0]:
        errs.append(f"{w}: granularity: must be the first drill level '{levels[0]}'")
    if "granularities" in p:
        errs.append(f"{w}: granularities: a drill-down already changes the granularity; remove `granularities` or `drill`")
    if "on_click" in p:
        errs.append(f"{w}: on_click: a drill-down click also filters the other panels by the period it opens; remove `on_click` (use ignore_filters: [period] on a panel that should not follow it)")
    for a, b in zip(levels, levels[1:], strict=False):
        if b == "week" and a in ("month", "quarter"):
            errs.append(f"{w}: drill: a week does not fit inside a {a}; drill {a} -> day instead")


def _click_errors(p, w, ids, filters, catalog, errs):
    """What a click on a panel carries must be something the named filters can take: each filter's dimension is one of the dimensions
    of the clicked mark (the bar's `by`, the treemap's group in order, a table row's dimension columns), or, for a time chart, a year."""
    by_id = {f["id"]: f for f in filters}
    ids = [i for i in ids if i in by_id]
    kind = p["type"]
    if kind == "timeseries":
        if len(ids) > 1:
            errs.append(f"{w}: on_click.set_filter: a click on a time chart carries one value, {len(ids)} filters are named")
        for i in ids:
            dim = by_id[i]["dimension"]
            if dim.partition(".")[2] not in TIME_FILTERS:
                errs.append(f"{w}: on_click.set_filter: filter '{i}' is on '{dim}'; a click on a time chart can set a filter on a fiscal_year or calendar_year dimension")
    elif kind in ("bar", "pie", "treemap", "table", "pivot"):
        carried = {"bar": [p.get("by")], "pie": [p.get("by")], "treemap": p.get("group", []), "pivot": [*p.get("rows", []), *([] if not isinstance(p.get("columns"), str) else [p["columns"]])], "table": [column_member(c) for c in p.get("columns", []) if (catalog.lookup(column_member(c)) or ("",))[0] != "measure"]}[kind]
        if kind in ("bar", "pie") and len(ids) > 1:
            errs.append(f"{w}: on_click.set_filter: a click on a {kind} carries one value, {len(ids)} filters are named")
        for pos, i in enumerate(ids):
            dim = by_id[i]["dimension"]
            if kind == "treemap" and pos < len(carried) and dim != carried[pos]:
                errs.append(f"{w}: on_click.set_filter: filter '{i}' is on '{dim}' but group[{pos}] is '{carried[pos]}': name the filters in the order of the group")
            elif kind != "treemap" and dim not in carried:
                errs.append(f"{w}: on_click.set_filter: filter '{i}' is on '{dim}', which this {kind} does not show ({', '.join(carried)})")
        if kind == "treemap" and len(ids) > len(carried):
            errs.append(f"{w}: on_click.set_filter: a click carries {len(carried)} value(s) here, {len(ids)} filters are named")


def _join_errors(spec, p, w, catalog, errs):
    """Cube cannot group a measure by a dimension of a cube it has no join path to; catch that here, not at render time."""
    measures = [m for _, m, want in _panel_members(p) if (catalog.lookup(m) or ("",))[0] == "measure"]
    if not measures:
        return
    dims = [(f"field '{f}'", m) for f, m, _ in _panel_members(p) if (catalog.lookup(m) or ("",))[0] == "dimension"]
    if p["type"] == "timeseries" or (p["type"] == "kpi" and "sparkline" in p):
        dims.append(("the time axis (time.dimension)", spec["time"]["dimension"]))
    ignored = set(p.get("ignore_filters", []))
    dims += [(f"filter '{f['id']}'", f["dimension"]) for f in spec.get("filters", []) if f["id"] not in ignored]
    for meas in sorted(set(measures)):
        mc = meas.partition(".")[0]
        for origin, dim in dims:
            dc = dim.partition(".")[0]
            if catalog.lookup(dim) and not catalog.reachable(mc, dc):
                hint = " Add the filter id to this panel's ignore_filters." if origin.startswith("filter") else ""
                errs.append(f"{w}: '{meas}' cannot be combined with '{dim}' ({origin}): cube '{mc}' has no join to '{dc}'.{hint}")


def layouts_of(spec):
    """[(label, layout)]: the one `layout` of a dashboard, or the layout of each of its tabs."""
    if "tabs" in spec:
        return [(f"tab '{t['id']}'", t["layout"]) for t in spec["tabs"]]
    return [("layout", spec["layout"])]


def _layout_errors(spec, panel_ids, errs):
    """Every row adds up to 12 and names a panel that exists; every panel is placed once, across all the tabs when there are tabs."""
    tabs = "tabs" in spec
    ids = [t["id"] for t in spec.get("tabs", [])]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errs.append(f"tabs: id '{dup}' is used by more than one tab")
    placed = {}
    for label, layout in layouts_of(spec):
        for r, row in enumerate(layout):
            total = 0
            for cell in row:
                (pid, span), = cell.items()
                total += span
                placed.setdefault(pid, []).append(label)
                if pid not in panel_ids:
                    errs.append(f"{label}: row {r + 1}: no panel with id '{pid}'")
            if total != 12:
                errs.append(f"{label}: row {r + 1}: the widths add up to {total}, a row has 12 columns")
    for pid in panel_ids:
        where = placed.get(pid, [])
        if len(where) != 1:
            names = f" ({' and '.join(where)})" if tabs and where else ""
            errs.append(f"{'tabs' if tabs else 'layout'}: panel '{pid}' is placed {len(where)} times{names}, it must be placed once")


# What each role may read, mirrored from cube/cube.js (a test compares the two): a dashboard listing a role must not ask for what Cube
# refuses that role, or the panel would show an error for every reader.
PROFIT_MEMBERS = {"gross_profit", "margin_pct", "product_cost"}
INVENTORY_CUBES = {"inventory_health", "offer_performance"}
ROLE_CUBES = {"purchasing": {"inventory_health", "products"}, "marketing": {"inventory_health", "offer_performance", "products"}}
SUPPLIER_MEMBERS = {
    "vendor_id", "vendor_name", "unit_cost", "lead_time_days", "replenishment_type", "suggested_order_qty", "suggested_order_value",
    "suggested_order_qty_total", "suggested_order_value_total", "min_order_qty", "max_order_qty",
}


def denied(role, member):
    """Why Cube would refuse `role` this member, or None. The per-member part of the role rules (a panel must also reach an inventory cube
    for purchasing and marketing: see _role_errors)."""
    cube, _, name = member.partition(".")
    if role == "rep" and name in PROFIT_MEMBERS:
        return "profit and margin are hidden from reps"
    if role in ROLE_CUBES:
        if cube not in ROLE_CUBES[role]:
            return f"cube '{cube}' is not available to {role}"
        if role == "marketing" and cube == "inventory_health" and name in SUPPLIER_MEMBERS:
            return "supplier and order data are not available to marketing"
    if role in ("manager", "rep"):
        if cube in INVENTORY_CUBES:
            return "inventory data is not available for this role"
        if cube == "customers":
            return "customer data is admin-only"
    return None


def _role_errors(spec, errs):
    for p in spec["panels"]:
        w = f"panel '{p['id']}' ({p['type']})"
        members = [m for _, m, _ in _panel_members(p)]
        ignored = set(p.get("ignore_filters", []))
        members += [f["dimension"] for f in spec.get("filters", []) if f["id"] not in ignored] if members else []
        if p["type"] == "timeseries" or (p["type"] == "kpi" and "sparkline" in p):
            members.append(spec["time"]["dimension"])
        if not members:
            continue
        cubes = {m.partition(".")[0] for m in members}
        for role in spec.get("roles", []):
            for m in dict.fromkeys(members):
                why = denied(role, m)
                if why:
                    errs.append(f"{w}: role '{role}' cannot read '{m}' ({why}): remove the role from `roles` or the member from the panel")
            if role in ROLE_CUBES and not cubes & INVENTORY_CUBES:
                errs.append(f"{w}: role '{role}' cannot read '{members[0]}' ({role} may only query inventory data): remove the role from `roles` or the member from the panel")


def validate(spec, catalog):
    """-> (errors, used members). The member checks only run on a spec that passes the schema."""
    errs = schema_errors(spec)
    if errs:
        return errs, {}
    return semantic_errors(spec, catalog)
