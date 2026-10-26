"""Render a dashboard (dashboards/build/<id>.json) from generated data and save screenshots: what the authoring agent looks at.

  scripts/dashspec build                      # first: compile the YAML
  uv run --with playwright python -I dashboard/cube/tests/shot.py <id> [--role rep] [--theme dark] [--width 1440 --width 390] [--dataset live|250m]

No stack needed: the mock Cube answers every query with deterministic rows, so the numbers mean nothing; layout, labels, formats, clicks
and error messages are real. Prints console errors and a panel-by-panel summary, and the PNG paths (dashboard/cube/tests/screenshots/).
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import mock_stack as ms  # noqa: E402

ARGS = sys.argv[1:]
if not ARGS or ARGS[0].startswith("--"):
    sys.exit(__doc__)


def option(name, default=None, many=False):
    vals = [ARGS[i + 1] for i, a in enumerate(ARGS) if a == name and i + 1 < len(ARGS)]
    return vals if many else (vals[0] if vals else default)


dash = ARGS[0]
role, theme, dataset = option("--role", "admin"), option("--theme", "light"), option("--dataset", "live")
widths = [int(w) for w in option("--width", many=True)] or [1440]
out = pathlib.Path(__file__).parent / "screenshots"
out.mkdir(exist_ok=True)
ms.start()
ms.FAKE["on"] = True
ms.BENCH["on"] = dataset == "250m"
ms.ROLE["role"] = role
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    for w in widths:
        ctx = browser.new_context(viewport={"width": w, "height": 1400})
        ctx.add_init_script(ms.SEED + f'try {{ localStorage.setItem("theme", "{theme}"); localStorage.setItem("dataset", "{dataset}"); }} catch (e) {{}}')
        page = ctx.new_page()
        problems = []
        page.on("pageerror", lambda e, found=problems: found.append(f"pageerror: {e}"))
        page.on("console", lambda m, found=problems: found.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        page.goto(f"http://localhost:{ms.PORT}/d/{dash}")
        page.wait_for_function("document.querySelector('#live-text')?.textContent.match(/Updated|Güncellendi|Stale|Eski/) || !document.querySelector('#error').hidden", timeout=30000)
        page.wait_for_timeout(1500)
        if page.is_visible("#error"):
            print(f"error banner: {page.inner_text('#error')}")
        print(f"--- {dash} as {role}, {theme}, {w}px: {page.title()!r}")
        for n in page.query_selector_all("[data-panel]"):
            err = n.query_selector(".panel-error")
            print(f"  {n.get_attribute('data-panel'):16s} {'ERROR: ' + err.inner_text() if err else 'ok, ' + str(len(n.inner_text())) + ' chars'}")
        over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        if over > 0:
            problems.append(f"the page scrolls sideways by {over}px")
        path = out / f"{dash}-{role}-{theme}-{w}.png"
        page.screenshot(path=str(path), full_page=True)
        print(f"  screenshot: {path}")
        print(f"  problems: {problems or 'none'}")
        ctx.close()
    browser.close()
