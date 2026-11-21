"""Temporary Databricks App: which outbound hosts can an App reach?

Runs the probe once at startup (printed to the app log as NET_PROBE_RESULT)
and serves the latest result as JSON at "/". "/?refresh=1" re-runs it.
Stdlib only, so deployment does not depend on PyPI access.
"""
import json
import os
import socket
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

# ponytail: fixed target list; each answers "can the app use this kind of service?"
TARGETS = {
    "google": "https://www.google.com/generate_204",
    "github_api": "https://api.github.com/zen",
    "pypi": "https://pypi.org/simple/requests/",
    "huggingface": "https://huggingface.co/api/models?limit=1",
    "osrm_routing": "https://router.project-osrm.org/route/v1/driving/85.1376,25.5941;85.0002,25.6093?overview=false",
    "nominatim_geocode": "https://nominatim.openstreetmap.org/reverse?format=json&lat=25.5941&lon=85.1376",
    "osm_tiles": "https://tile.openstreetmap.org/0/0/0.png",
    "wikipedia": "https://en.wikipedia.org/api/rest_v1/page/summary/Patna",
    "data_gov_in": "https://data.gov.in/",
    "pmjay_hospitals": "https://hospitals.pmjay.gov.in/",
}
USER_AGENT = "datathon-net-probe/0.1"
TIMEOUT_S = 10
_latest = {"status": "not run yet"}


def probe_one(url: str) -> dict:
    host = urllib.parse.urlparse(url).hostname
    out = {"host": host}
    try:
        out["dns"] = sorted({a[4][0] for a in socket.getaddrinfo(host, 443)})[:2]
    except OSError as e:
        out["dns_error"] = f"{type(e).__name__}: {e}"[:200]
        return out
    start = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            out["status"] = resp.status
            out["bytes"] = len(resp.read(65536))
    except urllib.error.HTTPError as e:
        out["status"] = e.code  # reached the server; it answered with an error code
    except Exception as e:  # report every failure mode, never crash the probe
        out["error"] = f"{type(e).__name__}: {e}"[:200]
    out["ms"] = round((time.monotonic() - start) * 1000)
    return out


def run_probe() -> dict:
    global _latest
    result = {
        "proxy_env": {k: bool(os.environ.get(k)) for k in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy")},
        "targets": {name: probe_one(url) for name, url in TARGETS.items()},
    }
    _latest = result
    print("NET_PROBE_RESULT " + json.dumps(result), flush=True)
    return result


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps(run_probe() if "refresh=1" in self.path else _latest, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    threading.Thread(target=run_probe, daemon=True).start()
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
