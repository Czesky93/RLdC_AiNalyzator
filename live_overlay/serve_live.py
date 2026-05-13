from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.getenv("RLDC_OVERLAY_PORT", "8099"))
BACKEND = os.getenv("RLDC_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
ROOT = Path(__file__).resolve().parent


def backend_json(path: str):
    url = BACKEND + path
    req = urllib.request.Request(url, headers={"User-Agent": "RLdC-Overlay/1.0"})
    with urllib.request.urlopen(req, timeout=6) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        rel = path.split("?", 1)[0].lstrip("/") or "index.html"
        return str(ROOT / rel)

    def _json(self, data, code=200):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in ["/health", "/api/health"]:
            return self._json({
                "ok": True,
                "backend": BACKEND,
                "dir": str(ROOT),
                "port": PORT,
            })

        if path in ["/api/live-state", "/live-state", "/api/state"]:
            try:
                return self._json(backend_json("/api/rldc/safe/live-state"))
            except Exception as e:
                return self._json({
                    "ok": False,
                    "backend": BACKEND,
                    "errors": [str(e)],
                    "warning": "Overlay działa, ale backend nie zwrócił live-state.",
                    "positions": [],
                }, 200)

        if path == "/":
            self.path = "/index.html"

        return super().do_GET()


if __name__ == "__main__":
    os.chdir(ROOT)
    print("Start RLdC LIVE overlay sync")
    print(f"Backend: {BACKEND}")
    print(f"OBS URL: http://127.0.0.1:{PORT}/index.html")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
