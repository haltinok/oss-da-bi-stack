"""The start page (/home/) in a real Chrome against the mock stack: the launcher, what was opened lately, what is shared, search, and who sees the admin link.

  uv run --with playwright --with pyyaml --with jsonschema python -I dashboard/cube/tests/home.py
"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import mock_stack as ms  # noqa: E402

BASE = f"http://localhost:{ms.PORT}"
failures = []
INDEX = json.loads((pathlib.Path(__file__).resolve().parents[3] / "dashboards" / "build" / "index.json").read_text())


def check(ok, msg):
    print(("PASS  " if ok else "FAIL  ") + msg)
    if not ok:
        failures.append(msg)
    return ok


def open_page(browser, path="/home/", lang=None, recent=None):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1400})
    init = ms.SEED + 'try { localStorage.setItem("theme", "light"); ' + (f'localStorage.setItem("dashLang", "{lang}");' if lang else "")
    if recent is not None:
        init += f'if (localStorage.getItem("dashRecent") === null) localStorage.setItem("dashRecent", {json.dumps(json.dumps(recent))});'
    ctx.add_init_script(init + " } catch (e) {}")
    page = ctx.new_page()
    page.problems = []
    page.on("pageerror", lambda e: page.problems.append(f"pageerror: {e}"))
    page.goto(f"{BASE}{path}")
    return ctx, page


def section(page, title):
    return page.locator(f".home-sec:has(h2:has-text('{title}'))")


ms.start()
ms.FAKE["on"] = True
ms.BENCH["on"] = False
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ms.reset_saved()
    ms.ROLE["role"] = "editor"
    ms.USER["name"] = "alice"
    ms.USER["groups"] = []
    mine_id = ms.seed_saved("Alice sales", "regional", owner="alice", role="editor")["id"]
    theirs_id = ms.seed_saved("Bob's report", "shared by bob", owner="bob", role="editor", visibility="everyone")["id"]
    built_id = next(d["id"] for d in INDEX if not d.get("roles") or "editor" in d["roles"])

    # ---- the launcher, the lists, and what was opened lately (a gone dashboard is left out)
    now = 1_700_000_000_000
    recent = [{"kind": "saved", "id": theirs_id, "title": "x", "at": now + 3}, {"kind": "built", "id": built_id, "title": "x", "at": now + 2},
              {"kind": "saved", "id": "no-longer-there", "title": "gone", "at": now + 1}]
    ctx, page = open_page(browser, recent=recent)
    page.wait_for_selector(".home-sec")
    check(page.locator(".home-card.start").count() == 3 and "Describe a new dashboard" in page.inner_text(".home-grid"), "the launcher offers describe, the live dashboard and all dashboards")
    check(page.locator("#admin-link").count() == 0 and "/admin/" not in page.inner_html("#main"), "a manager is not offered the admin console")
    rec = section(page, "Pick up").inner_text()
    check("Bob's report" in rec and "gone" not in rec and rec.index("Bob's report") < len(rec), "'pick up where you left off' lists what is still there (newest first), without what is gone")
    check(page.locator(".home-sec:has(h2:has-text('Pick up')) .home-card").count() == 2, "and has exactly the two that exist")
    check("Bob's report" in section(page, "Shared with you").inner_text() and "by bob" in section(page, "Shared with you").inner_text(), "what others made visible to you is under 'Shared with you'")
    check("Alice sales" in section(page, "Your dashboards").inner_text(), "your own saved dashboards are listed")
    check(section(page, "Samples").locator(".home-card").count() >= 1, "and the sample dashboards your role may open")
    href = section(page, "Your dashboards").locator(".home-card a, a.home-card").first.get_attribute("href")
    check(href == f"/d/s/{mine_id}", f"a saved dashboard links to its own page ({href})")

    # ---- search
    page.fill("#home-q", "bob")
    page.wait_for_selector("#results .home-card")
    check(page.locator("#results .home-card").count() == 1 and "Bob's report" in page.inner_text("#results") and page.locator("#sections").is_hidden(), "searching shows matching dashboards instead of the sections")
    page.fill("#home-q", "zzzzzz")
    check("Nothing matches" in page.inner_text("#results"), "and says when nothing matches")
    page.fill("#home-q", "")
    check(page.locator("#sections").is_visible(), "clearing the search brings the sections back")
    check(not [x for x in page.problems if "pageerror" in x], f"no script errors {page.problems[:1]}")
    ctx.close()

    # ---- opening a dashboard is what fills 'pick up where you left off'
    ctx, page = open_page(browser, path=f"/d/{built_id}")
    page.wait_for_selector("#title", timeout=20000)
    page.wait_for_function("document.querySelector('#title').textContent.length > 0")
    page.goto(f"{BASE}/home/")
    page.wait_for_selector(".home-sec")
    check(page.locator(".home-sec:has(h2:has-text('Pick up')) .home-card").count() == 1, "a dashboard you open shows up under 'Pick up where you left off'")
    page.goto(f"{BASE}/d/")
    page.wait_for_selector("#home-start")
    check(page.get_attribute("#home-start", "href") == "/home/", "the dashboards page links back to the start page")
    ctx.close()

    # ---- an admin is offered the console
    ms.ROLE["role"] = "admin"
    ms.USER["name"] = "admin"
    ctx, page = open_page(browser)
    page.wait_for_selector(".home-sec")
    check(page.locator(".home-card.start:has-text('Admin console')").count() == 1 and page.locator("#admin-link").count() == 1, "an admin gets the admin console in the launcher and the header")
    ctx.close()

    # ---- Turkish
    ms.ROLE["role"] = "editor"
    ms.USER["name"] = "alice"
    ctx, page = open_page(browser, lang="tr")
    page.wait_for_selector(".home-sec")
    check("Yeni bir pano tarif et" in page.inner_text("#main") and "Kaldığınız yerden devam edin" in page.inner_text("#main"), "the start page speaks Turkish on a Turkish page")
    ctx.close()
    ms.ROLE["role"] = "admin"
    ms.USER["name"] = "admin"
    browser.close()

if failures:
    print(f"\n{len(failures)} problem(s)")
    sys.exit(1)
print("\nhome page checks passed")
