"""District centres and the nearest-PIN district (matrix clusters district_centre_in_other_district and
area_names_other_district): the centre is a PIN point of the district itself, chosen by the same rule online
(facts/places.py centre_pin) and offline (static/offline.js districtCentre), and the nearest PIN scales longitude
by cos(lat)."""
from __future__ import annotations

import gzip
import json
import math
import random
import shutil
import subprocess
import sys
from itertools import accumulate
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import outcomes  # noqa: E402
from facts.places import Places, centre_pin, centre_pin_kept, kept_pins, norm  # noqa: E402

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


# ---------- the LGD correction (gov/pin_district_moved.csv): a moved PIN never becomes the centre ----------

def test_a_pin_the_lgd_correction_moves_away_is_not_the_centre():
    # PIN 3 sits on A's mean, but its point lies in B (the LGD correction), and the area view there names B
    rows = [(1, 25.0, 85.0, "A"), (2, 25.2, 85.2, "A"), (3, 25.1, 85.1, "A"), (9, 26.0, 86.0, "B")]
    where = [("A", "S"), ("A", "S"), ("B", "S"), ("B", "S")]
    assert Places(_pins(rows), None).districts["a"][0][2:] == (25.1, 85.1)
    assert Places(_pins(rows), None, where).districts["a"][0][2:] == (25.0, 85.0)


def test_a_pin_on_the_point_of_a_moved_pin_listed_first_is_not_the_centre():
    # Lalitpur's 284501 shares its point with 284123, which LGD moves; the area view names the first PIN on a tie
    rows = [(1, 25.0, 85.0, "A"), (2, 25.2, 85.2, "A"), (3, 25.1, 85.1, "A"), (4, 25.1, 85.1, "A")]
    where = [("A", "S"), ("A", "S"), ("B", "S"), ("A", "S")]
    assert Places(_pins(rows), None, where).districts["a"][0][2:] == (25.0, 85.0)  # not PIN 4, on the mean of 1, 2, 4
    # listed after the PIN that stays, the moved one does not matter: the area view at that point names A
    rows[2], rows[3], where[2], where[3] = rows[3], rows[2], where[3], where[2]
    assert Places(_pins(rows), None, where).districts["a"][0][2:] == (25.1, 85.1)


def test_a_district_whose_every_pin_is_moved_keeps_all_of_them():
    pts = [(1, 25000, 85000), (2, 25200, 85200), (3, 25100, 85100)]
    assert centre_pin_kept(pts, [False, False, False]) == (3, False)
    assert centre_pin_kept(pts, [True, True, False]) == (1, True)


def test_centre_flags_leave_out_moved_pins():
    import pandas as pd
    from facts.build import centre_flags
    p = pd.DataFrame({"pin": [1, 2, 3, 4], "state": ["S"] * 4, "district": ["A", "A", "A", "C"],
                      "district_from": [""] * 4, "lat": [25.0, 25.2, 25.1, 27.0], "lon": [85.0, 85.2, 85.1, 87.0]})
    assert centre_flags(p) == [0, 0, 1, 1]
    assert centre_flags(p, {"3": ["B", "S"], "4": ["D", "S"]}) == [1, 0, 0, 1]  # C has only moved PINs: all count
    q = pd.concat([p.iloc[[2]].assign(pin=5), p], ignore_index=True)  # PIN 5 first, on PIN 3's point, both in A
    assert centre_flags(q) == [0, 0, 0, 1, 1]
    assert centre_flags(q, {"5": ["B", "S"]}) == [0, 1, 0, 0, 1]  # 3 is on moved 5's point: neither is the centre
    assert centre_flags(q.iloc[::-1], {"5": ["B", "S"]}) == [1, 1, 0, 0, 0]  # PINs 4, 3, 2, 1, 5: 3 before 5 stays


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_offline_district_centre_skips_moved_pins_as_the_server_does():
    rnd = random.Random(11)
    pins, dist = [], []
    for d in range(60):
        la, lo = rnd.uniform(8, 34), rnd.uniform(69, 96)
        for _ in range(rnd.choice([1, 2, 3, 5, 12])):
            pins.append((rnd.randrange(110000, 860000), round(la + rnd.uniform(-0.3, 0.3), 3),
                         round(lo + rnd.uniform(-0.3, 0.3), 3)))
            dist.append(d)
    moved = sorted({p[0] for p in pins if rnd.random() < 0.4})
    pack = {"districts": [f"D{d}" for d in range(60)],
            "pins": {"pin": [p[0] for p in pins], "lat": [p[1] for p in pins], "lon": [p[2] for p in pins],
                     "d": dist, "not_centre": moved}}
    js = ("require(process.argv[1]); const pack = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
          "console.log(JSON.stringify(pack.districts.map(d => { const c = RSOffline.districtCentre(pack, d);"
          " return [c.lat, c.lon]; })));")
    out = subprocess.run(["node", "-e", js, str(APP / "static" / "offline.js")], input=json.dumps(pack),
                         capture_output=True, text=True, check=True).stdout
    want = []
    for d in range(60):
        own = [p for p, x in zip(pins, dist, strict=True) if x == d]
        c, _ = centre_pin_kept([(p[0], round(p[1] * 1000), round(p[2] * 1000)) for p in own],
                               [p[0] not in moved for p in own])
        want.append(next((p[1], p[2]) for p in own if p[0] == c))
    assert [tuple(x) for x in json.loads(out)] == want


