"""The example queries the SQL lab offers: the model's own (`lab.examples` in model.config.yml) or, when it has none, ones made from the catalog.

An example in the config lists the `cubes` it reads, so it is only offered to a person who can read them all:
  lab:
    examples:
      - { title: { en: Revenue by category, tr: Kategoriye göre ciro }, cubes: [sales, items], sql: "select category, measure(revenue) from sales cross join items group by 1 order by 2 desc" }
"""


def _humanize(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _text_dimension(cube: dict, fact: dict):
    """The first plain text dimension of `cube` that is not a key and whose name is not also a field of the fact (so the SQL needs no prefix)."""
    taken = {m["name"] for m in [*fact["measures"], *fact["dimensions"]]}
    return next((d for d in cube["dimensions"] if d["type"] == "string" and d["name"] not in taken and d["name"] not in ("key", "id") and not d["name"].endswith(("_key", "_id"))), None)


def made_from(visible: list[dict], facts: list[str], primary) -> list[dict]:
    """Up to three examples from the cubes a person can read: the first fact's first measure by a text field of each cube it joins to. `primary(cube)` is the catalog's first measure."""
    by_name = {c["name"]: c for c in visible}
    out = []
    for fact_name in facts:
        fact = by_name.get(fact_name)
        measure = primary(fact_name)
        if not fact or measure not in {m["name"] for m in fact["measures"]}:
            continue
        for joined in fact["joins"]:
            other = by_name.get(joined)
            dim = _text_dimension(other, fact) if other else None
            if dim:
                title = f"{_humanize(measure)} by {dim['name'].replace('_', ' ')}"
                out.append({"title": {"en": title, "tr": f"{_humanize(dim['name'])} bazında {measure.replace('_', ' ')}"},
                            "sql": f"select {dim['name']}, measure({measure}) as {measure}\nfrom {fact_name} cross join {joined}\ngroup by 1\norder by 2 desc"})
            if len(out) == 3:
                return out
    return out


def examples_for(catalog, visible: list[dict]) -> list[dict]:
    """[{ title: { en, tr }, sql }] for a person who can read the cubes in `visible` (the lab's schema)."""
    names = {c["name"] for c in visible}
    own = [{"title": e["title"], "sql": e["sql"]} for e in ((catalog.config.get("lab") or {}).get("examples") or []) if e.get("cubes") and set(e["cubes"]) <= names]
    return own or made_from(visible, catalog.facts(), catalog.primary)
