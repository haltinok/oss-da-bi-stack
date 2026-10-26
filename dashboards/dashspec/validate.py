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
    if err.validator == "oneOf" and err.context and all(c.validator == "required" for c in err.context):
        return "needs a 'member' (or a 'sum' / 'ratio' of measures, with a 'label')"
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


def _panel_members(p):
    """(field, member, wanted kind) for every Cube member a panel names; wanted is measure | dimension | any."""
    t = p["type"]
    if t == "kpi":
        for i, m in enumerate(p["measures"]):
            if "member" in m:
                yield f"measures[{i}].member", m["member"], "measure"
            for j, s in enumerate(m.get("sum", [])):
                yield f"measures[{i}].sum[{j}]", s, "measure"
            for part in ("num", "den"):
                for j, s in enumerate(m.get("ratio", {}).get(part, [])):
                    yield f"measures[{i}].ratio.{part}[{j}]", s, "measure"
    elif t == "timeseries":
        for i, s in enumerate(p["series"]):
            yield f"series[{i}].member", s["member"], "measure"
    elif t == "bar":
        yield "measure", p["measure"], "measure"
        yield "by", p["by"], "dimension"
        if "split" in p:
            yield "split", p["split"], "dimension"
    elif t == "treemap":
        yield "measure", p["measure"], "measure"
        for i, g in enumerate(p["group"]):
            yield f"group[{i}]", g, "dimension"
    elif t == "table":
        for i, c in enumerate(p["columns"]):
            yield f"columns[{i}]", column_member(c), "any"


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

    panel_ids = [p["id"] for p in spec["panels"]]
    for dup in sorted({i for i in panel_ids if panel_ids.count(i) > 1}):
        errs.append(f"dashboard: panels: id '{dup}' is used by more than one panel")

    for p in spec["panels"]:
        w = f"panel '{p['id']}' ({p['type']})"
        kinds = {}
        for field, member, want in _panel_members(p):
            kinds[member] = check(w, field, member, want)
        for fid in p.get("ignore_filters", []):
            if fid not in filter_ids:
                errs.append(f"{w}: ignore_filters: no filter with id '{fid}'")
        click = p.get("on_click", {}).get("set_filter")
        if click is not None:
            ids = [click] if isinstance(click, str) else click
            for fid in ids:
                if fid not in filter_ids:
                    errs.append(f"{w}: on_click.set_filter: no filter with id '{fid}'")
            carried = {"timeseries": 1, "treemap": len(p.get("group", []))}.get(p["type"])
            if carried is not None and len(ids) > carried:
                errs.append(f"{w}: on_click.set_filter: a click carries {carried} value(s) here, {len(ids)} filters are named")
        if p["type"] == "table":
            shown = [column_member(c) for c in p["columns"]]
            for col in p.get("order", {}):
                if col not in shown:
                    errs.append(f"{w}: order.{col}: not one of the table's columns")
        _join_errors(spec, p, w, catalog, errs)

    _layout_errors(spec, panel_ids, errs)
    return errs, used


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


def _layout_errors(spec, panel_ids, errs):
    placed = []
    for r, row in enumerate(spec["layout"]):
        total = 0
        for cell in row:
            (pid, span), = cell.items()
            total += span
            placed.append(pid)
            if pid not in panel_ids:
                errs.append(f"layout: row {r + 1}: no panel with id '{pid}'")
        if total != 12:
            errs.append(f"layout: row {r + 1}: the widths add up to {total}, a row has 12 columns")
    for pid in panel_ids:
        n = placed.count(pid)
        if n != 1:
            errs.append(f"layout: panel '{pid}' is placed {n} times, it must be placed once")


def validate(spec, catalog):
    """-> (errors, used members). The member checks only run on a spec that passes the schema."""
    errs = schema_errors(spec)
    if errs:
        return errs, {}
    return semantic_errors(spec, catalog)
