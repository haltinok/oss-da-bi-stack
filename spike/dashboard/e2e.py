"""Browser end-to-end for the re-pointed dashboard (Phase 6). Needs the spike stack up.

  set -a; . ./.env.spike; set +a
  uv run --with playwright python -I spike/dashboard/e2e.py
Drives the system Chrome: signs in through Keycloak as each test user, waits for the
page to render, checks what each role can and cannot see, applies cross-filters, and
saves screenshots to spike/dashboard/screenshots/.
"""
import os
import pathlib
import re
import sys
import time

from playwright.sync_api import sync_playwright

URL = "http://localhost:8250/"
PASSWORD = os.environ["TEST_USER_PASSWORD"]
OUT = pathlib.Path(__file__).parent / "screenshots"
EXPECT_REGIONS = {
    "admin": 10, "na_manager": 6, "de_rep": 1,
}
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
    for user, n_regions in EXPECT_REGIONS.items():
        print(f"--- {user}")
        ctx = browser.new_context(viewport={"width": 1500, "height": 1300})
        page = ctx.new_page()
        errors, cube_calls, legacy_calls = [], [], []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: (cube_calls if ":4000/" in r.url else legacy_calls if "/api/" in r.url else []).append(r))
        page.goto(URL)
        page.wait_for_selector("input#username", timeout=60_000)
        page.fill("input#username", user)
        page.fill("input#password", PASSWORD)
        t0 = time.time()
        page.click("#kc-login")
        wait_live(page)
        first_render = time.time() - t0
        check(True, f"signed in and rendered in {first_render:.1f}s")

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
            page.screenshot(path=str(OUT / "admin-filtered.png"), full_page=True)

        bad = [e for e in errors if "favicon" not in e]
        check(not bad, f"no console errors {bad[:2]}")
        ctx.close()
    browser.close()

print("\nFAILED" if failures else "\nall e2e checks passed")
sys.exit(1 if failures else 0)
