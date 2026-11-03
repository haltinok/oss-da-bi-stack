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
    ms.ROLE["role"] = "editor"
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

    # ---- export: the file is the statement's result, downloaded by the browser
    check(page.locator("#export-csv").is_visible() and page.locator("#export-xlsx").is_visible(), "a result offers CSV and Excel")
    with page.expect_download() as d:
        page.click("#export-csv")
    dl = d.value
    text = pathlib.Path(dl.path()).read_text(encoding="utf-8-sig")
    check(dl.suggested_filename == "lab-test.csv" and text.startswith("category,revenue,last_order") and "Bikes" in text, f"CSV downloads with the result ({dl.suggested_filename})")
    page.wait_for_function("document.querySelector('#status').textContent.includes('Exported 3 rows')")
    check(True, "and the page says how many rows were exported")
    ms.LAB["export_cut"] = True
    with page.expect_download():
        page.click("#export-xlsx")
    page.wait_for_function("document.querySelector('#status').textContent.includes('first 3 rows')")
    check("xlsx" in ms.LAB["exports"], "Excel is asked for, and a cut export says the file holds only the first rows")
    ms.LAB["export_cut"] = False

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

    # ---- saved queries: save, share, run as the runner, snapshots are your own
    ms.LAB.pop("lab_store", None)
    ms.USER["name"] = "alice"
    ms.USER["groups"] = []
    ms.ROLE["role"] = "editor"
    ms.LAB["on"] = True
    ctx, page = open_page(browser)
    page.wait_for_selector("#sql")
    check(page.locator("#save").is_hidden() is False and page.locator("#share").is_hidden(), "a new query can be saved but not yet shared or deleted")
    page.fill("#sql", "select category, measure(revenue) from internet_sales cross join products group by 1")
    page.click("#save")
    page.wait_for_selector("#share-dlg input[name=name]")
    page.fill('#share-dlg input[name="name"]', "Revenue by category")
    page.click("#share-dlg [data-go]")
    page.wait_for_selector("#linked:not([hidden])")
    check("Revenue by category" in page.inner_text("#linked") and "Revenue by category" in page.inner_text("#saved-box"), "saving names the query, lists it, and links the tab to it")
    page.click("#share")
    page.wait_for_selector("#sh-name")
    page.fill("#sh-name", "bob")
    page.click("#sh-add")
    page.select_option('#share-dlg select[name="folder"]', label="Quarterly")
    page.click("#share-dlg [data-go]")
    page.wait_for_function("!document.querySelector('#share-dlg').open")
    page.wait_for_function("document.querySelector('#linked').innerText.includes('Quarterly')")
    check("in Quarterly" in page.inner_text("#saved-box"), "sharing with a person and putting it in a folder is shown")
    page.click("#run")
    page.wait_for_selector("#note:has-text('Your result from')")
    alice_numbers = page.inner_text("#result")
    check("4279788.58" in alice_numbers, "running a saved query keeps the result as your snapshot and says until when")
    page.reload()
    page.wait_for_selector("#sql")
    page.click('#saved-box [data-open]')
    page.wait_for_selector("#note:has-text('Your result from')")
    check("4279788.58" in page.inner_text("#result"), "opening it later brings your last result back without running anything")
    ctx.close()

    ms.USER["name"] = "bob"
    ctx, page = open_page(browser)
    page.wait_for_selector("#sql")
    check("Shared with you" in page.inner_text("#saved-box") and "Revenue by category" in page.inner_text("#saved-box") and "alice" in page.inner_text("#saved-box"), "a person it is shared with finds it under 'Shared with you'")
    page.click('#saved-box [data-open]')
    page.wait_for_selector("#note:has-text('No saved result')")
    check(page.locator("#result table").count() == 0, "alice's result is not bob's to see: there is none for bob yet")
    check(page.locator("#share").is_hidden() and page.locator("#delete-q").is_hidden() and page.locator("#save").is_hidden(), "a viewer cannot share, delete or overwrite it")
    page.click("#run")
    page.wait_for_selector("#note:has-text('Your result from')")
    bob_numbers = page.inner_text("#result")
    check("4279788.58" not in bob_numbers and "427.98" in bob_numbers, "running it runs it as bob, under bob's rules: smaller numbers")
    ctx.close()
    ms.USER["name"] = "alice"
    ctx, page = open_page(browser)
    page.wait_for_selector("#sql")
    page.click('#saved-box [data-open]')
    page.wait_for_selector("#note:has-text('Your result from')")
    check("4279788.58" in page.inner_text("#result"), "and alice still has her own numbers")
    page.once("dialog", lambda d: d.accept())
    page.click("#delete-q")
    page.wait_for_function("document.querySelector('#saved-box').innerText.includes('Nothing saved yet')")
    check(page.locator("#linked").is_hidden(), "deleting a saved query removes it and unlinks the tab")
    check(not [x for x in page.problems if "pageerror" in x], f"no script errors {page.problems[:1]}")
    ctx.close()
    ms.LAB["saving"] = False
    ctx, page = open_page(browser)
    page.wait_for_selector("#sql")
    check("Saving queries is off" in page.inner_text("#saved-box") and page.locator("#save").is_hidden(), "without saving the lab says so and offers no Save")
    ctx.close()
    ms.LAB["saving"] = True
    ms.USER["name"] = "admin"
    ms.ROLE["role"] = "admin"
    ms.LAB["on"] = False

    # ---- the start page offers it, and an admin always has it
    ms.ROLE["role"] = "editor"
    ms.LAB["on"] = True
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
    ms.ROLE["role"] = "editor"
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
