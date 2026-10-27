"""The designer (design mode on /d/draft) in a real Chrome against the mock stack: pick a panel, change its fields, see the page drawn again, see a refusal.

  uv run --with playwright --with pyyaml --with 'jsonschema>=4.18' python -I dashboard/cube/tests/designer.py [--shots]

The mock's builder answers with the real validator (builder/), so a change is accepted or refused exactly as it would be for a hand-edited file.
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


def open_page(browser, path, width=1440, draft=None):
    ctx = browser.new_context(viewport={"width": width, "height": 1500})
    ctx.add_init_script(ms.SEED + (f"if (localStorage.getItem('builder.draft') === null) localStorage.setItem('builder.draft', {json.dumps(draft)});" if draft else "") + 'try { if (localStorage.getItem("theme") === null) localStorage.setItem("theme", "light"); localStorage.setItem("dataset", "live"); } catch (e) {}')
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


def drag(page, grip, x, y, shot=None):
    """Presses on a panel's grip, moves to (x, y) in steps and lets go (a real pointer drag); `shot` names a screenshot taken while it is held (with --shots)."""
    box = page.locator(grip).bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(x, y, steps=8)
    if KEEP and shot:
        page.wait_for_timeout(150)
        page.screenshot(path=str(SHOTS / shot))
    page.mouse.up()


def rows_of(page, tab=None):
    spec = yaml_of(page)
    layout = next(t["layout"] for t in spec["tabs"] if t["id"] == tab) if tab else spec["layout"]
    return [[(list(c)[0], list(c.values())[0]) for c in row] for row in layout]


def row_with(rows, pid):
    return next(row for row in rows if any(c[0] == pid for c in row))


