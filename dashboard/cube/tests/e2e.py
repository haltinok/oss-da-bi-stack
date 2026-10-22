"""Browser end-to-end for the re-pointed dashboard (Phase 6). Needs the stack up (`starrocks` profile, or the spike stack).

  set -a; . ./.env; set +a
  DASHBOARD_URL=http://localhost:8250/ CUBE_PORT=4000 \
  uv run --with playwright python -I dashboard/cube/tests/e2e.py
Drives the system Chrome: signs in through Keycloak as each test user, waits for the
page to render, checks what each role can and cannot see, applies cross-filters, and
saves screenshots to $SCREENSHOT_DIR (default: dashboard/cube/tests/screenshots/, git-ignored).
"""
import os
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

URL = os.environ.get("DASHBOARD_URL", "http://localhost:8250/")
CUBE_HOST = f":{os.environ.get('CUBE_PORT', '4000')}/"
PASSWORD = os.environ["TEST_USER_PASSWORD"]
OUT = pathlib.Path(os.environ.get("SCREENSHOT_DIR", pathlib.Path(__file__).parent / "screenshots"))
OUT.mkdir(parents=True, exist_ok=True)
EXPECT_REGIONS = {
    "admin": 10, "na_manager": 6, "de_rep": 1,
}
# Inventory views per role: (reorder list, overstock list, KPI tiles). purchasing and marketing get no sales view at all.
INVENTORY = {"admin": (True, True, 3), "na_manager": (False, False, 0), "de_rep": (False, False, 0),
             "buyer": (True, False, 2), "marketer": (False, True, 1)}
INV_ONLY = ("buyer", "marketer")
failures = []


def check(ok, msg):
    print(("PASS  " if ok else "FAIL  ") + msg)
    if not ok:
        failures.append(msg)


