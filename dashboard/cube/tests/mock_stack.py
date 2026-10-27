"""A small local server that plays every service the dashboard talks to (no stack needed), shared by the browser tests.

It serves dashboard/static and dashboard/cube, generates /cube/config.js (one or two datasets), and answers the auth service, the
actions service and two Cubes with empty data while counting what each page asked (`hits`).
"""
import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = pathlib.Path(__file__).resolve().parents[3]
PORT = 19350
hits: dict[str, int] = {}
BENCH = {"on": True}
USER = {"name": "admin"}     # who the mock auth service says is signed in (the owner of what they save)
ROLE = {"role": "admin"}  # what the mock auth service says the signed-in user is
FAIL = {"members": set(), "message": "Profit and margin are not available for your role"}   # queries naming these members answer 403
BUILDER = {"limit": False, "saving": True}   # True: /builder/build answers 429, as the service does when a user has built too often
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
MONTHS = [f"{2020 + (6 + i) // 12}-{(6 + i) % 12 + 1:02d}-01T00:00:00.000" for i in range(12)]     # Jul 2020 .. Jun 2021 (kept for older tests)


def buckets(granularity, date_range=None):
    """Time buckets of one granularity inside a date range (default: the fiscal year Jul 2020 - Jun 2021; years: 2019-2021), as Cube writes them."""
    import datetime as dt
    a, b = ([dt.date.fromisoformat(x[:10]) for x in date_range] if date_range else [dt.date(2019 if granularity == "year" else 2020, 1 if granularity == "year" else 7, 1),
                                                                                    dt.date(2021, 12 if granularity == "year" else 6, 31 if granularity == "year" else 30)])
    out, d = [], a
    while d <= b and len(out) < 62:
        if granularity == "year":
            d = dt.date(d.year, 1, 1)
            nxt = dt.date(d.year + 1, 1, 1)
        elif granularity == "quarter":
            d = dt.date(d.year, (d.month - 1) // 3 * 3 + 1, 1)
            nxt = dt.date(d.year + (d.month + 2) // 12, (d.month + 2) % 12 + 1, 1)
        elif granularity == "month":
            d = dt.date(d.year, d.month, 1)
            nxt = dt.date(d.year + d.month // 12, d.month % 12 + 1, 1)
        else:
            nxt = d + dt.timedelta(days=1)
        out.append(f"{d.isoformat()}T00:00:00.000")
        d = nxt
    return out or [f"{a.isoformat()}T00:00:00.000"]


def fake_rows(query):
    """Deterministic rows for any Cube query: every dimension takes values from POOLS, time dimensions take the months of one
    fiscal year, every measure a number derived from its name and the row index. The rows are not meaningful; the same query always
    gets the same rows, so a page rendered twice is identical (which is what the render test compares)."""
    axes = []
    for d in query.get("dimensions", []):
        axes.append((d, POOLS.get(d.partition(".")[2], ["a", "b"])))
    for t in query.get("timeDimensions", []):
        if t.get("granularity"):
            axes.append((f"{t['dimension']}.{t['granularity']}", buckets(t["granularity"], t.get("dateRange"))))
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
_builder_cache = {}


def builder_answer(path, body, method="GET", query=None):
    """The builder service without Keycloak: the real loop, validator and rule-based stand-in (builder/), for the role the mock signs in as."""
    if not _builder_cache:
        for extra in (str(ROOT), str(ROOT / "dashboards")):
            if extra not in sys.path:
                sys.path.insert(0, extra)
        from builder import core
        from builder.standin import StandInClient
        from dashspec import catalog as cat
        from dashspec.semantic import catalog_json
        _builder_cache.update(core=core, standin=StandInClient, catalog=cat.from_model(ROOT / "cube" / "model"), catalog_json=catalog_json)
    c, role = _builder_cache, ROLE["role"]
    if path == "/info":
        return 200, {"mode": "standin", "model": "rule-based stand-in", "role": role, "user": "admin", "rate_limit_per_hour": 20, "examples": c["core"].examples_for(role, (query or {}).get("lang", ["en"])[0]),
                     "saving": BUILDER["saving"], "builds_left": 20, "note": "A rule-based stand-in answers."}
    if path == "/catalog":
        return 200, c["catalog_json"](c["catalog"], role)
    if path == "/build":
        if BUILDER["limit"]:
            return 429, {"detail": "You can build 20 dashboards an hour; try again in 42 minutes."}
        return 200, c["core"].run_build(c["standin"](c["catalog"], role), c["catalog"], role, body["prompt"], body.get("current_yaml"), mode="standin")
    if path.startswith("/saved"):
        if not BUILDER["saving"]:
            return 503, {"detail": "Saving is not set up on this server (BUILDER_DB_PASSWORD is empty)."}
        return saved_answer(path, body, method, c)
    if path == "/validate":
        built, problems = c["core"].check_submission(body["yaml"], c["catalog"], role)
        return 200, {"ok": built is not None, "yaml": built and built["yaml"], "spec": built and built["spec"], "notes": built["notes"] if built else [], "problems": problems}
    return 404, {"detail": "not found"}


def reset_saved():
    _builder_cache.pop("saved_store", None)


def seed_saved(title, description, *, owner="admin", role="admin", visibility="private", shared_roles=(), tags=("sales",)):
    """Put a saved dashboard in the in-memory store as `owner`, without going through the page (for tests of the list)."""
    import re
    builder_answer("/info", {})                              # makes sure the builder pieces (catalog, checks) are loaded
    from builder import saved
    from builder.store import MemoryStore
    store = _builder_cache.setdefault("saved_store", MemoryStore())
    text = (ROOT / "dashboards" / "sales-overview.yml").read_text()
    line = f"description: {json.dumps(description, ensure_ascii=False)}"
    text = re.sub(r"(?m)^description: .*$", lambda _: line, text, count=1)      # a function: the text may hold backslashes
    text = re.sub(r"(?m)^tags: .*\n", f"tags: {json.dumps(list(tags), ensure_ascii=False)}\n" if tags else "", text, count=1)
    return saved.save_new(store, _builder_cache["catalog"], saved.Who(name=owner, role=role), text, title=title, visibility=visibility, shared_roles=list(shared_roles))


def saved_answer(path, body, method, c):
    """The saved-dashboard endpoints on an in-memory store, through the same rules (builder/saved.py) the service uses."""
    from builder import saved
    from builder.store import MemoryStore
    if "saved_store" not in _builder_cache:
        _builder_cache["saved_store"] = MemoryStore()
    store, catalog, who = _builder_cache["saved_store"], c["catalog"], saved.Who(name=USER["name"], role=ROLE["role"])
    parts = [p for p in path.split("/") if p]
    try:
        if parts == ["saved"] and method == "GET":
            return 200, saved.list_saved(store, catalog, who)
        if parts == ["saved"] and method == "POST":
            return 201, saved.save_new(store, catalog, who, body["yaml"], title=body.get("title"), visibility=body.get("visibility", "private"), shared_roles=body.get("shared_roles", []), tags=body.get("tags"))
        if len(parts) == 2 and method == "GET":
            return 200, saved.open_saved(store, catalog, who, parts[1])
        if len(parts) == 2 and method == "PUT":
            return 200, saved.update_saved(store, catalog, who, parts[1], yaml_text=body.get("yaml"), title=body.get("title"), visibility=body.get("visibility"), shared_roles=body.get("shared_roles"), tags=body.get("tags"))
        if len(parts) == 2 and method == "DELETE":
            saved.delete_saved(store, who, parts[1])
            return 204, {}
        if len(parts) == 3 and parts[2] == "versions":
            return 200, saved.versions(store, who, parts[1])
        if len(parts) == 3 and parts[2] == "restore":
            return 200, saved.restore(store, catalog, who, parts[1], body["version"])
    except saved.SavedError as e:
        return e.status, {"detail": {"message": e.message, "problems": e.problems} if e.problems else e.message}
    return 404, {"detail": "not found"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(b"")

    def do_POST(self):
        self.do_GET()

    do_PUT = do_DELETE = do_POST

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
            return self._send(json.dumps({"token": "t", "expires_in": 900, "user": USER["name"], "role": ROLE["role"], "territories": ["Canada"]}).encode())
        if path.startswith("/builder/"):
            body = {}
            if self.command in ("POST", "PUT"):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or "{}")
            status, answer = builder_answer(path[len("/builder"):], body, self.command, parse_qs(urlparse(self.path).query))
            return self._send(b"" if status == 204 else json.dumps(answer).encode(), status=status)
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
                  f'auth: "http://localhost:{PORT}/auth", actions: "http://localhost:{PORT}/actions", builder: "http://localhost:{PORT}/builder", cube: "http://localhost:{PORT}/cube-live" }}; '
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
    FAKE["on"] = "--data" in sys.argv                    # generated rows instead of empty answers: every panel draws something
    ROLE["role"] = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--role=")), "admin")
    start(port)
    base = f"http://localhost:{port}/_seed?to="
    kind = "generated data (the numbers mean nothing)" if FAKE["on"] else "no data behind it: the charts are empty"
    print(f"Mock stack, signed in as {ROLE['role']}, {kind}. Open in your browser (the first link fakes the sign-in):")
    print(f"  sales dashboard  {base}%2F%3Fdemo%3D1")
    print(f"  dashboards       {base}%2Fd%2F        (the list), then /d/sales-overview, /d/envanter-sagligi, /d/regional-sales")
    if BENCH["on"]:
        print(f"  250M benchmark   {base}%2F%3Fdataset%3D250m%26demo%3D1")
    print("Options: --data  --role=rep|manager|purchasing|marketing  --single (one dataset)   Ctrl-C to stop.")
    threading.Event().wait()
