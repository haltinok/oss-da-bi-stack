"""The admin console (/admin/) in a real Chrome against the mock stack: people, groups, the dialogs, and who is let in.

  uv run --with playwright python -I dashboard/cube/tests/admin.py
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


def open_page(browser, path="/admin/", lang=None, width=1440):
    ctx = browser.new_context(viewport={"width": width, "height": 1000})
    ctx.add_init_script(ms.SEED + 'try { localStorage.setItem("theme", "light"); ' + (f'localStorage.setItem("dashLang", "{lang}");' if lang else "") + " } catch (e) {}")
    page = ctx.new_page()
    page.problems = []
    page.on("pageerror", lambda e: page.problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: page.problems.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.goto(f"{BASE}{path}")
    return ctx, page


def names(page):
    return page.locator(".adm-table tbody tr td:first-child strong").all_inner_texts()


ms.start()
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)

    # ---- users: the list, search and filters
    ms.ROLE["role"] = "admin"
    ms.reset_admin()
    ctx, page = open_page(browser)
    page.wait_for_selector(".adm-table")
    check(names(page) == ["admin", "de_rep", "na_manager"], f"the people are listed by username ({names(page)})")
    check("3 people" in page.inner_text(".adm-count"), "and counted")
    page.select_option("#f-role", "rep")
    page.wait_for_function("document.querySelectorAll('.adm-table tbody tr').length === 1")
    check(names(page) == ["de_rep"], "the role filter narrows the list")
    page.select_option("#f-role", "")
    page.fill("#q", "na_")
    page.wait_for_function("document.querySelectorAll('.adm-table tbody tr').length === 1")
    check(names(page) == ["na_manager"], "search finds a person by part of the username")
    page.fill("#q", "")
    page.wait_for_function("document.querySelectorAll('.adm-table tbody tr').length === 3")

    # ---- groups first, so a new person can be put in one
    page.click('[data-tab="groups"]')
    check("No groups yet" in page.inner_text(".adm-page"), "a new install has no groups")
    page.click("#new-group")
    page.fill('#dlg input[name="name"]', "Sales team")
    page.click("#dlg [data-go]")
    page.wait_for_selector(".adm-table tbody tr")
    check(page.locator(".adm-table tbody tr td strong").first.inner_text() == "Sales team", "a group is created")

    # ---- create a user
    page.click('[data-tab="users"]')
    page.click("#new-user")
    page.fill('#dlg input[name="username"]', "ayse")
    page.fill('#dlg input[name="email"]', "ayse@example.com")
    page.select_option('#dlg select[name="role"]', "manager")
    page.check('#dlg input[name="g"]')
    page.fill('#dlg input[name="password"]', "short")
    page.click("#dlg [data-go]")
    page.wait_for_selector("#dlg .err:not([hidden])")
    check("at least 10" in page.inner_text("#dlg .err"), "a too-short password is refused in the dialog")
    page.fill('#dlg input[name="password"]', "a-long-password-1")
    page.click("#dlg [data-go]")
    page.wait_for_function("!document.querySelector('#dlg').open")
    page.wait_for_function("document.querySelectorAll('.adm-table tbody tr').length === 4")
    row = page.locator("tr:has(strong:text-is('ayse'))")
    check("manager" in row.inner_text() and "Sales team" in row.inner_text(), "the new person has the role and the group")
    page.click("#new-user")
    page.fill('#dlg input[name="username"]', "ayse")
    page.fill('#dlg input[name="password"]', "a-long-password-1")
    page.click("#dlg [data-go]")
    page.wait_for_selector("#dlg .err:not([hidden])")
    check("exists" in page.inner_text("#dlg .err"), "a taken username is refused, in the dialog")
    page.click("#dlg [data-close]")

    # ---- edit, deactivate, activate
    row.locator('[data-act="edit"]').click()
    page.select_option('#dlg select[name="role"]', "rep")
    page.click("#dlg [data-go]")
    page.wait_for_function("!document.querySelector('#dlg').open")
    check("rep" in page.locator("tr:has(strong:text-is('ayse'))").inner_text(), "editing changes the role")
    page.locator("tr:has(strong:text-is('ayse')) [data-act='deactivate']").click()
    page.click("#dlg [data-go]")
    page.wait_for_function("document.querySelector('tr:has(strong)') && [...document.querySelectorAll('tr.off')].length === 1")
    check("Inactive" in page.locator("tr.off").inner_text(), "deactivating marks the person inactive")
    page.select_option("#f-status", "inactive")
    page.wait_for_function("document.querySelectorAll('.adm-table tbody tr').length === 1")
    page.locator("tr.off [data-act='activate']").click()
    page.wait_for_function("document.querySelector('.adm-empty') !== null")
    page.select_option("#f-status", "")
    page.wait_for_function("document.querySelectorAll('tr.off').length === 0 && document.querySelectorAll('.adm-table tbody tr').length === 4")
    check(True, "activating brings them back")

    # ---- passwords: set, and reset (a temporary one, shown once)
    page.locator("tr:has(strong:text-is('ayse')) [data-act='password']").click()
    page.fill('#dlg input[name="password"]', "another-long-pass")
    page.click("#dlg [data-go]")
    page.wait_for_function("!document.querySelector('#dlg').open")
    page.locator("tr:has(strong:text-is('ayse')) [data-act='password']").click()
    page.click("#reset")
    page.click("#dlg [data-go]")
    page.wait_for_selector("#temp")
    check(page.inner_text("#temp") == "Temp-Pass-123456" and "Shown once" in page.inner_text("#dlg"), "a reset shows the temporary password once")
    page.click("#dlg button[value=ok]")
    page.wait_for_function("!document.querySelector('#dlg').open")

    # ---- groups: members
    page.click('[data-tab="groups"]')
    page.locator("tr:has(strong:text-is('Sales team')) [data-act='members']").click()
    page.wait_for_selector("#add-user")
    check("ayse" in page.inner_text(".adm-members"), "the group lists its members")
    page.select_option("#add-user", label="de_rep")
    page.click("#add-btn")
    page.wait_for_function("document.querySelector('.adm-members').innerText.includes('de_rep')")
    page.locator(".adm-members .m:has-text('ayse') [data-rm]").click()
    page.wait_for_function("!document.querySelector('.adm-members').innerText.includes('ayse')")
    check(True, "a person is added to and removed from a group")
    page.click("#dlg button[value=ok]")
    page.wait_for_function("!document.querySelector('#dlg').open")
    check("1" == page.locator("tr:has(strong:text-is('Sales team')) td").nth(1).inner_text(), "the member count follows")

    # ---- delete needs the username typed
    page.click('[data-tab="users"]')
    page.locator("tr:has(strong:text-is('ayse')) [data-act='delete']").click()
    page.fill('#dlg input[name="confirm"]', "nope")
    page.click("#dlg [data-go]")
    page.wait_for_selector("#dlg .err:not([hidden])")
    check("confirm" in page.inner_text("#dlg .err"), "a wrong confirmation is refused")
    page.fill('#dlg input[name="confirm"]', "ayse")
    page.click("#dlg [data-go]")
    page.wait_for_function("!document.querySelector('#dlg').open")
    page.wait_for_function("document.querySelectorAll('.adm-table tbody tr').length === 3")
    check("ayse" not in names(page), "typing the username deletes the person")
    check(not [x for x in page.problems if "pageerror" in x], f"no script errors {page.problems[:2]}")
    ctx.close()

    # ---- Turkish
    ctx, page = open_page(browser, lang="tr")
    page.wait_for_selector(".adm-table")
    check("Kullanıcılar" in page.inner_text(".adm-tabs") and "Yeni kullanıcı" in page.inner_text(".adm-bar"), "the console speaks Turkish on a Turkish page")
    ctx.close()

    # ---- anyone who is not an admin is turned away by the service
    ms.ROLE["role"] = "manager"
    ctx, page = open_page(browser)
    page.wait_for_selector(".adm-empty")
    check("Only an admin" in page.inner_text("#main") and not page.locator(".adm-table").count(), "a manager sees that only an admin can use the page")
    ctx.close()
    ms.ROLE["role"] = "admin"
    browser.close()

if failures:
    print(f"\n{len(failures)} problem(s)")
    sys.exit(1)
print("\nadmin console checks passed")
