"""The SQL lab (/lab/) in a real Chrome against the mock stack (the real statement checks, fake data): who gets it, the schema browser, running, the grid, tabs, history, Turkish.

  uv run --with playwright --with pyyaml --with jsonschema python -I dashboard/cube/tests/lab.py
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


def open_page(browser, path="/lab/", lang=None):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1300})
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE)
    ctx.add_init_script(ms.SEED + 'try { localStorage.setItem("theme", "light"); ' + (f'localStorage.setItem("dashLang", "{lang}");' if lang else "") + " } catch (e) {}")
    page = ctx.new_page()
    page.problems = []
    page.on("pageerror", lambda e: page.problems.append(f"pageerror: {e}"))
    page.goto(f"{BASE}{path}")
    return ctx, page


def ran(page, sql):
    page.fill("#sql", sql)
    page.click("#run")
    page.wait_for_function("!document.querySelector('#run').disabled")


ms.start()
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)

    # ---- a person without the lab is told how to get it, and gets no editor
    ms.ROLE["role"] = "manager"
    ms.LAB["on"] = False
    ctx, page = open_page(browser)
    page.wait_for_selector(".home-sec")
    check("not been given the SQL lab" in page.inner_text("#main") and page.locator("#sql").count() == 0, "without the lab there is an explanation and no editor")
    ctx.close()
    ctx, page = open_page(browser, path="/home/")
    page.wait_for_selector(".home-sec")
    check(page.locator(".home-card.start:has-text('SQL lab')").count() == 0, "and the start page does not offer it")
    ctx.close()

    # ---- a person with the lab: schema, insert, run, grid
    ms.LAB["on"] = True
    ms.LAB["ran"] = []
    ctx, page = open_page(browser)
    page.wait_for_selector("#sql")
    check(page.locator("#schema details").count() == 2 and "internet_sales" in page.inner_text("#schema"), "the schema browser lists the cubes this person may query")
    page.fill("#schema-q", "categ")
    check(page.locator("#schema .lab-field").count() == 1 and "category" in page.inner_text("#schema"), "searching the schema finds a field")
    page.fill("#schema-q", "")
    page.fill("#sql", "select  from internet_sales")
    page.evaluate("document.querySelector('#sql').setSelectionRange(7, 7)")
    page.locator("#schema summary", has_text="internet_sales").click()
    page.locator('#schema [data-insert="MEASURE(revenue)"]').click()
    check(page.input_value("#sql") == "select MEASURE(revenue) from internet_sales", "clicking a measure puts MEASURE(name) at the cursor")
    ran(page, "select category, measure(revenue) from internet_sales cross join products group by 1")
    page.wait_for_selector("#result table")
    check(page.locator("#result tbody tr").count() == 3 and "Bikes" in page.inner_text("#result") and "3 rows" in page.inner_text("#status"), "a result is shown with its row count")
    check("2026-06-29" in page.inner_text("#result") and "00:00:00" not in page.inner_text("#result"), "a time at midnight shows as a date")
    page.click('#result th[data-sort="1"]')
    first = page.locator("#result tbody tr").first.inner_text()
    page.click('#result th[data-sort="1"]')
    check("Clothing" in first and "Bikes" in page.locator("#result tbody tr").first.inner_text(), "clicking a header sorts, again reverses")
    page.click("#copy")
    page.wait_for_function("document.querySelector('#copy').textContent === 'Copied'")
    clip = page.evaluate("navigator.clipboard.readText()")
    check(clip.startswith("category\trevenue\tlast_order"), f"Copy puts the grid on the clipboard as tab-separated text ({clip[:30]!r})")

    # ---- keyboard, errors, refusals, empty, many rows
    page.fill("#sql", "select 'boom'")
    page.press("#sql", "Control+Enter")
    page.wait_for_selector("#err:not([hidden])")
    check("Profit and margin are not available" in page.inner_text("#err") and page.locator("#result table").count() == 0, "Ctrl+Enter runs; a refusal from the data is shown in its words")
    ran(page, "drop table internet_sales")
    page.wait_for_selector("#err:not([hidden])")
    check("Only SELECT" in page.inner_text("#err"), "a statement that is not a SELECT is refused")
    ran(page, "select 1; select 2")
    page.wait_for_selector("#err:not([hidden])")
    check("one statement" in page.inner_text("#err"), "two statements are refused")
    check(not any("drop" in q or "select 2" in q for q in ms.LAB["ran"]), "and none of those reached the data service's executor")
    ran(page, "select empty")
    page.wait_for_selector("#result .hint")
    check("no rows" in page.inner_text("#result"), "a query with no rows says so")
    ran(page, "select many")
    page.wait_for_selector("#result table")
    check(page.locator("#result tbody tr").count() == 1000 and "Showing 1000 of 1200" in page.inner_text("#status"), "a long result shows the first 1,000 rows and says so")

    # ---- tabs, history, examples, clear
    page.click("[data-newtab]")
    check(page.locator("#tabs [data-tab]").count() == 2 and page.input_value("#sql") == "", "a new tab is empty")
    page.select_option("#samples", "0")
    check("measure(revenue)" in page.input_value("#sql"), "an example fills the editor")
    page.locator("#tabs [data-tab]").first.click()
    check(page.input_value("#sql") == "select many", "switching tabs brings back each tab's query")
    page.reload()
    page.wait_for_selector("#sql")
    check(page.locator("#tabs [data-tab]").count() == 2, "tabs survive a reload (kept in this browser)")
    page.click(".lab-history summary")
    check(page.locator("#history li").count() >= 3 and "select many" in page.inner_text("#history"), "history lists what was run, newest first")
    page.locator("#history [data-hist]").nth(1).click()
    check(page.input_value("#sql") != "", "clicking a history entry loads it")
    page.click("#clear")
    check(page.input_value("#sql") == "", "Clear empties the editor")
    check(not [x for x in page.problems if "pageerror" in x], f"no script errors {page.problems[:1]}")
    ctx.close()

    # ---- the start page offers it, and an admin always has it
    ctx, page = open_page(browser, path="/home/")
    page.wait_for_selector(".home-sec")
    check(page.locator(".home-card.start:has-text('SQL lab')").count() == 1, "a person with the lab finds it on the start page")
    ctx.close()
    ms.LAB["on"] = False
    ms.ROLE["role"] = "admin"
    ctx, page = open_page(browser)
    page.wait_for_selector("#sql")
    check(True, "an admin has the lab without being given it")
    ctx.close()

    # ---- Turkish
    ms.ROLE["role"] = "manager"
    ms.LAB["on"] = True
    ctx, page = open_page(browser, lang="tr")
    page.wait_for_selector("#sql")
    check("Çalıştır" in page.inner_text(".lab-bar") and "ada tıklayın" in page.inner_text(".lab-side"), "the lab speaks Turkish on a Turkish page")
    ctx.close()
    ms.ROLE["role"] = "admin"
    ms.LAB["on"] = False
    browser.close()

if failures:
    print(f"\n{len(failures)} problem(s)")
    sys.exit(1)
print("\nsql lab checks passed")
