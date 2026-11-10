"""The semantic layer for people who write dashboards: what the Cube model offers (cubes, measures, dimensions, what each means, which cubes
join, who may read what), as JSON for the builder's page and as docs/semantic-layer.md (generated: a test keeps it current)."""
from .catalog import rank
from .validate import denied

ROLES = ("admin", "editor", "viewer")


def _members(name, c, kind, role):
    rows = []
    for m, t in sorted(c[kind].items()):
        if role and denied(role, f"{name}.{m}"):
            continue
        key = c.get("sort_by", {}).get(m) if kind == "dimensions" else None
        label = f"{c['label_prefix']} {m.replace('_', ' ')}" if c.get("label_prefix") else None
        meta = c.get("measure_meta", {}).get(m, {}) if kind == "measures" else {}
        rows.append({"name": m, "member": f"{name}.{m}", "type": t, "description": c.get("docs", {}).get(m, ""), **({"sort_by": f"{name}.{key}"} if key else {}), **({"label": label} if label else {}),
                     **({"primary": rank(meta["primary"])} if meta.get("primary") else {}), **({"format": meta["format"]} if meta.get("format") else {})})          # what the model prefers and how it is shown
    return rows


def catalog_json(catalog, role=None):
    """Cubes with their members, descriptions and joins. With a role, only what that role may read (and where it is hidden otherwise)."""
    out = []
    readable = {n for n, c in catalog.cubes.items() if not role or any(not denied(role, f"{n}.{m}") for m in [*c["measures"], *c["dimensions"]])}
    for name, c in sorted(catalog.cubes.items()):
        ms, ds = _members(name, c, "measures", role), _members(name, c, "dimensions", role)
        if role and not (ms or ds):
            continue
        out.append({"cube": name, **({"extends": c["extends"]} if c.get("extends") else {}), **({"label_prefix": c["label_prefix"]} if c.get("label_prefix") else {}), "description": c.get("description", ""), "joins": sorted(j for j in (c["joins"] or ()) if j in readable),
                    "fact": catalog.kind(name) == "fact", **({"series": catalog.series(name)[0]} if catalog.series(name)[0] else {}), **({"color": catalog.series(name)[1]} if catalog.series(name)[1] else {}), "measures": ms, "dimensions": ds,
                    **({"rollup_dimensions": c["rollup_dimensions"]} if c.get("rollup_dimensions") else {})})          # for the designer's note on a slicer whose field no rollup has
    return out


def _how_facts_join(catalog):
    """The first bullets of the guide, written from the catalog: which dimensions each fact joins to, and how to show facts together (with a real pair of measures when two facts share one)."""
    facts = catalog.facts()
    out = ["- A **fact** cube (`meta: { kind: fact }`) holds events. Its measures can be grouped by the dimensions of the cubes it **joins to**: "
           + (("; ".join(f"`{f}` joins {', '.join(f'`{j}`' for j in sorted(catalog.cubes[f]['joins'] or []))}" for f in facts) + ".") if facts else "(this model has none).")]
    pair = next(((a, b, m) for a in facts for b in facts if a < b for m in catalog.cubes[a]["measures"] if m in catalog.cubes[b]["measures"]), None)
    together = f"`sum: [{pair[0]}.{pair[2]}, {pair[1]}.{pair[2]}]`" if pair else "`sum: [a.measure, b.measure]`"
    out.append(f"- Cube cannot join two fact cubes in one query. To show facts together, use {together}, a `ratio` of two sums or a stacked bar; there is no other arithmetic in a spec.")
    return out


def generate(catalog):
    out = ["# The semantic layer", "",
           "What the Cube model offers a dashboard: the **cubes** (a fact, which holds events, or a dimension, which describes them), their "
           "**measures** (numbers to add up or count) and **dimensions** (things to group or filter by: a region, a category, a date). A dashboard spec names "
           "these as `cube.member` and nothing else; every number comes from Cube, which also enforces who may read what.",
           "", "Generated from the model's cube files by `scripts/dashspec semantic` (descriptions come from the model files; "
           "a test keeps this page current). The guide is [dashboards.md](dashboards.md).", "",
           "## How to think about it", "",
           *_how_facts_join(catalog),
           "- A text dimension with a natural order (a month's name, a quarter's, a weekday's) **sorts by another dimension** of its cube, declared in the model as `meta: { sort_by: <number field> }` and shown below as \"Sorted by\": tables, pivots, filter lists and slicers order by that field, so months run January to December, not alphabetically.",
           "- Row-level security: a person only gets the values a row rule gives them (a rule for them or their groups), on every cube the rule covers, whatever the dashboard asks for.", "",
           "## Who can read what", "",
           "Not decided by a role: a person's **role** says what they may *do* (`viewer` views dashboards, `editor` also builds and shares them, `admin` administers), and what data they may read comes from the "
           "**datasets** and grants and the **row rules** in the admin console (see [admin.md](admin.md)): a cube or single field that sits in a dataset needs a grant, and the cubes a row rule covers are limited to the person's values. "
           "Cube enforces it on every query, so a dashboard that uses something a reader may not read shows Cube's refusal in that panel. Whole cubes or single fields can be kept back by a dataset.", ""]
    for c in catalog_json(catalog):
        out += [f"## `{c['cube']}`" + (" (fact)" if c["fact"] else ""), "", c["description"], ""]
        if c.get("extends"):
            out += [f"A role of `{c['extends']}`: the same calendar table and fields, joined by its own key; the fields are named \"{c['label_prefix']} ...\" in reports (e.g. \"{c['label_prefix']} month name\").", ""]
        if c["joins"]:
            out += [f"Joins: {', '.join(f'`{j}`' for j in c['joins'])}.", ""]
        for title, key in (("Measures", "measures"), ("Dimensions", "dimensions")):
            if not c[key]:
                continue
            out += [f"### {title}", "", "| Member | Type | Meaning |", "|---|---|---|"]
            for m in c[key]:
                meaning = m["description"] + (f" Sorted by `{m['sort_by']}`." if m.get("sort_by") else "")
                out.append(f"| `{m['member']}` | {m['type']} | {meaning} |")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


__all__ = ["catalog_json", "generate"]
