"""The panel gallery of docs/dashboards.md: screenshots of each panel type, from generated data (the numbers mean nothing).

  scripts/dashspec build
  uv run --with playwright python -I dashboard/cube/tests/gallery.py            # writes docs/images/dashboards/*.png

Re-run it when a panel's look changes; the images are committed.
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import mock_stack as ms  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[3] / "docs" / "images" / "dashboards"
OUT.mkdir(parents=True, exist_ok=True)
# (file, dashboard, role, selector, width)
SHOTS = [
    ("page.png", "sales-overview", "admin", None, 1280),
    ("filters.png", "sales-overview", "admin", "#filters", 1280),
    ("kpi.png", "sales-overview", "admin", '[data-panel="kpis"]', 1280),
    ("timeseries.png", "sales-overview", "admin", '[data-panel="trend"]', 1280),
    ("line.png", "sales-overview", "admin", '[data-panel="margin"]', 1280),
    ("treemap.png", "sales-overview", "admin", '[data-panel="mix"]', 1280),
    ("bar.png", "sales-overview", "admin", '[data-panel="top"]', 1280),
    ("table.png", "sales-overview", "admin", '[data-panel="lines"]', 1280),
    ("text.png", "envanter-sagligi", "purchasing", '[data-panel="not"]', 1280),
    ("turkish.png", "envanter-sagligi", "purchasing", None, 1100),
    ("pie.png", "sales-drilldown", "admin", '[data-panel="donut"]', 1280),
    ("drill.png", "sales-drilldown", "admin", '[data-panel="trend"]', 1280, lambda page: page.locator('[data-panel="trend"] .hit').nth(1).click()),
    ("phone.png", "regional-sales", "rep", None, 390),
]
ms.start()
ms.FAKE["on"] = True
ms.BENCH["on"] = False
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    for name, dash, role, selector, width, *act in SHOTS:
        ms.ROLE["role"] = role
        ctx = browser.new_context(viewport={"width": width, "height": 900})
        ctx.add_init_script(ms.SEED + 'try { localStorage.setItem("theme", "light"); localStorage.setItem("dataset", "live"); } catch (e) {}')
        page = ctx.new_page()
        page.goto(f"http://localhost:{ms.PORT}/d/{dash}")
        page.wait_for_function("document.querySelector('#live-text')?.textContent.match(/Updated|Güncellendi/)", timeout=30000)
        page.wait_for_timeout(1200)
        if act:
            act[0](page)
            page.wait_for_timeout(1500)
        page.evaluate("document.querySelector('.tip')?.classList.remove('on')")
        if selector:
            page.locator(selector).screenshot(path=str(OUT / name))
        else:
            page.screenshot(path=str(OUT / name), full_page=True)
        ctx.close()
    browser.close()
for f in sorted(OUT.glob("*.png")):
    print(f"{f.name:16s} {f.stat().st_size // 1024:4d} KB")
