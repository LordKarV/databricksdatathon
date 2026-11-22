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
    # Spec section 7 (app_design/APP_EXPERIENCE.md): plan JSON <= 20 KB gzip on the wire. The decoded guard holds the
    # growth: the witness ledger took the largest release plan from 16 KB to 29 KB decoded, 4 to 5.5 KB gzip.
    assert r.headers.get("content-encoding") == "gzip" and int(r.headers["content-length"]) < 20_000
    assert len(r.content) < 32_000, "decoded plan JSON guard is 32 KB"


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


GEO = Path(__file__).resolve().parents[2] / "viz" / "geography" / "data"


def _area(service, lat, lon):
    r = client.post("/api/area", json={"service": service, "lat": lat, "lon": lon})
    assert r.status_code == 200
    return r.json()


@needs_data
def test_area_need_equals_the_committed_district_tables():
    """WS4 4b: Samastipur's brief is the viz/geography row of its LGD district (s1) and NFHS-5 district (s3)."""
    import pandas as pd
    a = _area("emergency_csection", 25.86, 85.78)
    need = a["area"]["need"]
    s1 = pd.read_csv(GEO / "s1_district.csv").query("dtname == 'Samastipur' and stname == 'BIHAR'").iloc[0]
    s3 = pd.read_csv(GEO / "s3_district.csv").query("nfhs_state == 'Bihar' and nfhs_district == 'Samastipur'").iloc[0]
    assert need["population"] == round(s1["pop"]) and need["listings"] == s1.records
    assert need["listings_per_million"] == round(s1.per_m, 2) and need["india_per_million"] == 6.8
    assert need["csection_pct"] == s3.births_delivered_by_csection_5y_pct
    assert need["public_csection_pct"] == s3.births_in_a_public_fac_that_were_delivered_by_csection_5y_pct
    assert need["private_csection_pct"] == s3.births_in_a_private_fac_that_were_delivered_by_csection_5y_pct
    assert need["institutional_pct"] == s3.institutional_birth_5y_pct
    assert "NFHS-5" in need["source"]["nfhs"]
    sadar = [g for g in a["area"]["gov_list"] if g["name"] == "Sadar Hospital Samastipur"]
    assert sadar and sadar[0]["valid_to"] == "2028-03-02" and "LaQshya" in sadar[0]["source"] + sadar[0]["what"]


@needs_data
def test_area_gov_list_and_csection_split_for_gaya():
    a = _area("emergency_csection", 24.79, 85.0)
    need, gov = a["area"]["need"], a["area"]["gov_list"]
    assert (need["public_csection_pct"], need["private_csection_pct"]) == (2.3, 48.3)
    # the NHSRC master data spells it "Sadar Hopsital Piligrim Gaya"; the page shows the source's own name
    pilgrim = [g for g in gov if "Gaya" in g["name"] and g["valid_to"] == "2027-03-31"]
    assert pilgrim and not pilgrim[0]["expired"]
    assert [g["expired"] for g in gov] == sorted(g["expired"] for g in gov)  # valid certificates first
    d = _area("dialysis", 24.79, 85.0)["area"]["gov_list"]
    assert d and d[0]["list"] == "pmndp" and d[0]["districts_total"] == 38
    assert _area("mri", 24.79, 85.0)["area"]["gov_list"] == []


@needs_data
def test_area_uses_the_committed_lgd_district_map():
    """(25.6, 85.95) lies in Begusarai by LGD, not Darbhanga, from app/facts/gov/pin_district_moved.csv alone."""
    a = _area("emergency_csection", 25.6, 85.95)
    assert a["area"]["district"] == "Begusarai" and a["area"]["need"]["lgd_district"] == "Begusarai"


@needs_data
def test_area_headline_from_the_first_call():
    a = _area("emergency_csection", 18.37, 76.57)  # Latur
    assert a["ten_calls"][0]["name"].startswith("Jeevan Jyot")
    assert a["headline"] == {"kind": "if_confirms", "rank": 1, "k": 22, "n": 22, "now": 6, "window_min": 60}
    h = _area("emergency_csection", 25.86, 85.78)["headline"]  # Samastipur: every sampled area is covered
    assert h["kind"] == "all_covered" and h["now"] == h["n"]
    gaya = _area("emergency_csection", 24.79, 85.0)["headline"]  # Gaya: nothing claimed within 60 min
    assert gaya["kind"] == "none_in_window"
