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

    # ---- undo and redo
    check(page.locator('#designer [data-hist="undo"]').is_enabled() and page.locator('#designer [data-hist="redo"]').is_disabled(), "undo is on after changes and redo is off")
    check("Board pack" in (page.get_attribute('#designer [data-hist="undo"]', "title") or "") or "page" in (page.get_attribute('#designer [data-hist="undo"]', "title") or "").lower(), "its tooltip says what it would undo")
    with page.expect_navigation():
        page.click('#designer [data-hist="undo"]')
    settled(page)
    check(page.inner_text("#title") != "Board pack" and yaml_of(page)["title"] != "Board pack", "Undo brings back the title before the change")
    check("Undid" in page.inner_text("#bd-msg") and page.get_attribute("#bd-design", "aria-pressed") == "true", "the draft bar says so and design mode stays on")
    check(page.locator('#designer [data-hist="redo"]').is_enabled(), "and now redo is on")
    with page.expect_navigation():
        page.click('#designer [data-hist="redo"]')
    settled(page)
    check(page.inner_text("#title") == "Board pack" and "Redid" in page.inner_text("#bd-msg"), "Redo puts it back")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    with page.expect_navigation():
        page.keyboard.press("Control+z")
    settled(page)
    check(page.inner_text("#title") != "Board pack", "Ctrl+Z undoes")
    with page.expect_navigation():
        page.keyboard.press("Control+Shift+z")
    settled(page)
    check(page.inner_text("#title") == "Board pack", "Ctrl+Shift+Z redoes")
    with page.expect_navigation():
        page.keyboard.press("Control+z")
    settled(page)
    with page.expect_navigation():
        page.keyboard.press("Control+y")
    settled(page)
    check(page.inner_text("#title") == "Board pack", "and so does Ctrl+Y")
    draft_before = page.evaluate("localStorage.getItem('builder.draft')")
    page.click('#designer [data-path="description"]')
    page.keyboard.type("xyz")
    page.keyboard.press("Control+z")
    page.wait_for_timeout(600)
    check(page.evaluate("localStorage.getItem('builder.draft')") == draft_before and not page.input_value('#designer [data-path="description"]').endswith("xyz"), "in a text field Ctrl+Z is the field's own undo, not the draft's")
    page.press('#designer [data-path="description"]', "Escape")

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

    # ---- the Change box and the designer together: with a panel picked, the model's change is about that panel only, and undo takes it back
    ctx, page = open_page(browser, "/d/draft", draft=kept_draft)
    page.wait_for_function("!document.querySelector('#bd-design')?.disabled", timeout=20000)
    settled(page)
    sent = []
    page.on("request", lambda r: sent.append(json.loads(r.post_data or "{}")) if r.method == "POST" and r.url.endswith("/build") else None)
    check(page.locator("#bd-focus").is_hidden(), "with nothing picked the Change box is about the whole dashboard")
    page.click("#bd-design")
    bar = panel_of(page, "bar")
    page.click(f'[data-panel="{bar}"] h2')
    bar_title = next(x for x in yaml_of(page)["panels"] if x["id"] == bar)["title"]
    check(page.locator("#bd-focus").is_visible() and bar_title in page.inner_text("#bd-focus"), "picking a panel says the Change box will change that panel only")
    others = [x for x in yaml_of(page)["panels"] if x["id"] != bar]
    with page.expect_navigation():
        page.fill("#bd-change", "make this one a donut")
        page.click("#bd-go")
    settled(page)
    after = yaml_of(page)["panels"]
    check(sent and sent[-1].get("focus") == bar, "the request names the picked panel")
    check(next(x for x in after if x["id"] == bar)["type"] == "pie" and [x for x in after if x["id"] != bar] == others, "the picked panel became a pie and no other panel was touched")
    check(page.locator(f'[data-panel="{bar}"]').evaluate("n => n.classList.contains('dz-selected')") and page.locator("#bd-focus").is_visible(), "the panel stays picked after the model's change")
    with page.expect_navigation():
        page.click('#designer [data-hist="undo"]')
    settled(page)
    check(next(x for x in yaml_of(page)["panels"] if x["id"] == bar)["type"] == "bar", "undo takes the model's change back, like a designer edit")
    page.keyboard.press("Escape")
    check(page.locator("#bd-focus").is_hidden(), "with the panel dropped the Change box is about the whole dashboard again")
    sent.clear()
    with page.expect_navigation():
        page.fill("#bd-change", "show the top 3")
        page.click("#bd-go")
    settled(page)
    check(sent and "focus" not in sent[-1], "with nothing picked the request carries no focus")
    ctx.close()

    # ---- formulas, lists of measures, and a pivot's own fields
    ctx, page = open_page(browser, "/d/draft", draft=kept_draft)
    page.wait_for_function("!document.querySelector('#bd-design')?.disabled", timeout=20000)
    settled(page)
    page.click("#bd-design")

    def reload_after(action):
        with page.expect_navigation():
            action()
        settled(page)

    def panel_src(pid):
        return next(x for x in yaml_of(page)["panels"] if x["id"] == pid)

    trend = panel_of(page, "timeseries")
    page.click(f'[data-panel="{trend}"] h2')
    n_series = len(panel_src(trend)["series"])
    reload_after(lambda: page.click('#designer [data-additem="series"]'))
    check(len(panel_src(trend)["series"]) == n_series + 1, "Add a series adds one to the time chart")
    reload_after(lambda: page.select_option(f'#designer [data-path="series.{n_series}.kind"]', "sum"))
    added = panel_src(trend)["series"][n_series]
    check("sum" in added and len(added["sum"]) == 2 and added.get("label"), f"a series can be turned into a sum ({added.get('sum')})")
    check("=" in page.inner_text("#designer .dz-preview") and "+" in page.inner_text("#designer .dz-preview"), "and the formula is told in words")
    reload_after(lambda: page.select_option(f'#designer [data-path="series.{n_series}.kind"]', "ratio"))
    check("ratio" in panel_src(trend)["series"][n_series] and "÷" in page.inner_text("#designer .dz-preview"), "then into a ratio, shown with a division sign")
    reload_after(lambda: page.locator("#designer [data-rmitem]").nth(n_series).click())
    check(len(panel_src(trend)["series"]) == n_series, "Remove this one takes the series out again")
    page.keyboard.press("Escape")

    n_panels = len(yaml_of(page)["panels"])
    reload_after(lambda: page.click('#dz-gallery [data-add="pivot"]'))
    pv = yaml_of(page)["panels"][-1]
    check(pv["type"] == "pivot" and len(yaml_of(page)["panels"]) == n_panels + 1, "a pivot is added and picked")
    reload_after(lambda: page.click('#designer [data-additem="measures"]'))
    pv = panel_src(pv["id"])
    check(len(pv["measures"]) == 2, "a pivot takes a second measure")
    second = pv["measures"][1]["member"] if isinstance(pv["measures"][1], dict) else pv["measures"][1]
    reload_after(lambda: page.select_option('#designer [data-path="heat.measure"]', second))
    check(panel_src(pv["id"]).get("heat") == {"measure": second}, "the heat map can be put on a measure of the pivot")
    reload_after(lambda: page.select_option('#designer [data-path="heat.measure"]', ""))
    check("heat" not in panel_src(pv["id"]), "and taken off again, leaving no empty `heat` behind")
    reload_after(lambda: (page.fill('#designer [data-path="limit.rows"]', "7"), page.press('#designer [data-path="limit.rows"]', "Tab")))
    check(panel_src(pv["id"]).get("limit") == {"rows": 7}, "a pivot's row limit is a field")
    reload_after(lambda: page.locator("#designer [data-rmitem]").first.click())
    check(len(panel_src(pv["id"])["measures"]) == 1 and not page.locator("#designer [data-rmitem]").count(), "a pivot's measure can be removed, and the last one cannot")
    ctx.close()

    # ---- tabs: split a page in two, add one, remove one, put them back on one page
    ctx, page = open_page(browser, "/d/draft", draft=kept_draft)
    page.wait_for_function("!document.querySelector('#bd-design')?.disabled", timeout=20000)
    settled(page)
    page.click("#bd-design")
    all_ids = sorted(x["id"] for x in yaml_of(page)["panels"])
    placed = lambda: sorted(next(iter(c)) for tab in (yaml_of(page).get("tabs") or [{"layout": yaml_of(page)["layout"]}]) for row in tab["layout"] for c in row)
    check("layout" in yaml_of(page) and "dz-totabs" in page.inner_html("#designer"), "a one-page dashboard offers to split into tabs")
    reload_after(lambda: page.click("#dz-totabs"))
    tabs = yaml_of(page).get("tabs")
    check(tabs and len(tabs) == 2 and "layout" not in yaml_of(page) and placed() == all_ids, f"it splits into two tabs with every panel still placed once ({[t['title'] for t in tabs]})")
    page.wait_for_selector("[role=tab]", timeout=10000)
    check(page.locator("[role=tab]").count() == 2, "and the page shows two tabs")
    page.fill("#dz-newtab", "Notes")
    reload_after(lambda: page.click("#dz-addtab"))
    check([t["title"] for t in yaml_of(page)["tabs"]][-1] == "Notes" and len(yaml_of(page)["tabs"]) == 3, "Add a tab adds one at the end, holding a text panel")
    with page.expect_navigation():
        page.once("dialog", lambda d: d.accept())
        page.locator('#designer [data-tab-remove="tab_3"]').click()
    settled(page)
    check(len(yaml_of(page)["tabs"]) == 2 and placed() == sorted([*all_ids, "note"]), "removing a tab keeps its panels (on the neighbouring tab)")
    with page.expect_navigation():
        page.once("dialog", lambda d: d.accept())
        page.click("#dz-onepage")
    settled(page)
    check("tabs" not in yaml_of(page) and placed() == sorted([*all_ids, "note"]), "Back to one page puts every panel on a single layout")
    ctx.close()

    # ---- colour rules on a key figure and on a table's measure column
    ctx, page = open_page(browser, "/d/draft", draft=kept_draft)
    page.wait_for_function("!document.querySelector('#bd-design')?.disabled", timeout=20000)
    settled(page)
    page.click("#bd-design")
    kpi = panel_of(page, "kpi")
    page.click(f'[data-panel="{kpi}"] .card', position={"x": 6, "y": 6})
    reload_after(lambda: page.click('#designer [data-addrule="measures.0"]'))
    check(panel_src(kpi)["measures"][0].get("rules") == [{"when": "below", "value": 0, "tone": "bad"}], "Add a colour rule gives a key figure its first rule")
    reload_after(lambda: page.select_option('#designer [data-path="measures.0.rules.0.when"]', "above"))
    reload_after(lambda: (page.fill('#designer [data-path="measures.0.rules.0.value"]', "0.25"), page.press('#designer [data-path="measures.0.rules.0.value"]', "Tab")))
    reload_after(lambda: page.select_option('#designer [data-path="measures.0.rules.0.tone"]', "good"))
    check(panel_src(kpi)["measures"][0]["rules"] == [{"when": "above", "value": 0.25, "tone": "good"}], "the rule's comparison, number (a fraction is fine) and tone are fields")
    page.wait_for_selector(f'[data-panel="{kpi}"] .kpi.tone-good', timeout=20000)
    check("✓" in page.locator(f'[data-panel="{kpi}"] .kpi.tone-good .value').first.inner_text(), "and the page shows the tone with its symbol")
    for _ in range(3):
        reload_after(lambda: page.click('#designer [data-addrule="measures.0"]'))
    check(len(panel_src(kpi)["measures"][0]["rules"]) == 4 and page.locator('#designer [data-addrule="measures.0"]').count() == 0, "four rules is the most: the button goes")
    for _ in range(4):
        reload_after(lambda: page.locator("#designer [data-rmrule]").first.click())
    check("rules" not in panel_src(kpi)["measures"][0], "removing the last rule leaves no empty `rules` behind")
    table = panel_of(page, "table")
    if table:
        page.click(f'[data-panel="{table}"] h2')
        n = page.locator("#designer [data-addrule]").count()
        check(n >= 1, f"a table offers a colour rule for its measure columns only ({n} of its columns)")
        base = page.locator("#designer [data-addrule]").first.get_attribute("data-addrule")
        reload_after(lambda: page.click(f'#designer [data-addrule="{base}"]'))
        idx = int(base.split(".")[1])
        col = panel_src(table)["columns"][idx]
        check(isinstance(col, dict) and col.get("rules") and "member" in col, "a plain column became an object with its rule")
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
