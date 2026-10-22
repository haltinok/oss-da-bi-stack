"""The Latest orders panel ignores every filter: changing one must not re-query or dim it.

  set -a; . ./.env; set +a
  DASHBOARD_URL=http://localhost:18250/ uv run --with playwright python -I dashboard/cube/tests/feed_static.py
"""
import os
import sys

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_page(viewport={"width": 1500, "height": 1300})
    feed_queries = []
    # the feed is the only query that reads order_status
    page.on("request", lambda r: feed_queries.append(r.url[:150]) if "order_status" in (r.url + (r.post_data or "")) else None)
    page.goto(os.environ.get("DASHBOARD_URL", "http://localhost:8250/"))
    page.wait_for_selector("input#username", timeout=60_000)
    page.fill("input#username", "admin")
    page.fill("input#password", os.environ["TEST_USER_PASSWORD"])
    page.click("#kc-login")
    page.wait_for_function("document.querySelector('#live-text')?.textContent.includes('Live')", timeout=300_000)
    page.wait_for_function("!document.querySelector('#kpis').classList.contains('pending')", timeout=300_000)
    page.wait_for_function("document.querySelector('.timer[data-key=latest_orders]')?.classList.contains('done')", timeout=300_000)
    first = len(feed_queries)
    rows_before = page.inner_text('[data-panel="feed"]')
    dimmed = []
    page.expose_function("noteDim", lambda: dimmed.append(1))
    page.evaluate("""new MutationObserver(() => { if (document.querySelector('[data-panel="feed"]').classList.contains('pending')) noteDim(); })
        .observe(document.querySelector('[data-panel="feed"]'), { attributes: true, attributeFilter: ['class'] })""")
    group = page.eval_on_selector_all("#f-group option", "o => o.map(x => x.value).filter(Boolean)")[0]
    page.select_option("#f-group", group)
    page.wait_for_function("!document.querySelector('#kpis').classList.contains('pending')", timeout=300_000)
    page.wait_for_timeout(35_000)  # covers one background poll: with no new orders it must not re-query the feed
    ok = len(feed_queries) == first and not dimmed and page.inner_text('[data-panel="feed"]') == rows_before
    print(f"feed queries on load: {first}; after filter: {len(feed_queries) - first}; dimmed: {len(dimmed)}; unchanged: {ok}")
    print(feed_queries[first:][:2])
    b.close()
    sys.exit(0 if ok else 1)
