"""A small local server that plays every service the dashboard talks to (no stack needed), shared by the browser tests.

It serves dashboard/static and dashboard/cube, generates /cube/config.js (one or two datasets), and answers the auth service, the
actions service and two Cubes with empty data while counting what each page asked (`hits`).
"""
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = pathlib.Path(__file__).resolve().parents[3]
PORT = 19350
hits: dict[str, int] = {}
BENCH = {"on": True}
ROLE = {"role": "admin"}  # what the mock auth service says the signed-in user is
FAIL = {"members": set(), "message": "Profit and margin are not available for your role"}   # queries naming these members answer 403
FAKE = {"on": False}      # True: the Cube mocks answer every query with generated rows instead of none (see fake_rows)

POOLS = {
    "fiscal_year": [2020, 2021], "calendar_year": [2020, 2021], "month_name": ["June", "July"],
    "category": ["Bikes", "Components", "Clothing", "Accessories"],
    "subcategory": ["Road Bikes", "Mountain Bikes", "Helmets", "Jerseys"],
    "name": ["Road-150 Red", "Mountain-200 Black", "Sport-100 Helmet", "Long-Sleeve Logo Jersey", "HL Road Frame"],
    "group_name": ["North America", "Europe"], "region": ["Canada", "Germany", "France"], "country": ["Canada", "Germany", "France"],
    "vendor_name": ["Proseware", "Litware", "Fabrikam"], "on_hand": [12, 480], "on_order": [0, 60], "days_of_cover": [4, 210], "suggested_order_qty": [100, 40],
    "suggested_order_value": [4200, 900], "excess_units": [30, 0], "excess_value": [1500, 80], "suggested_discount_pct": [10, 30],
    "order_date": ["2021-06-30T10:00:00.000", "2021-06-29T09:30:00.000"], "order_number": ["SO1", "SO2", "SO3", "SO4"], "order_status": [5], "status": ["stockout", "reorder_now", "overstock"],
}
MONTHS = [f"{2020 + (6 + i) // 12}-{(6 + i) % 12 + 1:02d}-01T00:00:00.000" for i in range(12)]     # Jul 2020 .. Jun 2021


def fake_rows(query):
    """Deterministic rows for any Cube query: every dimension takes values from POOLS, time dimensions take the months of one
    fiscal year, every measure a number derived from its name and the row index. The rows are not meaningful; the same query always
    gets the same rows, so a page rendered twice is identical (which is what the render test compares)."""
    axes = []
    for d in query.get("dimensions", []):
        axes.append((d, POOLS.get(d.partition(".")[2], ["a", "b"])))
    for t in query.get("timeDimensions", []):
        if t.get("granularity"):
            axes.append((f"{t['dimension']}.{t['granularity']}", MONTHS if t["granularity"] == "month" else MONTHS[:1]))
    rows = [{}]
    for key, values in axes:
        rows = [{**r, key: v} for r in rows for v in values][:80]
    for i, r in enumerate(rows):
        for m in query.get("measures", []):
            h = (sum(map(ord, m)) * 31 + i * 17) % 997
            r[m] = str(round(h * (1.5 if m.endswith(("revenue", "profit")) else 1), 2) if "pct" not in m else 20 + h % 30)
        if not axes:
            break
    return rows[: 1 if not axes else 80]
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
        if path == "/_seed":      # open this once in a normal browser: it fakes the sign-in session, then goes to ?to=
            to = parse_qs(urlparse(self.path).query).get("to", ["/"])[0]
            page = ('<!doctype html><script>sessionStorage.setItem("kc", JSON.stringify({access: "a", refresh: "r", expires: Date.now() + 3.6e6}));'
                    f'location.replace({json.dumps(to)});</script>')
            return self._send(page.encode(), "text/html")
        if path == "/auth/token":
            return self._send(json.dumps({"token": "t", "expires_in": 900, "user": "admin", "role": ROLE["role"], "territories": ["Canada"]}).encode())
        if path.startswith("/cube-"):
            query = {}
            if FAKE["on"]:
                if self.command == "POST":
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or "{}")
                else:
                    body = json.loads(parse_qs(urlparse(self.path).query).get("query", ["{}"])[0])
                query = body.get("query", body)
            ann = {"measures": {}, "dimensions": {}, "segments": {}, "timeDimensions": {}}
            queries = query if isinstance(query, list) else [query]
            if FAIL["members"] and any(m in FAIL["members"] for q in queries for m in q.get("measures", [])):
                return self._send(json.dumps({"error": FAIL["message"]}).encode(), status=403)
            results = [{"query": q, "data": fake_rows(q) if FAKE["on"] else [], "annotation": ann} for q in queries]
            # what Cube answers a queryType=multi request with (the client always asks that way)
            return self._send(json.dumps({"queryType": "regularQuery", "results": results, "pivotQuery": {**queries[0], "queryType": "regularQuery"}}).encode())
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
        if path == "/d" or path.startswith("/d/"):          # the renderer page, for /d/ and /d/<id>
            path = "/d.html"
        for base, strip in ((ROOT / "dashboards/build", "/dashboards/"), (ROOT / "dashboard/cube", "/cube/"), (ROOT / "dashboard/static", "/")):
            if path.startswith(strip):
                rel = path[len(strip):] or "index.html"
                f = base / rel
                if f.is_file():
                    page = f.read_bytes()
                    if rel == "index.html" and "demo=1" in self.path:
                        # no data behind the mock: put the status line in the state a working page shows (until the next poll)
                        page = page.replace(b"</body>", b"<script>addEventListener('load', () => setTimeout(() => { if (window.__app) { window.__app.state.data = { latest_orders: [{ order_date: '2021-06-30T10:00:00' }] }; window.__app.setLive(true); const e = document.querySelector('#error'); if (e) e.hidden = true; } }, 1800));</script></body>")
                    if rel == "index.html":
                        page = page.replace(b'<script type="module" src="app.js"></script>', b'<script src="cube/config.js"></script><script src="cube/boot.js"></script><script type="module" src="cube/cube-source.mjs"></script><script type="module" src="app.js"></script>')
                    ctype = "text/html" if rel.endswith(".html") else "text/javascript" if rel.endswith((".js", ".mjs")) else "text/css" if rel.endswith(".css") else "application/json" if rel.endswith(".json") else "application/octet-stream"
                    return self._send(page, ctype)
        self._send(b"not found", "text/plain", 404)



def start(port=PORT):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


SEED = 'sessionStorage.setItem("kc", JSON.stringify({access: "a", refresh: "r", expires: Date.now() + 3.6e6}));'


if __name__ == "__main__":
    import sys
    port = int(next((a for a in sys.argv[1:] if a.isdigit()), PORT))
    BENCH["on"] = "--single" not in sys.argv
    start(port)
    base = f"http://localhost:{port}/_seed?to="
    print("Mock dashboard (no data behind it: the header, banner and filters are real, the charts are empty). Open in your browser:")
    print(f"  live            {base}%2F%3Fdemo%3D1")
    if BENCH["on"]:
        print(f"  250M benchmark  {base}%2F%3Fdataset%3D250m%26demo%3D1")
    print("Ctrl-C to stop. The status line is put into its normal state a moment after load and flips to 'Stale' at the next 30 s poll.")
    threading.Event().wait()
