"""Every panel renders, from generated data, without a console error; and (for a refactor) the page renders exactly as before.

  uv run --with playwright python -I dashboard/cube/tests/render.py                  # smoke: panels filled, no errors
  uv run --with playwright python -I dashboard/cube/tests/render.py --dump a.html     # also write the normalised page
  uv run --with playwright python -I dashboard/cube/tests/render.py --compare a.html  # fail unless the page equals that dump

The mock Cube (mock_stack.FAKE) answers every query with deterministic rows, so two renders of the same code are identical and a
render of refactored code can be compared with one of the original (the dump drops timers and the tooltip ids, which are a counter).
"""
import difflib
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import mock_stack as ms  # noqa: E402

ARGS = sys.argv[1:]
DUMP = ARGS[ARGS.index("--dump") + 1] if "--dump" in ARGS else None
COMPARE = ARGS[ARGS.index("--compare") + 1] if "--compare" in ARGS else None
PANELS = ["kpis", "trend", "feed", "mix", "products", "territories"]
failures = []


def check(ok, msg):
    print(("PASS  " if ok else "FAIL  ") + msg)
    if not ok:
        failures.append(msg)


def normalise(html):
    html = re.sub(r'<span class="timer[^"]*"[^>]*>.*?</span>', "", html, flags=re.S)       # elapsed-time chips
    html = re.sub(r"([Uu]pdated) \d\d:\d\d:\d\d", r"\1 T", html)                           # the status line's clock
    html = re.sub(r'data-tip="\d+"', 'data-tip="T"', html)                            # a counter
    html = re.sub(r'(id|for|aria-controls|aria-labelledby)="[a-z]+-\d+"', r'\1="X"', html)
    return re.sub(r">\s+<", ">\n<", html)


server = ms.start()
ms.FAKE["on"] = True
ms.BENCH["on"] = False
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 1400})
    ctx.add_init_script(ms.SEED + 'try { localStorage.setItem("theme", "light"); } catch (e) {}')
    page = ctx.new_page()
    problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.goto(f"http://localhost:{ms.PORT}/")
    page.wait_for_selector("#who", timeout=20000)
    page.wait_for_function("!document.querySelector('#kpis').classList.contains('pending')", timeout=20000)
    page.wait_for_timeout(3000)                      # the slowest panels (exact order counts) draw last
    page.wait_for_timeout(500)
    check(not problems, f"no page or console errors ({len(problems)}): {problems[:3]}")
    for panel in PANELS:
        sel = "#kpis" if panel == "kpis" else f'[data-panel="{panel}"]'
        check(len(page.inner_text(sel).strip()) > 30 and not page.eval_on_selector(sel, "n => n.classList.contains('pending')"), f"panel {panel} is drawn")
    check(page.locator("#trend svg").count() > 0 and page.locator("#mix .tile, #mix [data-tip]").count() > 0, "trend chart and treemap tiles are drawn")
    # the table view and the Excel export go through the shared table / xlsx code
    page.click('[data-panel="products"] .tbl-btn, [data-panel="products"] [data-view="table"]') if page.locator('[data-panel="products"] .tbl-btn, [data-panel="products"] [data-view="table"]').count() else None
    with page.expect_download(timeout=10000) as dl:
        page.click('[data-panel="products"] .xls-btn')
    name = dl.value.suggested_filename
    check(name.startswith("adventureworks-") and name.endswith(".xlsx"), f"Excel export downloads a file ({name})")
    size = pathlib.Path(dl.value.path()).stat().st_size
    check(size > 1000 and pathlib.Path(dl.value.path()).read_bytes()[:2] == b"PK", f"the export is a zip ({size} bytes)")
    page.evaluate("document.querySelector('#kpis').scrollIntoView({ block: 'center' })")
    page.locator("#kpis .kpi svg.spark .spark-hit").nth(3).hover()
    check(page.locator("#tip.on").count() == 1 and "Revenue" in page.inner_text("#tip") and "$" in page.inner_text("#tip"), "hovering a mini chart on the sales dashboard shows the month and the value")
    page.mouse.move(5, 5)
    page.evaluate("document.querySelector('#trend').scrollIntoView({ block: 'center' })")
    page.locator("#trend [data-tip]").first.hover()
    page.wait_for_timeout(200)
    check(page.locator("#tip.on").count() == 1 and "Internet" in page.inner_text("#tip"), "hovering a bar shows its tooltip")
    tip = page.inner_html("#tip")
    page.evaluate("document.querySelector('#mix [data-tip]')?.scrollIntoView({ block: 'center' })")
    page.locator("#mix [data-tip]").first.hover()
    page.wait_for_timeout(200)
    tip += page.inner_html("#tip")
    html = normalise(page.inner_html("#app")) + "\n<!-- tooltips -->\n" + normalise(tip)
    if DUMP:
        pathlib.Path(DUMP).write_text(html)
        print(f"wrote {DUMP} ({len(html)} chars)")
    if COMPARE:
        before = pathlib.Path(COMPARE).read_text()
        same = before == html
        check(same, "the page renders exactly as in the dump")
        if not same:
            for line in list(difflib.unified_diff(before.splitlines(), html.splitlines(), "before", "after", lineterm="", n=1))[:40]:
                print("   " + line)
    browser.close()
server.shutdown()
if failures:
    sys.exit(1)
print("\nrender checks passed")
