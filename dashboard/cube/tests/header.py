"""The page header and the dataset banner, in a real browser, for both datasets, both themes and widths from 1920 down to a phone.

  uv run --with playwright python -I dashboard/cube/tests/header.py [--shots]

Runs against the mock services of mock_stack.py (no stack needed). At 1280 px and wider the header must be ONE row (brand on the
left; dataset select, status, Export, Refresh, theme and user on the right); below that it may wrap, but never overflow the page.
The benchmark dataset's status must be neutral ("Static snapshot · data to ..."), never "Live", and its banner one line with the
explanation behind a Details toggle. --shots keeps the screenshots (dashboard/cube/tests/screenshots/, git-ignored).
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mock_stack as ms  # noqa: E402
from mock_stack import BENCH, PORT, SEED  # noqa: E402

SHOTS = pathlib.Path(__file__).parent / "screenshots"
KEEP = "--shots" in sys.argv
WIDTHS = [1920, 1700, 1600, 1536, 1500, 1440, 1366, 1280, 1100, 1024, 768, 390]
failures = []


def check(ok, msg):
    if not ok:
        failures.append(msg)
        print("FAIL  " + msg)
    return ok


server = ms.start()
BENCH["on"] = True
INJECT = """() => {
  state.data = { latest_orders: [{ order_date: "2021-06-30T10:00:00" }] };
  setLive(true);
  return true;
}"""
GEOMETRY = """() => {
  const r = (s) => { const e = document.querySelector(s); if (!e || e.hidden || e.offsetParent === null) return null; const b = e.getBoundingClientRect(); return { top: b.top, bottom: b.bottom, left: b.left, right: b.right, h: b.height }; };
  return {
    header: r("header.top"), brand: r(".brand"), badge: r("#dataset-badge"), sel: r("#dataset-field"), live: r("#live"), export: r("#export-all"),
    refresh: r("#refresh"), theme: r("#theme"), who: r("#who"), banner: r("#dataset-banner"), title: r(".brand h1"),
    sel2: r("#f-dataset"),
    filters: [...document.querySelectorAll("nav.filters > :not([hidden])")].map((e) => { const b = e.getBoundingClientRect(); return { top: b.top, bottom: b.bottom, left: b.left, right: b.right, w: b.width }; }),
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    liveText: document.querySelector("#live-text").textContent, bannerText: document.querySelector("#dataset-banner").innerText,
  };
}"""

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    for dataset in ("live", "250m"):
        for theme in ("light", "dark"):
            for w in WIDTHS:
                ctx = browser.new_context(viewport={"width": w, "height": 900})
                ctx.add_init_script(SEED + f'try {{ localStorage.setItem("theme", "{theme}"); localStorage.setItem("dataset", "{dataset}"); }} catch (e) {{}}')
                page = ctx.new_page()
                page.goto(f"http://localhost:{PORT}/")
                page.wait_for_selector("#who", timeout=20000)
                page.wait_for_timeout(700)
                page.evaluate(INJECT)
                page.wait_for_timeout(200)
                g = page.evaluate(GEOMETRY)
                tag = f"{dataset} {theme} {w}px"
                tools = [k for k in ("sel", "live", "export", "refresh", "theme", "who") if g[k]]
                check(g["overflow"] <= 0, f"{tag}: the page scrolls sideways by {g['overflow']}px")
                check(all(g[k]["right"] <= w + 0.5 and g[k]["left"] >= -0.5 for k in tools + ["brand"]), f"{tag}: something sticks out of the viewport")
                if w >= 1280:
                    centers = [(g[k]["top"] + g[k]["bottom"]) / 2 for k in tools]
                    check(max(centers) - min(centers) <= 14, f"{tag}: the header is not one row (tool centres differ by {max(centers) - min(centers):.0f}px)")
                    check(g["header"]["h"] <= 80, f"{tag}: the header is {g['header']['h']:.0f}px tall")
                    check(g["brand"]["right"] < g["live"]["left"] - 8, f"{tag}: the brand runs into the status")
                    # the controls share one centre line (and it is the title's), and are the same height
                    heights = [g[k]["h"] for k in ("live", "export", "refresh", "theme") + (("sel2",) if g["sel2"] else ())]
                    check(max(heights) - min(heights) <= 1.5, f"{tag}: control heights differ: {[round(h) for h in heights]}")
                    check(max(centers) - min(centers) <= 2, f"{tag}: controls are not on one centre line ({max(centers) - min(centers):.1f}px apart)")
                    tcenter = (g["title"]["top"] + g["title"]["bottom"]) / 2
                    check(abs(tcenter - centers[0]) <= 4, f"{tag}: the tools are {abs(tcenter - centers[0]):.0f}px off the title's line")
                    # the six filters sit on ONE row (no orphan on a second line)
                    bottoms = [f["bottom"] for f in g["filters"]]          # bottoms: a label above a select makes those taller than the channel buttons
                    check(max(bottoms) - min(bottoms) <= 3 and all(f["right"] <= w for f in g["filters"]), f"{tag}: the filters wrap onto a second line (bottoms {sorted(set(round(x) for x in bottoms))})")
                if dataset == "live":
                    check(g["liveText"].startswith("Live · updated"), f"{tag}: status says {g['liveText']!r}")
                    check(g["banner"] is None and g["sel"] is not None, f"{tag}: no banner, switch shown")
                else:
                    check("Live" not in g["liveText"] and "Static snapshot" in g["liveText"] and "Jun 30, 2021" in g["liveText"], f"{tag}: status says {g['liveText']!r}")
                    check(g["banner"] is not None and "Approve is available in Live" in g["bannerText"], f"{tag}: banner says {g['bannerText'][:70]!r}")
                    if w >= 1280:
                        check(g["banner"]["h"] <= 44, f"{tag}: the banner is {g['banner']['h']:.0f}px tall (one line expected)")
                    check("postgres_active" not in g["bannerText"], f"{tag}: the full explanation shows before Details is opened")
                if w in (1920, 1536, 1280, 390) or KEEP:
                    SHOTS.mkdir(exist_ok=True)
                    page.screenshot(path=str(SHOTS / f"header-{dataset}-{theme}-{w}.png"), clip={"x": 0, "y": 0, "width": w, "height": 330})
                if dataset == "250m" and w == 1440 and theme == "light":
                    page.click("#dataset-banner-toggle")
                    page.wait_for_timeout(150)
                    full = page.evaluate("() => document.querySelector('#dataset-banner').innerText")
                    check("postgres_active" in full and "no ERP" in full, "250m: Details opens the full explanation")
                    check(page.get_attribute("#dataset-banner-toggle", "aria-expanded") == "true", "250m: the toggle reports expanded")
                    page.click("#dataset-banner-toggle")
                    check("postgres_active" not in page.evaluate("() => document.querySelector('#dataset-banner').innerText"), "250m: Details closes again")
                ctx.close()
    browser.close()

server.shutdown()
print(f"\n{len(failures)} problem(s)" if failures else "\nheader layout ok: both datasets, both themes, 1920 down to 390 px")
sys.exit(1 if failures else 0)
