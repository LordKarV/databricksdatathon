"""Referral Saathi app: FastAPI serving one HTML page, a service worker and the JSON API.

Answers come from model v2 through facts/engine.py (built by facts/build.py); see README.md.
"""
from __future__ import annotations

import functools
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import errors
import outcomes
from community import field
from community import pulse as area_pulse
from community.reporter import reporter_key
from facts.engine import RADIUS_KM, Engine
from facts.places import Places, load_places
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from inputs import translate, understand
from itinerary import attach
from pydantic import BaseModel, ConfigDict, Field
from services import SERVICES, haversine_km
from starlette.exceptions import HTTPException as StarletteHTTPException
from verify.check import Checker
from voice import transcribe as voice

LocationSource = Literal["gps", "last_fix", "pin", "district", "place", "manual"]
Depth = Literal["quick", "compare", "area"]

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
PACKS = HERE / "packs" / "out"  # built by packs/build_packs.py (git-ignored)
PLACES = HERE / "facts" / "out" / "places.json.gz"  # town and post office names, built by facts/build.py

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
    "how.js": "text/javascript; charset=utf-8",
    "input.js": "text/javascript; charset=utf-8",
    "passed.js": "text/javascript; charset=utf-8",
    "receipt.js": "text/javascript; charset=utf-8",
    "voice.js": "text/javascript; charset=utf-8",
    "speech.js": "text/javascript; charset=utf-8",
    "speech_templates.json": "application/json; charset=utf-8",
    "lexicon.json": "application/json; charset=utf-8",
    "stories.js": "text/javascript; charset=utf-8",
    "pulse.js": "text/javascript; charset=utf-8",
    "journey.js": "text/javascript; charset=utf-8",
    "community.js": "text/javascript; charset=utf-8",
    "translate.js": "text/javascript; charset=utf-8",
    "route.js": "text/javascript; charset=utf-8",
    "map.js": "text/javascript; charset=utf-8",
    "manifest.webmanifest": "application/manifest+json",
    # ICON-1: home-screen icons. Served here only; not in the sw.js SHELL, so they never weigh on first paint.
    "icon.svg": "image/svg+xml",
    "icon-180.png": "image/png",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
    "icon-512-maskable.png": "image/png",
}

