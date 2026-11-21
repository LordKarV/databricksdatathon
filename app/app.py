"""Referral Saathi app skeleton (issue #5).

FastAPI serving one plain HTML page, a service worker and stub JSON. No model and no
Databricks reads yet: /api/recommend returns placeholder data in the shape the lead will
fill from the model (see stub_data.py and README.md).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

from stub_data import SERVICES, recommend_stub

LocationSource = Literal["gps", "last_fix", "pin", "district", "manual"]

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"

# Only these files are served from the root. An allowlist keeps the shell small and
# avoids exposing anything else in the folder.
SHELL_FILES: dict[str, str] = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "sw.js": "text/javascript; charset=utf-8",
    "manifest.webmanifest": "application/manifest+json",
}

app = FastAPI(title="Referral Saathi", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(GZipMiddleware, minimum_size=500)


def _shell(name: str) -> FileResponse:
    # no-cache = revalidate every time; the service worker, not the HTTP cache, owns offline.
    return FileResponse(STATIC / name, media_type=SHELL_FILES[name], headers={"Cache-Control": "no-cache"})


@app.get("/")
def index() -> FileResponse:
    return _shell("index.html")


@app.get("/api/ping")
def ping() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/recommend")
def recommend(
    service: Annotated[str, Query(description="One of the 7 decision-layer service keys")],
    lat: Annotated[float, Query(ge=6.0, le=37.5)],
    lon: Annotated[float, Query(ge=68.0, le=97.5)],
    accuracy_m: Annotated[float | None, Query(ge=0)] = None,
    source: Annotated[LocationSource, Query()] = "gps",
) -> dict:
    if service not in SERVICES:
        raise HTTPException(422, f"unknown service; expected one of {sorted(SERVICES)}")
    # Round to 0.01 deg (~1.1 km) before anything else touches the point (spec section 8).
    acc = None if accuracy_m is None else round(accuracy_m)
    return recommend_stub(service, round(lat, 2), round(lon, 2), acc, source)


@app.get("/{name}")
def static_file(name: str) -> FileResponse:
    if name not in SHELL_FILES:
        raise HTTPException(404)
    return _shell(name)
