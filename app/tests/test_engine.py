"""Real facilities behind the plan contract (issue #42). Skips when app/facts/out is not built."""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import app as app_module  # noqa: E402
import itinerary  # noqa: E402
from facts.engine import Engine  # noqa: E402
from services import SERVICES  # noqa: E402

ENGINE = app_module._engine()
pytestmark = pytest.mark.skipif(ENGINE is None, reason="facility data not built (app/facts/build.py)")
client = TestClient(app_module.app)

# The three release queries from the issue.
QUERIES = {
    "gaya_dialysis": ("dialysis", 24.79, 85.0),
    "maharashtra_csection": ("emergency_csection", 19.88, 75.34),
    "nh19_trauma_mohania": ("trauma_emergency", 25.15, 83.68),
}


def plans():
    return {k: ENGINE.plan(s, la, lo, 40, "gps") for k, (s, la, lo) in QUERIES.items()}


@pytest.mark.parametrize("name", QUERIES)
def test_release_queries_answer_from_real_rows(name):
    s, la, lo = QUERIES[name]
    t = time.perf_counter()
    r = client.post("/api/plan", json={"service": s, "lat": la, "lon": lo, "accuracy_m": 40})
    ms = (time.perf_counter() - t) * 1000
    print(f"{name}: {ms:.0f} ms, {len(r.content)} B")
    assert r.status_code == 200 and ms < 500 and len(r.content) < 20_000
    j = r.json()
    assert j["meta"]["stub"] is False and j["options"]
    for o in j["options"]:
        assert o["facility_id"] in ENGINE.fid and "(sample)" not in o["name"]


def test_bands_are_conservative_and_points_reproduce_p():
    for p in plans().values():
        for o in p["options"]:
            pr = ENGINE.index[p["query"]["service"]][ENGINE.fid[o["facility_id"]]]
            assert (o["band"] == "likely") == (pr.status == "verified_true")
            assert o["band"] != "unlikely"  # never offered as an option
            total = sum(c["points"] for c in o["contributions"])
            assert abs(1 / (1 + math.exp(-total / 10)) - o["p"]) < 0.03, (o["name"], total, o["p"])


def test_evidence_is_verbatim_own_offer_sentences():
    for p in plans().values():
        for o in p["options"]:
            assert len(o["evidence"]) <= 3
            for e in o["evidence"]:
                field, text, nonoffer, attribution = ENGINE.claims[e["claim_id"]]
                assert e["quote"] == text and e["field"] == field
                assert not nonoffer and attribution != "other_facility"
                assert e["claim_id"].split(":")[0] == o["facility_id"][:8]


def test_abstains_when_nothing_is_confirmed():
    for p in plans().values():
        if not any(o["band"] == "likely" for o in p["options"]):
            assert p["abstain"] and p["abstain"]["text"]
    empty = ENGINE.plan("burn_care", 34.5, 77.5, None, "gps")  # Ladakh: nothing within reach in the data
    assert empty["options"] == [] and "lists burn care" in empty["abstain"]["text"]


def test_score_is_the_single_swap_point(monkeypatch):
    def everything_likely(self, facility_id, service_id):
        return "likely", 0.9, 0.8, 0.95, [{"label": "test model", "points": 22}], []

    monkeypatch.setattr(Engine, "score", everything_likely)
    p = ENGINE.plan("dialysis", 24.79, 85.0, 40, "gps")
    assert p["abstain"] is None and all(o["band"] == "likely" and o["p"] == 0.9 for o in p["options"])


def test_area_from_real_rows():
    a = client.post("/api/area", json={"service": "trauma_emergency", "lat": 25.15, "lon": 83.68}).json()
    s = a["summary"]
    assert a["area"]["district"] == "Kaimur (Bhabua)" and s["n_pins"] == len(a["pins"]) > 0
    assert s["access_now"] <= s["access_if_confirmed"]
    assert math.isclose(s["calls_could_close"], s["access_if_confirmed"] - s["access_now"], abs_tol=0.011)
    assert math.isclose(s["no_public_evidence"], 1 - s["access_if_confirmed"], abs_tol=0.011)
    assert s["n_without_option"] == sum(r["first"] is None for r in a["pins"])
    assert all(c["facility_id"] in ENGINE.fid for c in a["ten_calls"]) and len(a["ten_calls"]) <= 10