app = FastAPI(title="Referral Saathi", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.exception_handler(RequestValidationError)
async def _invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Field, rule and message only: the rejected value is never echoed (a NaN could not even be serialised, #85).
    # `code` and `message` sit beside `detail` (BE-T1): a phone fix outside India or too rough gets its own code.
    errs = exc.errors()
    return JSONResponse({"detail": [{"loc": list(e.get("loc", ())), "type": e.get("type"), "msg": e.get("msg")}
                                    for e in errs], **errors.payload(errors.validation_code(request.url.path, errs))},
                        422)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException) -> Response:
    # FastAPI's default body, plus `code` and `message` for a coded error or a plain 404.
    if exc.status_code in (204, 304):
        return Response(status_code=exc.status_code, headers=exc.headers)
    code = getattr(exc, "code", None) or ("not_found" if exc.status_code == 404 else None)
    return JSONResponse({"detail": exc.detail, **(errors.payload(code) if code else {})}, exc.status_code,
                        headers=exc.headers)


@app.exception_handler(Exception)
async def _crash(_: Request, exc: Exception) -> JSONResponse:
    # Was Starlette's text/plain "Internal Server Error"; the same words now sit in `detail`. Nothing is echoed.
    return JSONResponse({"detail": "Internal Server Error", **errors.payload("internal")}, 500)


def _err(code: str, status: int, text: str, **extra: Any) -> JSONResponse:
    """An {error: text} response (kept as it was) with `code` and `message` beside it."""
    return JSONResponse({**extra, "error": text, **errors.payload(code, **{k: str(v) for k, v in extra.items()})},
                        status)


def _shell(name: str) -> FileResponse:
    # no-cache = revalidate every time; the service worker, not the HTTP cache, owns offline.
    path = understand.LEXICON if name == "lexicon.json" else STATIC / name
    return FileResponse(path, media_type=SHELL_FILES[name], headers={"Cache-Control": "no-cache"})


@app.get("/")
def index() -> FileResponse:
    return _shell("index.html")


@app.get("/api/ping")
def ping() -> dict[str, bool]:
    return {"ok": True}


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    service: str = Field(description="One of the 7 decision-layer service keys")
    lat: float = Field(ge=6.0, le=37.5)
    lon: float = Field(ge=68.0, le=97.5)
    accuracy_m: float | None = Field(default=None, ge=0, le=1_000_000)
    source: LocationSource = "gps"
    depth: Depth = "quick"


@functools.lru_cache(maxsize=1)
def _engine() -> Engine | None:
    return Engine.load()  # None until app/facts/build.py has run; facts load once (about 0.05 s, 80 MB)


def _need_engine() -> Engine:
    e = _engine()
    if e is None:
        raise errors.Coded("facts_not_built", 503, "facility data is not built on this server (run app/facts/build.py)")
    return e


def _plan(req: PlanRequest) -> dict:
    if req.service not in SERVICES:
        raise errors.Coded("unknown_service", 422, f"unknown service; expected one of {sorted(SERVICES)}")
    # Round to 0.01 deg (~1.1 km) before anything else touches the point (spec section 8).
    acc = None if req.accuracy_m is None else round(req.accuracy_m)
    eng = _need_engine()
    plan = attach(eng.plan(req.service, round(req.lat, 2), round(req.lon, 2), acc, req.source), eng)
    # Field reports (community/field.py): never waits on the warehouse; without them the plan is unchanged plus a note.
    # With them the options are re-ranked and re-worded from the adjusted scores.
    plan = field.apply_field(plan, field.aggregates(wait=False), datetime.now(UTC), eng)
    plan["field_reports"] = field.status()
    plan["query"]["depth"] = req.depth
    return plan


@app.post("/api/plan")
def plan(req: PlanRequest) -> dict:
    """The page's endpoint: the point travels in the body, so it stays out of proxy URL logs."""
    return _plan(req)


class AreaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    service: str
    lat: float = Field(ge=6.0, le=37.5)
    lon: float = Field(ge=68.0, le=97.5)


@app.post("/api/area")
def area(req: AreaRequest) -> dict:
    """Standing referral plan for the area around a point (S11) and the ten calls (S12), from real rows."""
    if req.service not in SERVICES:
        raise errors.Coded("unknown_service", 422, f"unknown service; expected one of {sorted(SERVICES)}")
    return _need_engine().area(req.service, round(req.lat, 2), round(req.lon, 2))


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    facility_id: str = Field(min_length=1, max_length=64, pattern=r"^[\w-]+$")
    service_id: str


@functools.lru_cache(maxsize=1)
def _checker() -> Checker | None:
    return Checker.from_out()  # None until app/verify/build_sites.py has run


@app.post("/api/verify")
def verify(req: VerifyRequest) -> JSONResponse:
    """Live check of the facility's official website for the service (#37). Never changes the band."""
    if req.service_id not in SERVICES:
        raise errors.Coded("unknown_service", 422, f"unknown service; expected one of {sorted(SERVICES)}")
    ch = _checker()
    if ch is None:
        return _err("verify_not_set_up", 503, "website check is not set up on this server")
    return JSONResponse(ch.check(req.facility_id, req.service_id), headers={"Cache-Control": "no-store"})


class ParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    text: str = Field(min_length=1, max_length=understand.MAX_TEXT)


@app.post("/api/parse")
def parse(req: ParseRequest) -> JSONResponse:
    """Free text -> a suggested service and the words that decided it (#64). The user confirms with one tap."""
    return JSONResponse(understand.parse_text(req.text), headers={"Cache-Control": "no-store"})


class TranslateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a claim id only: the page never sends text to translate

    claim_id: str = Field(min_length=1, max_length=64, pattern=r"^[\w:.-]+$")


@app.post("/api/translate")
def translate_quote(req: TranslateRequest, request: Request) -> JSONResponse:
    """Hindi machine translation of one facility quote, looked up here by claim id (SAFETY.md 14). Not logged."""
    eng = _need_engine()
    c = eng.claims.get(req.claim_id)  # route stop quotes use the same claim ids
    if c is None:
        raise errors.Coded("translate_unknown_claim", 404, "unknown claim id")
    # A claim id starts with the first 8 characters of its facility's id: its name and city stay untranslated.
    # ponytail: linear scan of ~10k ids per request, an index if it ever shows up in a profile.
    prefix = req.claim_id.split(":")[0]
    i = next((j for u, j in eng.fid.items() if u.startswith(prefix)), None)
    keep = () if i is None else (eng.fac["name"][i] or "", eng.fac["city"][i] or "")
    # Rate limit per reporter key, else per signed-in user (in memory only), else one shared bucket.
    h = request.headers
    user = reporter_key(h) or (h.get("x-forwarded-user") or h.get("x-forwarded-email") or "").strip().lower() or None
    out = translate.translate(req.claim_id, c[1], user, keep)
    return JSONResponse(out, status_code=429 if out.get("reason") == "rate_limited" else 200,
                        headers={"Cache-Control": "no-store"})


NOTE_IMAGE = r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$"


class NoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    image: str = Field(max_length=4_000_000, pattern=NOTE_IMAGE, description="JPEG re-encoded in the browser")


@app.post("/api/read-note")
def read_note(req: NoteRequest) -> JSONResponse:
    """Referral-note photo -> detected text and a guarded suggestion (#64). The image is not stored or logged."""
    out = understand.read_note(req.image)
    if out.get("ok") is False and "guard" not in out:  # the model gave no usable reading; `note` stays as it was
        out |= errors.payload("note_no_service" if out.get("note") == understand.NOTE_NO_SERVICE
                              else "note_model_unavailable")
    return JSONResponse(out, headers={"Cache-Control": "no-store"})


class TranscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio: str = Field(description="data:audio/<webm|ogg|mp4|wav>;base64,... from MediaRecorder, up to 30 s and 2 MB")
    lang: Literal["hi", "en"] = Field(description="chosen by the user; forced, never auto-detected")


@app.post("/api/transcribe")
def transcribe(req: TranscribeRequest) -> JSONResponse:
    """Speech -> text on this server (faster-whisper small). The audio and the text are never stored or logged."""
    no_store = {"Cache-Control": "no-store"}
    try:
        return JSONResponse(voice.transcribe(req.audio, req.lang), headers=no_store)
    except voice.Rejected as e:
        return JSONResponse({"error": e.message, **errors.payload(e.code)}, status_code=e.status, headers=no_store)


class OutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    outcome_id: str = Field(pattern=outcomes.UUID, description="random UUID from the page; a retry writes once")
    facility_id: str = Field(min_length=1, max_length=64)
    service_id: str = Field(max_length=40)
    outcome: Literal["yes", "no", "no_answer", "accepted", "turned_away"]
    said_at_ms: int = Field(ge=0, le=4_102_444_800_000, description="ms since 1970; before 2100")
    lat: float = Field(ge=6.0, le=37.5, description="rounded to 0.01 degree by the page; only the district is kept")
    lon: float = Field(ge=68.0, le=97.5)
    # Field reports (community/field.py): fixed enums only, never free text; outcomes.check_report pairs them.
    kind: Literal["call", "visit"] = "call"
    reason: Literal[outcomes.REASONS] | None = None
    wait_bucket: Literal[outcomes.WAIT_BUCKETS] | None = None


@app.post("/api/outcome")
def outcome(req: OutcomeRequest, request: Request) -> JSONResponse:
    """A phone outcome (#65) or a visit outcome. No patient data: ids, the answer, a district, a time, and a keyed
    hash of the signed-in health worker (never the user itself)."""
    eng = _need_engine()
    try:
        out = outcomes.record(eng, req.outcome_id, req.facility_id, req.service_id, req.outcome, req.said_at_ms,
                              req.lat, req.lon, req.kind, req.reason, req.wait_bucket, reporter_key(request.headers))
    except ValueError as e:
        raise errors.Coded(getattr(e, "code", "request_invalid"), 422, str(e)) from e
    except outcomes.RateLimited as e:
        return _err("outcome_rate_limited", 429, str(e), ok=False)
    except outcomes.OutcomeError as e:
        return _err(e.code, 503, str(e), ok=False)
    return JSONResponse(out, headers={"Cache-Control": "no-store"})


@app.get("/api/outcomes/summary")
def outcomes_summary() -> JSONResponse:
    """Live count for "How this works": outcomes recorded and how many contradicted the band shown."""
    try:
        out = outcomes.summary(_need_engine())
    except outcomes.OutcomeError as e:
        return _err(e.code, 503, str(e))
    return JSONResponse(out, headers={"Cache-Control": "no-store"})


@app.get("/api/pulse")
def pulse(district: Annotated[str | None, Query(max_length=60)] = None,
          service: Annotated[str | None, Query(max_length=40)] = None,
          lat: Annotated[float | None, Query(ge=6.0, le=37.5)] = None,
          lon: Annotated[float | None, Query(ge=68.0, le=97.5)] = None) -> JSONResponse:
    """Area pulse for coordinators and planners: k-anonymous district counts from logged reports only."""
    try:
        out = area_pulse.pulse(_need_engine(), district, service, lat, lon)
    except ValueError as e:
        raise errors.Coded(getattr(e, "code", "request_invalid"), 422, str(e)) from e
    except outcomes.OutcomeError as e:
        return _err(e.code, 503, str(e))
    return JSONResponse(out, headers={"Cache-Control": "no-store"})


HOW = HERE / "howto" / "out" / "how.json"  # built by howto/build.py (git-ignored)


@app.get("/api/how")
def how() -> Response:
    """Data for the 'How this works' page (#45): every number with the repo file it comes from."""
    if not HOW.is_file():
        return _err("how_not_built", 503, "page data is not built on this server (run app/howto/build.py)")
    return FileResponse(HOW, media_type="application/json", headers={"Cache-Control": "no-cache"})


STORIES = HERE / "stories" / "out"  # built by stories/build.py from viz/gallery.json (git-ignored)


def _stories_doc() -> dict | None:
    path = STORIES / "stories.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


@app.get("/api/stories")
def stories() -> Response:
    """Data for the 'Data stories' page (#53): text copied from viz/gallery.json, charts by name."""
    if not (STORIES / "stories.json").is_file():
        return _err("stories_not_built", 503, "page data is not built on this server (run app/stories/build.py)")
    return FileResponse(STORIES / "stories.json", media_type="application/json", headers={"Cache-Control": "no-cache"})


@app.get("/api/stories/chart/{name}")
def story_chart(name: str) -> Response:
    """One chart as SVG. Only names listed in stories.json are served."""
    doc = _stories_doc()
    allowed = {c["file"] for s in doc["stories"] for c in s["charts"]} if doc else set()
    if name not in allowed or not (STORIES / "charts" / name).is_file():
        raise HTTPException(status_code=404)
    return FileResponse(STORIES / "charts" / name, media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=3600", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
                                 "X-Content-Type-Options": "nosniff"})


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
        r = _err("packs_not_built", 404, "no packs built")
        r.headers["Cache-Control"] = "no-cache"
        return r
    # The facility points (index.json "pts") are for /api/pack/locate only; the phone never needs them.
    packs = {k: {f: v for f, v in m.items() if f != "pts"} for k, m in idx["packs"].items()}
    return JSONResponse({**idx, "packs": packs}, headers={"Cache-Control": "no-cache"})


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
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

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
        return _err("packs_not_built", 404, "no packs built")
    states, sidx, lats, lons = _pin_index(path, path.stat().st_mtime)
    lat, lon = round(req.lat, 2), round(req.lon, 2)
    k = math.cos(math.radians(lat))
    i = min(range(len(lats)), key=lambda j: (lats[j] - lat) ** 2 + ((lons[j] - lon) * k) ** 2)
    slug, state = states[sidx[i]]
    idx = _pack_index() or {"packs": {}}
    if slug not in idx["packs"]:
        return _err("pack_no_state", 404, "no pack for this state", slug=slug, state=state)
    return JSONResponse({"slug": slug, "state": state,
                         "packs": [{"slug": slug, "state": state}] + _near_packs(idx, slug, lat, lon)})


class PlaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str = Field(min_length=1, max_length=80)


@functools.lru_cache(maxsize=1)
def _places() -> Places:
    eng = _need_engine()
    return Places(eng.pins, load_places(PLACES), eng.pin_where)


@app.post("/api/place")
def place(req: PlaceRequest) -> JSONResponse:
    """A typed PIN, district, town or post office name to a point (#121 bug 5), from facts and places.json.gz only.

    The text travels in the body and is never logged. 404 with no matches, so the page can say what to type.
    """
    matches, matched_as = _places().resolve(req.q)
    if not matches:
        return JSONResponse({"error": "place not found", "matches": [], **errors.payload("place_not_found")}, 404)
    # matched_as (additive): the name shown when the typed one is an old name or a near spelling of it
    return JSONResponse({"matches": matches, **({"matched_as": matched_as} if matched_as else {})})


class NearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=6, le=37.5)
    lon: float = Field(ge=68, le=97.5)


@app.post("/api/place/near")
def place_near(req: NearRequest) -> JSONResponse:
    """The phone's point in words for the home location line (#140 3f): nearest town or post office, district, PIN.

    The point travels in the body, rounded to 0.01 degree as /api/plan, and is never logged.
    """
    return JSONResponse(_places().near(round(req.lat, 2), round(req.lon, 2)))


