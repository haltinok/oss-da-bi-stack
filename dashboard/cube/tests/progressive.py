"""Progressive rendering + cancellation check (Phase 6). Needs the spike stack up.

  set -a; . ./.env.spike; set +a
  uv run --with playwright python -I dashboard/cube/tests/progressive.py [user] [subcategory]
Applies a subcategory filter as `user` (default admin) and reports when each panel stops being dimmed
and when the Orders tile resolves; then changes the filter again mid-flight and counts cancelled requests.
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

user = sys.argv[1] if len(sys.argv) > 1 else "admin"
t0 = 0.0


def now():
    return f"{time.time() - t0:6.1f}s"


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_page(viewport={"width": 1500, "height": 1300})
    aborted = []
    page.on("requestfailed", lambda r: aborted.append(r.url) if f":{os.environ.get('CUBE_PORT', '4000')}/" in r.url and "ERR_ABORTED" in (r.failure or "") else None)
    page.goto(os.environ.get("DASHBOARD_URL", "http://localhost:8250/"))
    page.wait_for_selector("input#username", timeout=60_000)
    page.fill("input#username", user)
    page.fill("input#password", os.environ["TEST_USER_PASSWORD"])
    page.click("#kc-login")
    page.wait_for_function("document.querySelector('#live-text')?.textContent.includes('Live')", timeout=300_000)
    page.wait_for_function("!document.querySelector('#kpis').classList.contains('pending')", timeout=300_000)
    subs = page.eval_on_selector_all("#f-subcategory option", "o => o.map(x => x.value).filter(Boolean)")
    print(f"signed in as {user}; subcategories: {subs[:3]}...")

    panels = {"kpis": "#kpis", "trend": '[data-panel="trend"]', "feed": '[data-panel="feed"]', "mix": '[data-panel="mix"]',
              "products": '[data-panel="products"]', "territories": '[data-panel="territories"]'}
    page.evaluate("""() => { window.__t = {}; }""")
    t0 = time.time()
    choice = sys.argv[2] if len(sys.argv) > 2 else "Road Bikes"
    page.select_option("#f-subcategory", choice if choice in subs else subs[0])
    seen, orders_done = {}, None
    deadline = time.time() + 600
    while time.time() < deadline:
        for name, sel in panels.items():
            if name not in seen and not page.eval_on_selector(sel, "n => n.classList.contains('pending')"):
                seen[name] = now()
                orders = page.locator("#kpis .kpi").nth(3).inner_text().replace("\n", " ") if name == "kpis" else ""
                print(f"{seen[name]}  {name:12s} drawn {orders}")
        tiles = page.locator("#kpis .kpi").all_inner_texts()
        orders_tile = next((t for t in tiles if t.startswith("Orders")), "")
        if orders_done is None and orders_tile and "…" not in orders_tile and "kpis" in seen:
            orders_done = now()
            print(f"{orders_done}  Orders tile resolved: {orders_tile.replace(chr(10), ' ')}")
        if len(seen) == len(panels) and orders_done:
            break
        page.wait_for_timeout(300)
    print("panels drawn:", ", ".join(f"{k}@{v.strip()}" for k, v in seen.items()), "| orders:", (orders_done or "not within 10 min").strip())

    # cancel: change the filter again while the exact order counts are still running
    aborted.clear()
    page.select_option("#f-subcategory", "")          # clear, then pick another one 1.5 s later
    page.wait_for_timeout(1500)
    opts = page.eval_on_selector_all("#f-subcategory option", "o => o.map(x => x.value).filter(Boolean)")
    page.select_option("#f-subcategory", opts[min(3, len(opts) - 1)])
    page.wait_for_function("!document.querySelector('#kpis').classList.contains('pending')", timeout=300_000)
    print(f"requests cancelled by the filter changes: {len(aborted)}")
    print("error banner visible:", page.is_visible("#error"))
    b.close()
