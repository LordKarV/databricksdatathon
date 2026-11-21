"""Pack endpoints and the pack.js loader (issue #9). Skips when app/packs/out is not built."""
import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from app import app  # noqa: E402

OUT = APP / "packs" / "out"
pytestmark = pytest.mark.skipif(not (OUT / "index.json").is_file(), reason="packs not built")
client = TestClient(app)


def test_version_lists_every_pack_file():
    j = client.get("/api/pack/version").json()
    assert j["v"] == 1 and "bihar" in j["packs"]
    for slug, meta in j["packs"].items():
        assert (OUT / f"{slug}.json.gz").stat().st_size == meta["gzip_bytes"]


def test_pack_served_pre_gzipped_once():
    r = client.get("/api/pack/bihar", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip" and r.headers["content-type"].startswith("application/json")
    assert r.headers["cache-control"] == "no-cache"
    assert int(r.headers["content-length"]) == (OUT / "bihar.json.gz").stat().st_size, "compressed twice?"
    pack = r.json()  # httpx decodes the gzip; a double encoding would fail here
    assert pack["state"] == "BIHAR" and pack["v"] == 1
    assert json.loads(gzip.decompress((OUT / "bihar.json.gz").read_bytes())) == pack


@pytest.mark.parametrize("path", ["/api/pack/atlantis", "/api/pack/..%2Fapp.py", "/api/pack/index",
                                  "/api/pack/bihar.json.gz", "/api/pack/%2E%2E"])
def test_unknown_or_traversal_slug_404(path):
    assert client.get(path).status_code == 404


def test_pack_js_is_a_shell_file():
    r = client.get("/pack.js")
    assert r.status_code == 200 and "RSPack" in r.text


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_loader_query_bihar_dialysis():
    out = subprocess.run(["node", str(APP / "packs" / "check_loader.mjs"), str(OUT / "bihar.json.gz"),
                          "26.5951", "85.4808", "dialysis"], capture_output=True, text=True, check=True)
    res = json.loads(out.stdout)
    assert res["pin"] and res["district"] and res["km_to_pin"] < 25
    opts = res["options"]
    assert len(opts) >= 3 and all(o["name"] for o in opts)
    assert [o["km_straight"] for o in opts] == sorted(o["km_straight"] for o in opts)
    for o in opts:
        assert 0 <= o["lo"] <= o["p"] <= o["hi"] <= 1
        for q in o["quotes"]:
            assert q["text"]
            assert q["claim_id"] is None or q["claim_id"].startswith(o["uid8"] + ":")
    assert any(q["claim_id"] for o in opts for q in o["quotes"]), "no quote carries a claim id"


@pytest.mark.parametrize("lat, lon, slug", [(26.5951, 85.4808, "bihar"), (19.07, 72.88, "maharashtra"),
                                            (28.61, 77.21, "delhi")])
def test_locate_picks_state_of_nearest_pin(lat, lon, slug):
    r = client.post("/api/pack/locate", json={"lat": lat, "lon": lon})
    assert r.status_code == 200 and r.json()["slug"] == slug


def test_locate_validates_body():
    assert client.post("/api/pack/locate", json={"lat": 50, "lon": 77}).status_code == 422
    assert client.post("/api/pack/locate", json={"lat": 26, "lon": 85, "user": "x"}).status_code == 422
    assert client.get("/api/pack/locate").status_code == 404  # GET /api/pack/{slug}: not a pack name
