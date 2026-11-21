"""Referral Saathi app skeleton (issue #5).

FastAPI serving one plain HTML page, a service worker and stub JSON. No model and no
Databricks reads yet: /api/recommend returns placeholder data in the shape the lead will
fill from the model (see stub_data.py and README.md).
"""
from __future__ import annotations

import functools
import json
import math
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from stub_data import SERVICES, recommend_stub

LocationSource = Literal["gps", "last_fix", "pin", "district", "manual"]
Depth = Literal["quick", "compare", "area"]

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
PACKS = HERE / "packs" / "out"  # built by packs/build_packs.py (git-ignored)

# Only these files are served from the root. An allowlist keeps the shell small and
# avoids exposing anything else in the folder.
SHELL_FILES: dict[str, str] = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "sw.js": "text/javascript; charset=utf-8",
    "pack.js": "text/javascript; charset=utf-8",
    "offline.js": "text/javascript; charset=utf-8",
    "slip.js": "text/javascript; charset=utf-8",
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


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(description="One of the 7 decision-layer service keys")
    lat: float = Field(ge=6.0, le=37.5)
    lon: float = Field(ge=68.0, le=97.5)
    accuracy_m: float | None = Field(default=None, ge=0)
    source: LocationSource = "gps"
    depth: Depth = "quick"


def _plan(req: PlanRequest) -> dict:
    if req.service not in SERVICES:
        raise HTTPException(422, f"unknown service; expected one of {sorted(SERVICES)}")
    # Round to 0.01 deg (~1.1 km) before anything else touches the point (spec section 8).
    acc = None if req.accuracy_m is None else round(req.accuracy_m)
    plan = recommend_stub(req.service, round(req.lat, 2), round(req.lon, 2), acc, req.source)
    plan["query"]["depth"] = req.depth
    return plan


@app.post("/api/plan")
def plan(req: PlanRequest) -> dict:
    """The page's endpoint: the point travels in the body, so it stays out of proxy URL logs."""
    return _plan(req)


@app.get("/api/recommend")
def recommend_dev_alias(req: Annotated[PlanRequest, Query()]) -> dict:
    """Dev-only alias for curl and browser checks. The page never calls it."""
    return _plan(req)


def _pack_index() -> dict | None:
    path = PACKS / "index.json"
    return json.loads(path.read_text()) if path.is_file() else None


@app.get("/api/pack/version")
def pack_version() -> JSONResponse:
    idx = _pack_index()
    if idx is None:
        return JSONResponse({"error": "no packs built"}, 404, headers={"Cache-Control": "no-cache"})
    return JSONResponse(idx, headers={"Cache-Control": "no-cache"})


@app.get("/api/pack/{slug}")
def pack(slug: str) -> Response:
    # The slug must be a key of index.json, so no client string ever reaches the filesystem path.
    idx = _pack_index()
    if idx is None or slug not in idx["packs"]:
        raise HTTPException(404)
    body = (PACKS / f"{slug}.json.gz").read_bytes()
    # Pre-compressed: Content-Encoding is set, so GZipMiddleware leaves it alone.
    return Response(body, media_type="application/json",
                    headers={"Content-Encoding": "gzip", "Cache-Control": "no-cache",
                             "ETag": f'"{idx["packs"][slug]["sha256"]}"'})


class LocateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=6.0, le=37.5)
    lon: float = Field(ge=68.0, le=97.5)


@functools.lru_cache(maxsize=4)
def _pin_index(path: Path, mtime: float) -> tuple[list[tuple[str, str]], list[int], list[float], list[float]]:
    """(states, state index, lat, lon) per PIN from packs/out/pin_index.json (all India, written by every build)."""
    j = json.loads(path.read_text())
    lats, lons, la, lo = [], [], 0, 0
    for dla, dlo in zip(j["lat"], j["lon"], strict=True):
        la, lo = la + dla, lo + dlo
        lats.append(la / j["scale"])
        lons.append(lo / j["scale"])
    return [tuple(x) for x in j["states"]], j["s"], lats, lons


@app.post("/api/pack/locate")
def pack_locate(req: LocateRequest) -> JSONResponse:
    """State of the nearest PIN centroid (from the all-India PIN index), then whether its pack is built.

    The point travels in the body and is never logged.
    """
    path = PACKS / "pin_index.json"
    if not path.is_file():
        return JSONResponse({"error": "no packs built"}, 404)
    states, sidx, lats, lons = _pin_index(path, path.stat().st_mtime)
    lat, lon = round(req.lat, 2), round(req.lon, 2)
    k = math.cos(math.radians(lat))
    i = min(range(len(lats)), key=lambda j: (lats[j] - lat) ** 2 + ((lons[j] - lon) * k) ** 2)
    slug, state = states[sidx[i]]
    if slug not in (_pack_index() or {"packs": {}})["packs"]:
        return JSONResponse({"error": "no pack for this state", "slug": slug, "state": state}, 404)
    return JSONResponse({"slug": slug, "state": state})


@app.get("/{name}")
def static_file(name: str) -> FileResponse:
    if name not in SHELL_FILES:
        raise HTTPException(404)
    return _shell(name)