def test_503_when_data_not_built(monkeypatch):
    monkeypatch.setattr(app_module, "_engine", lambda: None)
    assert client.post("/api/plan", json={"service": "mri", "lat": 20, "lon": 78}).status_code == 503
    assert client.post("/api/area", json={"service": "mri", "lat": 20, "lon": 78}).status_code == 503


def test_every_service_has_rows():
    assert set(ENGINE.pairs) == set(SERVICES) and all(ENGINE.pairs[s] for s in SERVICES)


def test_nearer_first_but_a_confirmed_listing_in_reach_is_never_hidden():
    p = ENGINE.plan("dialysis", 26.6, 85.48, 40, "gps")  # Sitamarhi: the only verified pair is about 150 km away
    bands = [o["band"] for o in p["options"]]
    assert "likely" in bands and p["abstain"] is None
    likely = next(o for o in p["options"] if o["band"] == "likely")
    assert likely["rank"] == len(p["options"])  # far away, so it takes the last slot rather than the first
    assert p["options"][0]["travel"]["minutes"] < likely["travel"]["minutes"]


# ---------- multi-stop route (#47) ----------
ROUTED = itinerary.itinerary(ENGINE, "trauma_emergency", 25.15, 83.68) if ENGINE else None
needs_planner = pytest.mark.skipif(ROUTED is None, reason="planner/out not built (planner/export_v1.py)")


@needs_planner
@pytest.mark.parametrize("name", QUERIES)
def test_route_rides_along_in_budget(name):
    s, la, lo = QUERIES[name]
    t = time.perf_counter()
    r = client.post("/api/plan", json={"service": s, "lat": la, "lon": lo, "accuracy_m": 40})
    ms = (time.perf_counter() - t) * 1000
    it = r.json()["itinerary"]
    assert r.status_code == 200 and ms < 500 and len(r.content) < 20_000, (ms, len(r.content))
    assert it["pathway"] and (it["plans"] or it["abstain"])
    for plan in it["plans"]:
        assert plan["stops"][-1]["purpose"] in ("definitive", "recurring")
        for st in plan["stops"]:
            assert st["eta_low"] <= st["eta_high"] and 0 <= st["p"] <= 1
            for e in st["evidence"]:  # quotes are the claim rows' own text, never another facility's sentence
                field, text, nonoffer, attribution = ENGINE.claims[e["claim_id"]]
                assert e["quote"] == text and not nonoffer and attribution != "other_facility"


@needs_planner
def test_route_does_not_change_the_options():
    plain = ENGINE.plan("trauma_emergency", 25.15, 83.68, 40, "gps")
    routed = client.post("/api/plan", json={"service": "trauma_emergency", "lat": 25.15, "lon": 83.68,
                                            "accuracy_m": 40}).json()
    assert [o["facility_id"] for o in routed["options"]] == [o["facility_id"] for o in plain["options"]]


def test_no_route_without_a_pathway_or_a_planner(monkeypatch):
    assert client.post("/api/plan", json={"service": "mri", "lat": 24.79, "lon": 85.0}).json()["itinerary"] is None
    monkeypatch.setattr(itinerary, "_planner", lambda: None)  # planner not shipped
    r = client.post("/api/plan", json={"service": "trauma_emergency", "lat": 25.15, "lon": 83.68}).json()
    assert r["itinerary"] is None and r["options"]


@needs_planner
def test_no_route_when_planner_data_missing(monkeypatch):
    svc = itinerary._planner()

    def not_built(*a, **k):
        raise RuntimeError("planner data not built")

    monkeypatch.setattr(svc, "plan_for_service", not_built)
    r = client.post("/api/plan", json={"service": "trauma_emergency", "lat": 25.15, "lon": 83.68}).json()
    assert r["itinerary"] is None and r["options"]
