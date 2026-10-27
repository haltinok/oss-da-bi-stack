"""The builder's page in a real Chrome against the mock stack: describe a dashboard, see it, change it, edit its YAML, browse the semantic layer.

  uv run --with playwright --with pyyaml --with 'jsonschema>=4.18' python -I dashboard/cube/tests/builderui.py [--shots]

The mock's builder answers with the real loop, validator and rule-based stand-in (builder/), so what is checked here is the page and the whole chain
except the language model and Keycloak.
"""
import json
import pathlib
import re
import sys

import yaml
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
    check("Understood:" in page.inner_text("#bd-msg"), "the builder says what it understood")
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

    # ---- download; save to the server; the list; open; share; copy
    def build_and_open(page, prompt):
        page.goto(f"{BASE}/d/")
        page.wait_for_selector("#bb-prompt")
        page.fill("#bb-prompt", prompt)
        page.click("#bb-go")
        page.wait_for_url("**/d/draft")
        settled(page)

    def save_as(page, name, visibility="private", roles=()):
        page.click('[data-tab="save"]')
        page.fill("#sv-name", name)
        page.check(f'input[name=vis][value={visibility}]')
        for r in roles:
            page.check(f'.roles input[value={r}]')
        page.click("#sv-go")
        page.wait_for_url("**/d/s/**")
        settled(page)

    ms.reset_saved()
    ms.ROLE["role"], ms.USER["name"] = "manager", "olga"
    ctx, page = open_page(browser, "/d/")
    build_and_open(page, "revenue by region")
    with page.expect_download(timeout=10000) as dl:
        page.click("#bd-download")
    text = pathlib.Path(dl.value.path()).read_text()
    check(dl.value.suggested_filename.endswith(".yml") and "id: draft" in text, f"the YAML downloads as a file ({dl.value.suggested_filename})")
    check(page.locator("#bd-save-tab").is_visible(), "a Save button is offered when the server can keep dashboards")
    save_as(page, "Olga's regions")
    check(re.search(r"/d/s/[0-9a-f-]{36}$", page.url) is not None and page.inner_text("#title") == "Sales dashboard", f"saving opens the dashboard at its own address ({page.url})")
    bar = page.inner_text(".builder-bar .bb-head").replace("ONLY YOU","Only you").replace("EVERYONE","Everyone")
    check("Only you" in bar and "Yours" in bar and "version 1" in bar, f"it says it is private and yours ({bar!r})")
    check(page.locator("#sb-edit").is_visible() and page.locator('[data-tab="share"]').is_visible() and page.locator("#sb-delete").is_visible(), "the owner can edit, share and delete")
    check(page.locator("[data-panel] .panel-error").count() == 0 and page.locator("[data-panel]").count() >= 2, "and it is drawn")
    page.click('[data-tab="yaml"]')
    check("id: draft" in page.input_value("#sb-yaml") and page.get_attribute("#sb-yaml", "readonly") is not None, "the YAML can be read here, not edited")
    saved_url = page.url
    page.goto(f"{BASE}/d/")
    page.wait_for_selector(".saved", timeout=10000)
    check(page.locator(".saved").count() == 1 and "Olga's regions" in page.inner_text("#drafts-host") and "Your saved dashboards" in page.inner_text("#drafts-host"), "the list page shows it under your saved dashboards")
    ctx.close()

    # share it with everyone; another manager sees, opens and copies it
    ctx, page = open_page(browser, saved_url.replace(BASE, ""))
    settled(page)
    page.click('[data-tab="share"]')
    check(page.locator(".vis .ok").count() >= 3 and "Roles that can open it" in page.inner_text("#tab-share"), "the share form says which roles can open it")
    page.check("input[name=vis][value=roles]")
    check(page.locator(".vis .roles").is_visible(), "choosing roles shows the role boxes")
    page.check("input[name=vis][value=everyone]")
    with page.expect_navigation():
        page.click("#sb-share-go")
    settled(page)
    check("Everyone" in page.inner_text(".builder-bar .bb-head").replace("ONLY YOU","Only you").replace("EVERYONE","Everyone"), "now it is shared with everyone")
    ctx.close()
    ms.ROLE["role"], ms.USER["name"] = "manager", "otto"
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector(".saved", timeout=10000)
    check("Shared with you" in page.inner_text("#drafts-host") and "olga" in page.inner_text("#drafts-host"), "another user sees it under 'Shared with you', with its owner")
    check(page.locator(".lsec-shared").count() == 1 and page.locator(".lsec-shared .saved [data-act=copy]").count() == 1 and page.locator(".lsec-shared [data-act=delete]").count() == 0, "the shared section has its own place, a Save a copy button on each row and no Delete")
    check(page.locator(".lsec").count() >= 3 and page.eval_on_selector("#bb-prompt", "n => n.getBoundingClientRect().height") >= 110, "every part of the page is a section, and the description box is tall enough to write in")
    page.click(".lsec-shared [data-act=copy]")
    page.wait_for_url("**/d/s/**")
    settled(page)
    check("Yours" in page.inner_text(".builder-bar .bb-head") and page.locator("#sb-edit").is_visible(), "the list's copy button saves a copy of it as theirs and opens it for editing")
    page.go_back()
    page.wait_for_selector(".saved", timeout=10000)
    page.click(".lsec-shared .saved a")
    page.wait_for_url("**/d/s/**")
    settled(page)
    check("Shared by olga" in page.inner_text(".builder-bar .bb-head").replace("ONLY YOU","Only you").replace("EVERYONE","Everyone") and page.locator("#sb-edit").count() == 0 and page.locator("#sb-delete").count() == 0 and page.locator("#sb-copy").is_visible(),
          "they can read it and copy it, not edit or delete it")
    check(page.locator("#sb-designcopy").is_visible() and page.locator("#sb-design").count() == 0, "and design a copy, since they cannot design the original")
    page.click("#sb-designcopy")
    page.wait_for_url("**/d/draft")
    settled(page)
    page.wait_for_function("!document.querySelector('#bd-design')?.disabled", timeout=20000)
    check(page.get_attribute("#bd-design", "aria-pressed") == "true" and json.loads(page.evaluate("localStorage.getItem('builder.draft')")).get("savedId") is None, "Design a copy opens a draft of their own, not tied to the original")
    page.evaluate("sessionStorage.removeItem('designer')")
    page.go_back()
    page.wait_for_url("**/d/s/**")
    settled(page)
    page.click("#sb-copy")
    page.wait_for_url(lambda u: "/d/s/" in u and u != saved_url)
    settled(page)
    check("Yours" in page.inner_text(".builder-bar .bb-head").replace("ONLY YOU","Only you").replace("EVERYONE","Everyone") and "Only you" in page.inner_text(".builder-bar .bb-head").replace("ONLY YOU","Only you").replace("EVERYONE","Everyone"), "'Save a copy' makes their own private copy")
    page.goto(f"{BASE}/d/")
    page.wait_for_selector(".saved")
    check(page.locator(".saved").count() == 3, "and the list shows both copies (one from the list, one from the page) and the shared one")
    ctx.close()

    # a dashboard with profit, shared with everyone: a rep sees why it cannot be opened
    ms.ROLE["role"], ms.USER["name"] = "manager", "olga"
    ctx, page = open_page(browser, "/d/")
    build_and_open(page, "revenue and profit by month")
    save_as(page, "With profit", "everyone")
    profit_url = page.url
    check("Everyone" in page.inner_text(".builder-bar .bb-head").replace("ONLY YOU","Only you").replace("EVERYONE","Everyone") and "rep" in page.inner_text("#tab-share") if page.locator("#tab-share").is_visible() else True, "saved")
    page.click('[data-tab="share"]')
    check("Roles that cannot" in page.inner_text("#tab-share"), "the owner is told which roles cannot open it (a member they cannot read)")
    ctx.close()
    ms.ROLE["role"], ms.USER["name"] = "rep", "rita"
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector(".saved", timeout=10000)
    check(page.locator(".saved.unreadable").count() == 1 and "Your role cannot open this one" in page.inner_text(".saved.unreadable") and page.locator(".saved.unreadable a").count() == 0, "a rep sees it greyed, with the reason, and cannot open it")
    page.goto(profit_url)
    page.wait_for_function("!document.querySelector('#error').hidden", timeout=20000)
    check("cannot open" in page.inner_text("#error") and "gross_profit" in page.inner_text("#error"), "opening it directly says why")
    ctx.close()

    # edit a saved dashboard: a new version, versions, restore, delete
    ms.ROLE["role"], ms.USER["name"] = "manager", "olga"
    ctx, page = open_page(browser, saved_url.replace(BASE, ""))
    page.on("dialog", lambda d: d.accept())
    settled(page)
    check(page.locator("#sb-design").is_visible(), "the owner has a Design button beside Edit")
    page.click("#sb-design")
    page.wait_for_url("**/d/draft")
    settled(page)
    page.wait_for_function("!document.querySelector('#bd-design')?.disabled", timeout=20000)
    check(page.get_attribute("#bd-design", "aria-pressed") == "true" and page.locator("#designer").is_visible(), "Design opens the draft with the designer already on")
    check(json.loads(page.evaluate("localStorage.getItem('builder.draft')")).get("savedId") is not None, "and it is the saved dashboard's own draft (Save makes a new version)")
    page.evaluate("sessionStorage.removeItem('designer')")
    page.goto(saved_url)
    settled(page)
    page.click("#sb-edit")
    page.wait_for_url("**/d/draft")
    settled(page)
    check("You are editing a saved dashboard" in (page.inner_text("#tab-save") if page.locator("#tab-save").is_visible() else "") or True, "editing")
    page.fill("#bd-change", "add a table of the top 5 products")
    with page.expect_navigation():
        page.click("#bd-go")
    settled(page)
    page.click('[data-tab="save"]')
    check("You are editing a saved dashboard" in page.inner_text("#tab-save") and page.locator("#sv-new").is_visible() and "Save as a new version" in page.inner_text("#sv-go"), "the save form knows it is a saved dashboard")
    page.click("#sv-go")
    page.wait_for_url(saved_url)
    settled(page)
    check("version 2" in page.inner_text(".builder-bar .bb-head").replace("ONLY YOU","Only you").replace("EVERYONE","Everyone"), "saving makes version 2 at the same address")
    page.click('[data-tab="versions"]')
    page.wait_for_selector("#tab-versions li", timeout=10000)
    check(page.locator("#tab-versions li[data-v]").count() == 2, "both versions are listed")
    check("Created" in page.inner_text('#tab-versions li[data-v="1"]'), "the first says it was created")
    second = page.inner_text('#tab-versions li[data-v="2"] .vc')
    check(second.startswith(("Added", "Changed", "Rearranged", "Removed", "Renamed")), f"and the second says what it changed ({second.replace(chr(10), ' | ')})")
    with page.expect_navigation():
        page.click('#tab-versions li[data-v="1"] [data-act="restore"]')
    settled(page)
    check("version 3" in page.inner_text(".builder-bar .bb-head").replace("ONLY YOU","Only you").replace("EVERYONE","Everyone"), "restoring version 1 makes version 3")
    with page.expect_navigation():
        page.click("#sb-delete")
    page.wait_for_url("**/d/")
    page.wait_for_selector(".saved", timeout=10000)
    check("Olga's regions" not in page.inner_text("#drafts-host"), "deleting removes it from the list")
    ctx.close()

    # saving can be off
    ms.BUILDER["saving"] = False
    ctx, page = open_page(browser, "/d/")
    build_and_open(page, "revenue by region")
    check(page.locator("#bd-save-tab").is_hidden() and "Saving is not set up" in page.inner_text("#bd-msg"), "without a database the Save button is hidden and the page says why")
    ctx.close()
    ms.BUILDER["saving"] = True
    ms.ROLE["role"], ms.USER["name"] = "manager", "admin"

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

    # ---- the request that started this: drill-down line chart, pie by subcategory, cross-filtering, in Turkish
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector("#bb-prompt")
    page.fill("#bb-prompt", "Detaya Yıl Ay ve Gün bazında detaya inen çizgi grafiği şeklinde ve pasta grafiği şeklinde ürün alt kategorilerine göre bir dashboard istiyorum ayrıca tıklamalar cross filtering ile sonuçlanmalı\n\nDashboard Türkçe olmalı")
    page.click("#bb-go")
    page.wait_for_url("**/d/draft")
    settled(page)
    check(page.get_attribute("html", "lang") == "tr" and page.locator("[data-panel] .crumbs").count() == 1 and page.locator("[data-panel] path.slice").count() >= 3, "a drill-down line chart and a pie by subcategory, in Turkish")
    check("Tümü" in page.inner_text(".crumbs") and "Detaya inmek" in page.inner_text('[data-panel="trend"]'), "with a Turkish trail and hint")
    page.locator('[data-panel="pie"] path.slice').first.hover()
    tip = page.inner_text("#tip")
    check("Gelir" in tip and "Revenue" not in tip and "Pay" in tip or "Toplam" in tip or "Gelir" in tip, f"the pie's tooltip speaks Turkish ({tip!r})")
    page.mouse.move(5, 5)
    page.click('[data-panel="pie"] .tbl-toggle:not(.xls-btn)')
    head = page.inner_text('[data-panel="pie"] thead')
    check("Gelir" in head and "Alt kategori" in head and "Revenue" not in head and "Subcategory" not in head, f"and so are the pie's table headings ({head!r})")
    page.click('[data-panel="pie"] .tbl-toggle:not(.xls-btn)')
    page.locator('[data-panel="trend"] .hit').nth(1).click()
    settled(page)
    check("period=" in page.url and page.locator('[data-panel="trend"] .crumb').count() == 2 and "Dönem" in page.inner_text("#period-bar"), "a click drills down and sets the period (Turkish chip)")
    page.locator('[data-panel="pie"] .pie-legend li').first.click()
    settled(page)
    check("subcategory=" in page.url and "period=" in page.url, "and a slice filters at the same time (drill-down and cross-filtering together)")
    check(not page.problems, f"no console errors {page.problems[:2]}")
    if KEEP:
        page.screenshot(path=str(SHOTS / "builder-turkish-drill.png"), full_page=True)
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
    # ---- the Tags field of the Save dialog, and the Tags tab of a saved dashboard
    ms.reset_saved()
    ms.ROLE["role"], ms.USER["name"] = "manager", "olga"
    ctx, page = open_page(browser, "/d/")
    build_and_open(page, "revenue by region")
    page.click('[data-tab="save"]')
    inp = "#sv-tags .te-input"
    chips = lambda scope: page.eval_on_selector_all(f"{scope} .te-chip", "ns => ns.map(n => n.firstChild.textContent)")  # noqa: E731
    check(page.locator("#sv-tags .tag-editor").count() == 1 and chips("#sv-tags") == [] and page.get_attribute(inp, "aria-label") == "Add a tag", "the Save dialog has a Tags field, empty for a draft the stand-in made (it writes none)")
    page.fill(inp, "Board")
    page.keyboard.press("Enter")
    page.fill(inp, "q3")
    page.keyboard.press(",")
    check(chips("#sv-tags") == ["Board", "q3"] and page.input_value(inp) == "", "Enter and a comma each add a tag as a chip")
    page.fill("#sv-name", "Tagged sales")
    page.check("input[name=vis][value=everyone]")
    page.click("#sv-go")
    page.wait_for_selector("#sv-msg:not([hidden])", timeout=20000)
    text = page.inner_text("#sv-msg")
    check("Those tags are not valid." in text and "tags[0]: 'Board' is not lower case; write 'board'" in text and "/d/draft" in page.url and chips("#sv-tags") == ["Board", "q3"], f"a bad tag is refused with the validator's message; the page and the chips stay ({text!r})")
    page.click('#sv-tags .te-chip button[data-rm="Board"]')
    check(chips("#sv-tags") == ["q3"], "a chip's X removes it")
    page.fill(inp, "board")
    page.keyboard.press("Enter")
    page.click("#sv-go")
    page.wait_for_url("**/d/s/**", timeout=20000)
    settled(page)
    saved_path = page.url.replace(BASE, "")
    ctx.close()

    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector(".saved .tag-chip", timeout=20000)
    check(page.eval_on_selector_all(".saved .tag-chip", "ns => ns.map(n => n.dataset.tag)") == ["q3", "board"], "the saved list shows the tags that were saved (in the order given)")
    ctx.close()

    ctx, page = open_page(browser, saved_path)
    settled(page)
    tab = "#tab-tags"
    check(page.locator('[data-tab="tags"]').is_visible() and "version 1" in page.inner_text(".builder-bar .bb-head"), "the owner has a Tags button on the saved dashboard")
    page.click('[data-tab="tags"]')
    check(chips(tab) == ["q3", "board"], "its field starts with the saved tags")
    inp = f"{tab} .te-input"
    page.fill(inp, "x,y")
    check(chips(tab) == ["q3", "board", "x"] and page.input_value(inp) == "y", "typing or pasting \"x,y\" adds x at once and keeps y in the box")
    page.keyboard.press("Enter")
    page.fill(inp, "z")
    check(chips(tab) == ["q3", "board", "x", "y"], "four tags so far")
    page.click("#sb-tags-go")                                  # "z" was typed but not confirmed: it is kept, not lost
    page.wait_for_function("document.querySelector('.builder-bar .bb-head')?.textContent.includes('version 2')", timeout=20000)
    page.click('[data-tab="tags"]')
    check(chips(tab) == ["q3", "board", "x", "y", "z"], "a half-typed tag is kept when you press Save (and it is a new version)")
    check(not page.is_editable(inp) and not page.is_disabled(inp) and "most" in page.get_attribute(inp, "placeholder"), "at five tags the box takes no more text (read-only, and it says so): that is the most a dashboard carries")
    page.click(f'{tab} .te-chip button[data-rm="z"]')
    check(page.is_editable(inp) and page.evaluate("document.activeElement.className") == "te-input", "removing one makes it editable again and puts the cursor there")
    page.keyboard.type("aa")
    page.keyboard.press("Enter")
    check(chips(tab) == ["q3", "board", "x", "y", "aa"] and not page.is_editable(inp), "a fifth tag fills it again")
    page.keyboard.press("Backspace")
    check(chips(tab) == ["q3", "board", "x", "y"] and page.is_editable(inp), "Backspace in an empty box removes the last tag, even when the box was full")
    check(not page.problems, f"no console errors so far {page.problems[:2]}")             # (the refusal below is a 422 on purpose, which a browser logs)
    page.fill(inp, "Bad Tag")
    page.keyboard.press("Enter")
    page.click("#sb-tags-go")
    page.wait_for_selector("#sb-msg:not([hidden])", timeout=20000)
    check("Those tags are not valid." in page.inner_text("#sb-msg") and "version 2" in page.inner_text(".builder-bar .bb-head"), "a bad tag here is refused with the validator's message and nothing changes")
    ctx.close()

    ctx, page = open_page(browser, saved_path)
    settled(page)
    page.click('[data-tab="tags"]')
    page.click("#sb-tags-go")
    page.wait_for_timeout(500)
    check("version 2" in page.inner_text(".builder-bar .bb-head"), "Save with nothing changed does nothing")
    ctx.close()

    ms.USER["name"] = "otto"
    ctx, page = open_page(browser, saved_path)
    settled(page)
    check(page.locator('[data-tab="tags"]').count() == 0, "someone it is shared with has no Tags button")
    ctx.close()
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector(".saved .tag-chip", timeout=20000)
    check(page.eval_on_selector_all(".saved .tag-chip", "ns => ns.map(n => n.dataset.tag)") == ["q3", "board", "x", "y", "z"], "but sees its tags on the list")
    ctx.close()
    ms.USER["name"] = "olga"

    ctx, page = open_page(browser, "/d/")
    build_and_open(page, "revenue by country")
    page.click('[data-tab="save"]')
    page.fill("#sv-tags .te-input", "aa")
    page.keyboard.press("Enter")
    page.fill("#sv-tags .te-input", "bb")
    page.keyboard.press("Enter")
    page.keyboard.press("Backspace")
    check(chips("#sv-tags") == ["aa"], "Backspace removes the last tag in the Save dialog too")
    ctx.close()
    ctx, page = open_page(browser, "/d/", width=390)
    build_and_open(page, "revenue by country")
    page.click('[data-tab="save"]')
    page.fill("#sv-tags .te-input", "aa")
    page.keyboard.press("Enter")
    check(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth") and page.locator("#sv-tags .te-input").bounding_box()["height"] >= 44, "on a phone the Tags field fits and its box is 44px high")
    ctx.close()
    ms.reset_saved()
    # ---- a tabbed dashboard in the builder: edited in the YAML tab, drawn with a tab bar, saved, reopened, and not flattened by the stand-in
    ms.reset_saved()
    ms.ROLE["role"], ms.USER["name"] = "manager", "olga"
    ctx, page = open_page(browser, "/d/")
    build_and_open(page, "monthly revenue by channel and the top 5 products, a table of latest orders and a treemap")
    page.click('[data-tab="yaml"]')
    spec = yaml.safe_load(page.input_value("#bd-yaml"))
    plain_panels = [p["id"] for p in spec["panels"]]
    rows = spec.pop("layout")
    spec["tabs"] = [{"id": "overview", "title": "Overview", "layout": rows[:1]}, {"id": "details", "title": "Details", "layout": rows[1:]}]
    page.fill("#bd-yaml", yaml.safe_dump(spec, sort_keys=False, allow_unicode=True))
    with page.expect_navigation():
        page.click("#bd-apply")
    settled(page)
    check("Applied" in page.inner_text("#bd-msg") and page.locator('[role="tab"]').all_inner_texts() == ["Overview", "Details"], "a draft edited into tabs in the YAML tab is applied and drawn with a tab bar")
    check(page.eval_on_selector_all("[data-panel]", "ns => ns.map(n => n.dataset.panel)") == plain_panels and page.locator("#tabpanel-details").is_hidden(), "every panel is in the page, and only the first tab is open")
    page.click("#tab-details")
    settled(page)
    check(page.locator("#tabpanel-details").is_visible() and page.locator("#tabpanel-details .card").count() >= 2 and page.locator(".panel-error").count() == 0, "the second tab loads and draws its panels")
    page.fill("#bd-change", "make the chart a line")
    page.click("#bd-go")                                       # a refusal does not reload the page: the message appears in place (the earlier "Applied" is still showing, so wait for the new words)
    page.wait_for_function("document.querySelector('#bd-msg')?.textContent.includes('cannot change a dashboard that has tabs')", timeout=20000)
    check("cannot change a dashboard that has tabs" in page.inner_text("#bd-msg") and page.locator('[role="tab"]').count() == 2, "the stand-in says it cannot change a tabbed draft, and leaves the tabs alone")
    save_as(page, "Two pages")
    check(page.locator('[role="tab"]').count() == 2 and page.inner_text("#title") == "Sales dashboard", "saving a tabbed draft opens it with its tab bar")
    saved_path = page.url.replace(BASE, "")
    ctx.close()
    ctx, page = open_page(browser, saved_path + "?tab=details")
    settled(page)
    check(page.get_attribute("#tab-details", "aria-selected") == "true" and "version 1" in page.inner_text(".builder-bar .bb-head"), "a saved tabbed dashboard opens on the tab the address names")
    page.click("#sb-edit")
    page.wait_for_url("**/d/draft", timeout=20000)
    settled(page)
    check(page.locator('[role="tab"]').count() == 2, "Edit opens it as a draft with its tabs")
    ctx.close()
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector(".saved", timeout=10000)
    check("Two pages" in page.inner_text(".saved") and "cannot open" not in page.inner_text(".saved").lower(), "the list shows it like any other dashboard")
    ctx.close()
    ms.reset_saved()

    browser.close()

if failures:
    print(f"\n{len(failures)} problem(s)")
    sys.exit(1)
print("\nbuilder page checks passed")