def _near_packs(idx: dict, home: str, lat: float, lon: float) -> list[dict]:
    """Other built packs with a facility of their state within the search radius (care crosses state lines).

    index.json keeps each state's facility points in 0.1 degree; nearest packs first.
    """
    scale = idx.get("pts_scale", 10)
    near = []
    for s, m in idx["packs"].items():
        if s == home or not m.get("pts"):
            continue
        d = min(haversine_km(lat, lon, a / scale, b / scale) for a, b in m["pts"])
        if d <= RADIUS_KM:
            near.append((d, {"slug": s, "state": m["state"]}))
    return [x for _, x in sorted(near, key=lambda t: t[0])]


@app.get("/{name}")
def static_file(name: str) -> FileResponse:
    if name not in SHELL_FILES:
        raise HTTPException(404)
    return _shell(name)


# UI2 (design/ui2/SPEC.md): the strings files and the self-hosted fonts. Fixed allowlists, so no client string reaches
# the filesystem path. Fonts never change under a name, so they may be cached for a year; strings revalidate.
STRING_FILES = {f"{code}.json" for code in ("en", "hi", "ta", "te", "kn", "ml", "bn", "mr", "gu", "ur")}
FONT_FILES = {"barlow-500.woff2", "barlow-600.woff2", "barlow-condensed-600.woff2", "plex-mono-500-digits.woff2",
              "hind-500-deva.woff2", "hind-600-deva.woff2"}


@app.get("/i18n/{name}")
def strings_file(name: str) -> FileResponse:
    if name not in STRING_FILES or not (STATIC / "i18n" / name).is_file():  # a language file not shipped yet
        raise HTTPException(404)
    return FileResponse(STATIC / "i18n" / name, media_type="application/json; charset=utf-8",
                        headers={"Cache-Control": "no-cache"})


@app.get("/fonts/{name}")
def font_file(name: str) -> FileResponse:
    if name not in FONT_FILES:
        raise HTTPException(404)
    return FileResponse(STATIC / "fonts" / name, media_type="font/woff2",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


_engine()  # load the facts at start-up, not on the first request
