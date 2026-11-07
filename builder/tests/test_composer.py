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
PIVOTS = ["a pivot of revenue by category and month, shaded", "revenue by region and fiscal year crosstab", "pivot of units by category and subcategory",
          "Türkçe: kategori ve aylık gelir çapraz tablo ısı haritası", "profit heatmap by region and month", "orders matrix by country and quarter"]
PROFIT = ["profit by month", "gross margin by region", "revenue, profit and margin by category"]


def build(role, prompt, current=None, focus=None):
    return core.run_build(StandInClient(CATALOG, role), CATALOG, role, prompt, current, mode="standin", focus=focus)


@pytest.mark.parametrize("role", core.ROLES)
@pytest.mark.parametrize("prompt", SALES + INVENTORY + PROFIT + CHARTS + PIVOTS)
def test_every_prompt_ends_in_a_valid_spec_or_a_refusal(role, prompt):
    out = build(role, prompt)
    assert out["status"] in ("ok", "cannot"), (role, prompt, out.get("problems"), out["message"])
    if out["status"] == "ok":
        assert out["attempts"] == 1, "the stand-in's file passes the checks the first time"
        assert "roles" not in out["spec"]
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


def test_a_picked_panel_is_the_only_one_that_changes():
    base = build("admin", "revenue by category and region")
    panels = {p["id"]: p for p in base["spec"]["panels"]}
    bar = next(p for p in base["spec"]["panels"] if p["type"] == "bar")
    out = build("admin", "make this one a donut", base["yaml"], focus=bar["id"])
    assert out["status"] == "ok"
    after = {p["id"]: p for p in out["spec"]["panels"]}
    assert after[bar["id"]]["type"] == "pie" and after[bar["id"]]["style"] == "donut" and after[bar["id"]]["title"] == bar["title"]
    assert all(after[i] == panels[i] for i in panels if i != bar["id"]) and out["spec"]["layout"] == base["spec"]["layout"]
    back = build("admin", "make it a bar chart", out["yaml"], focus=bar["id"])
    assert next(p for p in back["spec"]["panels"] if p["id"] == bar["id"])["type"] == "bar"
    gone = build("admin", "remove this", base["yaml"], focus=bar["id"])
    assert bar["id"] not in {p["id"] for p in gone["spec"]["panels"]} and bar["id"] not in str(gone["spec"]["layout"])


def test_a_picked_panel_that_is_gone_or_not_understood_changes_nothing():
    base = build("admin", "revenue by category and region")
    assert build("admin", "make it a donut", base["yaml"], focus="nope")["spec"] == build("admin", "make it a donut", base["yaml"])["spec"]       # an id that is not there is ignored
    bar = next(p for p in base["spec"]["panels"] if p["type"] == "bar")
    out = build("admin", "make it prettier", base["yaml"], focus=bar["id"])
    assert "understood nothing to change" in out["message"] and out["spec"]["panels"] == base["spec"]["panels"]


def test_the_model_is_told_which_panel_is_picked_and_an_unknown_id_is_not_passed_on():
    base = build("admin", "revenue by category")
    bar = next(p for p in base["spec"]["panels"] if p["type"] == "bar")
    assert core._picked_panel(base["yaml"], bar["id"])["id"] == bar["id"]
    assert core._picked_panel(base["yaml"], "nope") is None and core._picked_panel(None, "x") is None and core._picked_panel("a: [", "x") is None


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
    out = build("editor", USER_REQUEST)
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
    pie = next(p for p in build("editor", "pie of revenue by category")["spec"]["panels"] if p["type"] == "pie")
    assert pie["sum"] == ["internet_sales.revenue", "reseller_sales.revenue"] and pie["label"] == "Revenue"


def test_the_stand_in_writes_no_tags():
    for prompt in ("revenue by region", "a pivot of revenue by category and month", "inventory dashboard"):
        assert "tags" not in build("admin", prompt)["spec"], prompt


def pivot_of(out):
    return next(p for p in out["spec"]["panels"] if p["type"] == "pivot")


def test_a_pivot_request_gets_a_pivot_and_not_the_charts_it_replaces():
    out = build("admin", "a pivot of revenue by category and month, shaded")
    pv = pivot_of(out)
    assert pv["rows"] == ["products.category"] and pv["columns"] == {"member": "dates.full_date", "granularity": "month"}
    assert pv["heat"] == {"measure": "internet_sales.revenue"} and pv["title"] == "Revenue by category and month"
    assert pv["on_click"] == {"set_filter": ["category"]}, "a time column carries no click filter"
    assert set(kinds(out)) == {"kpi", "pivot"}, "no bar by category and no time chart on top of it"


