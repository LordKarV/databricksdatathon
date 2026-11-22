"""Travel time shared by the decision layer and the planner.

    from geo.travel import travel_minutes
    rows = travel_minutes((26.45, 85.95), [(26.365, 86.08), (26.152, 85.897)])

Each row is a dict:
    minutes   best single number (int)
    low, high range to show (int minutes); see "Ranges" below
    km        road distance (float), measured or estimated
    method    "osrm" (road route) or "haversine_factor" (straight line x measured road factor
              / measured speed)
    cached    True when an "osrm" row came from the on-disk cache instead of a live request
    factor    road km / straight-line km: measured for this pair ("osrm") or the constant used
    kmh       speed behind `minutes`: OSRM free flow for this pair, or the constant used
    terrain   "plain" or "hill": which constants an estimate used (None for "osrm" rows)
    label     words for the card, naming the method

Optional arguments, both for the estimate only:
    state     state or union territory name of the origin, any case. Hill states (listed in
              geo/road_factor.json) get their own measured factor and speed. Without it the
              plain constants are used, which is too fast in the hills.
    area      "urban" or "rural" origin. Narrows the range where enough pairs were measured.

Ranges. For an estimate, low and high are the 10th and 90th percentile of measured
(OSRM minutes / estimated minutes) for that terrain, distance and area, so about 8 in 10 road
routes fall inside. For an "osrm" row low = high = minutes: it is one free-flow route with no
traffic data, and nothing here measures how much slower a real journey is.

Order of work: on-disk cache, then one OSRM table request for what is missing (timeout, default
3 s), then the estimate for anything still missing. OSRM failures never raise. After a failure
OSRM is skipped for 60 s so callers do not wait for the timeout on every call.

OSRM durations are free flow (no traffic). Constants for the estimate come from
geo/road_factor.json, written by geo/fit_travel_constants.py from the measured pairs.

Standard library only. Coordinates are (lat, lon) in degrees.
Environment: OSRM_URL, TRAVEL_CACHE (path to the sqlite file; "off" disables the cache).
"""
import json
import math
import os
import sqlite3
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org")
CACHE_PATH = os.environ.get("TRAVEL_CACHE", str(HERE / "data" / "travel_cache.sqlite"))
UA = "cmu-datathon-care-finder/0.1"
TIMEOUT_S = 3.0
MAX_TABLE = 100            # OSRM default max-table-size, origin included
CACHE_DAYS = 30
BACKOFF_S = 60.0
ROUND = 4                  # cache key precision: 4 decimals is about 11 m

_CONST = json.loads((HERE / "road_factor.json").read_text())
_HILL = set(_CONST["hill_states"])
AREAS = (None, "urban", "rural")
_osrm_down_until = 0.0


def hav_km(a, b):
    """Great-circle distance in km between two (lat, lon) points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def terrain_of(state):
    """"hill" for a state with measured hill constants, else "plain" (also for None or unknown)."""
    if not state:
        return "plain"
    name = " ".join(str(state).upper().replace("&", "AND").split())
    return "hill" if name in _HILL else "plain"


def _consts(km, terrain="plain", area=None):
    """Factor, free-flow speed and 10th/90th percentile minutes ratio for a straight-line distance,
    interpolated between the measured distance bands and held flat outside them."""
    bands = _CONST["classes"][terrain]["bands"]
    if km <= bands[0]["mid_km"]:
        lo = hi = bands[0]
        t = 0.0
    elif km >= bands[-1]["mid_km"]:
        lo = hi = bands[-1]
        t = 0.0
    else:
        hi = next(b for b in bands if b["mid_km"] >= km)
        lo = bands[bands.index(hi) - 1]
        t = (km - lo["mid_km"]) / (hi["mid_km"] - lo["mid_km"])

    def ratio(b):  # the area's own percentiles where enough pairs were measured, else pooled
        return b["ratio_by_area"].get(area, {}).get("p10_p90", b["ratio_p10_p90"])

    def mix(x, y):
        return x + (y - x) * t
    return (mix(lo["factor"], hi["factor"]), mix(lo["kmh_free_flow"], hi["kmh_free_flow"]),
            mix(ratio(lo)[0], ratio(hi)[0]), mix(ratio(lo)[1], ratio(hi)[1]))


def _row(minutes, km, method, straight_km, low=None, high=None, factor=None, kmh=None, cached=False, terrain=None):
    low = minutes if low is None else low
    high = minutes if high is None else high
    if factor is None:
        factor = km / straight_km if straight_km > 0 else None
    if kmh is None:
        kmh = km / minutes * 60 if minutes > 0 else None
    if method == "haversine_factor":
        roads = " (hill roads)" if terrain == "hill" else ""
        label = f"rough estimate: straight line x {factor:.2f} at {kmh:.0f} km/h{roads}, no route check"
    else:
        label = "road route (saved), free flow, no traffic data" if cached else "road route, free flow, no traffic data"
    # A place any distance away is never "0 min" (Lucknow C-section: "0 to 227 min" for a point 0.3 km off).
    floor = 1 if km > 0 else 0
    m, lo_ = max(floor, round(minutes)), max(floor, round(low))
    return {"minutes": m, "low": lo_, "high": max(lo_, round(high)), "km": round(km, 1),
            "method": method, "cached": cached,
            "factor": None if factor is None else round(factor, 3), "kmh": None if kmh is None else round(kmh, 1),
            "terrain": terrain, "label": label}


def estimate(origin, dest, state=None, area=None):
    """Straight line x measured road factor at the measured free-flow speed for that distance and
    terrain. low and high are the measured 10th and 90th percentile of OSRM time / this estimate."""
    terrain = terrain_of(state)
    straight = hav_km(origin, dest)
    factor, kmh, lo_ratio, hi_ratio = _consts(straight, terrain, area)
    road = straight * factor
    minutes = road / kmh * 60
    return _row(minutes, road, "haversine_factor", straight, low=min(minutes, minutes * lo_ratio),
                high=max(minutes, minutes * hi_ratio), factor=factor, kmh=kmh, terrain=terrain)


def _key(p):
    return f"{p[0]:.{ROUND}f},{p[1]:.{ROUND}f}"


def _db():
    if CACHE_PATH == "off":
        return None
    try:
        Path(CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(CACHE_PATH, timeout=2.0)
        db.execute("CREATE TABLE IF NOT EXISTS route (o TEXT, d TEXT, minutes REAL, road_km REAL, ts REAL, "
                   "PRIMARY KEY (o, d))")
        return db
    except (sqlite3.Error, OSError) as e:  # a broken cache must never break an answer
        print(f"travel cache unavailable: {type(e).__name__}: {e}")
        return None


def _cache_get(db, origin, dests):
    out = {}
    if db is None:
        return out
    oldest = time.time() - CACHE_DAYS * 86400
    try:
        for i, d in enumerate(dests):
            r = db.execute("SELECT minutes, road_km FROM route WHERE o=? AND d=? AND ts>=?",
                           (_key(origin), _key(d), oldest)).fetchone()
            if r:
                out[i] = r
    except sqlite3.Error as e:
        print(f"travel cache read failed: {type(e).__name__}: {e}")
    return out


def _cache_put(db, origin, rows):
    if db is None or not rows:
        return
    try:
        with db:
            db.executemany("INSERT OR REPLACE INTO route VALUES (?,?,?,?,?)",
                           [(_key(origin), _key(d), m, km, time.time()) for d, m, km in rows])
    except sqlite3.Error as e:
        print(f"travel cache write failed: {type(e).__name__}: {e}")


def _fetch(url, timeout_s):
    """One HTTP GET returning parsed JSON. Separate so tests can replace it."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        return json.load(r)


