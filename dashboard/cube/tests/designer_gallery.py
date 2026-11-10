"""The screenshots of the designer's "Add a tab" walk-through in docs/dashboards.md: docs/images/designer/*.png, from generated data (the numbers mean nothing).

  uv run --with playwright --with pyyaml --with 'jsonschema>=4.18' python -I dashboard/cube/tests/designer_gallery.py

Re-run it when the designer's look changes; the images are committed.
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import mock_stack as ms  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[3] / "docs" / "images" / "designer"
OUT.mkdir(parents=True, exist_ok=True)
BASE = f"http://localhost:{ms.PORT}"


def settled(page):
    page.wait_for_function("document.querySelector('#live-text')?.textContent.match(/Updated|Stale/)", timeout=20000)
    page.wait_for_function("!document.querySelector('.card.pending, .kpi.pending')", timeout=20000)
    page.wait_for_timeout(500)


def changed(page, action):
    before = page.evaluate("localStorage.getItem('builder.draft')")
    action()
    page.wait_for_function("(b) => localStorage.getItem('builder.draft') !== b", arg=before, timeout=20000)
    settled(page)


ms.start()
ms.FAKE["on"] = True
ms.BENCH["on"] = False
ms.ROLE["role"] = "editor"
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(ms.SEED + 'try { localStorage.setItem("theme", "light"); localStorage.setItem("dataset", "live"); } catch (e) {}')
    page = ctx.new_page()
    page.goto(f"{BASE}/d/")
    page.wait_for_selector("#bb-prompt", timeout=20000)
    page.fill("#bb-prompt", "monthly revenue by channel, top 5 products, a table of the latest orders")
    page.click("#bb-go")
    page.wait_for_url("**/d/draft*", timeout=20000)
    settled(page)
    page.wait_for_function("!document.querySelector('#bd-design').disabled", timeout=20000)

    page.click("#bd-design")                                                                    # 1. design mode adds + Tab to the header
    page.wait_for_selector("#bd-addtab", state="visible")
    page.screenshot(path=str(OUT / "tab-1-plus-tab.png"))

    changed(page, lambda: page.click("#bd-addtab"))                                             # 2. the page is now "Page 1" and a new tab
    page.wait_for_selector("[role=tab]")
    page.screenshot(path=str(OUT / "tab-2-two-tabs.png"))

    page.fill('#designer [data-tab-title="tab_2"]', "Products")                                 # 3. rename it, give it a filter of its own
    page.press('#designer [data-tab-title="tab_2"]', "Tab")
    page.wait_for_timeout(1500)
    settled(page)
    changed(page, lambda: (page.select_option('#designer [data-scoped-field="page:tab_2"]', "products.category"), page.click('#designer [data-scoped-add="page:tab_2"]')))
    page.locator("#designer .dz-tabfilters").nth(1).scroll_into_view_if_needed()
    page.screenshot(path=str(OUT / "tab-3-tab-filter.png"))
    browser.close()
print(f"wrote {OUT}")