def test_a_pivot_across_the_fiscal_year_filters_by_row_and_year():
    pv = pivot_of(build("admin", "revenue by region and fiscal year crosstab"))
    assert pv["columns"] == "dates.fiscal_year" and "heat" not in pv
    assert pv["on_click"] == {"set_filter": ["region", "fy"]}


def test_the_turkish_word_for_a_cross_table_is_the_pivot_not_also_a_table():
    out = build("admin", "Türkçe: kategori ve aylık gelir çapraz tablo ısı haritası")
    assert set(kinds(out)) == {"kpi", "pivot"}
    assert pivot_of(out)["title"] == "Kategori ve ay bazında gelir" and pivot_of(out)["measures"][0]["label"] == "Gelir"
    assert "table" in kinds(build("admin", "a pivot of revenue by category and month, plus a table of the latest orders"))


def test_the_stand_in_will_not_flatten_a_dashboard_that_has_tabs():
    base = build("admin", "revenue by region and country")["spec"]
    rows = base.pop("layout")
    base["tabs"] = [{"id": "one", "title": "One", "layout": rows[:1]}, {"id": "two", "title": "Two", "layout": rows[1:]}]
    out = build("admin", "make the chart a line", current=yaml.safe_dump(base, sort_keys=False))
    assert out["status"] != "ok" or "tabs" in out["spec"], "either refused, or the tabs are still there"
    assert out["status"] == "cannot" and "tabs" in out["message"], out


@pytest.mark.parametrize("lang", ["en", "tr"])
@pytest.mark.parametrize("role", core.ROLES)
def test_every_example_offered_in_either_language_builds_for_the_role_it_is_offered_to(role, lang):
    examples = core.examples_for(role, lang)
    assert len(examples) >= 3
    for text in examples:
        out = build(role, text)
        assert out["status"] == "ok" and out["attempts"] == 1, (role, lang, text, out.get("message"), out.get("problems"))


def test_the_examples_follow_the_language_and_fall_back_to_english():
    assert core.examples_for("admin", "tr")[0].startswith("Kanala göre")
    assert core.examples_for("admin", "en")[0].startswith("Monthly revenue")
    assert core.examples_for("admin", "de") == core.examples_for("admin", "en") == core.examples_for("admin")
    assert core.examples_for("editor", "tr") != core.examples_for("editor", "en")
    assert set(core.examples_for("editor", "tr")) == set(core.examples_for("editor", "tr")), "sales roles share the sales examples"


# ---- the key figures' comparison with an earlier period
def kpi_of(out):
    return next(p for p in out["spec"]["panels"] if p["type"] == "kpi")


def test_sales_key_figures_compare_with_the_previous_year_by_default():
    out = build("admin", "monthly revenue by channel")
    assert kpi_of(out)["compare"] == "previous_year" and any(f["id"] == "fy" for f in out["spec"]["filters"]), "the fiscal-year filter is always there, so is the comparison"
    assert kpi_of(build("admin", "revenue by month compared with the previous period"))["compare"] == "previous_period"
    assert kpi_of(build("admin", "aylık gelir, önceki döneme göre"))["compare"] == "previous_period"


def test_inventory_key_figures_are_snapshots_and_do_not_compare():
    out = build("admin", "inventory dashboard")
    assert "compare" not in kpi_of(out)


def test_asking_turns_the_comparison_on_switches_its_kind_and_takes_it_away():
    source = yaml.safe_load(build("admin", "monthly revenue by channel")["yaml"])
    plain = yaml.safe_dump({**source, "panels": [{k: v for k, v in p.items() if k != "compare"} for p in source["panels"]]}, sort_keys=False)
    on = build("admin", "compare the key figures with last year", current=plain)
    assert on["status"] == "ok" and kpi_of(on)["compare"] == "previous_year" and "previous year" in on["message"]
    period = build("admin", "compare with the previous period instead", current=on["yaml"])
    assert kpi_of(period)["compare"] == "previous_period"
    off = build("admin", "remove the comparison", current=period["yaml"])
    assert off["status"] == "ok" and "compare" not in kpi_of(off) and len(off["spec"]["panels"]) == len(period["spec"]["panels"]), "only the comparison goes, not a panel"
    assert kpi_of(build("admin", "geçen yıla göre karşılaştır", current=plain))["compare"] == "previous_year"


def slicers_of(out):
    """The slicers of the file as written (in the compiled `spec` a slicer on a field already points at the filter made for it)."""
    return [p for p in yaml.safe_load(out["yaml"])["panels"] if p["type"] == "slicer"]


