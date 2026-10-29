"""The semantic layer for people who write dashboards: what the Cube model offers (cubes, measures, dimensions, what each means, which cubes
join, who may read what), as JSON for the builder's page and as docs/semantic-layer.md (generated: a test keeps it current)."""
from .validate import INVENTORY_CUBES, PROFIT_MEMBERS, ROLE_CUBES, SUPPLIER_MEMBERS, denied

ROLES = ("admin", "manager", "rep", "purchasing", "marketing")
FACTS = ("internet_sales", "reseller_sales")


def _members(name, c, kind, role):
    rows = []
    for m, t in sorted(c[kind].items()):
        hidden = [r for r in ROLES if denied(r, f"{name}.{m}")]
        if role and role in hidden:
            continue
        key = c.get("sort_by", {}).get(m) if kind == "dimensions" else None
        rows.append({"name": m, "member": f"{name}.{m}", "type": t, "description": c.get("docs", {}).get(m, ""), "hidden_from": hidden, **({"sort_by": f"{name}.{key}"} if key else {})})
    return rows


def catalog_json(catalog, role=None):
    """Cubes with their members, descriptions and joins. With a role, only what that role may read (and where it is hidden otherwise)."""
    out = []
    readable = {n for n, c in catalog.cubes.items() if not role or any(not denied(role, f"{n}.{m}") for m in [*c["measures"], *c["dimensions"]])}
    for name, c in sorted(catalog.cubes.items()):
        ms, ds = _members(name, c, "measures", role), _members(name, c, "dimensions", role)
        if role and not (ms or ds):
            continue
        readers = [r for r in ROLES if any(not denied(r, f"{name}.{m}") for m in [*c["measures"], *c["dimensions"]])]
        out.append({"cube": name, "description": c.get("description", ""), "joins": sorted(j for j in (c["joins"] or ()) if j in readable),
                    "fact": name in FACTS, "measures": ms, "dimensions": ds, "readers": readers})
    return out


def generate(catalog):
    out = ["# The semantic layer", "",
           "What the Cube model offers a dashboard: the **cubes** (a fact such as `internet_sales`, or a dimension such as `products`), their "
           "**measures** (numbers: revenue, orders) and **dimensions** (things to group or filter by: region, category, a date). A dashboard spec names "
           "these as `cube.member` and nothing else; every number comes from Cube, which also enforces who may read what.",
           "", "Generated from `cube/model/cubes/*.yml` by `scripts/dashspec semantic` (descriptions come from the model files; "
           "a test keeps this page current). The guide is [dashboards.md](dashboards.md).", "",
           "## How to think about it", "",
           "- A **fact** cube holds events (order lines, inventory rows). Its measures can be grouped by the dimensions of the cubes it **joins to**: "
           "`internet_sales` and `reseller_sales` join `products`, `dates` and `territories`; `inventory_health` joins `products`.",
           "- Cube cannot join two fact cubes in one query. To show both sales channels together, use `sum: [internet_sales.revenue, reseller_sales.revenue]`, "
           "a `ratio` of two sums (a margin over both channels) or a stacked bar; there is no other arithmetic in a spec.",
           "- `orders` is the exact count of distinct orders (right under every filter, slower at scale); `orders_placed` counts each order once on its first line "
           "(fast, right for date, territory and channel, wrong for product filters).",
           "- `margin_pct` is in percentage points (0-100). For a percentage in a spec use a `ratio` of `gross_profit` over `revenue` with `format: pct`.",
           "- A text dimension with a natural order (a month's name, a quarter's, a weekday's) **sorts by another dimension** of its cube, declared in the model as `meta: { sort_by: <number field> }` and shown below as \"Sorted by\": tables, pivots, filter lists and slicers order by that field, so months run January to December, not alphabetically.",
           "- Row-level security: reps and managers only get the territories assigned to them, whatever the dashboard asks for.", "",
           "## Who can read what", "",
           "| Role | Can read |", "|---|---|",
           "| `admin` | everything |",
           "| `manager` | the sales facts and their dimensions, profit included; not inventory or customers; own territories only |",
           f"| `rep` | like a manager but **no profit members** ({', '.join(f'`{m}`' for m in sorted(PROFIT_MEMBERS))}); own territories only |",
           f"| `purchasing` | inventory data only (`{'`, `'.join(sorted(ROLE_CUBES['purchasing']))}`) |",
           f"| `marketing` | inventory and offer data (`{'`, `'.join(sorted(ROLE_CUBES['marketing']))}`), **no supplier or order-size members** ({', '.join(f'`{m}`' for m in sorted(SUPPLIER_MEMBERS))}) |",
           "", "A dashboard that lists a role must only use members that role can read; the validator checks it. Customer data is admin-only.", ""]
    for c in catalog_json(catalog):
        out += [f"## `{c['cube']}`" + (" (fact)" if c["fact"] else ""), "", c["description"], ""]
        if c["joins"]:
            out += [f"Joins: {', '.join(f'`{j}`' for j in c['joins'])}.", ""]
        out += [f"Readable by: {', '.join(f'`{r}`' for r in c['readers'])}.", ""]
        for title, key in (("Measures", "measures"), ("Dimensions", "dimensions")):
            if not c[key]:
                continue
            out += [f"### {title}", "", "| Member | Type | Meaning | Hidden from |", "|---|---|---|---|"]
            for m in c[key]:
                hidden = ", ".join(f"`{r}`" for r in m["hidden_from"]) or ""
                meaning = m["description"] + (f" Sorted by `{m['sort_by']}`." if m.get("sort_by") else "")
                out.append(f"| `{m['member']}` | {m['type']} | {meaning} | {hidden} |")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


__all__ = ["catalog_json", "generate", "INVENTORY_CUBES"]
