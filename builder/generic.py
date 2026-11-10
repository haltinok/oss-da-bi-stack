"""The rule-based stand-in for any model: reads a request with keywords and composes a dashboard from the catalog the role may read, knowing no cube or member by name.

What it knows about a model comes from the catalog (the fact cubes, each cube's first measure, how fields are named and joined) and from the model's optional
`vocabulary` in model.config.yml (`words`: a word, English or Turkish and without accents, to a member: `ciro: sales.revenue`; `labels`: a member to the name a
Turkish page shows). Without a vocabulary it understands the members' own names ("orders by region"). It builds a key-figures row, a time chart, a bar (or pie) per
field asked for, and a table; it does not edit an existing dashboard (that is for the YAML or a language model). A model with a hand-made recipe (builder/recipes) uses that.
"""
from __future__ import annotations

import re

from builder.composer import Composition, has, layout, norm

GRAN = (("year", ("yil", "year", "yearly", "annual", "yillik")), ("quarter", ("ceyrek", "quarter", "quarterly")), ("month", ("ay", "month", "monthly", "aylik")),
        ("week", ("hafta", "week", "weekly", "haftalik")), ("day", ("gun", "day", "daily", "gunluk")))
KEY_LIKE = re.compile(r"^(key|id)$|_(key|id)$")