@pytest.mark.parametrize("role", core.ROLES)
@pytest.mark.parametrize("prompt", ["monthly revenue with a slicer for colour", "revenue by region, a slicer for region and colour", "Türkçe aylık gelir, renk dilimleyici",
                                    "inventory dashboard with a status slicer and a colour slicer", "revenue with a slicer for product", "a slicer", "revenue with a vendor slicer",
                                    "monthly revenue, slicers for colour, country, sales group and fiscal year"])
def test_slicer_prompts_end_in_a_valid_spec(role, prompt):
    out = build(role, prompt)
    assert out["status"] == "ok" and out["attempts"] == 1, (role, prompt, out.get("problems"))


def test_a_slicer_for_a_field_without_a_filter_is_a_slicer_on_that_field_under_the_key_figures():
    out = build("admin", "monthly revenue with a slicer for colour")
    (s,) = slicers_of(out)
    assert {k: s[k] for k in ("dimension", "label", "display")} == {"dimension": "products.color", "label": "Color", "display": "chips"}, "the source file keeps `dimension`"
    assert yaml.safe_load(out["yaml"])["layout"][1] == [{"slicer_color": 12}], "right under the key figures"
    assert not any(p["type"] == "bar" and p.get("by") == "products.color" for p in out["spec"]["panels"]), "the slicer's words are not read again as a breakdown"
    assert slicers_of(build("admin", "Türkçe aylık gelir, renk dilimleyici"))[0]["label"] == "Renk"
    assert slicers_of(build("admin", "revenue with a slicer for product"))[0]["display"] == "dropdown", "hundreds of products: not chips"


def test_a_field_that_has_a_filter_gets_a_slicer_drawing_it_not_a_second_control():
    out = build("admin", "revenue by region, a slicer for region and colour")
    region, color = slicers_of(out)
    assert region["filter"] == "region" and "dimension" not in region and color["dimension"] == "products.color"
    assert yaml.safe_load(out["yaml"])["layout"][1] == [{"slicer_region": 6}, {"slicer_color": 6}], "slicers side by side share a row"
    inv = build("admin", "inventory dashboard with a status slicer and a colour slicer")
    assert [s.get("filter") or s["dimension"] for s in slicers_of(inv)] == ["status", "products.color"]


def test_the_fields_of_a_slicer_are_read_before_or_after_the_word():
    from builder.composer import norm, slicer_fields
    for text, keys in [("a slicer for colour", ["color"]), ("colour and country slicers", ["color", "country"]), ("make region a slicer", ["region"]),
                       ("bölge filtresini dilimleyici yap", ["region"]), ("renge göre dilimleyici", ["color"]), ("slicer for sales group", ["group"]),
                       ("slicers for colour, country and fiscal year", ["color", "country", "fy"]), ("a status slicer and a colour slicer", ["status", "color"]),
                       ("revenue by region with a slicer for colour", ["color"]), ("a slicer", [])]:
        said, found, _ = slicer_fields(norm(text))
        assert said and found == keys, text
    assert slicer_fields(norm("revenue by region, product and alt kategori"))[2] == norm("revenue by region, product and alt kategori"), "no slicer: the text is left as it was"


def test_a_slicer_that_cannot_be_made_says_why_and_a_field_is_asked_for():
    out = build("admin", "revenue with a vendor slicer")
    assert not slicers_of(out) and "none of the panels can be filtered by it" in out["message"]
    out = build("admin", "a slicer")
    assert not slicers_of(out) and "A slicer needs a field" in out["message"]


def test_editing_adds_a_slicer_makes_a_filter_one_and_removes_them():
    base = build("admin", "monthly revenue by region")["yaml"]
    color = build("admin", "add a slicer for colour", current=base)
    assert color["status"] == "ok" and [s["dimension"] for s in slicers_of(color)] == ["products.color"]
    both = build("admin", "make region a slicer", current=color["yaml"])
    assert [s.get("filter") or s["dimension"] for s in slicers_of(both)] == ["products.color", "region"]
    assert yaml.safe_load(build("admin", "bölge filtresini dilimleyici yap", current=base)["yaml"])["panels"][1] == {"id": "slicer_region", "type": "slicer", "filter": "region", "display": "chips"}
    again = build("admin", "add a slicer for colour", current=both["yaml"])
    assert len(slicers_of(again)) == 2 and "already has a slicer" in again["message"]
    one = build("admin", "remove the colour slicer", current=both["yaml"])
    assert [s["id"] for s in slicers_of(one)] == ["slicer_region"] and len(one["spec"]["panels"]) == len(both["spec"]["panels"]) - 1
    none = build("admin", "remove the slicers", current=both["yaml"])
    assert not slicers_of(none) and "back in the bar above the panels" in none["message"]
    assert "no such slicer" in build("admin", "remove the slicer", current=base)["message"]
