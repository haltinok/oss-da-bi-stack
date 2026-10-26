"""The builder's page in a real Chrome against the mock stack: describe a dashboard, see it, change it, edit its YAML, browse the semantic layer.

  uv run --with playwright --with pyyaml --with 'jsonschema>=4.18' python -I dashboard/cube/tests/builderui.py [--shots]

The mock's builder answers with the real loop, validator and rule-based stand-in (builder/), so what is checked here is the page and the whole chain
except the language model and Keycloak.
"""
import json
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


def open_page(browser, path, width=1440, storage=None):
    ctx = browser.new_context(viewport={"width": width, "height": 1500}, accept_downloads=True)
    init = ms.SEED + 'try { localStorage.setItem("theme", "light"); localStorage.setItem("dataset", "live"); } catch (e) {}'
    if storage:
        init += "".join(f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)});" for k, v in storage.items())
    ctx.add_init_script(init)
    page = ctx.new_page()
    page.problems = []
    page.on("pageerror", lambda e: page.problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: page.problems.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.goto(f"{BASE}{path}")
    return ctx, page


def settled(page, timeout=20000):
    page.wait_for_function("document.querySelector('#live-text')?.textContent.match(/Updated|Stale|Güncellendi|Eski/)", timeout=timeout)
    page.wait_for_function("!document.querySelector('.card.pending, .kpi.pending')", timeout=timeout)


ms.start()
ms.FAKE["on"] = True
ms.BENCH["on"] = False
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)

    # ---- the prompt box
    ms.ROLE["role"] = "manager"
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector("#bb-prompt", timeout=20000)
    page.wait_for_selector(".bb-examples .chip", timeout=10000)
    check("rule-based stand-in" in page.inner_text("#bb-mode") and "fixed set of phrases" in page.inner_text("#bb-mode"), "the box says a rule-based stand-in answers, not an LLM")
    chips = page.locator(".bb-examples .chip").all_inner_texts()
    check(len(chips) == 4 and any("revenue" in c.lower() for c in chips), f"examples that fit the role are offered ({len(chips)})")
    page.click(".bb-examples .chip >> nth=0")
    check(page.input_value("#bb-prompt") == chips[0], "clicking an example fills the box")
    page.fill("#bb-prompt", "monthly revenue by channel, top 5 products, a table of the latest orders")
    page.click("#bb-go")
    page.wait_for_url("**/d/draft", timeout=20000)
    settled(page)
    check(not page.problems, f"the draft page loads without console errors {page.problems[:2]}")
    titles = page.locator("[data-panel] h2").all_inner_texts()
    check(page.locator(".kpi").count() >= 1 and any("Top" in t or "product" in t.lower() for t in titles) and page.locator('[data-panel] table').count() >= 1,
          f"the dashboard is drawn: kpis, a product bar and a table ({titles})")
    check(page.locator('[data-panel="trend"] .hit').count() > 5, "with the real renderer (hover bars, clicks)")
    check(page.locator(".builder-bar .badge").inner_text().lower() == "draft" and "title" and page.title().startswith("Draft:"), "the page says it is a draft")
    check("stand-in" in page.inner_text("#bd-mode"), "and who built it")
    check("Composed from your request" in page.inner_text("#bd-msg"), "the builder's message is shown")
    check(page.locator("[data-panel] .panel-error").count() == 0, "no panel errors for the manager")
    if KEEP:
        SHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SHOTS / "builder-draft.png"), full_page=True)

    # ---- change it by asking
    page.fill("#bd-change", "make the chart a line")
    with page.expect_navigation():
        page.click("#bd-go")
    settled(page)
    check(page.locator('[data-panel="trend"] svg path[stroke]').count() >= 2 and page.locator('[data-panel="trend"] svg rect[fill]').count() == 0, "'make the chart a line' redraws the trend as a line")
    page.fill("#bd-change", "show the top 3")
    with page.expect_navigation():
        page.press("#bd-change", "Enter")
    settled(page)
    check(page.locator('[data-panel^="by_product"] .rrow').count() == 3, "'show the top 3' limits the product bars to three (Enter submits)")
    page.fill("#bd-change", "make it prettier")
    with page.expect_navigation():
        page.click("#bd-go")
    settled(page)
    check("understood nothing to change" in page.inner_text("#bd-msg"), "a change the stand-in does not understand says so")

    # ---- the YAML tab
    page.click('[data-tab="yaml"]')
    yaml_text = page.input_value("#bd-yaml")
    check("id: draft" in yaml_text and "regional" not in yaml_text.lower() and "title:" in yaml_text, "the YAML tab shows the whole file")
    page.fill("#bd-yaml", yaml_text.replace("title: Sales dashboard", "title: My own title", 1))
    with page.expect_navigation():
        page.click("#bd-apply")
    settled(page)
    check(page.inner_text("#title") == "My own title" and "Applied" in page.inner_text("#bd-msg"), "an edited YAML is applied and drawn")
    page.click('[data-tab="yaml"]')
    page.fill("#bd-yaml", page.input_value("#bd-yaml").replace("internet_sales.orders", "internet_sales.ordrs", 1).replace("internet_sales.revenue", "internet_sales.revnue", 1))
    page.click("#bd-apply")
    page.wait_for_selector("#bd-problems:not([hidden])", timeout=10000)
    probs = page.inner_text("#bd-problems")
    check("is not in the Cube model" in probs and "Problems found" in probs, "a broken edit lists the validator's problems and changes nothing")
    check(page.inner_text("#title") == "My own title", "the dashboard stays as it was")

    # ---- the semantic layer
    page.click('[data-tab="semantic"]')
    page.wait_for_selector(".sem-cube", timeout=10000)
    cubes = page.locator(".sem-cube").evaluate_all("n => n.map((x) => x.dataset.cube)")
    check(set(cubes) == {"dates", "internet_sales", "products", "reseller_sales", "territories"}, f"the manager's semantic layer ({cubes})")
    check("customers" not in cubes and "inventory_health" not in cubes, "no customers, no inventory for a manager")
    page.locator('.sem-cube[data-cube="internet_sales"] summary').click()
    check("Sales amount of the order lines" in page.inner_text('.sem-cube[data-cube="internet_sales"]'), "members come with their descriptions")
    check(page.locator('.sem-cube[data-cube="internet_sales"] .badge').inner_text().lower() == "fact", "a fact cube is marked")
    page.fill(".sem-search", "fiscal")
    check(page.locator(".sem-cube:not([hidden])").count() == 1 and page.locator('.sem-cube[data-cube="dates"]').is_visible(), "search narrows to the cubes that match")
    page.fill(".sem-search", "zzzz")
    check("Nothing matches" in page.inner_text(".sem"), "and says when nothing does")
    page.fill(".sem-search", "")
    # clicking a member while the YAML tab is open inserts its name at the cursor
    if page.locator("#tab-yaml").is_hidden():
        page.click('[data-tab="yaml"]')
    page.locator("#bd-yaml").evaluate("n => { n.focus(); n.setSelectionRange(0, 0); }")
    page.locator('.sem-cube[data-cube="internet_sales"] summary').click()
    page.locator('.sem-cube[data-cube="internet_sales"] .member', has_text="revenue").first.click()
    check(page.input_value("#bd-yaml").startswith("internet_sales.revenue"), "a member clicked in the semantic layer is inserted into the open YAML at the cursor")
    page.wait_for_selector('.sem-cube[data-cube="internet_sales"] .member.copied', timeout=3000)
    check(True, "and marked as copied")
    ctx.close()

    # ---- download, save, saved list
    ctx, page = open_page(browser, "/d/")
    page.fill("#bb-prompt", "revenue by region")
    page.click("#bb-go")
    page.wait_for_url("**/d/draft")
    settled(page)
    with page.expect_download(timeout=10000) as dl:
        page.click("#bd-download")
    text = pathlib.Path(dl.value.path()).read_text()
    check(dl.value.suggested_filename.endswith(".yml") and "id: draft" in text, f"the YAML downloads as a file ({dl.value.suggested_filename})")
    page.click("#bd-save")
    check("Saved in this browser" in page.inner_text("#bd-msg"), "a draft can be saved in the browser")
    page.goto(f"{BASE}/d/")
    page.wait_for_selector(".drafts li", timeout=10000)
    check(page.locator(".drafts li").count() == 1 and "Your drafts" in page.inner_text("#drafts-host"), "the list page shows the saved drafts")
    page.click('.drafts [data-act="open"]')
    page.wait_for_url("**/d/draft")
    settled(page)
    check(page.locator(".kpi").count() >= 1, "opening a saved draft draws it")
    page.goto(f"{BASE}/d/")
    page.click('.drafts [data-act="remove"]')
    check(page.locator(".drafts li").count() == 0 or not page.is_visible("#drafts-host"), "a saved draft can be deleted")
    ctx.close()

    # ---- the semantic layer before building anything
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector("#sem-wrap", timeout=20000)
    page.click("#sem-wrap summary")
    page.wait_for_selector(".sem-cube", timeout=10000)
    check(page.locator(".sem-cube").count() == 5, "the semantic layer can be read on the list page, before building")
    ctx.close()

    # ---- no draft yet
    ctx, page = open_page(browser, "/d/draft")
    page.wait_for_function("!document.querySelector('#error').hidden", timeout=20000)
    check("no draft yet" in page.inner_text("#error").lower(), "/d/draft without a draft says to describe one")
    ctx.close()

    # ---- roles: what is refused, what each sees
    ms.ROLE["role"] = "rep"
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector("#bb-prompt")
    page.fill("#bb-prompt", "profit by region")
    page.click("#bb-go")
    page.wait_for_selector("#bb-out:not([hidden])", timeout=20000)
    out = page.inner_text("#bb-out")
    check("Cannot be built" in out and "hidden from reps" in out and page.url.endswith("/d/"), "a request the role cannot have is refused with the reason, and nothing is drawn")
    check(page.is_enabled("#bb-go"), "the button is usable again")
    page.click("#sem-wrap summary")
    page.wait_for_selector(".sem-cube")
    page.locator('.sem-cube[data-cube="internet_sales"] summary').click()
    members = page.locator('.sem-cube[data-cube="internet_sales"] .sem-members .member').all_inner_texts()
    check("gross_profit" not in members and "margin_pct" not in members and "revenue" in members, "a rep's semantic layer has no profit members")
    page.fill("#bb-prompt", "revenue and orders by region and country")
    page.click("#bb-go")
    page.wait_for_url("**/d/draft")
    settled(page)
    check("gross_profit" not in page.evaluate("localStorage.getItem('builder.draft')") and page.locator("[data-panel] .panel-error").count() == 0, "the rep's draft draws with no profit member and no error")
    ctx.close()
    ms.ROLE["role"] = "purchasing"
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector(".bb-examples .chip")
    check(all("stock" in c.lower() or "envanter" in c.lower() for c in page.locator(".bb-examples .chip").all_inner_texts()), "purchasing is offered inventory examples")
    page.click(".bb-examples .chip >> nth=0")
    page.click("#bb-go")
    page.wait_for_url("**/d/draft")
    settled(page)
    check(page.locator("[data-panel] .panel-error").count() == 0 and page.locator("[data-panel]").count() >= 3, "and the inventory draft draws")
    ctx.close()
    ms.ROLE["role"] = "admin"

    # ---- a rate limit, and Turkish
    ms.BUILDER["limit"] = True
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector("#bb-prompt")
    page.fill("#bb-prompt", "revenue by month")
    page.click("#bb-go")
    page.wait_for_selector("#bb-out:not([hidden])", timeout=20000)
    check("20 dashboards an hour" in page.inner_text("#bb-out") and page.is_enabled("#bb-go"), "the rate limit's message is shown")
    ctx.close()
    ms.BUILDER["limit"] = False
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector("#bb-prompt")
    page.fill("#bb-prompt", "Türkçe satış panosu: aylık gelir ve bölgeye göre gelir")
    page.click("#bb-go")
    page.wait_for_url("**/d/draft")
    settled(page)
    check(page.get_attribute("html", "lang") == "tr" and "Taslak" in page.text_content(".builder-bar") and "₺" in page.inner_text('[data-panel="kpis"]'), "a Turkish request gives a Turkish dashboard, bar and lira")
    check(not page.problems, f"no console errors on the Turkish draft {page.problems[:2]}")
    ctx.close()

    # ---- the pages at other widths
    for width in (1024, 390):
        ctx, page = open_page(browser, "/d/", width=width)
        page.wait_for_selector("#bb-prompt")
        over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        check(over <= 0, f"{width}px: the prompt page has no sideways scroll ({over}px)")
        page.fill("#bb-prompt", "revenue by month and region")
        page.click("#bb-go")
        page.wait_for_url("**/d/draft")
        settled(page)
        over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        check(over <= 0, f"{width}px: the draft page has no sideways scroll ({over}px)")
        if KEEP:
            page.screenshot(path=str(SHOTS / f"builder-draft-{width}.png"), full_page=True)
        ctx.close()
    browser.close()

if failures:
    print(f"\n{len(failures)} problem(s)")
    sys.exit(1)
print("\nbuilder page checks passed")