def wait_live(page, timeout=300_000):
    """Live, and every panel drawn (panels render one by one as their queries return)."""
    page.wait_for_function("document.querySelector('#live-text')?.textContent.includes('Live')", timeout=timeout)
    page.wait_for_function("document.querySelectorAll('.pending').length === 0", timeout=timeout)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    for user, n_regions in {**EXPECT_REGIONS, "buyer": 0, "marketer": 0}.items():
        print(f"--- {user}")
        ctx = browser.new_context(viewport={"width": 1500, "height": 1300})
        page = ctx.new_page()
        errors, cube_calls, legacy_calls = [], [], []
        page.on("console", lambda m, errors=errors: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
        page.on("request", lambda r, cube=cube_calls, legacy=legacy_calls: (cube if CUBE_HOST in r.url else legacy if "/api/" in r.url else []).append(r))
        page.goto(URL)
        page.wait_for_selector("input#username", timeout=60_000)
        page.fill("input#username", user)
        page.fill("input#password", PASSWORD)
        t0 = time.time()
        page.click("#kc-login")
        wait_live(page)
        first_render = time.time() - t0
        check(True, f"signed in and rendered in {first_render:.1f}s")

        reorder, overstock, tiles = INVENTORY[user]
        inv_calls = [r for r in cube_calls if "inventory_health" in r.url + (r.post_data or "")]
        check(page.locator("#inv").is_visible() == (reorder or overstock), f"inventory section {'shown' if reorder or overstock else 'hidden'} for {user}")
        check(page.locator('[data-panel="reorder"]').is_visible() == reorder, f"reorder list {'shown' if reorder else 'hidden'}")
        check(page.locator('[data-panel="overstock"]').is_visible() == overstock, f"overstock list {'shown' if overstock else 'hidden'}")
        check(page.locator("#inv-kpis .kpi").count() == tiles, f"{page.locator('#inv-kpis .kpi').count()} inventory KPI tiles (expected {tiles})")
        check(bool(inv_calls) == bool(reorder or overstock), f"inventory queried only when the role has it ({len(inv_calls)} calls)")
        # Approve controls exist and are inert until something is ticked (nothing is written here)
        if reorder:
            check(page.locator("#reorder-approve").count() == 1 and page.locator("#reorder-approve").is_disabled(), "reorder: Approve button present and disabled until a row is ticked")
        if overstock:
            check(page.locator("#camp-go").count() == 1 and page.locator("#camp-go").is_disabled() and page.locator("#camp-discount").count() == 1,
                  "overstock: campaign controls present and Create disabled until a row is ticked")
        if reorder:
            check(page.locator('[data-panel="reorder"] tbody tr').count() > 0, "reorder list has rows")
            check("Vendor" in page.locator('[data-panel="reorder"]').inner_text(), "reorder list shows the vendor column")
        if overstock:
            check(page.locator('[data-panel="overstock"] tbody tr').count() > 0, "overstock list has rows")
            check("Suggested discount" in page.locator('[data-panel="overstock"]').inner_text(), "overstock list shows suggested discounts")
        if user == "marketer":
            leaked = [r for r in cube_calls if any(m in (r.url + (r.post_data or "")) for m in ("vendor_name", "unit_cost", "suggested_order", "lead_time"))]
            check(not leaked, "marketing page never asks for supplier or order members")
        if user in INV_ONLY:
            sales = [r for r in cube_calls if any(m in (r.url + (r.post_data or "")) for m in ("internet_sales", "reseller_sales", "territories", "customers"))]
            check(not sales and not page.locator("#kpis").is_visible() and not page.locator("nav.filters").is_visible(),
                  f"no sales queries and no sales view for {user} ({len(sales)} sales calls)")
            check(page.locator("#who").count() == 1, "user badge shown")
            page.screenshot(path=str(OUT / f"{user}.png"), full_page=True)
            bad = [e for e in errors if "favicon" not in e]
            check(not bad, f"no console errors {bad[:2]}")
            ctx.close()
            continue

        regions = page.eval_on_selector_all("#f-region option", "o => o.map(x => x.textContent).filter(t => !t.startsWith('All'))")
        check(len(regions) == n_regions, f"region dropdown has {len(regions)} regions (expected {n_regions}): {regions}")
        check(page.locator("#kpis").inner_text().strip() != "", "KPI tiles rendered")
        kpi_text = page.locator("#kpis").inner_text()
        has_profit = "Gross profit" in kpi_text or "Gross margin" in kpi_text
        check(has_profit == (user != "de_rep"), f"profit tiles {'shown' if has_profit else 'hidden'} for {user}")
        territories = page.locator('[data-panel="territories"]').inner_text()
        shown = [r for r in ("Australia", "Canada", "Central", "France", "Germany", "Northeast", "Northwest", "Southeast", "Southwest", "United Kingdom") if r in territories]
        check(len(shown) == n_regions, f"territory panel lists {len(shown)} regions: {shown}")
        check(page.locator("#who").count() == 1, "user badge shown")
        check(not legacy_calls, f"no calls to the legacy /api/ ({len(legacy_calls)})")
        check(cube_calls and all(r.headers.get("authorization") for r in cube_calls if r.method == "POST"), "every Cube call carries a bearer token")
        page.screenshot(path=str(OUT / f"{user}.png"), full_page=True)

        if user == "admin":
            # cross-filtering: fiscal year, then a category, both re-query Cube
            page.select_option("#f-fy", index=3)
            wait_live(page)
            page.wait_for_timeout(1500)
            fy = page.input_value("#f-fy")
            cat_opts = page.eval_on_selector_all("#f-category option", "o => o.map(x => x.value).filter(Boolean)")
            page.select_option("#f-category", cat_opts[0])
            wait_live(page)
            check(bool(fy) and "No orders match" not in page.locator("#main").inner_text(), f"FY {fy} + {cat_opts[0]} filters render data")
            check(len([r for r in cube_calls if "inventory_health" in r.url + (r.post_data or "")]) == len(inv_calls),
                  "changing filters does not re-query inventory")
            page.screenshot(path=str(OUT / "admin-filtered.png"), full_page=True)

        bad = [e for e in errors if "favicon" not in e]
        check(not bad, f"no console errors {bad[:2]}")
        ctx.close()
    browser.close()

print("\nFAILED" if failures else "\nall e2e checks passed")
sys.exit(1 if failures else 0)
