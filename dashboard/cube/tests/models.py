"""Two models in one app (PLAN-models.md phase 3), in a real Chrome against the mock stack: the header switch, a list, a dashboard, the start page, the builder and the SQL lab all in the
model the person chose; the other model's dashboards are not shared; and a dashboard of another model opens the page in its own model.

  uv run --with playwright --with pyyaml --with jsonschema python -I dashboard/cube/tests/models.py
"""
import json
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


def open_page(browser, path, stored=None):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1300})
    ctx.add_init_script(ms.SEED + 'try { localStorage.setItem("theme", "light"); localStorage.setItem("dashLang", "en"); ' + (f'localStorage.setItem("model", "{stored}"); ' if stored else "") + "} catch (e) {}")
    page = ctx.new_page()
    page.problems, page.cubes = [], []
    page.on("pageerror", lambda e: page.problems.append(f"pageerror: {e}"))
    page.on("request", lambda r: page.cubes.append(r.url) if r.url.removeprefix(BASE).startswith("/cube-") else None)          # Cube calls (not /cube/cube-client.mjs)
    page.goto(f"{BASE}{path}")
    return ctx, page


ms.start()
ms.FAKE["on"] = True
ms.BENCH["on"] = False
ms.MODELS["on"] = True
ms.LAB["on"] = True
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ms.reset_saved()
    ms.ROLE["role"], ms.USER["name"] = "admin", "admin"

    # ---- the list: in the default model, with a switch; another model has other dashboards
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector(".lsec-samples .dcard")
    names = page.locator(".lsec-samples .dcard a").all_inner_texts()
    check(page.locator("#model-field").is_visible() and page.locator("#f-model option").all_inner_texts() == ["AdventureWorks", "Anadolu Dağıtım"], "the header has a model switch listing the stack's models")
    check(any("Sales overview" in n for n in names) and not any("Tahsilat" in n for n in names), f"the list is AdventureWorks' ({names})")
    page.select_option("#f-model", "distributor")
    page.wait_for_url("**/d/?model=distributor*")
    page.wait_for_selector(".lsec-samples .dcard")
    names = page.locator(".lsec-samples .dcard a").all_inner_texts()
    check(any("Tahsilat" in n for n in names) and not any("Sales overview" in n for n in names) and page.input_value("#f-model") == "distributor", f"switching shows the other model's dashboards ({names})")
    check(page.evaluate("localStorage.getItem('model')") == "distributor", "and remembers the choice for the next page")
    check(not [x for x in page.problems if "pageerror" in x], f"no script errors {page.problems[:1]}")
    ctx.close()

    # ---- a dashboard of the other model: drawn from that model's Cube
    ctx, page = open_page(browser, "/d/collections?model=distributor")
    page.wait_for_selector("[data-panel]", timeout=20000)
    page.wait_for_timeout(800)
    check(page.locator("[data-panel]").count() >= 3 and page.input_value("#f-model") == "distributor", "a distributor dashboard is drawn, in the distributor model")
    check(page.cubes and all("/cube-distributor" in u for u in page.cubes), f"and its queries go to the distributor's Cube ({sorted({u.removeprefix(BASE).split('/')[1] for u in page.cubes})})")
    ctx.close()

    # ---- a link to a dashboard of another model (stored model: AdventureWorks): the page follows the dashboard
    ctx, page = open_page(browser, "/d/collections", stored="adventureworks")
    page.wait_for_url("**/d/collections?model=distributor*", timeout=20000)
    page.wait_for_selector("[data-panel]", timeout=20000)
    check(page.input_value("#f-model") == "distributor" and page.evaluate("localStorage.getItem('model')") == "distributor", "a dashboard of another model opens the page in that model")
    ctx.close()
    ctx, page = open_page(browser, "/d/sales-overview", stored="distributor")
    page.wait_for_url("**/d/sales-overview?model=adventureworks*", timeout=20000)
    page.wait_for_selector("[data-panel]", timeout=20000)
    page.wait_for_timeout(500)
    check(page.input_value("#f-model") == "adventureworks" and all("/cube-distributor" not in u for u in page.cubes[-3:]), "and the other way round (its Cube is AdventureWorks')")
    ctx.close()

    # ---- the builder builds for the model the page is in, and says so
    ctx, page = open_page(browser, "/d/?model=distributor")
    page.wait_for_selector("#bb-prompt")
    page.fill("#bb-prompt", "revenue by region")
    page.click("#bb-go")
    page.wait_for_url("**/d/draft*", timeout=20000)
    draft = json.loads(page.evaluate("localStorage.getItem('builder.draft')"))
    check("model: distributor" in draft["yaml"] and "dealers.region" in draft["yaml"] and draft["spec"]["model"] == "distributor", "a build in the distributor model is a distributor dashboard that says so")
    page.wait_for_selector("[data-panel]", timeout=20000)
    check(page.input_value("#f-model") == "distributor", "and the draft opens in its own model")
    ctx.close()

    # ---- the start page and the lab follow the model
    ctx, page = open_page(browser, "/home/?model=distributor")
    page.wait_for_selector(".home-card, .home-sec", timeout=20000)
    check(page.input_value("#f-model") == "distributor" and "Tahsilat" in page.inner_text("#main") and "Sales overview" not in page.inner_text("#main"), "the start page lists the model's dashboards")
    ctx.close()
    ctx, page = open_page(browser, "/lab/?model=distributor")
    page.wait_for_selector("#schema details", timeout=20000)
    schema = page.inner_text("#schema")
    check("orders" in schema and "dealers" in schema and "internet_sales" not in schema, "the SQL lab's schema is the model's own")
    check(page.input_value("#f-model") == "distributor", "with the switch in the lab's header")
    page.select_option("#f-model", "adventureworks")
    page.wait_for_url("**/lab/?model=adventureworks*")
    page.wait_for_selector("#schema details", timeout=20000)
    check("internet_sales" in page.inner_text("#schema") and "orders" not in page.inner_text("#schema").replace("order_", ""), "and switching back gives AdventureWorks' schema")
    ctx.close()

    # ---- a stack with one model: no switch, nothing different
    ms.MODELS["on"] = False
    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector(".lsec-samples .dcard")
    check(page.locator("#model-field").is_hidden() and any("Sales overview" in n for n in page.locator(".lsec-samples .dcard a").all_inner_texts()), "a one-model stack has no switch and the usual list")
    ctx.close()
    browser.close()

if failures:
    print(f"\n{len(failures)} problem(s)")
    sys.exit(1)
print("\nmodels checks passed")
