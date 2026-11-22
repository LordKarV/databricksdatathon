"""POST /api/pack/locate (issue #29): the state comes from the all-India PIN index, not from whichever packs
are built. Uses a temporary pack directory with synthetic data, so it does not depend on local builds."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import app as app_module  # noqa: E402

client = TestClient(app_module.app)

# Three PIN centroids: Sitamarhi (Bihar), Mumbai (Maharashtra), New Delhi (Delhi), scale 1e-3, delta-encoded.
PINS = [(110001, 28.62, 77.21, 1), (400001, 18.94, 72.83, 2), (843302, 26.59, 85.48, 0)]


def _write(out: Path, built: list[str]) -> None:
    out.mkdir()
    lat = [round(p[1] * 1000) for p in PINS]
    lon = [round(p[2] * 1000) for p in PINS]
    (out / "pin_index.json").write_text(json.dumps({
        "v": 1, "scale": 1000, "states": [["bihar", "BIHAR"], ["delhi", "DELHI"], ["maharashtra", "MAHARASHTRA"]],
        "pin": [PINS[0][0]] + [PINS[i][0] - PINS[i - 1][0] for i in range(1, 3)],
        "lat": [lat[0]] + [lat[i] - lat[i - 1] for i in range(1, 3)],
        "lon": [lon[0]] + [lon[i] - lon[i - 1] for i in range(1, 3)],
        "s": [p[3] for p in PINS],
    }))
    (out / "index.json").write_text(json.dumps({"v": 1, "packs": {
        s: {"state": s.upper(), "gzip_bytes": 1, "sha256": "x", "built": "2026-11-21"} for s in built}}))


@pytest.fixture
def packs(tmp_path, monkeypatch):
    def make(built):
        out = tmp_path / ("out_" + "_".join(built or ["none"]))
        _write(out, built)
        monkeypatch.setattr(app_module, "PACKS", out)
    return make


def locate(lat, lon):
    return client.post("/api/pack/locate", json={"lat": lat, "lon": lon})


@pytest.mark.parametrize("lat, lon, slug", [(26.5951, 85.4808, "bihar"), (19.07, 72.88, "maharashtra"),
                                            (28.61, 77.21, "delhi")])
def test_all_built_picks_state_of_nearest_pin(packs, lat, lon, slug):
    packs(["bihar", "delhi", "maharashtra"])
    r = locate(lat, lon)
    assert r.status_code == 200 and r.json()["slug"] == slug


def test_partial_build_never_answers_another_state(packs):
    packs(["bihar"])
    assert locate(26.5951, 85.4808).json() == {"slug": "bihar", "state": "BIHAR",
                                               "packs": [{"slug": "bihar", "state": "BIHAR"}]}
    for lat, lon, slug, state in [(19.07, 72.88, "maharashtra", "MAHARASHTRA"), (28.61, 77.21, "delhi", "DELHI")]:
        r = locate(lat, lon)
        assert r.status_code == 404
        assert r.json().items() >= {"error": "no pack for this state", "slug": slug, "state": state}.items()
        assert r.json()["code"] == "pack_no_state" and state in r.json()["message"]["en"]


def test_nothing_built(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "PACKS", tmp_path / "missing")
    r = locate(26.6, 85.5)
    assert r.status_code == 404 and r.json()["error"] == "no packs built"


def test_locate_validates_body(packs):
    packs(["bihar"])
    assert locate(50, 77).status_code == 422
    assert client.post("/api/pack/locate", json={"lat": 26, "lon": 85, "user": "x"}).status_code == 422
