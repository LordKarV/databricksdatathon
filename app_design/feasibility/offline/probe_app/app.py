"""Probe for the team to deploy (NOT deployed by this feasibility task): service worker and
offline GPS behind the real Databricks Apps auth proxy. Results are printed to the app log
(Logs tab) as one JSON line per POST /api/result, prefixed PROBE_RESULT."""
import json
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

HERE = Path(__file__).resolve().parent
app = FastAPI()
TYPES = {"sw.js": "text/javascript", "manifest.webmanifest": "application/manifest+json", "icon.png": "image/png"}


@app.get("/")
def index():
    return FileResponse(HERE / "index.html", media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/{name}")
def static(name: str):
    if name not in TYPES:
        return JSONResponse({"error": "not found"}, 404)
    return FileResponse(HERE / name, media_type=TYPES[name], headers={"Cache-Control": "no-cache"})


@app.get("/api/ping")
def ping(request: Request):
    # which identity headers the proxy forwards (names only, never values)
    return {"ok": True, "forwarded_headers": sorted(h for h in request.headers if h.startswith("x-forwarded"))}


@app.post("/api/result")
async def result(request: Request):
    body = await request.json()
    print("PROBE_RESULT " + json.dumps(body)[:20000], file=sys.stderr, flush=True)
    return {"stored": True}
