"""The rule-based stand-in: every prompt it is given ends in a spec the role can render or a clear refusal, never an invalid file."""
import pathlib

import pytest
import yaml
from dashspec import catalog as cat

from builder import core
from builder.standin import StandInClient

REPO = pathlib.Path(__file__).resolve().parents[2]
CATALOG = cat.from_model(REPO / "cube" / "model")

SALES = [
    "monthly revenue by channel", "revenue and orders by region", "top 5 products by revenue", "a table of the latest orders",
    "revenue by country with a treemap of the product mix", "yearly revenue trend as a line chart", "quarterly units and orders over time",
    "average order value and revenue by category", "sales by region and country and category, click to filter", "show me revenue", "internet sales only by month",
    "reseller revenue by product, top 8", "a dashboard", "Türkçe satış panosu: aylık gelir, bölgeye göre gelir, son siparişler", "revenue for Germany by month",
    "revenue, orders, units and average order value with a fiscal year filter and a region filter",
]
INVENTORY = ["inventory dashboard", "stock status and reorder list", "overstock and excess stock table", "tedarikçiye göre envanter, Türkçe", "vendors and suppliers, top 5", "stockouts"]
CHARTS = [
    "Detaya Yıl Ay ve Gün bazında detaya inen çizgi grafiği şeklinde ve pasta grafiği şeklinde ürün alt kategorilerine göre bir dashboard istiyorum ayrıca tıklamalar cross filtering ile sonuçlanmalı Dashboard Türkçe olmalı",
    "a line chart that drills down year, month and day, and a pie chart of revenue by product subcategory", "donut of revenue by category", "area chart of revenue by month",
    "revenue by category as columns", "drill down from year to month", "yıl ay gün detay çizgi grafik", "quarterly revenue line chart", "pie of orders by region",
]
TWO_CHARTS = ("kolon chartlı yıl çeyrek ay gün drill eden internet satışını gösteren bir chart ayrıca yıl-çeyrek-ay reseller satışını gösteren ikinci bir chart "
              "ciro satış adedi ortalama sipariş tutarı")
CHARTS += [TWO_CHARTS, "a column chart of internet revenue with drill-down year to month, and a second chart for reseller revenue", "revenue as columns by month"]
PROFIT = ["profit by month", "gross margin by region", "revenue, profit and margin by category"]


def build(role, prompt, current=None):
    return core.run_build(StandInClient(CATALOG, role), CATALOG, role, prompt, current, mode="standin")


@pytest.mark.parametrize("role", core.ROLES)
@pytest.mark.parametrize("prompt", SALES + INVENTORY + PROFIT + CHARTS)
def test_every_prompt_ends_in_a_valid_spec_or_a_refusal(role, prompt):
    out = build(role, prompt)
    assert out["status"] in ("ok", "cannot"), (role, prompt, out.get("problems"), out["message"])
    if out["status"] == "ok":
        assert out["attempts"] == 1, "the stand-in's file passes the checks the first time"
        assert out["spec"]["roles"] == [role]
    else:
        assert out["message"] and out["spec"] is None


def kinds(out):
    return [p["type"] for p in out["spec"]["panels"]]


def test_what_was_asked_for_is_in_the_dashboard():
    out = build("admin", "monthly revenue by channel, top 5 products, a table of latest orders, a treemap")
    assert kinds(out) == ["kpi", "timeseries", "bar", "treemap", "table"] or set(kinds(out)) >= {"kpi", "timeseries", "bar", "table", "treemap"}
    bar = next(p for p in out["spec"]["panels"] if p["type"] == "bar")
    assert bar["by"] == "products.name" and bar["limit"] == 5 and len(bar["stack"]) == 2
    trend = next(p for p in out["spec"]["panels"] if p["type"] == "timeseries")
    assert trend["granularity"] == "month" and trend["style"] == "stacked-bar" and trend["on_click"] == {"set_filter": "fy"}
    assert any(f["id"] == "fy" for f in out["spec"]["filters"])


def test_a_single_channel_and_the_chosen_measures():
    out = build("admin", "internet orders and units by region")
    kpi = out["spec"]["panels"][0]
    assert [m.get("label") for m in kpi["measures"]] == ["Orders", "Units sold"]
    assert all(m["member"].startswith("internet_sales.") for m in kpi["measures"] if "member" in m)


def test_turkish_gives_turkish_labels_lira_and_locale():
    out = build("admin", "Türkçe satış panosu: aylık gelir ve bölgeye göre gelir")
    spec = out["spec"]
    assert spec["locale"] == "tr-TR" and spec["currency"] == "TRY" and spec["title"] == "Satış panosu"
    assert any(p.get("title") == "Bölge bazında gelir" for p in spec["panels"]) and spec["panels"][0]["measures"][0]["label"] == "Gelir"


