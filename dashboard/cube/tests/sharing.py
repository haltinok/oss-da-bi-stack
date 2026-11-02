"""Folders, sharing with people and groups, and the trash on the dashboards list (/d/), in a real Chrome against the mock stack.

  uv run --with playwright --with pyyaml --with jsonschema python -I dashboard/cube/tests/sharing.py
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


def open_page(browser, path="/d/", lang=None):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1400})
    ctx.add_init_script(ms.SEED + 'try { localStorage.setItem("theme", "light"); ' + (f'localStorage.setItem("dashLang", "{lang}");' if lang else "") + " } catch (e) {}")
    page = ctx.new_page()
    page.problems = []
    page.on("pageerror", lambda e: page.problems.append(f"pageerror: {e}"))
    page.on("dialog", lambda d: d.accept())                       # the confirm() of a delete
    page.goto(f"{BASE}{path}")
    return ctx, page


def titles(page, section):
    return page.locator(f".lsec-{section} .saved .saved-main > a").all_inner_texts()


ms.start()
ms.FAKE["on"] = True
ms.BENCH["on"] = False
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ms.reset_saved()
    ms.ROLE["role"] = "manager"
    ms.USER["name"] = "alice"
    ms.USER["groups"] = []
    ms.seed_saved("Alice sales", "regional", owner="alice", role="manager")

    # ---- alice: a folder, then share the dashboard with bob (edit) and a group, and put it in the folder
    ctx, page = open_page(browser)
    page.wait_for_selector(".lsec-mine .saved")
    page.click('[data-act="folder-new"]')
    page.fill('#share-dlg input[name="name"]', "Quarterly")
    page.click("#share-dlg [data-go]")
    page.wait_for_selector(".folder-h:has-text('Quarterly')")
    check(True, "a folder is created and shown with its (empty) heading")
    page.click('.saved [data-act="share"]')
    page.wait_for_selector("#sh-name")
    page.fill("#sh-name", "bob")
    page.select_option("#sh-perm", "edit")
    page.click("#sh-add")
    page.select_option("#sh-type", "group")
    page.fill("#sh-name", "Ops")
    page.click("#sh-add")
    check("bob" in page.inner_text("#sh-list") and "Ops" in page.inner_text("#sh-list") and "edit" in page.inner_text("#sh-list").lower(), "a person (edit) and a group (view) are added")
    page.select_option('#share-dlg select[name="folder"]', label="Quarterly")
    page.click("#share-dlg [data-go]")
    page.wait_for_function("!document.querySelector('#share-dlg').open")
    page.wait_for_function("document.querySelector('.folder-h[data-folder] + ul .saved')")
    check(page.locator(".folder-h:has-text('Quarterly') + ul .saved").count() == 1, "the dashboard sits under the folder it was moved to")
    page.click('.folder-h:has-text("Quarterly") [data-act="folder-share"]')
    page.fill("#sh-name", "carol")
    page.click("#sh-add")
    page.click("#share-dlg [data-go]")
    page.wait_for_function("!document.querySelector('#share-dlg').open")
    ctx.close()

    # ---- bob sees it, under "shared with you", can open it and copy it, but cannot share or delete it
    ms.USER["name"] = "bob"
    ctx, page = open_page(browser)
    page.wait_for_selector(".lsec-shared .saved")
    check(titles(page, "shared") == ["Alice sales"], "a person it is shared with finds it under 'Shared with you'")
    check(page.locator('.lsec-shared [data-act="share"]').count() == 0 and page.locator('.lsec-shared [data-act="delete"]').count() == 0, "and cannot share or delete it")
    ctx.close()

    # ---- a member of the group sees it too; a stranger does not
    ms.USER["name"] = "dave"
    ms.USER["groups"] = ["Ops"]
    ctx, page = open_page(browser)
    page.wait_for_selector(".lsec-shared .saved")
    check(titles(page, "shared") == ["Alice sales"], "a member of a group it is shared with finds it")
    ctx.close()
    ms.USER["groups"] = ["Other"]
    ctx, page = open_page(browser)
    page.wait_for_selector(".lsec-mine")
    check(page.locator(".lsec-shared .saved").count() == 0, "someone else does not see it")
    ctx.close()

    # ---- carol is in the folder's share: she sees the folder and what is in it
    ms.USER["name"] = "carol"
    ms.USER["groups"] = []
    ctx, page = open_page(browser)
    page.wait_for_selector(".lsec-shared .saved")
    check(page.locator(".folder-h:has-text('Quarterly')").count() == 1 and titles(page, "shared") == ["Alice sales"], "a folder shared with someone shows its dashboards")
    ctx.close()

    # ---- alice: delete goes to the trash; restore brings it back; rename and delete the folder
    ms.USER["name"] = "alice"
    ms.USER["groups"] = []
    ctx, page = open_page(browser)
    page.wait_for_selector(".lsec-mine .saved")
    page.click('.saved [data-act="delete"]')
    page.wait_for_selector("#trash:not([hidden])")
    check(page.locator(".lsec-mine .saved").count() == 0 and "Trash (1)" in page.inner_text("#trash summary"), "deleting moves a dashboard to the trash")
    page.click("#trash summary")
    page.click('#trash [data-act="restore"]')
    page.wait_for_selector(".lsec-mine .saved")
    check(titles(page, "mine") == ["Alice sales"] and page.locator("#trash:not([hidden])").count() == 0, "restoring brings it back")
    page.click('.folder-h:has-text("Quarterly") [data-act="folder-rename"]')
    page.fill('#share-dlg input[name="name"]', "Q4")
    page.click("#share-dlg [data-go]")
    page.wait_for_selector(".folder-h:has-text('Q4')")
    page.click('.folder-h:has-text("Q4") [data-act="folder-delete"]')
    page.wait_for_function("document.querySelectorAll('.folder-h[data-folder]:not([data-folder=\"\"])').length === 0")
    check(titles(page, "mine") == ["Alice sales"], "deleting a folder keeps what was in it")
    check(not [x for x in page.problems if "pageerror" in x], f"no script errors {page.problems[:1]}")
    ctx.close()

    # ---- Turkish
    ctx, page = open_page(browser, lang="tr")
    page.wait_for_selector(".lsec-mine .saved")
    check("Yeni klasör" in page.inner_text(".lsec-bar") and "Paylaş" in page.inner_text(".saved"), "the list speaks Turkish on a Turkish page")
    ctx.close()
    ms.USER["name"] = "admin"
    browser.close()

if failures:
    print(f"\n{len(failures)} problem(s)")
    sys.exit(1)
print("\nsharing checks passed")
