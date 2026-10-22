"""The dashboard's panel queries as Cube queries (what spike/dashboard/cube-source.mjs sends)."""
import copy

CH = {"internet": "internet_sales", "reseller": "reseller_sales"}


def eq(member, *values):
    return {"member": member, "operator": "equals", "values": [str(v) for v in values]}


def measures(c, profit=True):
    return [f"{c}.revenue"] + ([f"{c}.gross_profit"] if profit else []) + [f"{c}.orders", f"{c}.units"]


def panel_queries(ch, profit=True, fy=2013, region="Germany", category="Bikes"):
    """name -> Cube query for one channel. Mirrors the page's panels and a few cross-filter states."""
    c = CH[ch]
    month = [{"dimension": f"{c}.order_date", "granularity": "month"}]
    F = lambda *f: list(f)  # noqa: E731
    return {
        "kpis": {"measures": measures(c, profit)},
        "kpis_fy": {"measures": measures(c, profit), "dimensions": ["dates.fiscal_year"],
                    "filters": F({"member": "dates.fiscal_year", "operator": "equals", "values": [str(fy), str(fy - 1)]})},
        "monthly": {"measures": measures(c, profit), "timeDimensions": month},
        "monthly_fy": {"measures": measures(c, profit), "timeDimensions": month, "filters": F(eq("dates.fiscal_year", fy))},
        "mix_fy": {"measures": measures(c, profit), "dimensions": ["products.category", "products.subcategory"],
                   "filters": F(eq("dates.fiscal_year", fy))},
        "top_products_fy": {"measures": [f"{c}.revenue"] + ([f"{c}.gross_profit"] if profit else []) + [f"{c}.units"],
                            "dimensions": ["products.name", "products.category"], "filters": F(eq("dates.fiscal_year", fy))},
        "territories_fy": {"measures": [f"{c}.revenue"] + ([f"{c}.gross_profit"] if profit else []) + [f"{c}.orders"],
                           "dimensions": ["territories.group_name", "territories.region"], "filters": F(eq("dates.fiscal_year", fy))},
        # cross-filters
        "monthly_region": {"measures": measures(c, profit), "timeDimensions": month, "filters": F(eq("territories.region", region))},
        "mix_fy_region": {"measures": measures(c, profit), "dimensions": ["products.category", "products.subcategory"],
                          "filters": F(eq("dates.fiscal_year", fy), eq("territories.region", region))},
        "territories_fy_category": {"measures": [f"{c}.revenue", f"{c}.orders"], "dimensions": ["territories.group_name", "territories.region"],
                                    "filters": F(eq("dates.fiscal_year", fy), eq("products.category", category))},
    }


def defeat_rollups(query):
    """Same result, but no pre-aggregation can match: filter on a dimension no rollup carries."""
    q = copy.deepcopy(query)
    q.setdefault("filters", []).append({"member": "products.key", "operator": "gte", "values": ["0"]})
    return q
