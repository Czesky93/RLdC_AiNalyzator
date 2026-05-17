from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import urllib.request

BACKEND = "http://127.0.0.1:8000"

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path.startswith("/api/"):
                target = BACKEND + self.path

                with urllib.request.urlopen(target, timeout=8) as r:
                    data = r.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(data)
                return

            super().do_GET()

        except Exception as e:
            msg = f'{{"ok":false,"error":"proxy","detail":"{e}"}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(msg)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

print("RLdC overlay running: http://127.0.0.1:8099/index.html")
ThreadingHTTPServer(("127.0.0.1", 8099), Handler).serve_forever()
