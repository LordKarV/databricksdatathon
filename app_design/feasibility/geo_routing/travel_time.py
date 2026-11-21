"""Reference travel-time lookup for the App: precomputed row, else one live OSRM table call, else haversine model.

Every answer carries its source and a low/high range so the card can say how the number was made.
Constants come from out/osrm_summary.json (50 rural Bihar pairs, 2026-11-21).
Run directly for the self-check, which forces the OSRM-down path with an unroutable host.
"""
import json
import math
import urllib.request

UA = "cmu-datathon-care-finder/0.1"
CIRCUITY = 1.26          # median road_km / straight km, origin-bootstrap 95% CI 1.23 to 1.34
FREE_FLOW_KMH = 69.4     # OSRM median on-road speed in the sample (free flow, optimistic)
SLOW_KMH = 40.0          # decision-layer assumption, used as the pessimistic end
OSRM = "https://router.project-osrm.org"


def hav_km(a, b):
    (la1, lo1), (la2, lo2) = [(math.radians(x), math.radians(y)) for x, y in (a, b)]
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def estimate(origin, dest):
    road = CIRCUITY * hav_km(origin, dest)
    return {"minutes": round(road / FREE_FLOW_KMH * 60), "low": round(road / FREE_FLOW_KMH * 60),
            "high": round(road / SLOW_KMH * 60), "source": "estimate: straight line x 1.26, 40 to 69 km/h"}


def travel(origin, dests, precomputed=None, base=OSRM, timeout_s=3.0):
    """origin (lat, lon); dests list of (lat, lon); precomputed dict {(i): minutes} for this origin's PIN."""
    out = [None] * len(dests)
    for i, m in (precomputed or {}).items():
        out[i] = {"minutes": m, "low": m, "high": round(m * FREE_FLOW_KMH / SLOW_KMH), "source": "precomputed road network"}
    todo = [i for i in range(len(dests)) if out[i] is None]
    if todo:
        coords = ";".join(f"{lo:.6f},{la:.6f}" for la, lo in [origin] + [dests[i] for i in todo])
        try:
            req = urllib.request.Request(f"{base}/table/v1/driving/{coords}?sources=0", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                dur = json.load(r)["durations"][0][1:]
            for i, s in zip(todo, dur):
                if s is not None:
                    m = round(s / 60)
                    out[i] = {"minutes": m, "low": m, "high": round(m * FREE_FLOW_KMH / SLOW_KMH),
                              "source": "live OSRM road route, free flow"}
        except Exception as e:  # ponytail: any OSRM failure (timeout, DNS, 5xx, bad JSON) means fall back, logged
            print(f"osrm unavailable, using estimate: {type(e).__name__}: {e}")
    return [o or estimate(origin, d) for o, d in zip(out, dests)]


if __name__ == "__main__":
    o = (26.45, 85.95)
    d = [(26.3650, 86.0800), (26.1520, 85.8970)]
    r = travel(o, d, precomputed={0: 22}, base="https://osrm.invalid", timeout_s=1.0)
    assert r[0]["source"] == "precomputed road network" and r[0]["minutes"] == 22
    assert r[1]["source"].startswith("estimate") and r[1]["low"] < r[1]["high"]
    assert abs(hav_km((0, 0), (0, 1)) - 111.19) < 0.01
    print(json.dumps(r, indent=1))