def test_a_rep_never_gets_profit_and_is_told_what_was_left_out():
    out = build("rep", "revenue and margin by region")
    assert "gross_profit" not in str(out["spec"]) and "Left out because your role cannot read it" in out["message"]
    refused = build("rep", "profit by region")
    assert refused["status"] == "cannot" and "hidden from reps" in refused["message"]


def test_inventory_follows_the_role():
    assert build("manager", "inventory dashboard")["status"] == "cannot"
    assert build("purchasing", "revenue by region")["status"] == "cannot"
    mk = build("marketing", "stock status and excess stock")
    assert mk["status"] == "ok" and "vendor" not in str(mk["spec"]) and "Supplier and order figures are left out" in mk["message"]
    pu = build("purchasing", "reorder list and vendors")
    assert any(p["id"].startswith("reorder") for p in pu["spec"]["panels"]) and "vendor_name" in str(pu["spec"])


def test_layout_adds_up_and_places_every_panel_once():
    out = build("admin", "revenue by month, by region, by country, by category, a treemap and a table")
    seen = []
    for row in out["spec"]["layout"]:
        assert sum(c["span"] for c in row) == 12
        seen += [c["panel"] for c in row]
    assert sorted(seen) == sorted(p["id"] for p in out["spec"]["panels"])


def test_a_fixed_region_is_explained_not_faked():
    out = build("admin", "revenue for Germany by month")
    assert "region filter" in out["message"] and any(f["id"] == "region" for f in out["spec"]["filters"])


def current(role="admin", prompt="monthly revenue by channel and top products"):
    return build(role, prompt)["yaml"]


def test_refining_changes_the_style_the_limit_and_adds_and_removes_panels():
    base = current()
    line = build("admin", "make the chart a line", base)
    assert next(p for p in line["spec"]["panels"] if p["type"] == "timeseries")["style"] == "line"
    top3 = build("admin", "top 3", base)
    assert next(p for p in top3["spec"]["panels"] if p["type"] == "bar")["limit"] == 3
    table = build("admin", "add a table of the latest orders", base)
    assert "table" in kinds(table) and "timeseries" in kinds(table)
    gone = build("admin", "remove the trend", table["yaml"])
    assert "timeseries" not in kinds(gone) and "table" in kinds(gone)
    region = build("admin", "also show revenue by region", base)
    assert any(p.get("by") == "territories.region" for p in region["spec"]["panels"])
    for out in (line, top3, table, gone, region):
        assert out["status"] == "ok"


def test_a_refinement_it_does_not_understand_says_so_and_changes_nothing():
    base = current()
    out = build("admin", "make it prettier and more corporate", base)
    assert out["status"] == "ok" and "understood nothing to change" in out["message"]
    assert yaml.safe_load(out["yaml"])["panels"] == yaml.safe_load(base)["panels"]


USER_REQUEST = CHARTS[0]


def test_the_request_that_started_this_a_drill_down_line_chart_a_pie_by_subcategory_and_cross_filtering_in_turkish():
    out = build("admin", USER_REQUEST)
    spec = out["spec"]
    assert out["status"] == "ok" and spec["locale"] == "tr-TR" and spec["currency"] == "TRY"
    trend = next(p for p in spec["panels"] if p["type"] == "timeseries")
    assert trend["drill"] == ["year", "month", "day"] and trend["granularity"] == "year" and trend["style"] == "line"
    pie = next(p for p in spec["panels"] if p["type"] == "pie")
    assert pie["by"] == "products.subcategory" and pie["on_click"] == {"set_filter": "subcategory"} and pie["title"] == "Alt kategori bazında gelir"
    assert not [p for p in spec["panels"] if p["type"] == "bar"], "no extra bars for the words 'ürün alt kategori'"
    assert any(f["id"] == "subcategory" for f in spec["filters"]) and "on_click" not in trend, "a drill-down filters the others by period; the pie filters by subcategory"


def test_chart_words_choose_the_chart():
    def kinds(prompt, role="admin"):
        spec = build(role, prompt)["spec"]
        return {p["type"]: p for p in spec["panels"]}
    assert kinds("area chart of revenue by month")["timeseries"]["style"] == "area"
    assert kinds("donut of revenue by category")["pie"]["style"] == "donut" and kinds("pie of orders by region")["pie"]["style"] == "pie"
    assert kinds("revenue by category as columns")["bar"]["orientation"] == "vertical"
    assert "orientation" not in kinds("revenue by category")["bar"]
    assert kinds("quarterly revenue line chart")["timeseries"]["granularity"] == "quarter"
    assert "drill" not in kinds("monthly revenue by channel")["timeseries"]
    assert kinds("drill down from year to month")["timeseries"]["drill"] == ["year", "month"]


