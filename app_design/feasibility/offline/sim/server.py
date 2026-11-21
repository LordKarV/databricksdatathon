"""Local stand-in for the Databricks Apps auth proxy, to test a service worker behind cookie auth.

Not the real proxy. It copies the shape described in the Databricks Apps docs: every request to the
app origin needs a session; without one the proxy answers 302 to a login page on ANOTHER origin,
which bounces back to a callback on the app origin that sets an HttpOnly session cookie.
  app origin   http://localhost:8765   (stands in for <app>.databricksapps.com)
  login origin http://127.0.0.1:8766   (stands in for the workspace OAuth authorize page)
Every request is logged with whether it carried the cookie, to out/sim_requests.jsonl.
"""
import json
import sys
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "out"
APP, IDP = "http://localhost:8765", "http://127.0.0.1:8766"
TYPES = {".html": "text/html", ".js": "text/javascript", ".json": "application/json",
         ".webmanifest": "application/manifest+json"}
FILES = {"/": HERE / "index.html", "/sw.js": HERE / "sw.js", "/manifest.webmanifest": HERE / "manifest.webmanifest",
         "/pack_norm.json": OUT / "pack_bihar_pin_norm.json", "/pack_denorm.json": OUT / "pack_bihar_pin_denorm.json",
         "/picker.json": OUT / "picker_bihar.json"}
LOG = OUT / "sim_requests.jsonl"
lock = threading.Lock()


class App(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body=b"", ctype="text/plain", headers=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        has = SimpleCookie(self.headers.get("Cookie", "")).get("session") is not None
        with lock, LOG.open("a") as f:
            f.write(json.dumps({"path": u.path, "cookie": has, "sw": self.headers.get("Service-Worker"),
                                "dest": self.headers.get("Sec-Fetch-Dest"), "mode": self.headers.get("Sec-Fetch-Mode")}) + "\n")
        if u.path == "/.auth/callback":
            nxt = parse_qs(u.query).get("next", ["/"])[0]
            return self.send(302, headers=[("Set-Cookie", "session=ok; Path=/; HttpOnly; SameSite=Lax"), ("Location", nxt)])
        if not has:
            cb = quote(f"{APP}/.auth/callback?next={quote(u.path)}", safe="")
            return self.send(302, headers=[("Location", f"{IDP}/authorize?redirect_uri={cb}")])
        if u.query == "stopped=1":  # the proxy's answer while the app is stopped (shape assumed, not observed)
            return self.send(503, b"App is not available", "text/html")
        if u.path == "/api/ping":
            return self.send(200, b'{"ok":true}', "application/json")
        p = FILES.get(u.path)
        if not p:
            return self.send(404)
        self.send(200, p.read_bytes(), TYPES[p.suffix], [("Cache-Control", "no-cache")])


class Idp(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # auto-approve: the user is "already signed in to the workspace"
        to = parse_qs(urlparse(self.path).query).get("redirect_uri", [APP + "/"])[0]
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()


def serve():
    LOG.write_text("")
    for port, h in [(8765, App), (8766, Idp)]:
        srv = ThreadingHTTPServer(("localhost" if port == 8765 else "127.0.0.1", port), h)
        threading.Thread(target=srv.serve_forever, daemon=True).start()


if __name__ == "__main__":
    serve()
    print("serving", APP, IDP, file=sys.stderr)
    threading.Event().wait()
