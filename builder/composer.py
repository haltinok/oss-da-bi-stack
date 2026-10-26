"""The rule-based stand-in for the model: reads a request with keywords (English and Turkish) and composes a dashboard spec from the catalog the
role may read. It is not an LLM: it understands a fixed set of phrases (measures, a time axis, breakdowns, top N, a table, a treemap, filters,
clicks, Turkish and lira) and says so when it understood nothing. It exists so the builder, its page and its tests run without an API key; the
loop around it (core.run_build) and the checks are the ones the real model goes through."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml
from dashspec import catalog as cat
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
    "inventory": ("Inventory dashboard", "Envanter panosu"), "drilltitle": ("{m}: year, month, day", "{m}: yıl, ay, gün"), "built": ("Built from: {p}", "İstek: {p}"), "product_name": ("Product", "Ürün"),
    "stock_status": ("Products by status", "Duruma göre ürün sayısı"), "reorder_list": ("Reorder list", "Yeniden sipariş listesi"), "excess_list": ("Excess and dead stock", "Fazla ve ölü stok"),
    "vendor_value": ("Suggested order value by vendor", "Tedarikçiye göre önerilen sipariş tutarı"), "granularity": ("", ""),
}


@dataclass
class Composition:
    spec: dict | None = None
    reason: str = ""
    notes: list[str] = field(default_factory=list)


def _top_n(t: str) -> int | None:
    m = re.search(r"\b(?:top|best|first|en iyi|ilk)\s+(\d+)\b", t) or re.search(r"\b(\d+)\s+(?:best|top|products|urun)", t)
    return min(int(m.group(1)), 50) if m else None


def parse(prompt: str) -> dict:
    t = norm(prompt)
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
        "separate": has(t, "ayri", "separate", "ikinci", "second", "half", "yarim", "iki chart", "iki grafik", "two chart", "each channel", "her kanal", "her biri"),
        "chart_segments": chart_segments(t),
        "gran": next((g for g, w in (("quarter", ("quarter", "ceyrek")), ("year", ("yearly", "annual", "by year", "yillik", "per year")), ("day", ("daily", "by day", "gunluk")),
                                     ("month", ("month", "aylik", "monthly"))) if has(t, *w)), None),
        "trend": has(t, "trend", "over time", "time series", "zaman", "history"),
        "dims": [d for d, rx in (("region", r"\b(region|territor|bolge)"), ("country", r"\b(country|countries|ulke)"),
                                 ("category", r"\b(?<!sub)categor|(?<!alt )\bkategori"), ("subcategory", r"subcategor|alt kategori"),
                                 ("product", r"\b(product|urun)(?!\w* (alt kategori|subcategor))")) if re.search(rx, t)],
        "table": has(t, "table", "list", "latest order", "last order", "detail", "tablo", "liste", "son siparis"),
        "treemap": has(t, "treemap", "mix", "composition", "share", "karma"),
        "clickable": has(t, "click", "cross filter", "interactive", "tikla"),
        "style": next((s for s, w in (("stacked-bar", ("stacked",)), ("area", ("area", "alan grafik")), ("line", ("line", "cizgi")), ("bar", ("bar chart", "bars", "column", "kolon", "sutun"))) if has(t, *w)), None),
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


def compose(prompt: str, catalog: cat.Catalog, role: str, current_yaml: str | None = None) -> Composition:
    p = parse(prompt)
    if current_yaml:
        return refine(p, prompt, catalog, role, current_yaml)
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
    b.panels.append({"id": "kpis", "type": "kpi", "measures": terms[:8], "sparkline": {"granularity": "month"}})
    fid = b.add_filter("fy", "dates.fiscal_year", "fy")
    dims = p["dims"] + ([] if p["dims"] else (["region"] if has(p["t"], "region", "territor", "bolge") else []))
    want_time = p["trend"] or p["gran"] or p["drill"] or p["style"] in ("line", "area") or not (p["dims"] or p["table"] or p["treemap"] or p["pie"])
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
        measure_members = [f"{c}.{prim}" for c in c0]
        pie = {"id": b.pid("pie"), "type": "pie", "title": b.lab("by", m=b.lab(prim), d=b.lab("products" if pie_dim == "product" else pie_dim)), "measure": measure_members[0],
               "by": dim_members[pie_dim], "style": "pie" if has(p["t"], "pie", "pasta") else "donut", "limit": 8, "format": "money" if prim in ("revenue", "gross_profit") else "int"}
        if len(measure_members) > 1:
            pie["measure"] = measure_members[0]
            b.notes.append("Pasta grafik yalnızca İnternet kanalını gösterir." if b.tr else "A pie shows one measure, so it shows the Internet channel only.")
        if pf and clickable:
            pie["on_click"] = {"set_filter": pf}
        b.panels.append(pie)
    for d in dims:
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
        t = {"id": b.pid("mix"), "type": "treemap", "title": b.lab("mix"), "measure": f"{b.channels()[0]}.revenue", "group": ["products.category", "products.subcategory"], "format": "money"}
        if cf and sf and clickable:
            t["on_click"] = {"set_filter": [cf, sf]}
        b.panels.append(t)
    if p["table"]:
        c = b.channels()[0]
        b.panels.append({"id": b.pid("lines"), "type": "table", "title": b.lab("latest"), "columns": [
            {"member": f"{c}.order_number", "label": b.lab("order")}, {"member": f"{c}.order_date", "label": b.lab("date")},
            *([{"member": "territories.country", "label": b.lab("country")}] if b.can("territories.country") else []),
            {"member": f"{c}.revenue", "label": b.lab("revenue"), "format": "money"}], "order": {f"{c}.order_date": "desc"}, "limit": p["top"] or 25})
    for want in p["filters"]:
        {"fy": lambda: b.add_filter("fy", "dates.fiscal_year", "fy"), "region": lambda: b.add_filter("region", "territories.region", "region"),
         "category": lambda: b.add_filter("category", "products.category", "category"), "country": lambda: b.add_filter("country", "territories.country", "country")}[want]()
    if has(p["t"], "for germany", "in germany", "for canada", "in canada", "for europe", "in europe"):
        b.notes.append("A dashboard cannot be fixed to one region: use the region filter above the panels (your role's own territories are applied by Cube anyway).")
        b.add_filter("region", "territories.region", "region")
    levels_said = [f"{'Internet' if c == 'internet_sales' else 'Reseller'}: {' > '.join(lv)}" for c, lv in p["chart_segments"] if lv]
    heard = [f"measures: {', '.join(L[k][0].lower() for k in keys)}"] + ([f"chart style: {p['style']}"] if p["style"] else []) + ([f"drill-down {'; '.join(levels_said) or ' > '.join(p['levels'])}"] if p["drill"] or levels_said else []) \
        + (["a separate chart per channel"] if len(p["chart_segments"]) >= 2 else []) + (["pie"] if p["pie"] else [])
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


# ------------------------------------------------------------------------------------------------------------------ layout and the file
FLEXIBLE = {"timeseries": (8, 4), "treemap": (7, 5), "bar": (6, 6), "pie": (5, 7)}


def layout(panels: list[dict]) -> list[list[dict]]:
    """Rows of 12 columns: kpis, tables and notes take a row; two charts share one (the first sets the split)."""
    rows, i = [], 0
    while i < len(panels):
        p = panels[i]
        nxt = panels[i + 1] if i + 1 < len(panels) else None
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
            **({"filters": b.filters} if b.filters else {}), "panels": b.panels, "layout": layout(b.panels)}
    return Composition(spec=spec, notes=b.notes)


# ------------------------------------------------------------------------------------------------------------------ editing
def refine(p, prompt, catalog, role, current_yaml) -> Composition:
    try:
        spec = yaml.safe_load(current_yaml)
    except yaml.YAMLError:
        return Composition(reason="The current dashboard is not valid YAML.")
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
    if p["top"]:
        for x in spec["panels"]:
            if x["type"] in ("bar", "table"):
                x["limit"], changed = p["top"], True
        notes.append(f"Limit set to {p['top']}.")
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
    if not changed:
        return Composition(spec=spec, notes=["The rule-based stand-in understood nothing to change. It handles: a chart style (line, bar, stacked), top N, adding or removing a table, treemap or a breakdown by region, country, category or product."])
    return Composition(spec=spec, notes=notes)
