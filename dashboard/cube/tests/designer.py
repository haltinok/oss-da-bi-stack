"""The designer (design mode on /d/draft) in a real Chrome against the mock stack: pick a panel, change its fields, see the page drawn again, see a refusal.

  uv run --with playwright --with pyyaml --with 'jsonschema>=4.18' python -I dashboard/cube/tests/designer.py [--shots]

The mock's builder answers with the real validator (builder/), so a change is accepted or refused exactly as it would be for a hand-edited file.
"""
import json
import pathlib
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


def open_page(browser, path, width=1440, draft=None):
    ctx = browser.new_context(viewport={"width": width, "height": 1500})
    ctx.add_init_script(ms.SEED + (f"localStorage.setItem('builder.draft', {json.dumps(draft)});" if draft else "") + 'try { if (localStorage.getItem("theme") === null) localStorage.setItem("theme", "light"); localStorage.setItem("dataset", "live"); } catch (e) {}')
    page = ctx.new_page()
    page.problems = []
    page.on("pageerror", lambda e: page.problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: page.problems.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.goto(f"{BASE}{path}")
    return ctx, page


def settled(page, timeout=20000):
    page.wait_for_function("document.querySelector('#live-text')?.textContent.match(/Updated|Stale|Güncellendi|Eski/)", timeout=timeout)
    page.wait_for_function("!document.querySelector('.card.pending, .kpi.pending')", timeout=timeout)


def draft_yaml(page):
    return yaml.safe_load(json.loads(page.evaluate("localStorage.getItem('builder.draft')"))["yaml"])


def panel_of(page, type_):
    return page.evaluate("(t) => window.__render.spec.panels.find((p) => p.type === t)?.id", type_)


ms.start()
ms.FAKE["on"] = True
ms.BENCH["on"] = False
ms.ROLE["role"] = "manager"
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector("#bb-prompt", timeout=20000)
    page.fill("#bb-prompt", "monthly revenue by channel, top 5 products, a table of the latest orders")
    page.click("#bb-go")
    page.wait_for_url("**/d/draft", timeout=20000)
    settled(page)
    page.wait_for_function("!document.querySelector('#bd-design').disabled", timeout=20000)

    # ---- turning it on
    check(page.get_attribute("#bd-design", "aria-pressed") == "false" and page.locator("#designer").is_hidden(), "design mode starts off, with the drawer closed")
    page.click("#bd-design")
    check(page.get_attribute("#bd-design", "aria-pressed") == "true" and page.locator("#designer").is_visible() and "Click a panel" in page.inner_text("#designer"), "the Design button opens a drawer that says what to do")
    bar = panel_of(page, "bar")
    check(bool(bar), f"the draft has a bar panel ({bar})")
    check(page.get_attribute(f'[data-panel="{bar}"]', "tabindex") == "0", "panels can be reached with the keyboard in design mode")

    # ---- picking a panel does not also filter the page
    trend = panel_of(page, "timeseries")
    before = page.url
    page.locator(f'[data-panel="{trend}"] .hit').first.click()
    check(page.url == before and "fy" not in page.url, "a click on a chart in design mode selects the panel and does not filter the page")
    check(page.locator(f'[data-panel="{trend}"]').evaluate("n => n.classList.contains('dz-selected')") and "time chart" in page.inner_text("#designer").lower(), "the panel is outlined and the drawer shows its type")
    check(page.locator('#designer [data-path="style"]').count() == 1 and page.locator('#designer [data-path^="series."]').count() >= 3, "a time chart offers its style and each series")

    # ---- changing a field: the page is drawn again with the change, design mode and the selection are still there
    page.click(f'[data-panel="{bar}"] h2')
    check(page.locator("#designer .dz-head h2").inner_text() == draft_yaml(page)["panels"][[x["id"] for x in draft_yaml(page)["panels"]].index(bar)]["title"], "picking the bar chart shows its own title in the drawer")
    with page.expect_navigation():
        page.fill('#designer [data-path="title"]', "Best sellers")
        page.press('#designer [data-path="title"]', "Tab")
    settled(page)
    check(page.inner_text(f'[data-panel="{bar}"] h2') == "Best sellers", "the new title is drawn")
    check(next(x for x in draft_yaml(page)["panels"] if x["id"] == bar)["title"] == "Best sellers", "and stored in the draft's YAML")
    check(page.get_attribute("#bd-design", "aria-pressed") == "true" and page.locator(f'[data-panel="{bar}"]').evaluate("n => n.classList.contains('dz-selected')"), "design mode and the selected panel survive the redraw")
    check("Best sellers" in page.inner_text("#bd-msg"), "the draft bar says what changed")

    # ---- a dimension: only groupings the measure can reach are offered; changing it keeps the page valid
    opts = page.locator('#designer [data-path="by"] option').evaluate_all("os => os.map((o) => o.value)")
    check("products.category" in opts and "territories.region" in opts and not any(o.startswith("inventory") for o in opts), f"the grouping list holds what the bar's measures can join to ({len(opts)} options)")
    with page.expect_navigation():
        page.select_option('#designer [data-path="by"]', "territories.region")
    settled(page)
    check(next(x for x in draft_yaml(page)["panels"] if x["id"] == bar)["by"] == "territories.region", "choosing another grouping changes the bar's `by`")
    check("on_click" not in next(x for x in draft_yaml(page)["panels"] if x["id"] == bar), "its click rule, which pointed at the old grouping, is gone")

    # ---- a number, and a refusal
    with page.expect_navigation():
        page.fill('#designer [data-path="limit"]', "3")
        page.press('#designer [data-path="limit"]', "Tab")
    settled(page)
    check(next(x for x in draft_yaml(page)["panels"] if x["id"] == bar)["limit"] == 3, "a number field changes the limit")
    yaml_before = page.evaluate("localStorage.getItem('builder.draft')")
    page.fill('#designer [data-path="limit"]', "5000")
    page.press('#designer [data-path="limit"]', "Tab")
    page.wait_for_selector("#designer #dz-msg:not([hidden])", timeout=10000)
    check("not accepted" in page.inner_text("#dz-msg") and page.evaluate("localStorage.getItem('builder.draft')") == yaml_before, "a change the validator refuses shows its message and leaves the draft as it was")
    check(page.input_value('#designer [data-path="limit"]') == "3", "and the field goes back to what the draft holds")

    # ---- the table: columns, and the text of the page does not break
    table = panel_of(page, "table")
    page.click(f'[data-panel="{table}"] h2')
    cols = page.locator('#designer [data-path^="columns."]').count()
    check(cols >= 3, f"a table offers each column ({cols} fields)")

    # ---- leaving
    page.keyboard.press("Escape")
    check("Click a panel" in page.inner_text("#designer"), "Escape lets go of the panel")
    page.click("#bd-design")
    check(page.locator("#designer").is_hidden() and page.evaluate("!document.body.classList.contains('designing')") and page.get_attribute(f'[data-panel="{bar}"]', "tabindex") is None, "turning it off hides the drawer and the outlines")
    page.reload()
    settled(page)
    check(page.get_attribute("#bd-design", "aria-pressed") == "false", "and a reload keeps it off")
    check(not page.problems, f"no console errors ({page.problems[:2]})")
    kept_draft = page.evaluate("localStorage.getItem('builder.draft')")
    if KEEP:
        page.click("#bd-design")
        page.click(f'[data-panel="{bar}"] h2')
        page.screenshot(path=str(SHOTS / "designer.png"))
    ctx.close()

    # ---- on a phone the drawer is a sheet at the bottom
    ctx, page = open_page(browser, "/d/draft", width=390, draft=kept_draft)
    page.wait_for_function("!document.querySelector('#bd-design')?.disabled", timeout=20000)
    page.click("#bd-design")
    box = page.locator("#designer").bounding_box()
    check(box["width"] >= 380 and box["y"] > 300 and page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 0, f"on a phone the drawer is a sheet at the bottom ({box['width']:.0f}px wide, from y={box['y']:.0f}) and the page does not scroll sideways")
    ctx.close()

    # ---- Turkish
    ctx, page = open_page(browser, "/d/draft?lang=tr", draft=kept_draft)
    page.wait_for_function("!document.querySelector('#bd-design')?.disabled", timeout=20000)
    page.click("#bd-design")
    check(page.inner_text("#bd-design") == "Tasarla" and "bir panele tıklayın" in page.inner_text("#designer"), "the button and the drawer speak Turkish on a Turkish page")
    ctx.close()
    browser.close()

if failures:
    print(f"\n{len(failures)} problem(s)")
    sys.exit(1)
print("\ndesigner checks passed")
