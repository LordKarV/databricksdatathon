"""An LGD move (app/facts/gov/pin_district_moved.csv) never names a district its state does not have.

Durg and Pratapgarh (Uttar Pradesh) share LGD code 378 in gov/district_lgd.csv, so the committed map moved 11
Chhattisgarh PINs to "PRATAPGARH, CHHATTISGARH" and the area view at Bhilai named it; 782470 moved to West Jaintia
Hills, Assam (a Meghalaya district). facts/build.py moved_pins skips such moves."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from facts import build  # noqa: E402
from facts.places import norm  # noqa: E402

import app as app_module  # noqa: E402

client = TestClient(app_module.app)
ENGINE = app_module._engine()
needs_data = pytest.mark.skipif(ENGINE is None, reason="facility data not built (app/facts/build.py)")
needs_v1 = pytest.mark.skipif(not (build.V1 / "pin_gazetteer.parquet").is_file(), reason="derived/v1 not present")
GAZETTEER = {"492002": ("RAIPUR", "CHHATTISGARH"), "491002": ("DURG", "CHHATTISGARH")}


def _districts(pins: dict | pd.DataFrame) -> set[tuple[str, str]]:
    return {(norm(s), norm(d)) for d, s in zip(pins["district"], pins["state"], strict=True)}


def _foreign(moved: dict[str, list[str]], have: set[tuple[str, str]]) -> dict[str, list[str]]:
    return {p: w for p, w in moved.items() if (norm(w[1]), norm(w[0])) not in have}


def test_a_move_to_a_district_the_state_does_not_have_is_skipped():
    p = pd.DataFrame({"pin": [1, 2, 3], "state": ["S", "S", "T"], "district": ["A", "B", "C"]})
    moved = {"1": ["b", "S"], "2": ["C", "S"], "3": ["A District", "T"]}
    assert build.foreign_moves(moved, p) == {"2", "3"}


@needs_v1
def test_every_applied_lgd_move_names_a_district_of_its_state():
    assert _foreign(build.moved_pins(), _districts(build.pin_table(build.V1))) == {}


@needs_data
def test_every_lgd_move_the_app_reads_names_a_district_of_its_state():
    moved = json.loads((build.OUT / "pin_districts.json").read_text())
    assert _foreign(moved, _districts(ENGINE.pins)) == {}
    assert {(norm(s), norm(d)) for d, s in ENGINE.pin_where} <= _districts(ENGINE.pins)


@needs_data
def test_area_at_bhilai_names_durg():
    r = client.post("/api/area", json={"service": "trauma_emergency", "lat": 21.12, "lon": 81.23})
    assert r.status_code == 200
    a = r.json()["area"]
    assert (a["district"], a["state"]) == ("Durg", "Chhattisgarh")


@needs_data
@pytest.mark.parametrize("pin", sorted(GAZETTEER))
def test_a_pin_the_bad_move_took_keeps_its_gazetteer_district(pin):
    i = ENGINE.pins["pin"].index(int(pin))
    assert ENGINE.pin_where[i] == GAZETTEER[pin]
    r = client.post("/api/area", json={"service": "trauma_emergency", "lat": ENGINE.pins["lat"][i],
                                       "lon": ENGINE.pins["lon"][i]})
    assert r.status_code == 200
    assert r.json()["area"]["district"].upper() == GAZETTEER[pin][0]