PACKS = APP / "packs" / "out"
packs_built = built and (PACKS / "index.json").is_file() and shutil.which("node") is not None


def _pack_files() -> list[Path]:
    return [PACKS / f"{slug}.json.gz" for slug in json.loads((PACKS / "index.json").read_text())["packs"]]


def _offline_centres() -> dict[tuple[str, str], tuple[int, int]]:
    """{(state, district): (lat, lon) in 0.001 degree} from every built pack, by pack.js decode and districtCentre."""
    js = ("require(process.argv[1]); require(process.argv[2]); const fs = require('fs'), z = require('zlib');"
          "const out = {}; for (const f of process.argv.slice(3)) {"
          " const p = RSPack.decode(JSON.parse(z.gunzipSync(fs.readFileSync(f))));"
          " for (const d of p.districts) if (d) { const c = RSOffline.districtCentre(p, d);"
          "  out[p.state + '|' + d] = [Math.round(c.lat * 1000), Math.round(c.lon * 1000)]; } }"
          "console.log(JSON.stringify(out));")
    out = subprocess.run(["node", "-e", js, str(APP / "static" / "pack.js"), str(APP / "static" / "offline.js"),
                          *map(str, _pack_files())], capture_output=True, text=True, check=True).stdout
    return {tuple(k.split("|", 1)): tuple(v) for k, v in json.loads(out).items()}


@pytest.mark.skipif(not packs_built, reason="facts, places or packs not built, or node not installed")
def test_every_district_centre_stays_in_its_district_after_lgd_and_online_equals_offline():
    eng, places = app_module._engine(), app_module._places()
    p = eng.pins
    members: dict[tuple[str, str], list[int]] = {}
    for j, (d, s) in enumerate(zip(p["district"], p["state"], strict=True)):
        if not p["district_from"][j]:
            members.setdefault((s, d), []).append(j)
    kept = kept_pins(p["lat"], p["lon"], list(zip(p["district"], p["state"], strict=True)), eng.pin_where)
    lat, lon = np.array(p["lat"]), np.array(p["lon"])
    online, all_moved = {}, []
    for (s, d), idx in members.items():
        [j] = [i for i in idx if p["centre"][i]]
        # the PIN Engine.area takes as nearest to the centre (lowest index on a tie), whose district it names
        k = int(np.argmin((lat - lat[j]) ** 2 + ((lon - lon[j]) * math.cos(math.radians(lat[j]))) ** 2))
        if not any(kept[i] for i in idx):
            all_moved.append((s, d))  # no PIN of the district stays there: the centre comes from all of them
        else:
            assert eng.pin_where[k] == (d, s), f"{d}, {s}: centre PIN {p['pin'][j]}, area names {eng.pin_where[k]}"
        assert (d, s, p["lat"][j], p["lon"][j]) in places.districts[norm(d)]  # what /api/place serves
        online[(s, d)] = p["pin"][j]
    assert len(all_moved) < 0.02 * len(members)
    at = {}
    for f in _pack_files():
        pins = json.loads(gzip.decompress(f.read_bytes()))["pins"]
        at.update(zip(accumulate(pins["pin"]), zip(accumulate(pins["lat"]), accumulate(pins["lon"]), strict=True),
                      strict=True))
    assert {k: at[v] for k, v in online.items()} == _offline_centres()
