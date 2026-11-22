"""Offline packs by radius: /api/pack/locate names the home pack plus every pack with a facility of its state within
the search radius, and pack.js ranks across all saved packs. Synthetic packs built by build_packs.build_state, so
nothing depends on local builds."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "packs"))
import build_packs as bp

import app as app_module

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
client = TestClient(app_module.app)

PINS = pd.DataFrame([  # pin, state, district, lat, lon
    (841428, "BIHAR", "GOPALGANJ", 26.47, 84.44), (800001, "BIHAR", "PATNA", 25.61, 85.14),
    (274403, "UTTAR PRADESH", "KUSHINAGAR", 26.74, 83.89), (226001, "UTTAR PRADESH", "LUCKNOW", 26.85, 80.95),
], columns=["pin", "state", "district", "lat", "lon"])
FAC = pd.DataFrame([  # three Bihar facilities east of Gopalganj, one UP facility at the border, Lucknow, Patna
    ("b1" * 8, "Gopalganj One", 26.47, 84.50, "BIHAR"), ("b3" * 8, "Gopalganj Two", 26.48, 84.52, "BIHAR"),
    ("b4" * 8, "Gopalganj Three", 26.46, 84.54, "BIHAR"), ("b2" * 8, "Patna Hospital", 25.61, 85.14, "BIHAR"),
    ("u1" * 8, "Border Hospital", 26.62, 84.08, "UTTAR PRADESH"),
    ("u2" * 8, "Lucknow Hospital", 26.85, 80.95, "UTTAR PRADESH"),
    ("u3" * 8, "Lucknow Clinic", 26.86, 80.96, "UTTAR PRADESH"),
], columns=["unique_id", "name", "loc_lat", "loc_lon", "state_final"]).assign(
    loc_conf="high", tel="9999999999", tel_dir=0)
SVC = FAC[["unique_id"]].assign(service="dialysis", likely=0, score=0.5, score_lo=0.3, score_hi=0.7, listings=1,
                                quotes=[[("Dialysis unit open.", "c1")]] * len(FAC))


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    d = tmp_path_factory.mktemp("packs")
    idx = {}
    for st in ["BIHAR", "UTTAR PRADESH"]:
        pack = bp.build_state(st, PINS, FAC, SVC, "2026-11-21")
        _, gz = bp.encode(pack)
        (d / f"{bp.slug(st)}.json.gz").write_bytes(gz)
        idx[bp.slug(st)] = {"state": st, "gzip_bytes": len(gz), "sha256": "x", "built": "2026-11-21",
                            "pts": bp.state_points(st, FAC, SVC)}
    (d / "index.json").write_text(json.dumps({"v": 1, "pts_scale": bp.PTS_SCALE, "packs": idx}))
    old = bp.OUT
    bp.OUT = d
    try:
        bp.write_pin_index(PINS)
    finally:
        bp.OUT = old
    return d


@pytest.fixture
def served(out, monkeypatch):
    monkeypatch.setattr(app_module, "PACKS", out)
    return out


def locate(lat, lon):
    r = client.post("/api/pack/locate", json={"lat": lat, "lon": lon})
    assert r.status_code == 200
    return r.json()


def query(out, slugs, lat, lon):
    paths = ",".join(str(out / f"{s}.json.gz") for s in slugs)
    res = subprocess.run(["node", str(APP / "packs" / "check_loader.mjs"), paths, str(lat), str(lon), "dialysis"],
                         capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def test_border_point_gets_neighbour_pack_and_cross_border_first(served):
    # Home is Bihar (Gopalganj is the nearest PIN); the fix is just west of it, by the UP border hospital.
    lat, lon = 26.55, 84.20
    loc = locate(lat, lon)
    assert loc["slug"] == "bihar"
    assert [p["slug"] for p in loc["packs"]] == ["bihar", "uttar_pradesh"]
    state_only = query(served, ["bihar"], lat, lon)["options"]
    merged = query(served, ["bihar", "uttar_pradesh"], lat, lon)
    assert "Border Hospital" not in [o["name"] for o in state_only]  # Gopalganj's list holds only the 3 nearest
    first = merged["options"][0]
    assert first["name"] == "Border Hospital" and first["state"] == "UTTAR PRADESH"
    assert first["km_straight"] < state_only[0]["km_straight"]
    assert merged["state"] == "BIHAR" and merged["pin"] == 841428
    assert [o["km_straight"] for o in merged["options"]] == sorted(o["km_straight"] for o in merged["options"])
    assert len(merged["options"]) <= 4


def test_interior_point_gets_only_its_state(served):
    loc = locate(26.85, 80.95)  # Lucknow: every Bihar facility is more than 150 km away
    assert loc == {"slug": "uttar_pradesh", "state": "UTTAR PRADESH",
                   "packs": [{"slug": "uttar_pradesh", "state": "UTTAR PRADESH"}]}


@pytest.mark.parametrize("lat, lon", [(26.85, 80.95), (26.47, 84.44), (26.55, 84.20)])
def test_one_pack_ranks_exactly_as_the_single_pack_path(served, lat, lon):
    home = locate(lat, lon)["slug"]
    one = query(served, [home], lat, lon)
    same = query(served, [home, home], lat, lon)  # the merge path (dedupe, re-rank, trim) over one distinct pack
    assert [o["uid8"] for o in same["options"]] == [o["uid8"] for o in one["options"]]


def test_version_hides_facility_points(served):
    j = client.get("/api/pack/version").json()
    assert all("pts" not in m for m in j["packs"].values())
