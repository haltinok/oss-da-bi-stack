"""A viewer in a real Chrome against the mock stack: they can open dashboards (the built ones their role may open, and what is shared with them) and nothing that builds, changes or keeps.

  uv run --with playwright --with pyyaml --with jsonschema python -I dashboard/cube/tests/viewer.py
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import mock_stack as ms  # noqa: E402

BASE = f"http://localhost:{ms.PORT}"
failures = []


def check(ok, msg):
    print(("PASS  " if ok else "FAIL  ") + msg)
    if not ok:
        failures.append(msg)
    return ok


def open_page(browser, path):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1300})
    ctx.add_init_script(ms.SEED + 'try { localStorage.setItem("theme", "light"); localStorage.setItem("dashLang", "en"); } catch (e) {}')
    page = ctx.new_page()
    page.problems = []
    page.on("pageerror", lambda e: page.problems.append(f"pageerror: {e}"))
    page.goto(f"{BASE}{path}")
    return ctx, page


ms.start()
ms.FAKE["on"] = True
ms.BENCH["on"] = False
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ms.reset_saved()
    ms.LAB["on"] = False
    ms.ROLE["role"], ms.USER["name"], ms.USER["groups"] = "editor", "olga", []
    shared = ms.seed_saved("Shared with viewers", "for the team", owner="olga", role="editor", visibility="everyone", source="regional-sales.yml")["id"]
    ms.ROLE["role"], ms.USER["name"] = "viewer", "vera"

    ms.BUILDER["unreadable_samples"] = ("envanter-sagligi", "sales-overview")
    # ---- the dashboards list: no prompt box, no semantic layer, no Copy, no New folder, no Share or Delete; what may be opened is listed
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector(".lsec-shared .saved")
    check(page.locator("#bb-prompt").count() == 0 and page.locator("#sem-wrap").count() == 0 and page.locator("#builder-host").count() == 0, "a viewer has no prompt box and no semantic layer on the list")
    check(page.locator(".lsec-shared .saved").count() == 1 and "Shared with viewers" in page.inner_text(".lsec-shared"), "what is shared with them is listed")
    check(page.locator('[data-act="copy"], [data-act="share"], [data-act="delete"], [data-act="folder-new"]').count() == 0, "with no Copy, Share, Delete or New folder")
    samples = page.locator(".lsec-samples .dcard a").all_inner_texts()
    check(any("Regional" in s for s in samples) and not any("Sales overview" in s or "Inventory" in s for s in samples), f"and only the sample dashboards their role may open ({samples})")
    check(not [x for x in page.problems if "pageerror" in x], f"no script errors {page.problems[:1]}")
    ctx.close()

    # ---- a dashboard: drawn, with no builder bar and no designer
    ctx, page = open_page(browser, "/d/regional-sales")
    page.wait_for_selector("[data-panel]", timeout=20000)
    check(page.locator("#builder-host").count() == 0 and page.locator("#bd-design").count() == 0, "an opened dashboard has no builder bar or Design button")
    ctx.close()
    ctx, page = open_page(browser, f"/d/s/{shared}")
    page.wait_for_selector("[data-panel]", timeout=20000)
    check(page.locator("#builder-host").count() == 0, "nor a shared saved dashboard (no Save, Design or sharing bar)")
    ctx.close()
    ctx, page = open_page(browser, "/d/draft")
    page.wait_for_selector("#error:not([hidden])", timeout=20000)
    check(page.locator("#bd-design").count() == 0, "and there are no drafts to open")
    ctx.close()

    # ---- the start page: no 'describe', no SQL lab, no admin
    ctx, page = open_page(browser, "/home/")
    page.wait_for_selector(".home-sec")
    cards = page.locator(".home-card.start").all_inner_texts()
    check(not any("Describe" in c or "SQL lab" in c or "Admin" in c for c in cards) and any("All dashboards" in c for c in cards), f"the start page offers dashboards only ({[c.splitlines()[0] for c in cards]})")
    ctx.close()

    # ---- the lab and the console turn a viewer away
    ctx, page = open_page(browser, "/lab/")
    page.wait_for_selector(".home-sec")
    check("not been given the SQL lab" in page.inner_text("#main") and page.locator("#sql").count() == 0, "the SQL lab is not theirs")
    ctx.close()
    ctx, page = open_page(browser, "/admin/")
    page.wait_for_selector(".adm-empty")
    check("Only an admin" in page.inner_text("#main"), "nor the admin console")
    ctx.close()
    ms.ROLE["role"], ms.USER["name"] = "admin", "admin"
    browser.close()

if failures:
    print(f"\n{len(failures)} problem(s)")
    sys.exit(1)
print("\nviewer checks passed")
