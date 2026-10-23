"""A small local server that plays every service the dashboard talks to (no stack needed), shared by the browser tests.

It serves dashboard/static and dashboard/cube, generates /cube/config.js (one or two datasets), and answers the auth service, the
actions service and two Cubes with empty data while counting what each page asked (`hits`).
"""
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parents[3]
PORT = 19350
hits: dict[str, int] = {}
BENCH = {"on": True}
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



def start(port=PORT):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


SEED = 'sessionStorage.setItem("kc", JSON.stringify({access: "a", refresh: "r", expires: Date.now() + 3.6e6}));'