def yaml_of(page):
    return draft_yaml(page)


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

    # ---- the page view: nothing picked
    page.keyboard.press("Escape")
    check(page.locator("#dz-gallery [data-add]").count() == 8 and page.locator("#dz-newfilter option").count() > 5, "with nothing picked the drawer shows the page: a gallery of eight panel types and a list of fields to filter by")
    check(page.input_value('#designer [data-path="title"]') == page.inner_text("#title"), "and the page's own fields, starting with its title")
    with page.expect_navigation():
        page.fill('#designer [data-path="title"]', "Board pack")
        page.press('#designer [data-path="title"]', "Tab")
    settled(page)
    check(page.inner_text("#title") == "Board pack" and yaml_of(page)["title"] == "Board pack", "changing the page's title redraws the page and the draft")
    check(page.get_attribute("#bd-design", "aria-pressed") == "true", "design mode is still on")
    if KEEP:
        page.screenshot(path=str(SHOTS / "designer-page.png"))

    # ---- adding every type of panel: the validator accepts each one
    page.on("dialog", lambda d: d.accept())
    for ty in ("kpi", "timeseries", "bar", "pie", "treemap", "table", "pivot", "text"):
        before = {x["id"] for x in yaml_of(page)["panels"]}
        try:
            with page.expect_navigation(timeout=15000):
                page.click(f'#dz-gallery [data-add="{ty}"]')
        except Exception:
            pass                                               # a refusal does not reload: the check below says what the drawer showed
        settled(page)
        added = [x for x in yaml_of(page)["panels"] if x["id"] not in before]
        ok = len(added) == 1 and added[0]["type"] == ty
        check(ok, f"adding a {ty} panel: accepted, one new panel of that type" + ("" if ok else f" ({page.inner_text('#dz-msg') if page.locator('#dz-msg').count() else ''})"))
        if ok:
            check(page.locator(f'[data-panel="{added[0]["id"]}"]').count() == 1 and page.locator(f'[data-panel="{added[0]["id"]}"].dz-selected').count() == 1, f"the new {ty} is on the page and picked")
        page.keyboard.press("Escape")
    check(not page.locator(".panel-error").count(), "none of the new panels shows an error")
    last_row = yaml_of(page)["layout"][-1]
    check(len(last_row) == 1 and list(last_row[0].values())[0] == 12, "a new panel is a full-width row at the end")

    # ---- duplicate and delete
    page.click(f'[data-panel="{bar}"] h2')
    n = len(yaml_of(page)["panels"])
    page.click("#dz-dup")
    page.wait_for_function("document.querySelector('#designer .dz-head h2')?.textContent.includes('(copy)')", timeout=20000)
    settled(page)
    panels_now = yaml_of(page)["panels"]
    check(len(panels_now) == n + 1 and any(x.get("title", "").endswith("(copy)") for x in panels_now), "Duplicate adds a copy with its own id and a marked title, and picks it")
    copy_id = next(x["id"] for x in panels_now if x.get("title", "").endswith("(copy)"))
    page.click("#dz-del")
    page.wait_for_function("(id) => !document.querySelector(`[data-panel='${id}']`)", arg=copy_id, timeout=20000)
    settled(page)
    check(len(yaml_of(page)["panels"]) == n and not page.locator(".panel-error").count(), "Delete removes the panel and the layout still adds up")
    rows = yaml_of(page)["layout"]
    check(all(sum(list(c.values())[0] for c in row) == 12 for row in rows), "every row still adds up to 12")

    # ---- filters
    page.keyboard.press("Escape")
    filters_before = len(yaml_of(page).get("filters", []))
    page.select_option("#dz-newfilter", "products.color")
    page.click("#dz-addfilter")
    page.wait_for_function("(n) => document.querySelectorAll('#dz-filters .dz-filter').length > n", arg=filters_before, timeout=20000)
    settled(page)
    added_filter = yaml_of(page)["filters"][-1]
    check(added_filter["dimension"] == "products.color" and page.locator("#filters select").count() == filters_before + 1, "a new filter appears in the page's filter bar")
    page.click(f'[data-rm-filter="{added_filter["id"]}"]')
    page.wait_for_function("(n) => document.querySelectorAll('#dz-filters .dz-filter').length === n", arg=filters_before, timeout=20000)
    settled(page)
    check(len(yaml_of(page).get("filters", [])) == filters_before, "and Remove takes it out again")

    # ---- layout: commands in the drawer, dragging, resizing
    page.keyboard.press("Escape")
    page.click('[data-panel="pie"]', position={"x": 140, "y": 24})
    check(page.locator('#designer [data-cmd]').count() == 9 and page.locator('#designer [data-cmd="narrower"]').is_disabled(), "a picked panel offers nine layout commands; Narrower is off while it is alone in its row")
    before = [i for i, row in enumerate(rows_of(page)) if any(c[0] == "pie" for c in row)][0]
    with page.expect_navigation():
        page.click('#designer [data-cmd="up"]')
    settled(page)
    after = [i for i, row in enumerate(rows_of(page)) if any(c[0] == "pie" for c in row)][0]
    check(after == before - 1 and page.locator('[data-panel="pie"].dz-selected').count() == 1, "Up swaps its row with the one above, and the panel stays picked")
    with page.expect_navigation():
        page.click('#designer [data-cmd="join-up"]')
    settled(page)
    shared = row_with(rows_of(page), "pie")
    check(len(shared) == 2 and sum(w for _, w in shared) == 12, f"Join the row above puts it beside the panel there ({shared})")
    check(page.locator('#designer [data-cmd="narrower"]').is_enabled(), "and now it can be made narrower")
    with page.expect_navigation():
        page.click('#designer [data-cmd="wider"]')
    settled(page)
    widths = [w for _, w in row_with(rows_of(page), "pie")]
    check(widths == [5, 7] or widths == [7, 5] or sum(widths) == 12 and widths != [6, 6], f"Wider moves a column from its neighbour ({widths})")
    with page.expect_navigation():
        page.click('#designer [data-cmd="own-row"]')
    settled(page)
    check(len(row_with(rows_of(page), "pie")) == 1, "Own row takes it out again")

    page.keyboard.press("Escape")
    page.locator('[data-panel="pivot"]').scroll_into_view_if_needed()
    check(page.locator('[data-panel="text"] .dz-grip').count() == 1, "every panel has a grip in design mode")
    pivot = page.locator('[data-panel="pivot"]').bounding_box()
    with page.expect_navigation():
        drag(page, '[data-panel="text"] .dz-grip', pivot["x"] + pivot["width"] * 0.08, pivot["y"] + pivot["height"] / 2, shot="designer-drag.png")
    settled(page)
    shared = row_with(rows_of(page), "pivot")
    check(sorted(c[0] for c in shared) == ["pivot", "text"] and [c[0] for c in shared][0] == "text" and sum(w for _, w in shared) == 12, f"dragging a panel onto another's left edge puts them side by side, dragged first ({shared})")
    check(page.locator('[data-panel="text"].dz-selected').count() == 1, "and the dragged panel is the picked one")

    page.locator('[data-panel="text"]').scroll_into_view_if_needed()
    page.wait_for_timeout(500)                                  # the page puts the scroll position back after a redraw: measure after that
    bars = page.locator(".dz-resize")
    check(bars.count() >= 1, f"a bar between two neighbours in a row can be dragged ({bars.count()})")
    text_box = page.locator('[data-panel="text"]').bounding_box()
    box = next(bb for bb in (bars.nth(i).bounding_box() for i in range(bars.count())) if text_box["y"] <= bb["y"] + 5 <= text_box["y"] + text_box["height"])        # the bar of the text panel's row, not another row's
    grid_w = page.evaluate("document.querySelector('.rgrid').getBoundingClientRect().width")
    step = (grid_w + 16) / 12
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + step * 2, box["y"] + box["height"] / 2, steps=6)
    page.wait_for_timeout(150)
    check(page.locator(".dz-tip").inner_text().replace(" ", "") == "8|4", "while dragging, a tip says the widths (8 | 4) and the panels follow")
    with page.expect_navigation():
        page.mouse.up()
    settled(page)
    check([w for _, w in row_with(rows_of(page), "text")] == [8, 4], "letting go sets the widths: two columns wider on the left")

    page.locator('[data-panel="text"]').scroll_into_view_if_needed()
    page.click('[data-panel="text"]', position={"x": 120, "y": 20})
    start = page.locator('[data-panel="text"] .dz-grip').bounding_box()
    page.mouse.move(start["x"] + 10, start["y"] + 10)
    page.mouse.down()
    page.mouse.move(start["x"] + 60, start["y"] - 80, steps=5)
    page.keyboard.press("Escape")
    page.mouse.up()
    check(page.locator(".dz-ghost").count() == 0 and page.locator(".dz-drop").count() == 0 and [w for _, w in row_with(rows_of(page), "text")] == [8, 4], "Escape in the middle of a drag drops nothing")

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

    # ---- a draft with tabs: a new panel goes to the tab that is open
    spec_yaml = yaml.safe_load(json.loads(kept_draft)["yaml"])
    rows = spec_yaml.pop("layout")
    spec_yaml["tabs"] = [{"id": "overview", "title": "Overview", "layout": rows[:1]}, {"id": "details", "title": "Details", "layout": rows[1:]}]
    status, built = ms.builder_answer("/validate", {"yaml": yaml.safe_dump(spec_yaml, sort_keys=False)})
    tabbed = json.dumps({"yaml": built["yaml"], "spec": built["spec"], "prompt": "", "message": "", "notes": [], "mode": "standin", "model": ""})
    ctx, page = open_page(browser, "/d/draft?tab=details", draft=tabbed)
    page.wait_for_function("!document.querySelector('#bd-design')?.disabled", timeout=20000)
    settled(page)
    page.click("#bd-design")
    page.keyboard.press("Escape")
    with page.expect_navigation():
        page.click('#dz-gallery [data-add="pie"]')
    settled(page)
    tabs = yaml_of(page)["tabs"]
    check(list(tabs[1]["layout"][-1][0]) == ["pie_2"] and not any("pie_2" in c for row in tabs[0]["layout"] for c in row), "with tabs, a new panel goes to the tab that is open (Details), not the first")
    page.keyboard.press("Escape")
    check(page.locator('#dz-tabs .dz-tab').count() == 2, "the page view lists the tabs")
    page.locator('[data-panel="pie_2"]').scroll_into_view_if_needed()
    page.evaluate("window.scrollTo(0, 0)")
    page.click('[data-panel="pie_2"]', position={"x": 140, "y": 24})
    page.locator('[data-panel="pie_2"] .dz-grip').scroll_into_view_if_needed()
    grip = page.locator('[data-panel="pie_2"] .dz-grip').bounding_box()
    with page.expect_navigation():
        page.mouse.move(grip["x"] + 10, grip["y"] + 10)
        page.mouse.down()
        page.mouse.move(grip["x"] + 40, 4, steps=4)                    # to the top edge of the window: the page scrolls by itself
        page.wait_for_function("window.scrollY === 0", timeout=15000)
        tb = page.locator('[role="tab"][data-tab="overview"]').bounding_box()
        page.mouse.move(tb["x"] + tb["width"] / 2, tb["y"] + tb["height"] / 2, steps=6)
        page.wait_for_timeout(100)
        page.mouse.up()
    settled(page)
    tabs = yaml_of(page)["tabs"]
    check(list(tabs[0]["layout"][-1][0]) == ["pie_2"] and not any("pie_2" in c for row in tabs[1]["layout"] for c in row), "a panel dropped on a tab moves to the end of that tab")
    page.keyboard.press("Escape")
    with page.expect_navigation():
        page.fill('#dz-tabs [data-tab-title="details"]', "More")
        page.press('#dz-tabs [data-tab-title="details"]', "Tab")
    settled(page)
    check(page.locator('[role="tab"]').all_inner_texts() == ["Overview", "More"], "renaming a tab changes its title in the tab bar")
    with page.expect_navigation():
        page.click('#dz-tabs [data-tab-move="overview:1"]')
    settled(page)
    check([t["id"] for t in yaml_of(page)["tabs"]] == ["details", "overview"] and page.locator('[role="tab"]').all_inner_texts() == ["More", "Overview"], "the arrow moves a tab one place later")
    ctx.close()

    # ---- a role that may read less: the starting panels use only what it can read
    for role in ("rep", "purchasing"):
        ms.ROLE["role"] = role
        ctx, page = open_page(browser, "/d/")
        page.wait_for_selector(".bb-examples .chip", timeout=20000)
        page.click(".bb-examples .chip >> nth=0")
        page.click("#bb-go")
        page.wait_for_url("**/d/draft", timeout=20000)
        settled(page)
        page.wait_for_function("!document.querySelector('#bd-design')?.disabled", timeout=20000)
        page.click("#bd-design")
        page.keyboard.press("Escape")
        made = []
        for ty in ("kpi", "timeseries", "bar", "pie", "treemap", "table", "pivot"):
            before = len(yaml_of(page)["panels"])
            try:
                with page.expect_navigation(timeout=15000):
                    page.click(f'#dz-gallery [data-add="{ty}"]')
            except Exception:
                pass
            settled(page)
            made.append((ty, len(yaml_of(page)["panels"]) == before + 1))
            page.keyboard.press("Escape")
        check(all(ok for _, ok in made), f"as {role}: every type can be added ({', '.join(t for t, ok in made if not ok) or 'all accepted'})")
        new_panels = json.dumps(yaml_of(page)["panels"][-7:])
        if role == "rep":
            check(not re.search(r"gross_profit|margin_pct|product_cost", new_panels), "as rep: the new panels hold no profit or cost member")
        else:
            check(all(c in ("inventory_health", "products", "offer_performance") for c in re.findall(r"\b([a-z_]+)\.[a-z_]+\b", new_panels)), "as purchasing: the new panels use only inventory and product members")
        ctx.close()
    ms.ROLE["role"] = "manager"

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
