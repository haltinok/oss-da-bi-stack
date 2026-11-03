"""Screenshots of the pages around the dashboards (the start page, the dashboards list with folders, the admin console, the SQL lab), for the README: docs/images/pages/*.png.
Generated against the mock stack, so the people, numbers and names are made up.

  uv run --with playwright --with pyyaml --with jsonschema python -I dashboard/cube/tests/pages_gallery.py

Re-run it when a page's look changes; the images are committed.
"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import mock_stack as ms  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "images" / "pages"
OUT.mkdir(parents=True, exist_ok=True)
BASE = f"http://localhost:{ms.PORT}"
INDEX = json.loads((ROOT / "dashboards" / "build" / "index.json").read_text())


def open_page(browser, path, recent=None, width=1280, height=800):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    init = ms.SEED + 'try { localStorage.setItem("theme", "light"); localStorage.setItem("dashLang", "en");'
    if recent is not None:
        init += f'if (localStorage.getItem("dashRecent") === null) localStorage.setItem("dashRecent", {json.dumps(json.dumps(recent))});'
    ctx.add_init_script(init + " } catch (e) {}")
    page = ctx.new_page()
    page.on("dialog", lambda d: d.accept())
    page.goto(f"{BASE}{path}")
    return ctx, page


def shot(page, name, selector=None):
    page.wait_for_timeout(400)
    (page.locator(selector) if selector else page).screenshot(path=str(OUT / name))
    print("wrote", name)


ms.start()
ms.FAKE["on"] = True
ms.BENCH["on"] = False
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)

    # ---- the start page and the dashboards list with folders, for a manager with the lab
    ms.reset_saved()
    ms.LAB.pop("lab_store", None)
    ms.ROLE["role"], ms.USER["name"], ms.USER["groups"], ms.LAB["on"] = "editor", "ayse", [], True
    mine = ms.seed_saved("Regional sales, last quarter", "North America and Europe", owner="ayse", role="editor")["id"]
    ms.seed_saved("Stock cover by vendor", "what to reorder", owner="ayse", role="editor")
    theirs = ms.seed_saved("Weekly revenue review", "shared by Mehmet", owner="mehmet", role="editor", visibility="everyone")["id"]
    built = [d["id"] for d in INDEX if not d.get("roles") or "editor" in d["roles"]][:2]
    now = 1_700_000_000_000
    recent = [{"kind": "saved", "id": theirs, "title": "x", "at": now + 3}, {"kind": "saved", "id": mine, "title": "x", "at": now + 2}] + [{"kind": "built", "id": b, "title": "x", "at": now + 1} for b in built]
    ctx, page = open_page(browser, "/home/", recent=recent)
    page.wait_for_selector(".home-sec")
    shot(page, "home.png")
    ctx.close()

    ctx, page = open_page(browser, "/d/")
    page.wait_for_selector(".lsec-mine .saved")
    page.evaluate("""async (id) => {
      const b = window.STACK.builder, h = { "Content-Type": "application/json", Authorization: "Bearer x" };
      const f = await (await fetch(b + "/folders", { method: "POST", headers: h, body: JSON.stringify({ name: "Quarterly reviews" }) })).json();
      await fetch(b + "/saved/" + id, { method: "PUT", headers: h, body: JSON.stringify({ folder_id: f.id, shares: [{ type: "group", principal: "Finance", permission: "view" }, { type: "user", principal: "mehmet", permission: "edit" }] }) });
    }""", mine)
    page.reload()
    page.wait_for_selector(".folder-h")
    page.evaluate("document.querySelector('#builder-host') && (document.querySelector('#builder-host').hidden = true)")
    shot(page, "folders.png", "#main")
    page.click('.saved [data-act="share"]')
    page.wait_for_selector("#sh-name")
    shot(page, "share.png", "#share-dlg")
    ctx.close()

    # ---- the admin console as an admin
    ms.ROLE["role"], ms.USER["name"] = "admin", "admin"
    ms.reset_admin()
    for name, role in (("ayse", "editor"), ("mehmet", "editor"), ("buyer", "editor"), ("marketer", "editor"), ("zeynep", "editor")):
        ms._add_user(name, role)
    ms.ADMIN["users"][next(i for i, u in ms.ADMIN["users"].items() if u["username"] == "zeynep")]["enabled"] = False
    ms.ADMIN["n"] += 1
    ms.ADMIN["groups"]["g1"] = {"name": "Finance"}
    ms.ADMIN["groups"]["g2"] = {"name": "EU sales"}
    for u in ms.ADMIN["users"].values():
        if u["username"] in ("ayse", "mehmet"):
            u["groups"] = ["g1"]
        if u["username"] == "de_rep":
            u["groups"] = ["g2"]
    ms.ADMIN["rules"].update({("user", "de_rep"): ["Germany"], ("group", "EU sales"): ["France", "Germany"], ("user", "na_manager"): ["Canada", "United States"]})
    ms.ADMIN["datasets"].update({
        "sales": {"id": "sales", "name": "Sales facts", "description": "Revenue and orders", "cubes": ["internet_sales", "reseller_sales", "products", "dates", "territories"],
                  "grants": [{"type": "role", "principal": "editor", "permission": "lab"}, {"type": "group", "principal": "Finance", "permission": "view"}]},
        "inventory": {"id": "inventory", "name": "Inventory", "description": "Stock and reorder", "cubes": ["inventory_health", "offer_performance"], "grants": [{"type": "role", "principal": "editor", "permission": "view"}]}})
    ctx, page = open_page(browser, "/admin/")
    page.wait_for_selector(".adm-table")
    shot(page, "admin-users.png", "#app")
    page.click('[data-tab="rules"]')
    page.wait_for_selector("#pv-user option[value='de_rep']", state="attached")
    page.select_option("#pv-user", "de_rep")
    page.click("#pv-go")
    page.wait_for_selector("#pv-out .adm-chip")
    shot(page, "admin-rules.png", "#app")
    page.click('[data-tab="datasets"]')
    page.wait_for_selector("tr[data-id='sales']")
    shot(page, "admin-datasets.png", "#app")
    ctx.close()

    # ---- the SQL lab
    ms.ROLE["role"], ms.USER["name"], ms.USER["groups"] = "editor", "ayse", []
    ms.LAB["on"] = True
    ctx, page = open_page(browser, "/lab/", height=860)
    page.wait_for_selector("#sql")
    page.select_option("#samples", "0")
    page.click("#run")
    page.wait_for_selector("#result table")
    page.locator("#schema summary", has_text="internet_sales").click()
    shot(page, "lab.png", "#app")
    ctx.close()
    ms.ROLE["role"], ms.USER["name"], ms.LAB["on"] = "admin", "admin", False
    browser.close()