def test_a_rep_gets_the_drill_down_and_the_pie_without_profit():
    out = build("rep", USER_REQUEST)
    assert out["status"] == "ok" and "gross_profit" not in str(out["spec"])


def test_two_charts_one_per_channel_with_their_own_drill_levels_in_columns():
    out = build("admin", TWO_CHARTS)
    spec = out["spec"]
    assert out["status"] == "ok"
    charts = {p["id"]: p for p in spec["panels"] if p["type"] == "timeseries"}
    assert set(charts) == {"trend_internet", "trend_reseller"}
    assert charts["trend_internet"]["drill"] == ["year", "quarter", "month", "day"] and charts["trend_reseller"]["drill"] == ["year", "quarter", "month"]
    assert all(c["style"] == "bar" and len(c["series"]) == 1 for c in charts.values())
    assert charts["trend_internet"]["series"][0]["member"] == "internet_sales.revenue" and charts["trend_reseller"]["series"][0]["member"] == "reseller_sales.revenue"
    assert [m["label"] for m in spec["panels"][0]["measures"]] == ["Revenue", "Units sold", "Avg order value"], "'average order value' is not also an order count"
    assert spec["layout"][1] == [{"panel": "trend_internet", "span": 6}, {"panel": "trend_reseller", "span": 6}], "side by side, half each"
    assert "Understood:" in out["message"] and "Internet: year > quarter > month > day" in out["message"] and "Reseller: year > quarter > month" in out["message"]


def test_converting_to_columns_and_splitting_a_chart_by_channel():
    base = build("admin", "monthly revenue by channel")["yaml"]
    cols = build("admin", "Kolon charta çevir", base)
    assert next(p for p in cols["spec"]["panels"] if p["type"] == "timeseries")["style"] == "bar" and "understood nothing" not in cols["message"]
    again = build("admin", "convert it to a column chart", base)
    assert next(p for p in again["spec"]["panels"] if p["type"] == "timeseries")["style"] == "bar"
    split = build("admin", "Internet ve reseller için iki yarım pane chart yap", cols["yaml"])
    charts = [p for p in split["spec"]["panels"] if p["type"] == "timeseries"]
    assert [c["series"][0]["label"] for c in charts] == ["Internet", "Reseller"] and all(c["style"] == "bar" for c in charts)
    assert [(c["panel"], c["span"]) for c in split["spec"]["layout"][1]] == [(charts[0]["id"], 6), (charts[1]["id"], 6)]
    assert build("admin", "make separate charts for internet and reseller", base)["status"] == "ok"


def test_column_words_make_vertical_bars_when_there_is_no_time_chart():
    base = build("admin", "revenue by region")["yaml"]
    out = build("admin", "show it as columns", base)
    assert next(p for p in out["spec"]["panels"] if p["type"] == "bar")["orientation"] == "vertical"


def test_average_order_value_alone_does_not_add_the_order_count():
    out = build("admin", "average order value and revenue")
    assert [m["label"] for m in out["spec"]["panels"][0]["measures"]] == ["Revenue", "Avg order value"]


def test_a_turkish_dashboard_labels_its_pie_bars_and_treemap_in_turkish():
    spec = build("admin", "Türkçe satış panosu: alt kategoriye göre pasta grafiği, bölgeye göre gelir ve ürün karması treemap")["spec"]
    pie = next(p for p in spec["panels"] if p["type"] == "pie")
    assert pie["label"] == "Gelir" and pie["by_label"] == "Alt kategori" and pie["sum"] == ["internet_sales.revenue", "reseller_sales.revenue"], "both channels, labelled"
    bar = next(p for p in spec["panels"] if p["type"] == "bar")
    assert bar["by_label"] == "Bölge"
    tree = next(p for p in spec["panels"] if p["type"] == "treemap")
    assert tree["label"] == "Gelir" and tree["group_labels"] == ["Kategori", "Alt kategori"]
    assert "Internet channel only" not in str(build("admin", "pie of revenue by category")["message"])


def test_an_english_pie_sums_both_channels_too_and_a_rep_gets_the_same_without_profit():
    pie = next(p for p in build("rep", "pie of revenue by category")["spec"]["panels"] if p["type"] == "pie")
    assert pie["sum"] == ["internet_sales.revenue", "reseller_sales.revenue"] and pie["label"] == "Revenue"