def _stem(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _words(name: str) -> set[str]:
    return {_stem(w) for w in name.split("_") if w}


def _top_n(t: str) -> int | None:
    m = re.search(r"\b(?:top|best|first|en iyi|ilk)\s+(\d+)\b", t)
    return min(int(m.group(1)), 50) if m else None


def humanize(name: str) -> str:
    return name.replace("_", " ").capitalize()


class Model:
    """What the composer reads from a catalog."""

    def __init__(self, catalog):
        self.catalog = catalog
        self.vocab = {norm(k): v for k, v in ((catalog.config.get("vocabulary") or {}).get("words") or {}).items()}
        self.labels = (catalog.config.get("vocabulary") or {}).get("labels") or {}
        self.facts = [f for f in catalog.facts() if catalog.cubes[f]["measures"]]

    def is_measure(self, member: str) -> bool:
        cube, _, name = member.partition(".")
        return name in self.catalog.cubes.get(cube, {}).get("measures", {})

    def is_dimension(self, member: str) -> bool:
        cube, _, name = member.partition(".")
        return name in self.catalog.cubes.get(cube, {}).get("dimensions", {})

    def measures(self):
        return [f"{f}.{m}" for f in self.facts for m in self.catalog.cubes[f]["measures"]]

    def dimensions(self, measure: str) -> list[str]:
        """The text fields a measure can be grouped by: those of the cubes its cube joins to (a key is not one)."""
        fact = measure.partition(".")[0]
        out = []
        for cube, c in sorted(self.catalog.cubes.items()):
            if cube == fact or cube in self.facts or "time" in c["dimensions"].values() or not self.catalog.reachable(fact, cube):
                continue                                          # a calendar (a cube with a time field) is the time axis, not a breakdown
            out += [f"{cube}.{d}" for d, t in c["dimensions"].items() if t == "string" and not KEY_LIKE.search(d)]
        return out

    def time_dimension(self):
        configured = (self.catalog.config.get("time") or {}).get("dimension")
        if configured and self.is_dimension(configured):
            return configured
        for cube, c in sorted(self.catalog.cubes.items()):
            if cube not in self.facts:
                for d, t in c["dimensions"].items():
                    if t == "time":
                        return f"{cube}.{d}"
        return None

    def label(self, member: str, tr: bool) -> str:
        return (self.labels.get(member) if tr else None) or humanize(member.partition(".")[2])

    def fmt(self, member: str) -> str:
        meta = self.catalog.measure_meta(member).get("format")
        return meta if meta in ("money", "int", "pct", "decimal", "number") else "number"

    def pick_measures(self, tokens: list[str]) -> list[str]:
        """The measures a request names (by the vocabulary or by a word of the measure's own name), in the order said; else each fact's first."""
        named: list[str] = []
        for tok in tokens:
            hit = [self.vocab[tok]] if self.vocab.get(tok) and self.is_measure(self.vocab[tok]) else [m for m in self.measures() if _stem(tok) in _words(m.partition(".")[2])]
            named += [m for m in hit if m not in named]
        if named:
            return named[:6]
        firsts = [f"{f}.{self.catalog.primary(f)}" for f in self.facts]
        return [m for m in firsts if self.is_measure(m)][:4]

    def pick_dimensions(self, tokens: list[str], measures: list[str]) -> list[str]:
        """The fields a request groups by: by the vocabulary, a word of the field's name, or the name of its cube (a field called `name` then)."""
        reachable = {d for m in measures for d in self.dimensions(m)}
        named: list[str] = []
        for tok in tokens:
            hit = [self.vocab[tok]] if self.vocab.get(tok) in reachable else [d for d in sorted(reachable) if _stem(tok) in _words(d.partition(".")[2])]
            if not hit:
                cube = [d for d in sorted(reachable) if _stem(tok) in _words(d.partition(".")[0])]
                hit = [next((d for d in cube if d.endswith(".name")), cube[0])] if cube else []
            named += [d for d in hit if d not in named]
        return named


def compose(prompt: str, catalog, role: str, current_yaml: str | None = None, focus: str | None = None) -> Composition:
    if current_yaml:
        return Composition(reason="On this model the rule-based stand-in builds a new dashboard from your request; to change this one, edit the YAML or use a language model.")
    model = Model(catalog)
    if not model.facts:
        return Composition(reason="This model has no fact cubes you can read, so there is nothing to build a dashboard from.")
    t = norm(prompt)
    tr = has(t, "turkish", "turkce", "lira", "turk") and not has(t, "english", "ingilizce")
    measures = model.pick_measures(t.split())
    time_dim = model.time_dimension()
    if not time_dim:
        return Composition(reason="This model has no time field to build a dashboard on.")
    dims = model.pick_dimensions(t.split(), measures)
    gran = next((g for g, words in GRAN if has(t, *words)), None)
    top = _top_n(t)
    pie, table = has(t, "pie", "pasta", "donut", "halka"), has(t, "table", "list", "latest", "tablo", "liste")
    want_time = bool(gran) or has(t, "trend", "over time", "history", "zaman") or not (dims or table or pie)
    years = catalog.year_fields()
    year = next(iter(sum(years.values(), [])), None) if years else None
    panels, filters, ids = [], [], set()

    def pid(base):
        n, name = 1, base
        while name in ids:
            n += 1
            name = f"{base}_{n}"
        ids.add(name)
        return name

    def add_filter(member, label):
        fid = member.partition(".")[2]
        if not any(f["id"] == fid for f in filters):
            filters.append({"id": fid, "dimension": member, "label": label})
        return fid

    reach_time = [m for m in measures if catalog.reachable(m.partition(".")[0], time_dim.partition(".")[0])]
    year_filter = add_filter(year, humanize(year.partition(".")[2])) if year else None
    kpi = {"id": pid("kpis"), "type": "kpi", "measures": [{"member": m, "label": model.label(m, tr), "format": model.fmt(m)} for m in measures[:8]]}
    if reach_time and len(reach_time) == len(measures[:8]):
        kpi["sparkline"] = {"granularity": "month"}
    if year_filter and reach_time:
        kpi["compare"] = "previous_year"
    panels.append(kpi)
    if want_time and reach_time:
        series = [{"member": m, "label": model.label(m, tr), "format": model.fmt(m), **({"color": catalog.series(m.partition(".")[0])[1]} if catalog.series(m.partition(".")[0])[1] else {})} for m in reach_time[:3]]
        chart = {"id": pid("trend"), "type": "timeseries", "title": ", ".join(s["label"] for s in series), "series": series, "granularity": gran or "month", "style": "line"}
        if year_filter:
            chart["on_click"] = {"set_filter": year_filter}
        panels.append(chart)
    for d in dims[:3]:
        m = next((x for x in measures if d in model.dimensions(x)), None)
        if not m:
            continue
        label = model.label(d, tr)
        fid = add_filter(d, label)
        base = {"title": f"{model.label(m, tr)} / {label}", "by": d, "measure": m, "format": model.fmt(m), "on_click": {"set_filter": fid}}
        if pie and d == dims[0]:
            panels.append({"id": pid("pie"), "type": "pie", **base, "limit": 8})
        else:
            panels.append({"id": pid(f"by_{d.partition('.')[2]}"), "type": "bar", **base, "sort": "desc", "limit": top or 10})
    if table:
        d = dims[:2] or [x for x in model.dimensions(measures[0])[:1]]
        cols = [*d, *measures[:3]]
        if d:
            panels.append({"id": pid("table"), "type": "table", "title": ", ".join(model.label(c, tr) for c in cols[:3]), "columns": cols, "order": {measures[0]: "desc"}, "limit": top or 15})
    heard = [f"measures: {', '.join(model.label(m, tr).lower() for m in measures)}"] + ([f"by: {', '.join(model.label(d, tr).lower() for d in dims)}"] if dims else []) + ([f"time step: {gran}"] if gran else [])
    spec = {"spec": 1, "id": "draft", "title": " · ".join(model.label(m, tr) for m in measures[:2]), "description": ("İstek: " if tr else "Built from: ") + " ".join(prompt.split())[:180],
            "locale": catalog.config.get("locale") or ("tr-TR" if tr else "en-US"), "currency": catalog.config.get("currency") or ("TRY" if tr else "USD"),
            "time": {"dimension": time_dim}, "filters": filters, "panels": panels}
    spec["layout"] = layout(spec["panels"])
    return Composition(spec=spec, notes=[("Anladığım: " if tr else "Understood: ") + "; ".join(heard) + "."])


def _say(member: str) -> str:
    """How a request names a field: its own name, or its cube's (singular) when it is just called `name` ("dealer", not "name")."""
    cube, _, name = member.partition(".")
    return (_stem(cube) if name == "name" else name).replace("_", " ")


def example_requests(catalog) -> list[tuple[str, str]]:
    """[(what the example shows, a request for it)]: what the model's prompt is shown, made from this catalog's first facts, measures and fields."""
    model = Model(catalog)
    measures = [m for m in (f"{f}.{catalog.primary(f)}" for f in model.facts) if model.is_measure(m)]
    if not measures:
        return []
    dims = model.pick_dimensions([_stem(w) for m in measures for d in model.dimensions(m)[:3] for w in d.partition(".")[2].split("_")], measures)[:2] or model.dimensions(measures[0])[:2]
    said = [m.partition(".")[2].replace("_", " ") for m in measures[:2]]
    by = " and ".join(_say(d) for d in dims)
    return [("a dashboard with key figures, a time chart, breakdowns and a table", f"{' and '.join(said)} by month" + (f", by {by}" if by else "") + ", a table")]


def suggestions(catalog) -> dict[str, list[str]]:
    """The requests the builder page offers: {en: [...], tr: [...]}, from this catalog (the model's own `builder.examples` win, see composer.suggestions)."""
    asks = [ask for _, ask in example_requests(catalog)]
    model = Model(catalog)
    measure = next((f"{f}.{catalog.primary(f)}" for f in model.facts), None)
    if measure:
        said = measure.partition(".")[2].replace("_", " ")
        asks += [f"{said} by month"] + [f"{said} by {_say(d)}" for d in model.dimensions(measure)[:2]]
    return {"en": asks[:4], "tr": asks[:4]}
