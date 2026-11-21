"""Referral Saathi app skeleton (issue #5).

FastAPI serving one plain HTML page, a service worker and stub JSON. No model and no
Databricks reads yet: /api/recommend returns placeholder data in the shape the lead will
fill from the model (see stub_data.py and README.md).
"""
from __future__ import annotations

import gzip
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


_PIN_STATES: tuple[list[str], list[float], list[float]] | None = None


def _pin_states() -> tuple[list[str], list[float], list[float]]:
    """(slug, lat, lon) per PIN centroid across all built packs, decoded once."""
    global _PIN_STATES
    if _PIN_STATES is None:
        slugs: list[str] = []
        lats: list[float] = []
        lons: list[float] = []
        for slug in (_pack_index() or {"packs": {}})["packs"]:
            pack = json.loads(gzip.decompress((PACKS / f"{slug}.json.gz").read_bytes()))
            scale = pack["scale"]["pin"]
            la = lo = 0
            for dla, dlo in zip(pack["pins"]["lat"], pack["pins"]["lon"], strict=True):
                la, lo = la + dla, lo + dlo
                slugs.append(slug)
                lats.append(la / scale)
                lons.append(lo / scale)
        _PIN_STATES = (slugs, lats, lons)
    return _PIN_STATES


@app.post("/api/pack/locate")
def pack_locate(req: LocateRequest) -> dict:
    """Which state pack covers this point: the state of the nearest PIN centroid. Point in the body, never logged."""
    slugs, lats, lons = _pin_states()
    if not slugs:
        raise HTTPException(404, "no packs built")
    lat, lon = round(req.lat, 2), round(req.lon, 2)
    k = math.cos(math.radians(lat))
    i = min(range(len(slugs)), key=lambda j: (lats[j] - lat) ** 2 + ((lons[j] - lon) * k) ** 2)
    return {"slug": slugs[i], "state": (_pack_index() or {})["packs"][slugs[i]]["state"]}


@app.get("/{name}")
def static_file(name: str) -> FileResponse:
    if name not in SHELL_FILES:
        raise HTTPException(404)
    return _shell(name)
