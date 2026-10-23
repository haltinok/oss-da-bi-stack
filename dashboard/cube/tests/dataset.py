"""The dashboard's dataset switch, against mock services (no stack needed).

  uv run --with playwright python -I dashboard/cube/tests/dataset.py

Serves dashboard/static and dashboard/cube from a small local server that also plays Keycloak's replacement (a
pre-seeded session), the auth service, the actions service and two Cubes, and records which of them each page
asked. Checks: with one dataset offered there is no switch; with two, the switch shows, the default is the live
mart, picking the benchmark reloads the page on the other Cube only (?dataset=250m, remembered), the benchmark is
read-only (no actions service call, a banner says so), and picking live again goes back.
"""
import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[3]
PORT = 19350
hits: dict[str, int] = {}
BENCH = {"on": True}
failures = []


def check(ok, msg):
    print(("PASS  " if ok else "FAIL  ") + msg)
    if not ok:
        failures.append(msg)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(b"")

    def do_POST(self):
        self.do_GET()

    def do_GET(self):
        path = urlparse(self.path).path
        for prefix in ("/cube-live", "/cube-bench", "/actions", "/auth"):
            if path.startswith(prefix):
                hits[prefix] = hits.get(prefix, 0) + 1
        if path == "/auth/token":
            return self._send(json.dumps({"token": "t", "expires_in": 900, "user": "admin", "role": "admin", "territories": ["Canada"]}).encode())
        if path.startswith("/cube-"):
            return self._send(json.dumps({"data": [], "query": {}, "annotation": {"measures": {}, "dimensions": {}, "segments": {}, "timeDimensions": {}}}).encode())
        if path.startswith("/actions"):
            return self._send(json.dumps({"entries": [], "proposals": []}).encode())
        if path == "/cube/config.js":
            ds = '[{ id: "live", label: "Live (simulator)", mart: "mart", cube: window.STACK.cube }'
            if BENCH["on"]:
                ds += f', {{ id: "250m", label: "250M benchmark", mart: "mart_250m", cube: "http://localhost:{PORT}/cube-bench", readOnly: true }}'
            js = (f'window.STACK = {{ keycloak: {{ url: "http://localhost:{PORT}/kc", realm: "spike", clientId: "dashboard" }}, '
                  f'auth: "http://localhost:{PORT}/auth", actions: "http://localhost:{PORT}/actions", cube: "http://localhost:{PORT}/cube-live" }}; '
                  f"window.STACK.datasets = {ds}];")
            return self._send(js.encode(), "application/javascript")
        for base, strip in ((ROOT / "dashboard/cube", "/cube/"), (ROOT / "dashboard/static", "/")):
            if path.startswith(strip):
                rel = path[len(strip):] or "index.html"
                f = base / rel
                if f.is_file():
                    page = f.read_bytes()
                    if rel == "index.html":
                        page = page.replace(b'<script src="app.js"></script>', b'<script src="cube/config.js"></script><script src="cube/boot.js"></script><script type="module" src="cube/cube-source.mjs"></script><script src="app.js"></script>')
                    ctype = "text/html" if rel.endswith(".html") else "text/javascript" if rel.endswith((".js", ".mjs")) else "text/css" if rel.endswith(".css") else "application/octet-stream"
                    return self._send(page, ctype)
        self._send(b"not found", "text/plain", 404)


server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
SEED = 'sessionStorage.setItem("kc", JSON.stringify({access: "a", refresh: "r", expires: Date.now() + 3.6e6}));'


def load(browser, url, wait=3000):
    hits.clear()
    ctx = browser.new_context()
    ctx.add_init_script(SEED)
    page = ctx.new_page()
    page.goto(url)
    page.wait_for_timeout(wait)
    return ctx, page


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    base = f"http://localhost:{PORT}/"

    BENCH["on"] = False
    ctx, page = load(browser, base)
    check(page.locator("#dataset-field").is_hidden(), "one dataset offered: no switch")
    check(page.text_content("#dataset-badge") == "Live (simulator)" and "read" not in (page.get_attribute("#dataset-badge", "class") or ""), "the header names the live dataset")
    check(hits.get("/cube-live", 0) > 0 and not hits.get("/cube-bench"), "reads the live Cube")
    ctx.close()

    BENCH["on"] = True
    ctx, page = load(browser, base)
    check(page.locator("#dataset-field").is_visible() and page.locator("#f-dataset option").count() == 2, "two datasets offered: the switch is shown")
    check(page.input_value("#f-dataset") == "live" and page.inner_text("#mart-name") == "mart", "default is the live mart")
    check(hits.get("/cube-live", 0) > 0 and not hits.get("/cube-bench"), "live: only the live Cube is asked")
    check(hits.get("/actions", 0) > 0, "live: the actions service is used")
    check(page.locator("#dataset-banner").is_hidden(), "live: no benchmark banner")

    hits.clear()
    page.select_option("#f-dataset", "250m")
    page.wait_for_timeout(3500)
    check("dataset=250m" in page.url, f"picking the benchmark reloads on ?dataset=250m ({page.url})")
    check(page.input_value("#f-dataset") == "250m" and page.inner_text("#mart-name") == "mart_250m", "the switch and the mart name follow")
    check(hits.get("/cube-bench", 0) > 0 and not hits.get("/cube-live"), f"benchmark: only the benchmark Cube is asked ({hits})")
    check(not hits.get("/actions"), "benchmark: the actions service is never called")
    check(page.locator("#dataset-banner").is_visible() and "Approve is disabled" in page.inner_text("#dataset-banner") and "postgres_active" in page.inner_text("#dataset-banner"),
          "benchmark: a banner says Approve is disabled and why")
    check(page.text_content("#dataset-badge") == "250M benchmark" and "ro" in (page.get_attribute("#dataset-badge", "class") or "").split(), "the header names the benchmark dataset")
    check(page.locator('[data-panel="proposals"]').is_hidden(), "benchmark: no proposals panel")

    page.reload()                                   # remembered without the URL parameter too
    page.wait_for_timeout(1500)
    page2 = ctx.new_page()
    hits.clear()
    page2.goto(base)
    page2.wait_for_timeout(2500)
    check(page2.input_value("#f-dataset") == "250m" and hits.get("/cube-bench", 0) > 0, "the choice is remembered in this browser")

    hits.clear()
    page2.select_option("#f-dataset", "live")
    page2.wait_for_timeout(3500)
    check(hits.get("/cube-live", 0) > 0 and not hits.get("/cube-bench") and "dataset=" not in page2.url, f"back to live ({page2.url})")
    ctx.close()
    browser.close()

server.shutdown()
print("\nFAILED" if failures else "\nall dataset checks passed")
sys.exit(1 if failures else 0)
