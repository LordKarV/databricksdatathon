"""Contract tests for the plan API on real derived/v1 rows (#42). Run from app/: python -m pytest tests -q"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as app_module
from app import app
from services import SERVICES

client = TestClient(app)
needs_data = pytest.mark.skipif(app_module._engine() is None, reason="facility data not built (app/facts/build.py)")
OPTION_KEYS = {"facility_id", "name", "lat", "lon", "travel", "band", "band_word", "p", "p_lo", "p_hi",
               "evidence", "contributions", "flags", "call_ahead"}


def get(**params):
    """POST /api/plan, the endpoint the page uses (name kept short for the tests below)."""
    return client.post("/api/plan", json=params)


@needs_data
@pytest.mark.parametrize("service", sorted(SERVICES))
def test_contract_shape(service):
    r = get(service=service, lat=26.5951, lon=85.4808, accuracy_m=40.4)
    assert r.status_code == 200
    j = r.json()
    assert j["location"] == {"lat": 26.6, "lon": 85.48, "accuracy_m": 40, "source": "gps", "rounded_to_deg": 0.01}
    assert j["as_of"] and j["meta"]["stub"] is False
    assert j["emergency_numbers"][0]["number"] == "108"
    assert j["options"] or j["abstain"], "either options to call or a clean abstention"
    for o in j["options"]:
        assert OPTION_KEYS <= o.keys()
        assert o["band"] in {"likely", "not_verified", "unlikely"}
        assert 0 <= o["p_lo"] <= o["p_hi"] <= 1
        if o["range_kind"] == "interval":  # v2's lo-hi is the score bin's record, which p need not lie inside
            assert o["p_lo"] <= o["p"] <= o["p_hi"]
        assert o["travel"]["method"] in {"osrm", "haversine_factor"}
        assert o["travel"]["low"] <= o["travel"]["minutes"] <= o["travel"]["high"]
        assert {"km", "method", "cached", "factor", "kmh", "terrain", "label"} <= o["travel"].keys()
        for e in o["evidence"]:
            assert {"claim_id", "field", "quote", "source_url"} <= e.keys()
        for c in o["call_ahead"]:
            assert c["question"] and c["asked_because"]
    assert len(r.content) < 20_000, "plan JSON budget is 20 KB (spec section 7)"


@needs_data
def test_abstention_shape():
    j = get(service="nicu", lat=19.9, lon=83.17).json()  # Kalahandi: no confirmed NICU in reach on v2
    assert j["abstain"]["text"]
    assert all(o["band"] != "likely" for o in j["options"])
    assert {n["number"] for n in j["emergency_numbers"]} == {"108", "102"}


@needs_data
def test_coordinates_rounded_before_use():
    j = get(service="dialysis", lat=26.59951, lon=85.48049, source="pin").json()
    assert (j["location"]["lat"], j["location"]["lon"], j["location"]["source"]) == (26.6, 85.48, "pin")


@pytest.mark.parametrize("params", [
    {"service": "nope", "lat": 20, "lon": 78},
    {"service": "mri", "lat": 50, "lon": 78},
    {"service": "mri", "lat": 20, "lon": 120},
    {"service": "mri", "lat": 20, "lon": 78, "source": "ip"},
    {"service": "mri", "lat": 20},
])
def test_rejects_bad_input(params):
    assert get(**params).status_code == 422


def test_shell_allowlist():
    for path, ctype in [("/", "text/html"), ("/app.js", "text/javascript"), ("/sw.js", "text/javascript"),
                        ("/app.css", "text/css"), ("/manifest.webmanifest", "application/manifest+json")]:
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith(ctype)
        assert r.headers["cache-control"] == "no-cache"
    assert client.get("/app.py").status_code == 404
    assert client.get("/stub_data.py").status_code == 404
    assert client.get("/docs").status_code == 404


@needs_data
def test_dev_alias_matches_post():
    params = {"service": "mri", "lat": 26.5951, "lon": 85.4808, "accuracy_m": 12, "source": "manual"}
    a, b = client.post("/api/plan", json=params).json(), client.get("/api/recommend", params=params).json()
    for j in (a, b):
        j["meta"].pop("generated_at")
    assert a == b and a["query"]["depth"] == "quick"


def test_plan_rejects_unknown_fields_and_get():
    assert get(service="mri", lat=20, lon=78, user_id="x").status_code == 422
    assert get(service="mri", lat=20, lon=78, depth="deep").status_code == 422
    assert client.get("/api/plan").status_code == 405


def test_main_reads_databricks_port(monkeypatch):
    import runpy

    import uvicorn
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: seen.update(k))
    monkeypatch.setenv("DATABRICKS_APP_PORT", "8123")
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "main.py"), run_name="__main__")
    assert seen["port"] == 8123 and seen["access_log"] is False and seen["host"] == "0.0.0.0"


def test_stub_travel_comes_from_geo_module():
    from geo.travel import estimate

    import stub_data
    assert stub_data._geo_estimate is estimate
    o = get(service="dialysis", lat=26.5951, lon=85.4808).json()["options"][0]
    assert o["travel"] == estimate((26.6, 85.48), (o["lat"], o["lon"]))
    assert "40 km/h" not in o["travel"]["label"]


@pytest.mark.parametrize("path,body", [
    ("/api/plan", '{"service": "dialysis", "lat": NaN, "lon": 85.1}'),
    ("/api/plan", '{"service": "dialysis", "lat": 25.6, "lon": 85.1, "accuracy_m": 1e400}'),
    ("/api/plan", '{"service": "dialysis", "lat": 25.6, "lon": 85.1, "accuracy_m": 1e9}'),
    ("/api/area", '{"service": "dialysis", "lat": Infinity, "lon": 85.1}'),
    ("/api/pack/locate", '{"lat": 25.6, "lon": NaN}'),
    ("/api/outcome", ('{"outcome_id": "00000000-0000-4000-8000-000000000000", "facility_id": "x", "service_id": "y",'
                      ' "outcome": "yes", "said_at_ms": 99999999999999999999, "lat": 25.6, "lon": 85.1}')),
])
def test_non_finite_or_huge_numbers_are_422(path, body):
    # #85: these returned 500 before; every request model forbids NaN/inf and bounds its numbers
    r = client.post(path, content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 422
