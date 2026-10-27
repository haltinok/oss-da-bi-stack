"""The dashboard renderer (/d/) in a real Chrome against the mock stack: no services needed.

  uv run --with playwright python -I dashboard/cube/tests/renderer.py [--shots]

Checks the list page, every panel type of dashboards/sales-overview.yml drawn from generated data, the filters (cascading options, the
queries they send, cancelling what is still running), one failing panel not blanking the rest, the Excel export, the dataset switch, a role
the dashboard is not for, and that the KPI tiles show the same figures as the sales dashboard does for the same data.
"""
import io
import json
import pathlib
import sys
import zipfile
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import mock_stack as ms  # noqa: E402

KEEP = "--shots" in sys.argv
SHOTS = pathlib.Path(__file__).parent / "screenshots"
BASE = f"http://localhost:{ms.PORT}"
failures = []


def check(ok, msg):
    print(("PASS  " if ok else "FAIL  ") + msg)
    if not ok:
        failures.append(msg)
    return ok


def open_page(browser, path, dataset="live", width=1440, theme="light"):
    ctx = browser.new_context(viewport={"width": width, "height": 1500}, accept_downloads=True)
    ctx.add_init_script(ms.SEED + f'try {{ localStorage.setItem("theme", "{theme}"); localStorage.setItem("dataset", "{dataset}"); }} catch (e) {{}}')
    page = ctx.new_page()
    page.problems, page.queries, page.aborted = [], [], []
    page.on("pageerror", lambda e: page.problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: page.problems.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("request", lambda r: page.queries.append(r.url) if "/cube-" in r.url and "/load" in r.url else None)
    page.on("requestfailed", lambda r: page.aborted.append(r.url) if "ERR_ABORTED" in (r.failure or "") and "/cube-" in r.url else None)
    page.goto(f"{BASE}{path}")
    return ctx, page


def settled(page, timeout=20000):
    page.wait_for_function("document.querySelector('#live-text')?.textContent.match(/Updated|Stale|Güncellendi|Eski/)", timeout=timeout)
    page.wait_for_function("!document.querySelector('.card.pending, .kpi.pending')", timeout=timeout)


def sent(page):
    """The Cube queries the page sent, decoded."""
    out = []
    for u in page.queries:
        q = parse_qs(urlparse(u).query).get("query", ["{}"])[0]
        out.append(json.loads(q))
    return out


def has_filter(q, member):
    return any(f.get("member") == member for f in q.get("filters", []))


def tiles(page):
    return {t.query_selector(".label").inner_text(): t.query_selector(".value").inner_text() for t in page.query_selector_all(".kpi")}


ms.start()
ms.FAKE["on"] = True
ms.BENCH["on"] = True
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)

    # ---- the list
    ms.ROLE["role"] = "admin"
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector(".dlist a", timeout=20000)
    names = page.locator(".dlist h2").all_inner_texts()
    check(sorted(names) == ["Envanter sağlığı", "Pivot gallery", "Sales drill-down", "Sales overview"], f"/d/ lists the dashboards the role may open ({names})")
    check(page.get_attribute(".dlist a >> nth=0", "href").startswith("/d/"), "the list links to /d/<id>")
    check(not page.problems, f"the list loads without console errors {page.problems[:2]}")
    ctx.close()

    ms.ROLE["role"] = "rep"
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector(".dlist a", timeout=20000)
    check(page.locator(".dlist h2").all_inner_texts() == ["Regional sales"], "a rep is offered only the dashboard made for reps")
    ctx.close()
    ms.ROLE["role"] = "admin"

    # ---- the way back to the list
    home = "#home-link"
    ctx, page = open_page(browser, "/d/sales-overview")
    settled(page)
    check(page.locator(home).is_visible() and page.get_attribute(home, "href") == "/d/" and page.inner_text(home).strip() == "Dashboards", "a dashboard page has a Dashboards link to /d/")
    page.locator(home).click()
    page.wait_for_selector(".dlist a", timeout=20000)
    check(page.url.endswith("/d/") and page.locator(".dlist a").count() >= 3, "and it opens the list")
    check(not page.locator(home).is_visible(), "the list itself does not show it")
    check(not page.problems, f"no console errors {page.problems[:2]}")
    ctx.close()
    for path, why in (("/d/draft", "a draft page with nothing to show"), ("/d/no-such-dashboard", "a dashboard that does not exist")):
        ctx, page = open_page(browser, path)
        page.wait_for_function("!document.querySelector('#error').hidden", timeout=20000)
        check(page.locator(home).is_visible() and page.get_attribute(home, "href") == "/d/", f"an error page still leads back to the list ({why})")
        ctx.close()
    ms.ROLE["role"] = "purchasing"
    ctx, page = open_page(browser, "/d/envanter-sagligi")
    settled(page)
    check(page.inner_text(home).strip() == "Panolar" and page.get_attribute(home, "title") == "Panolar", "the link speaks the dashboard's language (Turkish)")
    ctx.close()
    ms.ROLE["role"] = "admin"
    ctx, page = open_page(browser, "/d/sales-overview", width=390)
    settled(page)
    box = page.locator(home).bounding_box()
    check(page.locator(home).is_visible() and page.inner_text(home).strip() == "Dashboards", "on a phone the link keeps its word")
    check(box["width"] >= 44 and box["height"] >= 44, f"with a 44px touch target ({box['width']:.0f}x{box['height']:.0f})")
    check(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "and the page does not overflow sideways")
    ctx.close()

    # ---- search on the list: the built dashboards and the saved lists, in the browser, as you type
    ms.reset_saved()
    ms.USER["name"] = "admin"
    ms.seed_saved("Quarterly review", "Numbers for the board")
    ms.seed_saved("Satış panosu", "Bölge ve kategori")
    ms.seed_saved("Stok raporu", "Ürün stok durumu")
    ms.seed_saved("<b>Bold</b> trap", "Escaped, not bold")
    ms.seed_saved("Regional deep dive", "Shared by Olga", owner="olga", visibility="everyone")
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector(".dlist a", timeout=20000)
    page.wait_for_selector(".saved", timeout=20000)
    box, status = "#list-q", "#list-q-status"
    built = lambda: page.locator(".dlist > a:not([hidden])").count()  # noqa: E731
    savedn = lambda: page.locator(".saved").count()  # noqa: E731
    check(built() == 4 and savedn() == 5 and page.inner_text(status) == "" and not page.locator("#list-q-clear").is_visible(), "the list starts whole: 4 built and 5 saved, no count, no Clear")
    check(page.get_by_label("Search dashboards").count() == 1 and page.get_attribute(box, "type") == "search", "the search field has an accessible name")
    requests = []
    page.on("request", lambda r: requests.append(r.url))
    page.fill(box, "satis")
    check(savedn() == 1 and "Satış panosu" in page.inner_text(".saved"), "\"satis\" finds the saved \"Satış panosu\" (Turkish letters fold)")
    check(built() == 1 and "Envanter" in page.inner_text(".dlist > a:not([hidden])"), "and the built \"Envanter sağlığı\", whose description says \"satış panosundaki\"")
    check(page.inner_text(status) == "2 of 9" and page.locator("#list-q-clear").is_visible(), "the count says 2 of 9 and Clear appears")
    page.fill(box, "sales")
    check(built() == 3 and savedn() == 0 and "(0 of 4)" in page.inner_text("#drafts-host") and "No saved dashboard matches" in page.inner_text("#drafts-host") and page.inner_text(status) == "3 of 9", "\"sales\" finds 3 built dashboards (two by title, the gallery by description); the saved list says none match, with its own count")
    page.fill(box, "olga")
    check(built() == 0 and savedn() == 1 and "Shared with you" in page.inner_text("#drafts-host") and "(1 of 1)" in page.inner_text("#drafts-host"), "the owner's name is searched: a dashboard shared by Olga")
    page.fill(box, "SAGLIG")
    check(built() == 1 and "Envanter" in page.inner_text(".dlist > a:not([hidden])"), "\"SAGLIG\" finds \"Envanter sağlığı\" (capitals, ğ and ı)")
    page.fill(box, "board QUARTERLY")
    check(savedn() == 1 and "Quarterly review" in page.inner_text(".saved"), "several words, in any order, across title and description")
    check(built() == 0, "and no built dashboard matches those words")
    page.fill(box, "(")
    check(built() == 0 and savedn() == 0 and not page.locator("#list-q-none").is_hidden() and "No dashboard matches" in page.inner_text("#list-q-none"), "a bracket is plain text: nothing matches and nothing breaks")
    page.fill(box, "zzz")
    check(page.inner_text("#list-q-none") == "No dashboard matches “zzz”.", "no match: one clear message that names the search")
    page.click("#list-q-clear")
    check(built() == 4 and savedn() == 5 and page.input_value(box) == "" and page.evaluate("document.activeElement.id") == "list-q" and page.locator("#list-q-none").is_hidden(), "Clear brings everything back and keeps the focus in the field")
    page.fill(box, "trap")
    check(savedn() == 1 and page.locator(".saved b").count() == 0 and "<b>Bold</b> trap" in page.inner_text(".saved"), "a title with HTML is shown as text, never as markup")
    page.keyboard.press("Escape")
    check(page.input_value(box) == "" and savedn() == 5, "Escape clears the search")
    page.locator("h1").click()
    page.keyboard.press("/")
    check(page.evaluate("document.activeElement.id") == "list-q" and page.input_value(box) == "", "\"/\" jumps to the search when you are not typing")
    page.keyboard.type("a/b")
    check(page.input_value(box) == "a/b", "and a slash typed in the field is just a slash")
    page.fill(box, "")
    page.fill(box, "quart")
    page.on("dialog", lambda d: d.accept())
    page.click(".saved button[data-act=delete]")
    page.wait_for_function("!document.querySelector('.saved')", timeout=10000)
    check(page.input_value(box) == "quart" and "No dashboard matches" in page.inner_text("#list-q-none") and page.inner_text(status) == "0 of 8", "deleting from a filtered list keeps the search and updates the count")
    page.fill(box, "")
    check(savedn() == 4, "and the deleted dashboard is gone from the full list")
    page_requests = [u for u in requests if "/builder/" in u or "/dashboards/" in u]
    check(len(page_requests) <= 3, f"typing asked the server for nothing: only the delete and its refresh went out ({[u.rsplit('/', 2)[-2:] for u in page_requests]})")
    check(not page.problems, f"no console errors {page.problems[:2]}")
    ctx.close()
    ctx, page = open_page(browser, "/d/", width=390)
    page.wait_for_selector(".dlist a", timeout=20000)
    check(page.locator(box).bounding_box()["height"] >= 44 and page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "on a phone the field is 44px high and the page does not scroll sideways")
    ctx.close()
    ms.reset_saved()

    # ---- a whole dashboard
    ctx, page = open_page(browser, "/d/sales-overview")
    settled(page)
    check(not page.problems, f"no console errors or warnings {page.problems[:3]}")
    check(page.inner_text("#title") == "Sales overview" and page.title().startswith("Sales overview"), "the title comes from the spec")
    check(page.text_content("#dataset-badge") == "Live (simulator)", "the dataset badge names the dataset")
    t = tiles(page)
    check(list(t) == ["Revenue", "Gross profit", "Gross margin", "Orders", "Avg order value", "Units sold"], f"six KPI tiles in order ({list(t)})")
    check(all(v not in ("…", "—", "") for v in t.values()), f"every tile has a value ({t})")
    check(page.locator(".kpi svg.spark").count() == 6, "every tile has a sparkline")
    page.locator(".kpi:first-child svg.spark .spark-hit").nth(2).hover()
    tip = page.inner_text("#tip")
    check(page.locator("#tip.on").count() == 1 and "Revenue" in tip and "$" in tip and "'" not in tip and any(m in tip for m in ("Sep", "Aug", "Sept")) , f"hovering a mini chart shows the period and the value ({tip!r})")
    check(page.evaluate("getComputedStyle(document.querySelector('.kpi:first-child .spark-pt:nth-of-type(3) .spark-guide')).opacity") != "0", "with a guide line at that point")
    page.mouse.move(5, 5)
    check(page.locator('[data-panel="trend"] svg rect, [data-panel="trend"] svg path').count() > 12, "the monthly chart draws bars")
    check(page.locator('[data-panel="trend"] .legend span').count() == 2, "the chart has a legend for its two series")
    check("Jul '20" in page.inner_text('[data-panel="trend"]'), "the time axis has month labels")
    check(page.locator('[data-panel="top"] .rrow').count() == 5, "the bar panel has one row per product")
    check(page.locator('[data-panel="lines"] tbody tr').count() > 3, "the table panel has rows")
    check("Order" in page.inner_text('[data-panel="lines"] thead') and "Revenue" in page.inner_text('[data-panel="lines"] thead'), "table columns use the spec's labels")
    check(page.locator('[data-panel="mix"] .cell').count() > 6 and page.locator('[data-panel="mix"] .group-label').count() == 4, "the treemap draws a tile per subcategory and a heading per category")
    check(page.locator('[data-panel="territories"] .rrow').count() == 3 and page.locator('[data-panel="margin"] svg path[stroke]').count() == 1, "territory bars and the margin line are drawn")
    check(page.locator('[data-panel="top"] .hbar i').count() >= 10, "stacked bars: one segment per channel")
    check([b.inner_text() for b in page.query_selector_all('[data-panel="trend"] .seg button')] == ["month", "quarter", "year"], "the time chart offers its granularities")
    check(page.locator("#filters select").count() == 4, "a select per filter")
    check(page.locator('#filters select >> nth=0 >> option').all_inner_texts() == ["All", "2020", "2021"], "fiscal years sorted numerically")

    # tooltip + table view + excel
    page.evaluate("document.querySelector('[data-panel=\"trend\"]').scrollIntoView({ block: 'center' })")
    page.locator('[data-panel="trend"] .hit').first.hover()
    check(page.locator("#tip.on").count() == 1 and "Internet" in page.inner_text("#tip") and "Total" in page.inner_text("#tip"), "hovering a month shows both series and the total")
    page.click('[data-panel="trend"] .tbl-toggle:not(.xls-btn)')
    check(page.locator('[data-panel="trend"] table').count() == 1 and page.locator('[data-panel="trend"] tbody tr').count() == 12, "the Table view lists the 12 months")
    page.click('[data-panel="trend"] .tbl-toggle:not(.xls-btn)')
    with page.expect_download(timeout=10000) as dl:
        page.click('[data-panel="top"] .xls-btn')
    name = dl.value.suggested_filename
    check(name.startswith("sales-overview-top-10-products-") and name.endswith(".xlsx"), f"a panel exports its own Excel file ({name})")
    check(pathlib.Path(dl.value.path()).read_bytes()[:2] == b"PK", "the export is a zip")
    with page.expect_download(timeout=10000) as dl:
        page.click("#export-all")
    check("dashboard" in dl.value.suggested_filename, f"Export all downloads every panel in one file ({dl.value.suggested_filename})")
    if KEEP:
        SHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SHOTS / "renderer-live-1440.png"), full_page=True)

    # ---- parity: the same figures as the sales dashboard for the same data
    ctx2, old = open_page(browser, "/")
    old.wait_for_function("!document.querySelector('#kpis').classList.contains('pending') && document.querySelectorAll('#kpis .kpi').length === 6", timeout=20000)
    old.wait_for_timeout(1500)
    oldt = {n.query_selector(".label").inner_text().split("\n")[0]: n.query_selector(".value").inner_text() for n in old.query_selector_all("#kpis .kpi")}
    for label in ("Revenue", "Gross profit", "Gross margin", "Units sold"):
        check(oldt.get(label) == t.get(label), f"{label}: the renderer shows {t.get(label)}, the sales dashboard {oldt.get(label)}")
    ctx2.close()

    # ---- filters
    page.queries.clear()
    page.aborted.clear()
    page.select_option("#filters select >> nth=0", "2021")
    page.select_option("#filters select >> nth=2", "Bikes")      # a second change straight away: the first load is still running
    settled(page)
    check("fy=2021" in page.url and "category=Bikes" in page.url, f"the filters are in the URL ({page.url})")
    q = " ".join(page.queries)
    check("dates.fiscal_year" in q and "products.category" in q, "queries carry the filters")
    check(page.locator("#filters .reset").is_visible(), "Reset filters appears")
    sub = page.locator('#filters select >> nth=3 >> option').all_inner_texts()
    check(sub[0] == "All" and "Road Bikes" in sub, f"the subcategory list is there ({sub})")
    page.select_option("#filters select >> nth=3", "Helmets")
    settled(page)
    page.select_option("#filters select >> nth=2", "Clothing")     # the parent changes: the child's options are narrowed again
    check(page.locator("#filters select >> nth=3").input_value() in ("", "Helmets"), "a child filter keeps or drops its value with its parent")
    settled(page)
    page.click("#filters .reset")
    settled(page)
    check("fy=" not in page.url and page.input_value("#filters select >> nth=0") == "", "Reset clears the filters and the URL")
    page.reload()
    settled(page)
    page.goto(f"{BASE}/d/sales-overview?fy=2020")
    settled(page)
    check(page.input_value("#filters select >> nth=0") == "2020", "a filter in the URL is applied on load")
    ctx.close()

    # ---- click to filter
    ctx, page = open_page(browser, "/d/sales-overview")
    settled(page)
    terr = '[data-panel="territories"]'
    first = page.locator(f"{terr} .rrow").first
    label = first.locator(".name").inner_text()
    page.queries.clear()
    first.click()
    settled(page)
    check(f"region={label}" in page.url and page.input_value("#filters select >> nth=1") == label, f"clicking a bar sets the region filter ({label})")
    check("sel" in (page.locator(f"{terr} .rrow").first.get_attribute("class") or ""), "the clicked bar is marked as selected")
    qs = sent(page)
    own = [q for q in qs if q.get("dimensions") == ["territories.region"]]
    check(not own, "the clicked panel does not query again (its own filter does not narrow it)")
    check(qs and all(has_filter(q, "territories.region") for q in qs if "territories.region" not in q.get("dimensions", [])
                     and any(m.endswith(("revenue", "orders", "units", "gross_profit")) for m in q.get("measures", []))), "every other panel's queries carry the filter")
    check(page.locator("#filters .reset").is_visible(), "Reset filters appears after a click")
    page.locator(f"{terr} .rrow").first.click()
    settled(page)
    check("region=" not in page.url and page.input_value("#filters select >> nth=1") == "", "clicking the selected bar again undoes it")
    page.locator(f"{terr} .rrow").nth(1).focus()
    page.keyboard.press("Enter")
    settled(page)
    check("region=" in page.url, "a bar can be picked with the keyboard (Enter)")
    page.click("#filters .reset")
    settled(page)

    # the treemap: a tile sets category and subcategory, a heading only the category; clicking again restores what was there before
    mix = '[data-panel="mix"]'
    page.select_option("#filters select >> nth=2", "Bikes")
    settled(page)
    tile = page.locator(f"{mix} .cell", has_text="Helmets").first
    page.queries.clear()
    tile.click()
    settled(page)
    cat, sub = page.input_value("#filters select >> nth=2"), page.input_value("#filters select >> nth=3")
    check(sub == "Helmets" and cat != "", f"a treemap tile sets the subcategory and its category ({cat} / {sub})")
    check(page.locator(f"{mix} .cell.sel").count() == 1 and "✓" in page.locator(f"{mix} .cell.sel").inner_text(), "the selected tile is outlined and ticked")
    check(not [q for q in sent(page) if q.get("dimensions") == ["products.category", "products.subcategory"]], "the treemap keeps showing every category (no query of its own)")
    page.locator(f"{mix} .cell.sel").click()
    settled(page)
    check(page.input_value("#filters select >> nth=2") == "Bikes" and page.input_value("#filters select >> nth=3") == "", "clicking it again brings back the category that was chosen before")
    check(page.locator(f"{mix} .group-label.sel").count() == 1, "the category chosen in the filter bar is marked in the treemap")
    head = page.locator(f"{mix} .group-label:not(.sel)").first
    name = head.text_content().split(" · ")[0].replace("✓ ", "")
    head.click()
    settled(page)
    check(page.input_value("#filters select >> nth=2") == name and page.input_value("#filters select >> nth=3") == "", f"a heading sets only the category ({name})")
    check(page.locator(f"{mix} .group-label.sel").count() == 1, "the selected heading is marked")
    page.click("#filters .reset")
    settled(page)

    # the time chart: a click sets the fiscal year; the granularity switch re-queries
    trend = '[data-panel="trend"]'
    page.evaluate("document.querySelector('[data-panel=\"trend\"]').scrollIntoView({ block: 'center' })")
    page.locator(f"{trend} .hit").nth(2).click()
    settled(page)
    check("fy=2021" in page.url, "a click on a month sets its fiscal year (Sep '20 is FY2021)")
    page.locator(f"{trend} .hit").nth(2).click()
    settled(page)
    check("fy=" not in page.url, "and clicking again clears it")
    page.queries.clear()
    page.click(f'{trend} .seg button[data-g="quarter"]')
    page.wait_for_function("document.querySelector('[data-panel=\"trend\"] .seg button[data-g=\"quarter\"]').getAttribute('aria-pressed') === 'true'")
    page.wait_for_timeout(800)
    check(any(q.get("timeDimensions", [{}])[0].get("granularity") == "quarter" for q in sent(page)), "the granularity switch queries by quarter")
    check("Q3 2020" in page.inner_text(trend), "and labels the buckets as quarters")
    check(page.locator('[data-panel="kpis"]').count() == 1 and not any(q.get("timeDimensions", [{}])[0].get("granularity") == "quarter" and "internet_sales.units" in q.get("measures", []) for q in sent(page)), "other panels are not reloaded by it")
    ctx.close()

    # a table whose rows filter (patched into the spec: the sales dashboard's table has no click)
    ctx, page = open_page(browser, "/d/sales-overview")
    def patch(route):
        spec = json.loads(route.fetch().text())
        spec["filters"].append({"id": "country", "dimension": "territories.country", "label": "Country"})
        next(p for p in spec["panels"] if p["id"] == "lines")["on_click"] = {"set_filter": "country"}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(spec))
    page.route("**/dashboards/sales-overview.json", patch)
    page.reload()
    settled(page)
    row = page.locator('[data-panel="lines"] tbody tr').first
    country = row.locator("td").nth(2).inner_text()
    row.click()
    settled(page)
    check(f"country={country}" in page.url, f"clicking a table row sets the filter from the row ({country})")
    check(page.locator('[data-panel="lines"] tr.sel').count() >= 1, "the matching rows are marked")
    ctx.close()

    # a table's total row (patched into the spec): bold, dimension cells empty, from its own query over the whole set, and frozen
    def with_totals(where):
        def patch_totals(route):
            spec = json.loads(route.fetch().text())
            next(p for p in spec["panels"] if p["id"] == "lines")["totals"] = where
            route.fulfill(status=200, content_type="application/json", body=json.dumps(spec))
        return patch_totals
    geom = """() => { const w = document.querySelector('[data-panel="lines"] .tbl-wrap'), r = w.querySelector('tr.tot td').getBoundingClientRect(),
        h = w.querySelector('thead th').getBoundingClientRect(), b = w.getBoundingClientRect();
      return { top: r.top, bottom: r.bottom, wrapTop: b.top, wrapBottom: b.bottom, titleBottom: h.bottom, scrollTop: w.scrollTop, scrollable: w.scrollHeight > w.clientHeight }; }"""
    for where in ("footer", "header"):
        ctx, page = open_page(browser, "/d/sales-overview")
        page.route("**/dashboards/sales-overview.json", with_totals(where))
        page.reload()
        settled(page)
        tot = page.locator('[data-panel="lines"] tr.tot')
        check(tot.count() == 1 and page.locator(f'[data-panel="lines"] {"tfoot" if where == "footer" else "thead"} tr.tot').count() == 1, f"totals: {where} puts one total row in the {where}")
        cells = tot.locator("td").all_inner_texts()
        check(cells[:3] == ["", "", ""] and cells[3].startswith("$") and cells[3] != "–", f"the dimension cells are empty and the revenue cell has a figure ({cells})")
        check(int(tot.locator("td").nth(3).evaluate("n => getComputedStyle(n).fontWeight")) >= 600, "the total row is bold")
        whole = [q for q in sent(page) if q.get("measures") == ["internet_sales.revenue"] and not q.get("dimensions") and not q.get("timeDimensions") and "limit" not in q]
        check(len(whole) >= 1, "the total is its own query: no grouping, no limit")
        g = page.evaluate(geom)
        check(g["scrollable"], "the table is taller than its scroll area, so freezing means something")
        page.eval_on_selector('[data-panel="lines"] .tbl-wrap', "w => { w.scrollTop = 160; }")
        page.wait_for_timeout(100)
        g = page.evaluate(geom)
        if where == "footer":
            check(g["scrollTop"] > 0 and abs(g["bottom"] - g["wrapBottom"]) <= 2, f"the footer total stays at the bottom edge while the rows scroll ({g['bottom']} vs {g['wrapBottom']})")
        else:
            check(g["scrollTop"] > 0 and abs(g["top"] - g["titleBottom"]) <= 2 and g["top"] >= g["wrapTop"], f"the header total stays under the column titles while the rows scroll ({g['top']} vs {g['titleBottom']})")
        btn = page.locator('[data-panel="lines"] .tot-btn')
        check(btn.get_attribute("aria-pressed") == "true", "the Totals button is on by default")
        queries_before = len(page.queries)
        btn.click()
        check(page.locator('[data-panel="lines"] tr.tot').count() == 0 and btn.get_attribute("aria-pressed") == "false", "the Totals button hides the total row")
        check(page.locator('[data-panel="lines"] tbody tr').count() > 3 and len(page.queries) == queries_before, "without asking Cube again")
        btn.click()
        check(page.locator('[data-panel="lines"] tr.tot').count() == 1, "and shows it again")
        check(not page.problems, f"no console errors {page.problems[:2]}")
        if where == "footer":
            with page.expect_download(timeout=10000) as dl:
                page.locator('[data-panel="lines"] .xls-btn').click()
            sheet = zipfile.ZipFile(io.BytesIO(pathlib.Path(dl.value.path()).read_bytes())).read("xl/worksheets/sheet1.xml").decode()
            check(sheet.count("<row") >= page.locator('[data-panel="lines"] tbody tr').count() + 1, "the Excel sheet has the total row too")
        ctx.close()

    # click a column title to sort: measures desc/asc/none, dimensions asc/desc/none; none = every dimension ascending, left to right
    ctx, page = open_page(browser, "/d/sales-overview")
    settled(page)
    def table_order():
        qs = [q for q in sent(page) if "internet_sales.order_number" in q.get("dimensions", []) and "limit" in q]
        return list(qs[-1].get("order", {}).items())
    DIMS_ASC = [["internet_sales.order_number", "asc"], ["internet_sales.order_date", "asc"], ["territories.country", "asc"]]
    check(table_order() == [("internet_sales.order_date", "desc")], f"the table opens in the spec's order ({table_order()})")
    th = lambda label: page.locator('[data-panel="lines"] th.sortable', has_text=label)
    def click(label):
        n = len(page.queries)
        th(label).click()
        page.wait_for_function("document.querySelector('[data-panel=lines]') && !document.querySelector('[data-panel=lines]').classList.contains('pending')", timeout=10000)
        page.wait_for_timeout(150)
        check(len(page.queries) > n, f"clicking '{label}' asks Cube for the new order")
    click("Revenue")
    check(table_order() == [("internet_sales.revenue", "desc")] + [tuple(x) for x in DIMS_ASC] and th("Revenue").get_attribute("aria-sort") == "descending" and "↓" in th("Revenue").inner_text(), f"a measure sorts descending first ({table_order()})")
    click("Revenue")
    check(table_order()[0] == ("internet_sales.revenue", "asc") and th("Revenue").get_attribute("aria-sort") == "ascending", "then ascending")
    click("Revenue")
    check(table_order() == [tuple(x) for x in DIMS_ASC] and th("Revenue").get_attribute("aria-sort") == "none", f"then none: every dimension ascending, left to right ({table_order()})")
    click("Country")
    check(table_order()[0] == ("territories.country", "asc") and th("Country").get_attribute("aria-sort") == "ascending", "a dimension sorts ascending first")
    click("Country")
    check(table_order()[0] == ("territories.country", "desc") and "↓" in th("Country").inner_text(), "then descending")
    click("Country")
    check(table_order() == [tuple(x) for x in DIMS_ASC] and page.locator('[data-panel="lines"] th[aria-sort="ascending"], [data-panel="lines"] th[aria-sort="descending"]').count() == 0, "then none")
    th("Order").focus()
    page.keyboard.press("Enter")
    page.wait_for_timeout(400)
    check(th("Order").get_attribute("aria-sort") == "ascending", "the keyboard sorts too")
    check(not page.problems, f"no console errors {page.problems[:2]}")
    ctx.close()

    # pivot panels (patched into the spec): axes, then values for those keys; totals; clicks; the Excel sheet; limits
    def with_pivot(**panel):
        def patch_pivot(route):
            spec = json.loads(route.fetch().text())
            spec["panels"].append({"id": "xtab", "type": "pivot", "title": "Revenue by category and year", "rows": ["products.category"], "columns": "dates.fiscal_year",
                                   "measures": [{"member": "internet_sales.revenue", "format": "money"}], **panel})
            spec["layout"].append([{"panel": "xtab", "span": 12}])
            route.fulfill(status=200, content_type="application/json", body=json.dumps(spec))
        return patch_pivot
    xt = '[data-panel="xtab"]'
    ctx, page = open_page(browser, "/d/sales-overview")
    page.route("**/dashboards/sales-overview.json", with_pivot(on_click={"set_filter": ["category", "fy"]}))
    page.reload()
    settled(page)
    page.wait_for_selector(f"{xt} table.pivot", timeout=20000)
    check(not page.problems, f"a pivot loads without console errors {page.problems[:2]}")
    check(page.locator(f"{xt} thead th.ck").all_inner_texts() == ["2020", "2021"] and page.locator(f"{xt} thead th.tc").all_inner_texts() == ["Total"], "the columns are the fiscal years, then Total")
    check(page.locator(f"{xt} tbody tr").count() == 4 and page.locator(f"{xt} tbody th.rl").all_inner_texts()[0] == "Bikes", "one row per category")
    cells = page.locator(f"{xt} tbody tr").first.locator("td").all_inner_texts()
    check(len(cells) == 3 and all(c.startswith("$") for c in cells), f"cells are money, with the row's total last ({cells})")
    foot = page.locator(f"{xt} tfoot tr.tot")
    check(foot.count() == 1 and foot.locator("th").inner_text() == "Total" and len(foot.locator("td").all_inner_texts()) == 3, "a frozen total row with a grand total")
    check(int(foot.locator("td").first.evaluate("n => getComputedStyle(n).fontWeight")) >= 600, "the total row is bold")
    qs = sent(page)
    axis = [q for q in qs if q.get("dimensions") == ["products.category"] and q.get("limit") == 26]
    cellq = [q for q in qs if q.get("dimensions") == ["products.category", "dates.fiscal_year"]]
    check(len(axis) == 1 and axis[0]["order"] == {"internet_sales.revenue": "desc", "products.category": "asc"}, "wave 1 asks for the top 25 rows (+1) by the first measure")
    check(any(q.get("dimensions") == ["dates.fiscal_year"] and q.get("limit") == 13 and q["order"] == {"dates.fiscal_year": "asc"} for q in qs), "and the first 12 columns (+1) by name")
    check(len(cellq) == 1 and any(f.get("member") == "products.category" and f.get("values") for f in cellq[0]["filters"]), "wave 2 asks for the cells of those rows and columns")
    check(any(not q.get("dimensions") and q.get("measures") == ["internet_sales.revenue"] and not q.get("filters") and q.get("limit") is None for q in qs), "the grand total is its own query over the whole set")
    first = page.locator(f"{xt} tbody tr").first
    first.locator("td").nth(1).click()
    settled(page)
    check("category=Bikes" in page.url and "fy=2021" in page.url and page.locator(f"{xt} td.sel").count() >= 1, "a click on a cell sets the row's and the column's filters")
    page.locator(f"{xt} tbody th.rl").nth(1).click()
    settled(page)
    check("category=Components" in page.url, "a click on a row name sets the row's filter")
    page.locator(f"{xt} thead th.ck").first.click()
    settled(page)
    check("fy=2020" in page.url, "a click on a column title sets the column's filter")
    check(page.locator(f"{xt} tfoot td.tc.clickable, {xt} tfoot td.tc[data-r], {xt} tfoot td.tc[data-c]").count() == 0, "the grand total filters nothing")
    with page.expect_download(timeout=10000) as dl:
        page.locator(f"{xt} .xls-btn").click()
    sheet = zipfile.ZipFile(io.BytesIO(pathlib.Path(dl.value.path()).read_bytes())).read("xl/worksheets/sheet1.xml").decode()
    check(sheet.count("<row") >= 4 + 1 + 1 and "Bikes" in sheet and "Total" in sheet, "the Excel sheet has the rows, the headings and the total row")
    ctx.close()

    ctx, page = open_page(browser, "/d/sales-overview")
    page.route("**/dashboards/sales-overview.json", with_pivot(rows=["products.category", "products.subcategory"], measures=[{"member": "internet_sales.revenue", "format": "money"}, {"member": "internet_sales.units", "format": "int"}]))
    page.reload()
    settled(page)
    page.wait_for_selector(f"{xt} table.pivot", timeout=20000)
    check(page.locator(f"{xt} tr.grp").count() == 4 and page.locator(f"{xt} tbody tr:not(.grp)").count() == 16, "two row levels: a group row per category and its subcategories under it")
    check(page.locator(f"{xt} thead tr").count() == 2 and page.locator(f"{xt} th.mh").count() == 6, "two measures: a second title row")
    check(any(q.get("dimensions") == ["products.category", "dates.fiscal_year"] for q in sent(page)) and any(q.get("dimensions") == ["products.category"] and q.get("limit") == 200 for q in sent(page)), "the groups are asked for too")
    check(not page.problems, f"no console errors {page.problems[:2]}")
    ctx.close()

    ctx, page = open_page(browser, "/d/sales-overview")
    page.route("**/dashboards/sales-overview.json", with_pivot(limit={"rows": 2, "columns": 1}, totals="rows"))
    page.reload()
    settled(page)
    page.wait_for_selector(f"{xt} table.pivot", timeout=20000)
    check(page.locator(f"{xt} tbody tr").count() == 2 and page.locator(f"{xt} thead th.ck").count() == 1, "the limits cut the rows and the columns")
    note = page.inner_text(xt)
    check("Only the first 2 rows are shown" in note and "Only the first 1 columns are shown" in note, "and the panel says that more exist")
    check(page.locator(f"{xt} tfoot").count() == 0 and page.locator(f"{xt} th.tc").count() == 1, "totals: rows has a total column and no total row")
    ctx.close()

    # time columns and heat: months across, the first six; shading on revenue; a title click filters nothing; contrast in both themes
    MONTHS_HEAT = dict(columns={"member": "dates.full_date", "granularity": "month"}, limit={"columns": 6}, heat={"measure": "internet_sales.revenue"}, on_click={"set_filter": ["category"]})
    contrast = """() => {
      const td = [...document.querySelectorAll('[data-panel="xtab"] td.heat')].reduce((a, b) => (+b.style.getPropertyValue('--heat') > +a.style.getPropertyValue('--heat') ? b : a));
      const parse = (c) => c.match(/[\\d.]+/g).map(Number);
      const over = (fg, bg) => { const a = fg[3] ?? 1; return [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a)); };
      const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
      const card = parse(getComputedStyle(td.closest('.card')).backgroundColor), bg = over(parse(getComputedStyle(td).backgroundColor), card), fg = parse(getComputedStyle(td).color);
      const [l1, l2] = [lum(fg.slice(0, 3)), lum(bg)].sort((x, y) => y - x);
      return (l1 + 0.05) / (l2 + 0.05);
    }"""
    for theme in ("light", "dark"):
        ctx, page = open_page(browser, "/d/sales-overview", theme=theme)
        page.route("**/dashboards/sales-overview.json", with_pivot(**MONTHS_HEAT))
        page.reload()
        settled(page)
        page.wait_for_selector(f"{xt} table.pivot", timeout=20000)
        if theme == "light":
            titles = page.locator(f"{xt} thead th.ck").all_inner_texts()
            check(len(titles) == 6 and titles[0] == "Jul '20", f"the columns are months, the first six, labelled by month ({titles})")
            check("(month)" in page.inner_text(f"{xt} th.corner"), "and the corner names the granularity")
            check(any(q.get("timeDimensions", [{}])[0].get("dateRange") == ["2020-07-01", "2020-12-31"] and q.get("dimensions") == ["products.category"] for q in sent(page)), "the cells are asked for those six months only")
            check(page.locator(f"{xt} td.heat").count() == 24, "every cell is shaded (4 rows x 6 months)")
            levels = sorted(float(v) for v in page.eval_on_selector_all(f"{xt} td.heat", "ns => ns.map(n => n.style.getPropertyValue('--heat'))"))
            check(levels[0] == 0 and levels[-1] == 1, f"from the smallest cell (0) to the largest (1) ({levels[0]}..{levels[-1]})")
            check(page.locator(f"{xt} tfoot td.heat, {xt} td.tc.heat").count() == 0, "totals are not shaded")
            check(all(t.strip() for t in page.locator(f"{xt} td.heat").all_inner_texts()), "every shaded cell still shows its number")
            check("Shading: Internet sales revenue" in page.inner_text(xt) or "Shading: Revenue" in page.inner_text(xt) or "Shading:" in page.inner_text(xt), "a legend explains the shading")
            check("Only the first 6 columns are shown" in page.inner_text(xt), "and the panel says more months exist")
            url = page.url
            page.locator(f"{xt} thead th.ck").first.click()
            page.wait_for_timeout(300)
            check(page.url == url and page.locator(f"{xt} thead th.ck.clickable").count() == 0, "a time column's title filters nothing")
            page.locator(f"{xt} tbody tr").first.locator("td").nth(2).click()
            settled(page)
            check("category=" in page.url and "fy=" not in page.url, "a cell sets the row's filter only")
        ratio = page.evaluate(contrast)
        check(ratio >= 4.5, f"the strongest shade keeps the text readable in the {theme} theme (contrast {ratio:.1f}:1)")
        check(not page.problems, f"no console errors ({theme}) {page.problems[:2]}")
        ctx.close()

    # shares: percentages from the totals Cube returned
    ctx, page = open_page(browser, "/d/sales-overview")
    page.route("**/dashboards/sales-overview.json", with_pivot(show="share_of_column", measures=[{"member": "internet_sales.revenue", "format": "money"}]))
    page.reload()
    settled(page)
    page.wait_for_selector(f"{xt} table.pivot", timeout=20000)
    body = page.locator(f"{xt} tbody td:not(.tc)").all_inner_texts()
    check(body and all(c.endswith("%") for c in body), f"the cells are percentages ({body[:3]})")
    check(all(c == "100.0%" for c in page.locator(f"{xt} tfoot td:not(.tc)").all_inner_texts()), "each column's total is 100%")
    check(not page.problems, f"no console errors {page.problems[:2]}")
    ctx.close()

    # the pivot gallery dashboard: every variant draws from the checked-in spec
    ctx, page = open_page(browser, "/d/pivot-gallery")
    settled(page)
    page.wait_for_selector("table.pivot", timeout=20000)
    page.wait_for_function("document.querySelectorAll('table.pivot').length === 5", timeout=20000)
    check(not page.problems, f"the pivot gallery loads without console errors {page.problems[:2]}")
    check(page.locator('[data-panel="groups"] tr.grp').count() > 0 and page.locator('[data-panel="heatmap"] td.heat').count() > 0, "it has groups and a heatmap")
    check(page.locator('[data-panel="sidebyside"] th.mh').count() == 6 and page.locator('[data-panel="share"] td.heat').count() > 0, "two measures side by side, and a shaded share table")
    check(all(c.endswith("%") for c in page.locator('[data-panel="share"] tbody td:not(.tc)').all_inner_texts()), "the share table shows percentages")
    page.locator('[data-panel="crosstab"] tbody tr').first.locator("td").first.click()
    settled(page)
    check("category=" in page.url and "fy=" in page.url, "a click on a cell filters the whole page")
    ctx.close()

    # a total that fails must not take the rows with it
    ctx, page = open_page(browser, "/d/sales-overview")
    def no_total(route):
        q = json.loads(parse_qs(urlparse(route.request.url).query).get("query", ["{}"])[0])
        if q.get("measures") == ["internet_sales.revenue"] and not q.get("dimensions") and not q.get("timeDimensions"):
            route.fulfill(status=500, content_type="application/json", body='{"error":"boom"}')
        else:
            route.continue_()
    page.route("**/dashboards/sales-overview.json", with_totals("footer"))
    page.route("**/cube-*/**/load*", no_total)
    page.reload()
    page.wait_for_function("document.querySelectorAll('[data-panel=lines] tbody tr').length > 3", timeout=20000)
    check(page.locator('[data-panel="lines"] tr.tot td').nth(3).inner_text() == "–", "when only the total fails its cells show a dash and the rows stay")
    ctx.close()

    # ---- one failing panel does not blank the rest
    ms.FAIL["members"] = {"internet_sales.gross_profit"}
    ctx, page = open_page(browser, "/d/sales-overview")
    settled(page)
    t = tiles(page)
    check(t["Revenue"] not in ("—", "…") and t["Gross profit"] == "—" and t["Gross margin"] == "—", f"tiles that need the forbidden measure show — ({t})")
    check("not available for your role" in page.inner_text(".kpi >> nth=1"), "the tile says why")
    check(page.locator('[data-panel="top"] .rrow').count() == 5 and page.locator('[data-panel="lines"] tbody tr').count() > 3, "the other panels still draw")
    ms.FAIL["members"] = {"internet_sales.revenue"}
    ctx.close()
    ctx, page = open_page(browser, "/d/sales-overview")
    settled(page)
    check("not available for your role" in page.inner_text('[data-panel="trend"] .panel-error'), "a panel whose query fails shows a readable error in its card")
    check(page.locator('[data-panel="trend"].error').count() == 1 and "Updated" in page.inner_text("#live-text"), "the page still reports an update")
    ms.FAIL["members"] = set()
    ctx.close()

    # ---- dataset switch
    ctx, page = open_page(browser, "/d/sales-overview", dataset="live")
    settled(page)
    check(page.locator("#f-dataset").is_visible() and page.locator("#f-dataset option").count() == 2, "two datasets: a switch in the header")
    page.queries.clear()
    page.select_option("#f-dataset", "250m")
    page.wait_for_url("**dataset=250m**")
    settled(page)
    check(page.queries and all("/cube-bench/" in u for u in page.queries), "the 250M dataset reads its own Cube")
    check(page.text_content("#dataset-badge") == "250M benchmark", "the badge names the benchmark")
    ctx.close()

    # ---- language, currency, theme
    ms.ROLE["role"] = "purchasing"
    ctx, page = open_page(browser, "/d/envanter-sagligi")
    settled(page)
    check(not page.problems, f"the Turkish dashboard loads without console errors {page.problems[:2]}")
    check(page.get_attribute("html", "lang") == "tr", "the page language follows the spec's locale")
    check("Durum" in page.inner_text("#filters") and "Tümü" in page.inner_text("#filters"), "filter labels and 'All' are Turkish")
    check("Tümünü dışa aktar" in page.inner_text("#export-all") and "Güncellendi" in page.inner_text("#live-text"), "the page's own words are Turkish")
    check(page.locator('[data-panel="durumlar"] .tbl-toggle', has_text="Tablo").count() == 1, "panel buttons are Turkish")
    check("₺" in page.inner_text('[data-panel="ozet"]'), "money tiles use the lira sign")
    check("₺4.200" in page.inner_text('[data-panel="siparis"]'), "a table shows whole lira with Turkish separators")
    check("Sign out" not in page.inner_text("#who") and "Çıkış" in page.inner_text("#who"), "Sign out is translated")
    with page.expect_download(timeout=10000) as dl:
        page.click("#export-all")
    xl = zipfile.ZipFile(io.BytesIO(pathlib.Path(dl.value.path()).read_bytes()))
    styles = xl.read("xl/styles.xml").decode()
    check("&quot;₺&quot;#,##0.00" in styles and "&quot;$&quot;" not in styles, "the Excel file formats money with the lira sign")
    ctx.close()
    ms.ROLE["role"] = "rep"
    ctx, page = open_page(browser, "/d/envanter-sagligi")
    page.wait_for_function("!document.querySelector('#error').hidden", timeout=20000)
    check("rolünüz (rep) için kullanılamaz" in page.inner_text("#error"), "the role message is Turkish too")
    ctx.close()
    ms.ROLE["role"] = "admin"

    ctx, page = open_page(browser, "/d/sales-overview")
    def themed(route):
        spec = json.loads(route.fetch().text())
        spec.update(locale="tr-TR", currency="TRY", theme={"name": "Fairstone", "logo": "/render/none.svg", "colors": {"internet": "#112233"}})
        route.fulfill(status=200, content_type="application/json", body=json.dumps(spec))
    page.route("**/dashboards/sales-overview.json", themed)
    page.reload()
    settled(page)
    check("Tem '20" in page.inner_text('[data-panel="trend"]'), "month names follow the locale (Tem = July)")
    check(page.text_content("#brand-name") == "Fairstone" and page.is_visible("#brand-name"), "the theme's name is shown above the title")
    check(page.get_attribute("#logo", "src") == "/render/none.svg" and not page.eval_on_selector("#logo", "n => n.hidden"), "the theme's logo is set")
    check(page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--internet').trim()") == "#112233", "the theme's colours replace the tokens")
    check(page.evaluate("getComputedStyle(document.querySelector('[data-panel=\"trend\"] .legend .swatch')).backgroundColor") == "rgb(17, 34, 51)", "a series coloured `internet` follows the theme")
    ctx.close()

    # ---- drill-down, pie, columns, area
    ctx, page = open_page(browser, "/d/sales-drilldown")
    settled(page)
    trend = '[data-panel="trend"]'
    crumbs = lambda: page.locator(f"{trend} .crumb").all_inner_texts()  # noqa: E731
    hits = lambda: page.locator(f"{trend} .hit").count()  # noqa: E731
    check(not page.problems, f"the drill-down dashboard loads without console errors {page.problems[:2]}")
    check(crumbs() == ["All"] and hits() == 3 and "2019" in page.inner_text(trend) and "Click a point to drill down" in page.inner_text(trend), "the chart starts at the year level with a trail")
    check(page.locator(f"{trend} svg path[fill-opacity]").count() >= 2, "a stacked area is drawn")
    check(page.locator('[data-panel="donut"] path.slice').count() == 4 and page.locator('[data-panel="donut"] .pie-legend li').count() == 4, "the donut has a slice and a legend row per subcategory")
    check("Total" in page.inner_text('[data-panel="donut"]') and "$" in page.text_content('[data-panel="donut"] .pie-total'), "with the total in the middle")
    detail = '[data-panel="detail"]'
    cells = page.locator(f"{detail} tfoot tr.tot td").all_inner_texts()
    check(page.locator(f"{detail} tbody tr").count() > 3 and cells[:2] == ["", ""] and all(c.startswith("$") for c in cells[2:4]) and all(c.endswith("%") for c in cells[4:]), f"the subcategory table has a footer total: dimensions empty, revenue and margin filled ({cells})")
    wholes = [q for q in sent(page) if not q.get("dimensions") and not q.get("timeDimensions") and q.get("measures") in (["internet_sales.revenue", "internet_sales.margin_pct"], ["reseller_sales.revenue", "reseller_sales.margin_pct"])]
    check(len(wholes) == 2, f"one total query per measure cube, margins included, so each margin is the set's own ratio ({len(wholes)})")
    page.locator('[data-panel="donut"] path.slice').first.hover()
    check("Revenue" in page.inner_text("#tip") and "Share" in page.inner_text("#tip"), "the slice tooltip uses the author's measure label")
    page.mouse.move(5, 5)
    check(page.locator('[data-panel="categories"] svg .hit').count() == 4 and page.locator('[data-panel="categories"] svg rect[fill]').count() >= 4, "vertical columns are drawn for the category bars")
    check(page.locator("#period-bar").is_hidden(), "no period yet")

    page.queries.clear()
    page.locator(f"{trend} .hit").nth(1).click()
    settled(page)
    check(crumbs() == ["All", "2020"] and hits() == 12, f"a click on 2020 opens its twelve months ({crumbs()}, {hits()} points)")
    check("period=2020-01-01..2020-12-31" in page.url and "drill_trend=2020-01-01" in page.url, f"the period and the drill path are in the URL ({page.url})")
    check(page.locator("#period-bar .chip").is_visible() and "2020" in page.inner_text("#period-bar"), "a chip names the period")
    qs = sent(page)
    own = [q for q in qs if q.get("timeDimensions", [{}])[0].get("granularity") == "month" and q.get("measures") == ["internet_sales.revenue"]]
    check(own and own[0]["timeDimensions"] == [{"dimension": "dates.full_date", "granularity": "month", "dateRange": ["2020-01-01", "2020-12-31"]}], "the chart queries months of that year, with one time entry")
    donut = [q for q in qs if q.get("dimensions") == ["products.subcategory"]]
    check(donut and donut[0]["timeDimensions"] == [{"dimension": "dates.full_date", "dateRange": ["2020-01-01", "2020-12-31"]}], "the donut follows the period (cross-filtering)")
    kpi = [q for q in qs if q.get("measures") == ["internet_sales.revenue"] and "dimensions" not in q and q.get("timeDimensions", [{}])[0].get("granularity") != "month"]
    check(kpi and kpi[0]["timeDimensions"][0].get("dateRange") == ["2020-01-01", "2020-12-31"], "so do the KPI tiles")
    check(all(q.get("timeDimensions", [{}])[0].get("dateRange") == ["2020-01-01", "2020-12-31"] for q in qs if q.get("dimensions") in (["products.category"], ["territories.region"])), "and the other bars")

    page.locator(f"{trend} .hit").nth(2).click()
    settled(page)
    check(crumbs() == ["All", "2020", "Mar 2020"] and hits() == 31 and "period=2020-03-01..2020-03-31" in page.url, f"then March: its 31 days ({crumbs()}, {hits()})")
    page.locator(f"{trend} .hit").nth(4).click()
    settled(page)
    check("period=2020-03-05..2020-03-05" in page.url and crumbs() == ["All", "2020", "Mar 2020"], "on the last level a click picks the day")
    page.locator(f"{trend} .hit").nth(4).click()
    settled(page)
    check("period=2020-03-01..2020-03-31" in page.url, "and the same day again goes back to the month")
    page.click(f"{trend} .crumb >> text=2020")
    settled(page)
    check(crumbs() == ["All", "2020"] and hits() == 12 and "period=2020-01-01..2020-12-31" in page.url and "drill_trend=2020-01-01" in page.url and "2020-03" not in page.url, "the trail goes back up a level")
    page.click(f"{trend} .crumb >> text=All")
    settled(page)
    check(crumbs() == ["All"] and hits() == 3 and "period=" not in page.url and page.locator("#period-bar").is_hidden() and "drill_trend" not in page.url, "and to the top: no period, no chip")

    # the pie and the drill-down work together: a slice filters everything, the chart keeps its place
    page.locator(f"{trend} .hit").nth(1).click()
    settled(page)
    page.queries.clear()
    page.locator('[data-panel="donut"] .pie-legend li').first.click()
    settled(page)
    check("subcategory=" in page.url and "period=2020-01-01..2020-12-31" in page.url and crumbs() == ["All", "2020"], "a slice sets the subcategory while the drill-down keeps its place")
    own = [q for q in sent(page) if q.get("timeDimensions", [{}])[0].get("granularity") == "month"]
    check(own and own[0]["filters"] and own[0]["timeDimensions"][0]["dateRange"] == ["2020-01-01", "2020-12-31"], "the chart's queries carry the subcategory filter and its own range")
    check(page.locator('[data-panel="donut"] path.slice.dim').count() == 3 and page.locator('[data-panel="donut"] .pie-legend li.sel').count() == 1, "the chosen slice is marked and the others fade")
    page.locator('[data-panel="donut"] .pie-legend li').first.click()
    settled(page)
    check("subcategory=" not in page.url, "clicking it again undoes it")
    page.locator('[data-panel="donut"] path.slice').nth(1).hover()
    check(page.locator("#tip.on").count() == 1 and "%" in page.inner_text("#tip"), "hovering a slice shows its value and share")
    page.locator('[data-panel="donut"] path.slice').nth(1).click()
    settled(page)
    check("subcategory=" in page.url and page.locator('[data-panel="donut"] path.slice.dim').count() == 3, "a slice can be clicked too")
    page.locator('[data-panel="categories"] .hit').nth(0).click()
    settled(page)
    check("category=" in page.url and page.locator('[data-panel="categories"] svg g.dim').count() == 3, "a column sets the category and the others fade")
    page.click('[data-panel="donut"] .tbl-toggle:not(.xls-btn)')
    check(page.locator('[data-panel="donut"] tbody tr').count() >= 1 and "Share" in page.inner_text('[data-panel="donut"] thead'), "the donut has a Table view with its shares")

    # reload restores the place; the chip's x puts the chart back
    page.reload()
    settled(page)
    check(crumbs() == ["All", "2020"] and hits() == 12, "a reload keeps the drill-down (from the URL)")
    page.click("#period-bar .chip-x")
    settled(page)
    check(crumbs() == ["All"] and hits() == 3 and page.locator("#period-bar").is_hidden() and "period=" not in page.url, "the chip's x clears the period and the chart goes back to years")
    page.click("#filters .reset")
    settled(page)
    check("category=" not in page.url and "subcategory=" not in page.url, "Reset filters clears the filters too")
    ctx.close()

    # a panel can opt out of the period; the Table, Excel and phone widths
    ctx, page = open_page(browser, "/d/sales-drilldown")
    def optout(route):
        spec = json.loads(route.fetch().text())
        next(p for p in spec["panels"] if p["id"] == "kpis")["ignore_filters"] = ["period"]
        route.fulfill(status=200, content_type="application/json", body=json.dumps(spec))
    page.route("**/dashboards/sales-drilldown.json", optout)
    page.reload()
    settled(page)
    page.queries.clear()
    page.locator(f"{trend} .hit").nth(1).click()
    settled(page)
    qs = sent(page)
    dated = lambda q: any(t.get("dateRange") for t in q.get("timeDimensions", []))  # noqa: E731
    check([q for q in qs if q.get("dimensions") == ["products.subcategory"] and dated(q)] and not [q for q in qs if "internet_sales.orders" in q.get("measures", []) and dated(q)],
          "ignore_filters: [period] keeps a panel out of the drill-down's period while the others follow it")
    ctx.close()
    ctx, page = open_page(browser, "/d/sales-drilldown", width=390)
    settled(page)
    page.locator(f"{trend} .hit").nth(1).click()
    settled(page)
    check(page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 0, "390px: the drill-down page has no sideways scroll")
    ctx.close()

    # ---- unknown dashboard, wrong role
    ctx, page = open_page(browser, "/d/nope")
    page.wait_for_function("!document.querySelector('#error').hidden", timeout=20000)
    check("no dashboard 'nope'" in page.inner_text("#error"), "an unknown id says so")
    ctx.close()
    ms.ROLE["role"] = "rep"
    ctx, page = open_page(browser, "/d/sales-overview")
    page.wait_for_function("!document.querySelector('#error').hidden", timeout=20000)
    check("not available for your role (rep)" in page.inner_text("#error") and page.locator(".kpi").count() == 0, "a role the dashboard is not for gets a message, and no data is requested")
    check(not [u for u in page.queries], "no Cube query is sent")
    ctx.close()
    ms.ROLE["role"] = "admin"

    # ---- layout at other widths, both themes
    for width, theme in ((1920, "light"), (1024, "dark"), (390, "light")):
        ctx, page = open_page(browser, "/d/sales-overview", width=width, theme=theme)
        settled(page)
        over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        check(over <= 0, f"{width}px {theme}: no sideways scroll ({over}px)")
        check(not page.problems, f"{width}px {theme}: no console errors")
        if width == 390:
            xs = page.evaluate("[...document.querySelectorAll('[data-panel]')].map((n) => Math.round(n.getBoundingClientRect().width))")
            check(max(xs) <= 390, f"390px: panels fit the screen ({max(xs)}px)")
        if KEEP:
            page.screenshot(path=str(SHOTS / f"renderer-{theme}-{width}.png"), full_page=True)
        ctx.close()
    browser.close()

if failures:
    print(f"\n{len(failures)} problem(s)")
    sys.exit(1)
print("\nrenderer checks passed")