def _osrm(origin, dests, timeout_s):
    """Return [(minutes, road_km) or None per destination]. Raises on any failure."""
    out = []
    for i in range(0, len(dests), MAX_TABLE - 1):
        part = dests[i:i + MAX_TABLE - 1]
        coords = ";".join(f"{p[1]:.6f},{p[0]:.6f}" for p in [origin] + part)
        body = _fetch(f"{OSRM_URL}/table/v1/driving/{coords}?sources=0&annotations=duration,distance", timeout_s)
        if body.get("code") != "Ok":
            raise RuntimeError(f"OSRM code {body.get('code')}")
        dur, dist = body["durations"][0][1:], body["distances"][0][1:]
        if len(dur) != len(part) or len(dist) != len(part):
            raise RuntimeError("OSRM returned the wrong number of results")
        out += [None if s is None or m is None else (s / 60.0, m / 1000.0) for s, m in zip(dur, dist)]
    return out


def _check(p):
    try:
        lat, lon = float(p[0]), float(p[1])
    except (TypeError, ValueError, IndexError):
        raise ValueError(f"point must be (lat, lon), got {p!r}") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or math.isnan(lat) or math.isnan(lon):
        raise ValueError(f"point out of range (lat, lon): {p!r}")
    return lat, lon


def travel_minutes(origin, destinations, mode="road", timeout_s=TIMEOUT_S, use_osrm=True, state=None, area=None):
    """Travel time from origin to each destination. See the module docstring for the row shape.

    origin: (lat, lon). destinations: list of (lat, lon). mode: only "road".
    use_osrm=False skips the network (cache and estimate only), for offline packs and bulk scoring.
    state, area: optional, used only by the estimate (see the module docstring).
    """
    global _osrm_down_until
    if mode != "road":
        raise ValueError(f"unsupported mode {mode!r}; only 'road' is implemented")
    if area not in AREAS:
        raise ValueError(f"area must be 'urban', 'rural' or None, got {area!r}")
    origin = _check(origin)
    dests = [_check(d) for d in destinations]
    out: list = [None] * len(dests)

    db = _db()
    try:
        for i, (m, km) in _cache_get(db, origin, dests).items():
            out[i] = _row(m, km, "osrm", hav_km(origin, dests[i]), cached=True)
        todo = [i for i in range(len(dests)) if out[i] is None]
        if todo and use_osrm and time.time() >= _osrm_down_until:
            try:
                got = _osrm(origin, [dests[i] for i in todo], timeout_s)
                fresh = []
                for i, r in zip(todo, got):
                    if r is not None:
                        out[i] = _row(r[0], r[1], "osrm", hav_km(origin, dests[i]))
                        fresh.append((dests[i], r[0], r[1]))
                _cache_put(db, origin, fresh)
            except Exception as e:  # timeout, DNS, 5xx, bad JSON: fall back, never raise
                _osrm_down_until = time.time() + BACKOFF_S
                print(f"osrm unavailable, using estimate for {BACKOFF_S:.0f} s: {type(e).__name__}: {e}")
    finally:
        if db is not None:
            db.close()
    return [o or estimate(origin, d, state, area) for o, d in zip(out, dests)]


if __name__ == "__main__":
    o = (26.45, 85.95)
    d = [(26.3650, 86.0800), (26.1520, 85.8970)]
    print(json.dumps(travel_minutes(o, d), indent=1))
    print(json.dumps(travel_minutes(o, d, use_osrm=False, state="Sikkim", area="rural"), indent=1))
