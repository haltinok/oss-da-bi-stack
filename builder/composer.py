"""The rule-based stand-in for the model: reads a request with keywords (English and Turkish) and composes a dashboard spec from the catalog the
role may read. It is not an LLM: it understands a fixed set of phrases (measures, a time axis, breakdowns, top N, a table, a treemap, filters,
clicks, Turkish and lira) and says so when it understood nothing. It exists so the builder, its page and its tests run without an API key; the
loop around it (core.run_build) and the checks are the ones the real model goes through."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml
from dashspec import catalog as cat
from dashspec import slicers as slicer_rules
from dashspec.validate import denied

TR_MAP = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iissgguuoocc")


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower().translate(TR_MAP)).strip()


def has(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}", text) for w in words)


def word(text: str, *words: str) -> bool:
    """Whole words only: "ay" (month) must not match "ayrica" (also)."""
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def chart_segments(t: str) -> list[tuple[str, list[str]]]:
    """"…a chart for internet… also a second chart for reseller…": the pieces of the request that name a channel, as (cube, time levels named there)."""
    out = []
    for part in re.split(r"\b(?:ayrica|also|furthermore|ikinci bir|second|bir de)\b", t):
        internet, reseller = word(part, "internet", "online"), word(part, "reseller", "bayi")
        if internet == reseller:
            continue
        out.append(("internet_sales" if internet else "reseller_sales", drill_levels(part)))
    return out if len({c for c, _ in out}) == 2 else []


def drill_levels(t: str) -> list[str]:
    """The time levels named in the request, coarse to fine: "Yıl Ay ve Gün" -> [year, month, day]."""
    named = [(g, word(t, *w)) for g, w in (("year", ("yil", "year", "yillik", "yearly", "annual")), ("quarter", ("ceyrek", "quarter", "quarterly")),
                                           ("month", ("ay", "month", "aylik", "monthly")), ("week", ("hafta", "week", "weekly", "haftalik")), ("day", ("gun", "day", "gunluk", "daily")))]
    return [g for g, on in named if on]


L = {  # label -> (English, Turkish)
    "revenue": ("Revenue", "Gelir"), "gross_profit": ("Gross profit", "Brüt kâr"), "margin": ("Gross margin", "Brüt marj"), "orders": ("Orders", "Siparişler"),
    "units": ("Units sold", "Satılan adet"), "aov": ("Avg order value", "Ort. sipariş tutarı"), "internet": ("Internet", "İnternet"), "reseller": ("Reseller", "Bayi"),
    "fy": ("Fiscal year", "Mali yıl"), "region": ("Region", "Bölge"), "country": ("Country", "Ülke"), "category": ("Category", "Kategori"),
    "subcategory": ("Subcategory", "Alt kategori"), "product": ("Product", "Ürün"), "status": ("Status", "Durum"), "order": ("Order", "Sipariş"), "date": ("Date", "Tarih"),
    "mix": ("Product mix", "Ürün karması"), "latest": ("Latest orders", "Son siparişler"), "products": ("Products", "Ürün"), "stockout": ("Out of stock", "Stoksuz"),
    "reorder": ("Reorder now", "Sipariş gerekli"), "overstock": ("Overstock", "Fazla stok"), "dead": ("Dead stock", "Ölü stok"), "suggested": ("Suggested order value", "Önerilen sipariş tutarı"),
    "excess": ("Excess stock value", "Fazla stok tutarı"), "vendor": ("Vendor", "Tedarikçi"), "on_hand": ("On hand", "Eldeki"), "on_order": ("On order", "Siparişte"),
    "cover": ("Days of cover", "Kapsama (gün)"), "qty": ("Suggested qty", "Önerilen adet"), "excess_units": ("Excess units", "Fazla adet"), "discount": ("Suggested discount %", "Önerilen indirim %"),
    "by": ("{m} by {d}", "{d} bazında {m}"), "monthly": ("{m} by month", "Aylık {m}"), "trend": ("{m} over time", "Zaman içinde {m}"), "sales": ("Sales dashboard", "Satış panosu"),
    "pivot": ("{m} by {d} and {c}", "{d} ve {c} bazında {m}"), "month": ("month", "ay"), "quarter": ("quarter", "çeyrek"),
    "inventory": ("Inventory dashboard", "Envanter panosu"), "drilltitle": ("{m}: year, month, day", "{m}: yıl, ay, gün"), "built": ("Built from: {p}", "İstek: {p}"), "product_name": ("Product", "Ürün"),
    "stock_status": ("Products by status", "Duruma göre ürün sayısı"), "reorder_list": ("Reorder list", "Yeniden sipariş listesi"), "excess_list": ("Excess and dead stock", "Fazla ve ölü stok"),
    "vendor_value": ("Suggested order value by vendor", "Tedarikçiye göre önerilen sipariş tutarı"), "granularity": ("", ""),
    "color": ("Color", "Renk"), "group": ("Sales group", "Satış grubu"),
}


@dataclass
class Composition:
    spec: dict | None = None
    reason: str = ""
    notes: list[str] = field(default_factory=list)


def _top_n(t: str) -> int | None:
    m = re.search(r"\b(?:top|best|first|en iyi|ilk)\s+(\d+)\b", t) or re.search(r"\b(\d+)\s+(?:best|top|products|urun)", t)
    return min(int(m.group(1)), 50) if m else None


# ---- slicers: "a slicer for colour", "colour and country slicers", "make region a slicer", "renk dilimleyici", "bölge filtresini dilimleyici yap"
SLICER_WORD = re.compile(r"^(slicer|dilimleyic)")
SLICER_FIELDS = (            # key -> token prefixes, longest first where one contains another
    ("subcategory", (("subcategor",), ("alt", "kategori"))), ("category", (("categor",), ("kategori",))),
    ("group", (("sales", "group"), ("territory", "group"), ("satis", "grub"), ("group",), ("grup",), ("grub",))),
    ("color", (("colo",), ("renk",), ("reng",))), ("region", (("region",), ("territor",), ("bolge",))), ("country", (("countr",), ("ulke",))),
    ("fy", (("fiscal", "year"), ("mali", "yil"), ("year",), ("yil",))), ("status", (("status",), ("durum",))),
    ("vendor", (("vendor",), ("supplier",), ("tedarik",))), ("product", (("product",), ("urun",))),
)
LEAD = {"for", "on", "of", "by", "a", "an", "the", "per", "with", "icin", "olarak"}          # "slicer for colour", "slicers on the country"
AND = {"and", "or", "ve", "veya", "ile"}                                                   # "colour and country slicers", "slicers for colour and country"
BEFORE = {"a", "an", "the", "as", "into", "to", "bir", "olarak", "icin", "gore", "filter", "filters", "filtre", "filtresi", "filtresini", "filtreyi"}   # "make the region filter a slicer"


def _field_at(tokens: list[str], i: int, backwards: bool = False) -> tuple[str, int] | None:
    """The slicer field whose words start at token i (or end there, going backwards), and how many tokens it takes."""
    for key, forms in SLICER_FIELDS:
        for form in forms:
            start = i - len(form) + 1 if backwards else i
            if start >= 0 and start + len(form) <= len(tokens) and all(tokens[start + k].startswith(w) for k, w in enumerate(form)):
                return key, len(form)
    return None


def _fields_from(tokens: list[str], i: int, step: int, skip: set[str]) -> tuple[list[str], set[int]]:
    """The fields named next to the slicer word at i, walking forwards (step 1) or backwards (-1): first past the words in `skip`, then a field, and
    more fields, side by side or joined by "and"."""
    found, used, j = [], set(), i + step
    while 0 <= j < len(tokens) and tokens[j] in skip:
        j += step
    while 0 <= j < len(tokens):
        hit = _field_at(tokens, j, backwards=step < 0)
        if not hit:
            break
        found.append(hit[0])
        span = range(j, j + hit[1]) if step > 0 else range(j - hit[1] + 1, j + 1)
        used.update(span)
        j = (span[-1] if step > 0 else span[0]) + step
        if 0 <= j < len(tokens) and tokens[j] in AND:             # "colour and country"; a list's commas are already spaces ("colour, country")
            j += step
    return (found if step > 0 else found[::-1]), used


def slicer_fields(t: str) -> tuple[bool, list[str], str]:
    """(a slicer was asked for, the fields named for slicers in order, the text without those words): the fields are the words right after the
    slicer word ("slicer for colour and country") or, when none follow, right before it ("make region a slicer", "colour and country slicers").
    The words a slicer took are not read again as breakdowns, so "a slicer for country" does not also add a bar chart by country."""
    tokens, used, keys, said = t.split(), set(), [], False
    for i, tok in enumerate(tokens):
        if not SLICER_WORD.match(tok):
            continue
        said = True
        found, took = _fields_from(tokens, i, 1, LEAD)
        if not found:
            found, took = _fields_from(tokens, i, -1, BEFORE)
        used |= took
        keys += [k for k in found if k not in keys]
    return said, keys, (" ".join(w for k, w in enumerate(tokens) if k not in used) if used else t)


def parse(prompt: str) -> dict:
    slicer_said, slicers, t = slicer_fields(norm(prompt))
    wants = {k: has(t, *w) for k, w in {
        "revenue": ("revenue", "sales", "gelir", "satis", "ciro"), "profit": ("profit", "kar"), "margin": ("margin", "marj"), "orders": ("order", "siparis"),
        "units": ("units", "quantity", "adet", "aded", "miktar"), "aov": ("average order", "avg order", "aov", "ortalama siparis"),
    }.items()}
    stripped = re.sub(r"average order\w*|avg order\w*|ortalama siparis\w*", " ", t)        # "average order value" is not a request for the number of orders
    wants["orders"] = has(stripped, "order", "siparis") and not has(t, "latest order", "last order", "orders table", "list of order", "son siparis")
    return {
        "t": t, "wants": wants, "top": _top_n(t),
        "inventory": has(t, "inventory", "stock", "reorder", "overstock", "envanter", "stok", "supplier", "vendor", "tedarik", "excess"),
        "tr": has(t, "turkish", "turkce", "lira", "turk") and not has(t, "english", "ingilizce"),
        "internet_only": has(t, "internet", "online") and not has(t, "reseller", "bayi", "channel", "kanal"),
        "reseller_only": has(t, "reseller", "bayi") and not has(t, "internet", "online", "channel", "kanal"),
        "by_channel": has(t, "channel", "kanal"),
        "drill": has(t, "drill", "detaya", "detay") and len(drill_levels(t)) >= 2, "levels": drill_levels(t),
        "pie": has(t, "pie", "pasta", "donut", "halka"), "area": has(t, "area", "alan grafik"),
        "column": has(t, "column", "sutun", "dikey", "kolon"),
        # the key figures' comparison: "previous period" (the month or range before), else any word about a comparison means the year before
        "compare": ("previous_period" if has(t, "previous period", "prior period", "period before", "onceki donem", "bir onceki donem") else
                    "previous_year" if has(t, "compar", "previous year", "prior year", "last year", "year over year", "yoy", "growth", "vs last", "versus last",
                                           "karsilastir", "gecen yil", "onceki yil", "gecen yila", "onceki yila", "buyume") else None),
        "separate": has(t, "ayri", "separate", "ikinci", "second", "half", "yarim", "iki chart", "iki grafik", "two chart", "each channel", "her kanal", "her biri"),
        "chart_segments": chart_segments(t),
        "gran": next((g for g, w in (("quarter", ("quarter", "ceyrek")), ("year", ("yearly", "annual", "by year", "yillik", "per year")), ("day", ("daily", "by day", "gunluk")),
                                     ("month", ("month", "aylik", "monthly"))) if has(t, *w)), None),
        "trend": has(t, "trend", "over time", "time series", "zaman", "history"),
        "dims": [d for d, rx in (("region", r"\b(region|territor|bolge)"), ("country", r"\b(country|countries|ulke)"),
                                 ("category", r"\b(?<!sub)categor|(?<!alt )\bkategori"), ("subcategory", r"subcategor|alt kategori"),
                                 ("product", r"\b(product|urun)(?!\w* (alt kategori|subcategor))")) if re.search(rx, t)],
        "pivot": has(t, "pivot", "crosstab", "cross-tab", "cross tab", "matrix", "capraz", "heatmap", "heat map", "isi haritasi"),
        "heat": has(t, "heatmap", "heat map", "heat", "shaded", "shade", "isi haritasi"),
        "table": has(t, "table", "list", "latest order", "last order", "detail", "tablo", "liste", "son siparis"),
        "treemap": has(t, "treemap", "mix", "composition", "share", "karma"),
        "clickable": has(t, "click", "cross filter", "interactive", "tikla"),
        "style": next((s for s, w in (("stacked-bar", ("stacked",)), ("area", ("area", "alan grafik")), ("line", ("line", "cizgi")), ("bar", ("bar chart", "bars", "column", "kolon", "sutun"))) if has(t, *w)), None),
        "slicer_said": slicer_said, "slicers": slicers,
        "filters": [f for f, w in (("fy", ("fiscal", "year filter", "filter by year", "yil")), ("region", ("filter by region", "region filter", "bolge filtre")),
                                   ("category", ("filter by category", "category filter", "kategori filtre")), ("country", ("filter by country", "country filter"))) if has(t, *w)],
    }


class Builder:
    """Composes (or edits) one spec for one role. `cat` is the catalog the role can read."""

    def __init__(self, catalog: cat.Catalog, role: str, p: dict):
        self.catalog, self.role, self.p, self.tr = catalog, role, p, p["tr"]
        self.panels: list[dict] = []
        self.filters: list[dict] = []
        self.notes: list[str] = []
        self.ids: set[str] = set()

    # ---- helpers
    def lab(self, key: str, **kw) -> str:
        if self.tr and "m" in kw and key != "drilltitle":
            kw["m"] = kw["m"].lower()                 # "Bölge bazında gelir": the measure inside a sentence is not capitalised
        return L[key][1 if self.tr else 0].format(**kw)

    def can(self, member: str) -> bool:
        c, _, n = member.partition(".")
        return c in self.catalog.cubes and (n in self.catalog.cubes[c]["measures"] or n in self.catalog.cubes[c]["dimensions"])

    def pid(self, base: str) -> str:
        i, name = 1, base
        while name in self.ids:
            i += 1
            name = f"{base}_{i}"
        self.ids.add(name)
        return name

    def add_filter(self, fid: str, dim: str, label_key: str, parent: str | None = None) -> str | None:
        if not self.can(dim):
            return None
        if not any(f["id"] == fid for f in self.filters):
            self.filters.append({"id": fid, "dimension": dim, "label": self.lab(label_key), **({"parent": parent} if parent else {})})
        return fid

    def channels(self) -> list[str]:
        out = [c for c in ("internet_sales", "reseller_sales") if c in self.catalog.cubes]
        if self.p["internet_only"] and "internet_sales" in out:
            return ["internet_sales"]
        if self.p["reseller_only"] and "reseller_sales" in out:
            return ["reseller_sales"]
        return out

    def term(self, key: str, fmt: str) -> dict | None:
        """A KPI/series measure over the chosen channels: member, sum or ratio."""
        ch = self.channels()
        m = {"revenue": "revenue", "gross_profit": "gross_profit", "orders": "orders", "units": "units"}
        if key in m:
            members = [f"{c}.{m[key]}" for c in ch]
            if not members or any(denied(self.role, x) for x in members):
                return None
            return ({"member": members[0], "label": self.lab(key), "format": fmt} if len(members) == 1 else {"sum": members, "label": self.lab(key), "format": fmt})
        num, den = ({"margin": ("gross_profit", "revenue"), "aov": ("revenue", "orders")}[key])
        n, d = [f"{c}.{num}" for c in ch], [f"{c}.{den}" for c in ch]
        if not n or any(denied(self.role, x) for x in [*n, *d]):
            return None
        return {"ratio": {"num": n, "den": d}, "label": self.lab(key), "format": "pct" if key == "margin" else "money"}


def compose(prompt: str, catalog: cat.Catalog, role: str, current_yaml: str | None = None, focus: str | None = None) -> Composition:
    p = parse(prompt)
    if current_yaml:
        return refine(p, prompt, catalog, role, current_yaml, focus)
    if p["inventory"]:
        return compose_inventory(p, prompt, catalog, role)
    return compose_sales(p, prompt, catalog, role)


# ------------------------------------------------------------------------------------------------------------------ sales
def compose_sales(p, prompt, catalog, role) -> Composition:
    b = Builder(catalog, role, p)
    if not b.channels():
        return Composition(reason="Sales data is not available for your role." + (" Ask for an inventory dashboard instead." if "inventory_health" in catalog.cubes else ""))
    w = p["wants"]
    keys = [k for k, on in (("revenue", w["revenue"]), ("gross_profit", w["profit"]), ("margin", w["margin"]), ("orders", w["orders"]), ("units", w["units"]), ("aov", w["aov"])) if on]
    if not keys:
        keys = ["revenue", "orders", "aov", "units"]
    terms, left_out = [], []
    for k in keys:
        t = b.term(k, "money" if k in ("revenue", "gross_profit") else "int")
        (terms if t else left_out).append(t or L[k][0].lower())
    if left_out:
        b.notes.append(f"Left out because your role cannot read it: {', '.join(left_out)}.")
    if not terms:
        return Composition(reason="None of the figures you asked for are available for your role (profit and margin are hidden from reps).", notes=b.notes)
    b.ids.update({"kpis"})
    # the fiscal-year filter below is always there, so the tiles compare with the year before by default (with "All" chosen they say there is no period to compare)
    b.panels.append({"id": "kpis", "type": "kpi", "measures": terms[:8], "sparkline": {"granularity": "month"}, "compare": p["compare"] or "previous_year"})
    fid = b.add_filter("fy", "dates.fiscal_year", "fy")
    dims = p["dims"] + ([] if p["dims"] else (["region"] if has(p["t"], "region", "territor", "bolge") else []))
    want_time = p["trend"] or p["gran"] or p["drill"] or p["style"] in ("line", "area") or not (p["dims"] or p["table"] or p["treemap"] or p["pie"] or p["pivot"])
    if p["pivot"] and not (p["trend"] or p["drill"] or p["style"] in ("line", "area")):
        want_time = False                                  # "revenue by category and month as a pivot" asks for the pivot, not also for a time chart
    pivot_dims = (["category", "subcategory"] if "category" in dims and "subcategory" in dims else dims[:1] or ["category"]) if p["pivot"] else []
    clickable = True                                       # charts filter the other panels on a click: it is what a dashboard is for
    prim = next((k for k in keys if k in ("revenue", "orders", "units", "gross_profit")), "revenue")
    if len(p["chart_segments"]) >= 2:
        inherit = next((lv for _, lv in p["chart_segments"] if len(lv) >= 2), [])
        for cube, lv in p["chart_segments"]:
            if denied(role, f"{cube}.{prim}"):
                continue
            ch = "internet" if cube == "internet_sales" else "reseller"
            levels = lv if len(lv) >= 2 else (inherit if p["drill"] or inherit else [])
            gran = levels[0] if levels else (p["gran"] or "month")
            panel = {"id": b.pid(f"trend_{ch}"), "type": "timeseries", "title": f"{b.lab(ch)}: {b.lab(prim)}", "granularity": gran, "style": p["style"] or "line",
                     "series": [{"member": f"{cube}.{prim}", "label": b.lab(ch), "color": ch, "format": "money" if prim in ("revenue", "gross_profit") else "int"}]}
            if len(levels) >= 2:
                panel["drill"] = levels
            else:
                panel["granularities"] = ["month", "quarter", "year"]
                if fid and clickable:
                    panel["on_click"] = {"set_filter": fid}
            b.panels.append(panel)
        want_time = False
    if want_time:
        series = [{"member": f"{c}.{ {'revenue': 'revenue', 'gross_profit': 'gross_profit', 'orders': 'orders', 'units': 'units'}[prim] }", "label": b.lab("internet" if c == "internet_sales" else "reseller"),
                   "color": "internet" if c == "internet_sales" else "reseller", "format": "money" if prim in ("revenue", "gross_profit") else "int"}
                  for c in b.channels() if not denied(role, f"{c}.{prim}")]
        levels = p["levels"] if p["drill"] else []
        gran = levels[0] if levels else (p["gran"] or "month")
        style = p["style"] or ("stacked-bar" if len(series) > 1 and not levels else "line")
        panel = {"id": b.pid("trend"), "type": "timeseries", "title": b.lab("monthly" if gran == "month" else "trend", m=b.lab(prim)), "series": series, "granularity": gran, "style": style}
        if levels:
            panel["drill"] = levels                                   # a click opens the next level and filters the other panels to the period
            panel["title"] = b.lab("drilltitle", m=b.lab(prim))
        else:
            if gran in ("month", "quarter", "year"):
                panel["granularities"] = ["month", "quarter", "year"]
            if fid and clickable:
                panel["on_click"] = {"set_filter": fid}
        b.panels.append(panel)
    dim_members = {"region": "territories.region", "country": "territories.country", "category": "products.category", "subcategory": "products.subcategory", "product": "products.name"}
    pie_dim = next((d for d in ("subcategory", "category", "region", "country", "product") if d in dims), "category") if p["pie"] else None
    if pie_dim and b.can(dim_members[pie_dim]) and not denied(role, f"{b.channels()[0]}.{prim}"):
        c0 = b.channels()
        pf = b.add_filter({"region": "region", "country": "country", "category": "category", "subcategory": "subcategory"}.get(pie_dim, "x"), dim_members[pie_dim], pie_dim) if pie_dim != "product" else None
        measure_members = [f"{c}.{prim}" for c in c0 if not denied(role, f"{c}.{prim}")]
        pie = {"id": b.pid("pie"), "type": "pie", "title": b.lab("by", m=b.lab(prim), d=b.lab("products" if pie_dim == "product" else pie_dim)),
               "label": b.lab(prim), "by_label": b.lab("products" if pie_dim == "product" else pie_dim),
               "by": dim_members[pie_dim], "style": "pie" if has(p["t"], "pie", "pasta") else "donut", "limit": 8, "format": "money" if prim in ("revenue", "gross_profit") else "int"}
        pie.update({"sum": measure_members} if len(measure_members) > 1 else {"measure": measure_members[0]})     # both channels, added up
        if pf and clickable:
            pie["on_click"] = {"set_filter": pf}
        b.panels.append(pie)
    for d in dims:
        if d in pivot_dims:
            continue                                       # the pivot already shows it
        if d in ("category", "subcategory") and p["treemap"]:
            continue
        if d == pie_dim:
            continue
        if not b.can(dim_members[d]):
            continue
        measure_key = prim
        stack = [{"member": f"{c}.{measure_key}", "label": b.lab("internet" if c == "internet_sales" else "reseller"), "color": "internet" if c == "internet_sales" else "reseller"} for c in b.channels()
                 if not denied(role, f"{c}.{measure_key}")]
        fmt = "money" if measure_key in ("revenue", "gross_profit") else "int"
        panel = {"id": b.pid(f"by_{d}"), "type": "bar", "title": b.lab("by", m=b.lab(measure_key), d=b.lab("products" if d == "product" else d)),
                 "by_label": b.lab("products" if d == "product" else d), **({"label": b.lab(measure_key)} if len(stack) <= 1 else {}),
                 "by": dim_members[d], "sort": "desc", "limit": p["top"] or (10 if d in ("product", "category", "subcategory") else 15), "format": fmt}
        panel.update({"stack": stack} if len(stack) > 1 else {"measure": stack[0]["member"]})
        if p["column"]:
            panel["orientation"] = "vertical"
        if d in ("region", "country", "category", "subcategory"):
            f = b.add_filter({"region": "region", "country": "country", "category": "category", "subcategory": "subcategory"}[d], dim_members[d], d)
            if f and clickable:
                panel["on_click"] = {"set_filter": f}
        b.panels.append(panel)
    if p["treemap"] and b.can("products.category") and not denied(role, f"{b.channels()[0]}.revenue"):
        cf = b.add_filter("category", "products.category", "category")
        sf = b.add_filter("subcategory", "products.subcategory", "subcategory", parent="products.category")
        t = {"id": b.pid("mix"), "type": "treemap", "title": b.lab("mix"), "label": b.lab("revenue"), "group_labels": [b.lab("category"), b.lab("subcategory")],
             "measure": f"{b.channels()[0]}.revenue", "group": ["products.category", "products.subcategory"], "format": "money"}
        if cf and sf and clickable:
            t["on_click"] = {"set_filter": [cf, sf]}
        b.panels.append(t)
    if p["table"] and not (p["pivot"] and not has(p["t"], "latest order", "last order", "list of order", "son siparis")):     # "çapraz tablo" is the pivot, not a list
        c = b.channels()[0]
        b.panels.append({"id": b.pid("lines"), "type": "table", "title": b.lab("latest"), "columns": [
            {"member": f"{c}.order_number", "label": b.lab("order")}, {"member": f"{c}.order_date", "label": b.lab("date")},
            *([{"member": "territories.country", "label": b.lab("country")}] if b.can("territories.country") else []),
            {"member": f"{c}.revenue", "label": b.lab("revenue"), "format": "money"}], "order": {f"{c}.order_date": "desc"}, "limit": p["top"] or 25})
    lead = next((c for c in b.channels() if not denied(role, f"{c}.{prim}")), None)
    if p["pivot"] and lead and all(b.can(dim_members[d]) for d in pivot_dims) and b.can("dates.fiscal_year") and b.can("dates.full_date"):
        gran = p["gran"] if p["gran"] in ("month", "quarter") else None                      # months or quarters across the top; otherwise the fiscal year
        col_label = b.lab(gran) if gran else b.lab("fy")
        member = f"{lead}.{prim}"
        pivot = {"id": b.pid("pivot"), "type": "pivot", "title": b.lab("pivot", m=b.lab(prim), d=" / ".join(b.lab("products" if d == "product" else d) if b.tr else b.lab("products" if d == "product" else d).lower() for d in pivot_dims), c=col_label.lower()),
                 "rows": [dim_members[d] for d in pivot_dims], "columns": {"member": "dates.full_date", "granularity": gran} if gran else "dates.fiscal_year",
                 "measures": [{"member": member, "label": b.lab(prim), "format": "money" if prim in ("revenue", "gross_profit") else "int"}]}
        if p["heat"]:
            pivot["heat"] = {"measure": member}
        row_filter = b.add_filter(pivot_dims[-1], dim_members[pivot_dims[-1]], pivot_dims[-1]) if pivot_dims[-1] in ("region", "country", "category", "subcategory") else None
        year_filter = b.add_filter("fy", "dates.fiscal_year", "fy") if not gran else None
        click = [f for f in (row_filter, year_filter) if f]
        if click and clickable:
            pivot["on_click"] = {"set_filter": click}
        b.panels.append(pivot)
    for want in p["filters"]:
        {"fy": lambda: b.add_filter("fy", "dates.fiscal_year", "fy"), "region": lambda: b.add_filter("region", "territories.region", "region"),
         "category": lambda: b.add_filter("category", "products.category", "category"), "country": lambda: b.add_filter("country", "territories.country", "country")}[want]()
    if has(p["t"], "for germany", "in germany", "for canada", "in canada", "for europe", "in europe"):
        b.notes.append("A dashboard cannot be fixed to one region: use the region filter above the panels (your role's own territories are applied by Cube anyway).")
        b.add_filter("region", "territories.region", "region")
    levels_said = [f"{'Internet' if c == 'internet_sales' else 'Reseller'}: {' > '.join(lv)}" for c, lv in p["chart_segments"] if lv]
    heard = [f"measures: {', '.join(L[k][0].lower() for k in keys)}"] + ([f"chart style: {p['style']}"] if p["style"] else []) + ([f"drill-down {'; '.join(levels_said) or ' > '.join(p['levels'])}"] if p["drill"] or levels_said else []) \
        + (["a separate chart per channel"] if len(p["chart_segments"]) >= 2 else []) + (["pie"] if p["pie"] else []) + (["a pivot" + (" with shading" if p["heat"] else "")] if p["pivot"] else []) \
        + ([f"slicers: {', '.join(L[k][0].lower() for k in p['slicers'])}"] if p["slicers"] else [])
    b.notes.insert(0, ("Anladığım: " if b.tr else "Understood: ") + "; ".join(heard) + ".")
    return finish(b, prompt, "dates.full_date", "sales")


# ------------------------------------------------------------------------------------------------------------------ inventory
def compose_inventory(p, prompt, catalog, role) -> Composition:
    b = Builder(catalog, role, p)
    ih = "inventory_health"
    if ih not in catalog.cubes:
        return Composition(reason="Inventory data is not available for your role.")
    ok = lambda m: not denied(role, f"{ih}.{m}")  # noqa: E731
    tiles = [("product_count", "products", "int"), ("stockout_items", "stockout", "int"), ("reorder_items", "reorder", "int"), ("overstock_items", "overstock", "int"),
             ("dead_stock_items", "dead", "int"), ("suggested_order_value_total", "suggested", "money"), ("excess_value_total", "excess", "money")]
    shown = [{"member": f"{ih}.{m}", "label": b.lab(k), "format": f} for m, k, f in tiles if ok(m)]
    skipped = [k for m, k, _ in tiles if not ok(m)]
    if skipped:
        b.notes.append("Supplier and order figures are left out because your role cannot read them.")
    b.ids.add("summary")
    b.panels.append({"id": "summary", "type": "kpi", "measures": shown[:8]})
    sf = b.add_filter("status", f"{ih}.status", "status")
    b.add_filter("category", "products.category", "category")
    b.panels.append({"id": b.pid("by_status"), "type": "bar", "title": b.lab("stock_status"), "measure": f"{ih}.product_count", "by": f"{ih}.status", "sort": "desc", "limit": 8,
                     "format": "int", **({"on_click": {"set_filter": sf}} if sf else {})})
    if ok("vendor_name") and ok("suggested_order_value_total") and has(p["t"], "vendor", "supplier", "tedarik", "reorder", "order"):
        b.panels.append({"id": b.pid("by_vendor"), "type": "bar", "title": b.lab("vendor_value"), "measure": f"{ih}.suggested_order_value_total", "by": f"{ih}.vendor_name",
                         "sort": "desc", "limit": p["top"] or 10, "format": "money"})
    if ok("suggested_order_value") and (p["table"] or has(p["t"], "reorder", "order", "siparis")):
        b.panels.append({"id": b.pid("reorder"), "type": "table", "title": b.lab("reorder_list"), "columns": [
            {"member": f"{ih}.product_name", "label": b.lab("product")}, {"member": f"{ih}.status", "label": b.lab("status")},
            {"member": f"{ih}.on_hand", "label": b.lab("on_hand"), "format": "int"}, {"member": f"{ih}.on_order", "label": b.lab("on_order"), "format": "int"},
            {"member": f"{ih}.days_of_cover", "label": b.lab("cover"), "format": "int"}, {"member": f"{ih}.suggested_order_qty", "label": b.lab("qty"), "format": "int"},
            {"member": f"{ih}.suggested_order_value", "label": b.lab("suggested"), "format": "money"}, {"member": f"{ih}.vendor_name", "label": b.lab("vendor")}],
            "order": {f"{ih}.suggested_order_value": "desc"}, "limit": p["top"] or 25})
    if p["table"] or has(p["t"], "excess", "overstock", "dead", "fazla"):
        b.panels.append({"id": b.pid("excess"), "type": "table", "title": b.lab("excess_list"), "columns": [
            {"member": f"{ih}.product_name", "label": b.lab("product")}, {"member": f"{ih}.status", "label": b.lab("status")},
            {"member": f"{ih}.on_hand", "label": b.lab("on_hand"), "format": "int"}, {"member": f"{ih}.excess_units", "label": b.lab("excess_units"), "format": "int"},
            {"member": f"{ih}.excess_value", "label": b.lab("excess"), "format": "money"}, {"member": f"{ih}.suggested_discount_pct", "label": b.lab("discount"), "format": "int"}],
            "order": {f"{ih}.excess_value": "desc"}, "limit": p["top"] or 25})
    return finish(b, prompt, f"{ih}.last_sale_date", "inventory")


# ------------------------------------------------------------------------------------------------------------------ slicers
SLICER_MEMBERS = {"color": "products.color", "category": "products.category", "subcategory": "products.subcategory", "product": "products.name",
                  "region": "territories.region", "country": "territories.country", "group": "territories.group_name", "fy": "dates.fiscal_year",
                  "status": "inventory_health.status", "vendor": "inventory_health.vendor_name"}
MANY_VALUES = ("product", "vendor")                                       # hundreds of values: a dropdown, not a wall of chips


def add_slicers(spec: dict, keys: list[str], catalog: cat.Catalog, role: str, tr: bool) -> list[str]:
    """A slicer for each field asked for, placed under the key figures. A field that already has a visible filter gets a slicer that draws that filter
    (`filter:`; one control per field), any other field a slicer of its own (`dimension:`). A field the role cannot read, or no panel can be filtered by,
    is left out with a note. Returns the notes; the caller lays the panels out again."""
    notes, panels, filters = [], spec["panels"], spec.setdefault("filters", [])
    ids = {x["id"] for x in panels} | {f["id"] for f in filters}
    for key in keys:
        member, name, label = SLICER_MEMBERS[key], L[key][0], L[key][1 if tr else 0]      # notes are in English, as the stand-in's others; the label in the dashboard's language
        c, _, n = member.partition(".")
        if c not in catalog.cubes or n not in catalog.cubes[c]["dimensions"] or denied(role, member):
            notes.append(f"No slicer for {name.lower()}: your role cannot read it.")
            continue
        if not any(slicer_rules.joins(catalog, x, member) for x in panels if x["type"] not in slicer_rules.DATA_LESS):
            notes.append(f"No slicer for {name.lower()}: none of the panels can be filtered by it.")
            continue
        flt = next((f for f in filters if f["dimension"] == member and f.get("visible", True) is not False), None)
        drawn = [x for x in panels if x["type"] == "slicer" and (x.get("dimension") == member or (flt and x.get("filter") == flt["id"]))]
        if drawn:
            notes.append(f"{name} already has a slicer ({drawn[0]['id']}).")
            continue
        sid, i = f"slicer_{key}", 1
        while sid in ids:
            i += 1
            sid = f"slicer_{key}_{i}"
        ids.add(sid)
        listed = flt is None or flt.get("type", "select") in ("select", "multiselect")
        panel = {"id": sid, "type": "slicer", **({"filter": flt["id"]} if flt else {"dimension": member, "label": label}),
                 **({"display": "dropdown" if key in MANY_VALUES else "chips"} if listed else {})}
        at = next((k for k, x in enumerate(panels) if x["type"] not in ("kpi", "slicer")), len(panels))     # under the key figures and the slicers already there
        panels.insert(at, panel)
        notes.append(f"Added a slicer for {name.lower()}" + (f" (it draws the filter '{flt['id']}', which moves from the bar above the panels)." if flt else "."))
    if not filters:
        spec.pop("filters")
    return notes


# ------------------------------------------------------------------------------------------------------------------ layout and the file
FLEXIBLE = {"timeseries": (8, 4), "treemap": (7, 5), "bar": (6, 6), "pie": (5, 7)}


def layout(panels: list[dict]) -> list[list[dict]]:
    """Rows of 12 columns: kpis, tables and notes take a row; two charts share one (the first sets the split); slicers next to each other share one evenly (up to 4)."""
    rows, i = [], 0
    while i < len(panels):
        p = panels[i]
        nxt = panels[i + 1] if i + 1 < len(panels) else None
        if p["type"] == "slicer":
            run = [x["id"] for x in panels[i:i + 4]]
            run = run[:next((k for k, x in enumerate(panels[i:i + 4]) if x["type"] != "slicer"), len(run))]
            rows.append([{sid: 12 // len(run) + (12 % len(run) if k == 0 else 0)} for k, sid in enumerate(run)])
            i += len(run)
            continue
        if p["type"] in FLEXIBLE and nxt and nxt["type"] in FLEXIBLE:
            a, c = FLEXIBLE[p["type"]]
            if nxt["type"] == "pie" and p["type"] != "pie":
                a, c = 7, 5                                           # a pie needs room for its legend
            if p["type"] == nxt["type"] == "timeseries":
                a, c = 6, 6                                           # two time charts share a row evenly
            rows.append([{p["id"]: a}, {nxt["id"]: c}])
            i += 2
        else:
            rows.append([{p["id"]: 12}])
            i += 1
    return rows


def finish(b: Builder, prompt: str, time_dim: str, kind: str) -> Composition:
    spec = {"spec": 1, "id": "draft", "title": b.lab(kind), "description": b.lab("built", p=" ".join(prompt.split())[:180]),
            "locale": "tr-TR" if b.tr else "en-US", "currency": "TRY" if b.tr else "USD", "time": {"dimension": time_dim, **({"fiscal_year_start": 7} if kind == "sales" else {})},
            "filters": b.filters, "panels": b.panels}
    b.notes.extend(add_slicers(spec, b.p["slicers"], b.catalog, b.role, b.tr))
    if b.p["slicer_said"] and not b.p["slicers"]:
        b.notes.append(SLICER_WHICH)
    spec["layout"] = layout(spec["panels"])
    return Composition(spec=spec, notes=b.notes)


# ------------------------------------------------------------------------------------------------------------------ editing
SLICER_WHICH = ("A slicer needs a field: say which, for example \"a slicer for colour\" (colour, category, subcategory, product, region, country, sales group, "
                "fiscal year; status or vendor on inventory).")
FOCUS_UNDERSTOOD = "With one panel picked the rule-based stand-in handles: pie or donut, bars or columns, a chart style (line, area, bar, stacked), top N, and removing it."
KEEP = ("id", "title", "description", "measure", "label", "by", "by_label", "format", "on_click")


def _fill_row(row: list[dict]) -> list[dict]:
    """A row that lost a panel gives its 12 columns to the ones that are left, in the proportions they had."""
    spans = [next(iter(c.values())) for c in row]
    if sum(spans) == 12:
        return row
    new = [max(1, round(12 * w / sum(spans))) for w in spans]
    new[0] += 12 - sum(new)
    return [{next(iter(c)): w} for c, w in zip(row, new, strict=True)]


def refine_panel(p, spec: dict, focus: str) -> Composition:
    """A change to the one panel the designer has picked. Nothing else is touched, and the layout is not rebuilt, so tabs survive."""
    panel = next((x for x in spec.get("panels", []) if x.get("id") == focus), None)
    if panel is None:
        return Composition(reason=f"The picked panel ({focus}) is not in the dashboard any more.")
    t, notes, kind = p["t"], [], panel["type"]
    if has(t, "remove", "delete", "drop", "kaldir", "sil"):
        if len(spec["panels"]) < 2:
            return Composition(reason="That is the only panel; a dashboard needs at least one.")
        spec["panels"] = [x for x in spec["panels"] if x is not panel]
        for holder in [spec, *spec.get("tabs", [])]:
            if "layout" in holder:
                rows = [[c for c in row if focus not in c] for row in holder["layout"]]
                holder["layout"] = [_fill_row(row) for row in rows if row]
        return Composition(spec=spec, notes=[f"Removed {panel.get('title') or focus}."])
    if p["pie"] and kind in ("bar", "pie"):
        if kind == "bar":
            if "split" in panel or not ("measure" in panel or "stack" in panel):
                return Composition(reason="This bar chart is split by a second dimension, which a pie cannot show. Edit the YAML, or use a language model.")
            keep = {k: v for k, v in panel.items() if k in KEEP}
            keep["type"] = "pie"
            if "stack" in panel:                                             # stacked measures become one slice size: their sum
                keep["sum"] = [s["member"] for s in panel["stack"]]
                keep["label"] = panel.get("label") or panel.get("title") or "Total"
            if isinstance(panel.get("limit"), int):
                keep["limit"] = min(30, max(2, panel["limit"]))
            panel.clear()
            panel.update(keep)
        panel["style"] = "donut" if has(t, "donut", "halka") else "pie"
        notes.append(f"Now a {panel['style']} chart.")
    elif kind == "pie" and has(t, "bar", "column", "sutun", "kolon") and ("measure" in panel or "sum" in panel):
        keep = {k: v for k, v in panel.items() if k in KEEP or k == "limit"}
        if "sum" in panel:                                                  # one slice size made of several measures: they become stacked bars again
            keep["stack"] = [{"member": m} for m in panel["sum"]]
            keep.pop("label", None)
        keep.update(type="bar", orientation="vertical" if p["column"] else "horizontal")
        panel.clear()
        panel.update(keep)
        notes.append("Now a bar chart.")
    elif kind == "bar" and p["column"]:
        panel["orientation"] = "vertical"
        notes.append("Drawn as columns.")
    elif kind == "timeseries" and p["style"]:
        panel["style"] = p["style"]
        notes.append(f"Chart style set to {p['style']}.")
    if p["top"] and kind in ("bar", "table", "pie"):
        panel["limit"] = max(p["top"], 2) if kind == "pie" else p["top"]
        notes.append(f"Limit set to {panel['limit']}.")
    if not notes:
        return Composition(spec=spec, notes=[f"The rule-based stand-in understood nothing to change in this panel. {FOCUS_UNDERSTOOD}"])
    return Composition(spec=spec, notes=notes)


def refine(p, prompt, catalog, role, current_yaml, focus: str | None = None) -> Composition:
    try:
        spec = yaml.safe_load(current_yaml)
    except yaml.YAMLError:
        return Composition(reason="The current dashboard is not valid YAML.")
    if focus and isinstance(spec, dict):
        return refine_panel(p, spec, focus)
    if isinstance(spec, dict) and "tabs" in spec:        # editing rebuilds `layout` from `panels`, which would flatten the tabs: do not
        return Composition(reason="The rule-based stand-in cannot change a dashboard that has tabs (it would lose them). Edit the YAML, or use a language model, which edits the whole file.")
    t, notes, changed = p["t"], [], False
    remove = has(t, "remove", "delete", "drop", "without", "kaldir", "sil")
    kinds = {"table": "table", "treemap": "treemap", "trend": "timeseries", "chart": None, "kpi": "kpi", "tiles": "kpi"}
    if remove:
        for word, kind in kinds.items():
            if kind and has(t, word) and len([x for x in spec["panels"] if x["type"] != kind]) >= 1:
                gone = {x["id"] for x in spec["panels"] if x["type"] == kind}
                if gone:
                    spec["panels"] = [x for x in spec["panels"] if x["id"] not in gone]
                    spec["layout"] = layout(spec["panels"])
                    changed = True
                    notes.append(f"Removed the {word}.")
    if p["style"]:
        for x in spec["panels"]:
            if x["type"] == "timeseries":
                x["style"], changed = p["style"], True
        notes.append(f"Chart style set to {p['style']}.")
    if p["column"]:
        for x in spec["panels"]:
            if x["type"] == "bar":
                x["orientation"], changed = "vertical", True
        notes.append("Bars drawn as columns.")
    if p["separate"] and not remove and (has(t, "internet", "reseller", "bayi", "channel", "kanal", "chart", "grafik", "panel", "pane")):
        panels = []
        for x in spec["panels"]:
            if x["type"] == "timeseries" and len(x["series"]) > 1:
                for k, ser in enumerate(x["series"]):
                    clone = {**x, "id": f"{x['id']}_{k + 1}", "title": f"{ser.get('label', '')}: {x.get('title', '')}".strip(": "), "series": [ser]}
                    panels.append(clone)
                changed = True
                notes.append("Split the chart into one chart per series, side by side.")
            else:
                panels.append(x)
        spec["panels"] = panels
        spec["layout"] = layout(spec["panels"])
    if p["compare"]:
        kpis = [x for x in spec["panels"] if x["type"] == "kpi"]
        for x in kpis:
            if remove:
                changed = x.pop("compare", None) is not None or changed
            else:
                x["compare"], changed = p["compare"], True
        if kpis:
            notes.append("The key figures no longer compare with an earlier period." if remove else
                         f"The key figures compare with the {'previous period' if p['compare'] == 'previous_period' else 'previous year'}.")
    if p["top"]:
        for x in spec["panels"]:
            if x["type"] in ("bar", "table"):
                x["limit"], changed = p["top"], True
        notes.append(f"Limit set to {p['top']}.")
    if p["slicer_said"]:
        if remove:
            named = {SLICER_MEMBERS[k] for k in p["slicers"]}
            by_id = {f["id"]: f["dimension"] for f in spec.get("filters", [])}
            gone = [x for x in spec["panels"] if x["type"] == "slicer" and (not named or (x.get("dimension") or by_id.get(x.get("filter"))) in named)]
            if gone:
                spec["panels"] = [x for x in spec["panels"] if x not in gone]
                spec["layout"] = layout(spec["panels"])
                changed = True
                notes.append(f"Removed the slicer{'s' if len(gone) > 1 else ''} {', '.join(x['id'] for x in gone)}" +
                             (" (a filter it drew is back in the bar above the panels)." if any("filter" in x for x in gone) else "."))
            else:
                notes.append("There is no such slicer to remove.")
        elif p["slicers"]:
            before = len(spec["panels"])
            notes.extend(add_slicers(spec, p["slicers"], catalog, role, spec.get("locale", "tr-TR" if p["tr"] else "en-US") == "tr-TR"))
            if len(spec["panels"]) > before:
                spec["layout"] = layout(spec["panels"])
                changed = True
        else:
            notes.append(SLICER_WHICH)
    if not remove and (p["table"] or p["treemap"] or p["dims"]):
        # add what was asked for as a fresh composition of just that part, then merge it in
        fresh = compose(prompt, catalog, role)
        if fresh.spec:
            have = {x["id"] for x in spec["panels"]}
            for x in fresh.spec["panels"]:
                if x["type"] != "kpi" and x["id"] not in have and not any(x["type"] == y["type"] and x.get("by") == y.get("by") and x["type"] != "table" for y in spec["panels"]):
                    spec["panels"].append(x)
                    changed = True
            known = {f["id"] for f in spec.get("filters", [])}
            spec["filters"] = [*spec.get("filters", []), *[f for f in fresh.spec.get("filters", []) if f["id"] not in known]]
            spec["layout"] = layout(spec["panels"])
            notes.extend(fresh.notes)
    if not changed and p["slicer_said"] and notes:
        return Composition(spec=spec, notes=notes)                      # "colour already has a slicer", "your role cannot read it": say so, not "understood nothing"
    if not changed:
        return Composition(spec=spec, notes=["The rule-based stand-in understood nothing to change. It handles: a chart style (line, bar, stacked), top N, adding or removing a table, treemap or a breakdown by region, country, category or product, comparing the key figures with the previous year or period (or not), and adding or removing a slicer (\"a slicer for colour\", \"make region a slicer\")."])
    return Composition(spec=spec, notes=notes)
