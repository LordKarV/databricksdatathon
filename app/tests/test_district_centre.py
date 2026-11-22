"""District centres and the nearest-PIN district (matrix clusters district_centre_in_other_district and
area_names_other_district): the centre is a PIN point of the district itself, chosen by the same rule online
(facts/places.py centre_pin) and offline (static/offline.js districtCentre), and the nearest PIN scales longitude
by cos(lat)."""
from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import outcomes  # noqa: E402
from facts.places import Places, centre_pin  # noqa: E402

import app as app_module  # noqa: E402

client = TestClient(app_module.app)
built = app_module._engine() is not None and app_module.PLACES.is_file()


def _pins(rows: list[tuple[int, float, float, str]], state: str = "S") -> dict[str, list]:
    return {"pin": [r[0] for r in rows], "lat": [r[1] for r in rows], "lon": [r[2] for r in rows],
            "district": [r[3] for r in rows], "state": [state] * len(rows)}


def test_centre_is_a_pin_of_the_district_even_when_its_mean_is_nearer_another():
    # A's PINs ring B's only PIN, so the mean of A's points falls on B (as Anakapalli's fell in Visakhapatnam)
    ring = [(100 + i, 17.7 + 0.2 * dy, 82.9 + 0.2 * dx, "A") for i, (dy, dx) in enumerate(
        [(1, 0), (0, 1), (-1, 0), (0, -1), (0.7, 0.7)])]
    p = Places(_pins(ring + [(200, 17.7, 82.9, "B")]), None)
    [m] = p.lookup("A")
    assert (m["lat"], m["lon"]) in {(r[1], r[2]) for r in ring}
    assert outcomes.district(SimpleNamespace(pins=p.pins), m["lat"], m["lon"]) == "A"


def test_two_pins_tie_and_the_lower_pin_wins():
    assert centre_pin([(500, 25000, 85000), (300, 25002, 85004)]) == 300
    assert centre_pin([(300, 25002, 85004), (500, 25000, 85000)]) == 300


def test_nearest_pin_scales_longitude_by_cos_lat():
    # at 60 N a degree of longitude is half a degree of latitude: 0.8 east is nearer than 0.5 north
    eng = SimpleNamespace(pins=_pins([(1, 60.5, 10.0, "NORTH"), (2, 60.0, 10.8, "EAST")]))
    assert outcomes.district(eng, 60.0, 10.0) == "East"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_offline_district_centre_picks_the_same_pin_as_the_server():
    rnd = random.Random(7)
    pins, dist = [], []
    for d in range(60):
        n = rnd.choice([1, 2, 2, 3, 5, 12])  # two PINs always tie
        la, lo = rnd.uniform(8, 34), rnd.uniform(69, 96)
        for _ in range(n):
            pins.append((rnd.randrange(110000, 860000), round(la + rnd.uniform(-0.3, 0.3), 3),
                         round(lo + rnd.uniform(-0.3, 0.3), 3)))
            dist.append(d)
    pack = {"districts": [f"D{d}" for d in range(60)],
            "pins": {"pin": [p[0] for p in pins], "lat": [p[1] for p in pins], "lon": [p[2] for p in pins],
                     "d": dist}}
    js = ("require(process.argv[1]); const pack = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
          "console.log(JSON.stringify(pack.districts.map(d => { const c = RSOffline.districtCentre(pack, d);"
          " return [c.lat, c.lon]; })));")
    out = subprocess.run(["node", "-e", js, str(APP / "static" / "offline.js")], input=json.dumps(pack),
                         capture_output=True, text=True, check=True).stdout
    got = [tuple(x) for x in json.loads(out)]
    want = []
    for d in range(60):
        own = [p for p, x in zip(pins, dist, strict=True) if x == d]
        c = centre_pin([(p[0], round(p[1] * 1000), round(p[2] * 1000)) for p in own])
        want.append(next((p[1], p[2]) for p in own if p[0] == c))
    assert got == want


@pytest.mark.skipif(not built, reason="facts or places not built (app/facts/build.py)")
@pytest.mark.parametrize("district, state", [("Anakapalli", "Andhra Pradesh"), ("Jalandhar", "Punjab"),
                                             ("Hisar", "Haryana")])
def test_area_at_a_district_centre_names_that_district(district, state):
    # the district centre /api/place serves (a town of the same name is listed before it, so read it directly)
    _, _, la, lo = next(c for c in app_module._places().districts[district.lower()] if c[1] == state.upper())
    a = client.post("/api/area", json={"service": "nicu", "lat": round(la, 2), "lon": round(lo, 2)})
    assert a.status_code == 200 and a.json()["area"]["district"].lower() == district.lower()


def test_a_pin_with_a_guessed_district_never_becomes_the_centre():
    import pandas as pd
    from facts.build import centre_flags
    p = pd.DataFrame({"pin": [1, 2, 3], "state": ["S"] * 3, "district": ["A", "A", "A"],
                      "district_from": ["", "", "nearest_pin"], "lat": [25.0, 25.2, 25.1], "lon": [85.0, 85.2, 85.1]})
    assert centre_flags(p) == [1, 0, 0]  # PIN 3 sits on the mean, but the gazetteer does not file it under A
