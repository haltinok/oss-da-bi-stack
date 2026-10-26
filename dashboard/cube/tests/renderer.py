"""The dashboard renderer (/d/) in a real Chrome against the mock stack: no services needed.

  uv run --with playwright python -I dashboard/cube/tests/renderer.py [--shots]

Checks the list page, every panel type of dashboards/sales-overview.yml drawn from generated data, the filters (cascading options, the
queries they send, cancelling what is still running), one failing panel not blanking the rest, the Excel export, the dataset switch, a role
the dashboard is not for, and that the KPI tiles show the same figures as the sales dashboard does for the same data.
"""
import pathlib
import sys

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
    page.wait_for_function("document.querySelector('#live-text')?.textContent.match(/Updated|Stale/)", timeout=timeout)
    page.wait_for_function("!document.querySelector('.card.pending, .kpi.pending')", timeout=timeout)


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
    check(page.locator(".dlist a").count() == 1 and "Sales overview" in page.inner_text(".dlist"), "/d/ lists the dashboards the role may open")
    check(page.get_attribute(".dlist a", "href") == "/d/sales-overview", "the list links to /d/<id>")
    check(not page.problems, f"the list loads without console errors {page.problems[:2]}")
    ctx.close()

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
    check(page.locator('[data-panel="trend"] svg rect, [data-panel="trend"] svg path').count() > 12, "the monthly chart draws bars")
    check(page.locator('[data-panel="trend"] .legend span').count() == 2, "the chart has a legend for its two series")
    check("Jul '20" in page.inner_text('[data-panel="trend"]'), "the time axis has month labels")
    check(page.locator('[data-panel="top"] .rrow').count() == 5, "the bar panel has one row per product")
    check(page.locator('[data-panel="lines"] tbody tr').count() > 3, "the table panel has rows")
    check("Order" in page.inner_text('[data-panel="lines"] thead') and "Revenue" in page.inner_text('[data-panel="lines"] thead'), "table columns use the spec's labels")
    check("not drawn by this renderer yet" in page.inner_text('[data-panel="mix"]'), "a panel type for a later phase says so instead of failing")
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
