"""The dashboard's dataset switch, against mock services (no stack needed).

  uv run --with playwright python -I dashboard/cube/tests/dataset.py

Serves dashboard/static and dashboard/cube from a small local server that also plays Keycloak's replacement (a
pre-seeded session), the auth service, the actions service and two Cubes, and records which of them each page
asked. Checks: with one dataset offered there is no switch; with two, the switch shows, the default is the live
mart, picking the benchmark reloads the page on the other Cube only (?dataset=250m, remembered), the benchmark is
read-only (no actions service call, a banner says so), and picking live again goes back.
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mock_stack as ms  # noqa: E402
from mock_stack import BENCH, PORT, SEED, hits  # noqa: E402

failures = []


def check(ok, msg):
    print(("PASS  " if ok else "FAIL  ") + msg)
    if not ok:
        failures.append(msg)


server = ms.start()


def load(browser, url, wait=3000):
    hits.clear()
    ctx = browser.new_context()
    ctx.add_init_script(SEED)
    page = ctx.new_page()
    page.goto(url)
    page.wait_for_timeout(wait)
    return ctx, page


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    base = f"http://localhost:{PORT}/"

    BENCH["on"] = False
    ctx, page = load(browser, base)
    check(page.locator("#f-dataset").is_hidden() and page.locator("#dataset-static").is_visible() and page.text_content("#dataset-static") == "Live (simulator)",
          "one dataset offered: no switch, a plain label names it")
    check("ro" not in (page.get_attribute("#dataset-field", "class") or "").split() and page.locator("#dataset-badge").count() == 0, "the header names the live dataset (no badge in the title)")
    check(hits.get("/cube-live", 0) > 0 and not hits.get("/cube-bench"), "reads the live Cube")
    ctx.close()

    BENCH["on"] = True
    ctx, page = load(browser, base)
    check(page.locator("#dataset-field").is_visible() and page.locator("#f-dataset option").count() == 2, "two datasets offered: the switch is shown")
    check(page.input_value("#f-dataset") == "live" and page.inner_text("#mart-name") == "mart", "default is the live mart")
    check(hits.get("/cube-live", 0) > 0 and not hits.get("/cube-bench"), "live: only the live Cube is asked")
    check(hits.get("/actions", 0) > 0, "live: the actions service is used")
    check(page.locator("#dataset-banner").is_hidden(), "live: no benchmark banner")

    hits.clear()
    page.select_option("#f-dataset", "250m")
    page.wait_for_timeout(3500)
    check("dataset=250m" in page.url, f"picking the benchmark reloads on ?dataset=250m ({page.url})")
    check(page.input_value("#f-dataset") == "250m" and page.inner_text("#mart-name") == "mart_250m", "the switch and the mart name follow")
    check(hits.get("/cube-bench", 0) > 0 and not hits.get("/cube-live"), f"benchmark: only the benchmark Cube is asked ({hits})")
    check(not hits.get("/actions"), "benchmark: the actions service is never called")
    check(page.locator("#dataset-banner").is_visible() and "Approve is available in Live" in page.inner_text("#dataset-banner"), "benchmark: a one-line banner says Approve is available in Live")
    page.click("#dataset-banner-toggle")
    check("Approve is disabled" in page.inner_text("#dataset-banner") and "postgres_active" in page.inner_text("#dataset-banner"), "benchmark: Details gives the reason (the live ERP)")
    check("ro" in (page.get_attribute("#dataset-field", "class") or "").split() and "250M benchmark" in (page.get_attribute("#dataset-field", "title") or ""), "the header marks the benchmark dataset")
    check(page.locator('[data-panel="proposals"]').is_hidden(), "benchmark: no proposals panel")

    page.reload()                                   # remembered without the URL parameter too
    page.wait_for_timeout(1500)
    page2 = ctx.new_page()
    hits.clear()
    page2.goto(base)
    page2.wait_for_timeout(2500)
    check(page2.input_value("#f-dataset") == "250m" and hits.get("/cube-bench", 0) > 0, "the choice is remembered in this browser")

    hits.clear()
    page2.select_option("#f-dataset", "live")
    page2.wait_for_timeout(3500)
    check(hits.get("/cube-live", 0) > 0 and not hits.get("/cube-bench") and "dataset=" not in page2.url, f"back to live ({page2.url})")
    ctx.close()
    browser.close()

server.shutdown()
print("\nFAILED" if failures else "\nall dataset checks passed")
sys.exit(1 if failures else 0)
