"""Route guard (#140 WS2 2c) on the built data: named cases and a seeded 50-point sweep over PIN centres.

Rule 1 reading (lead, D1 on #140): a route is dropped as "past card 1" only when card 1 is Likely AND has evidence
for every stage itself (the planner's first_stop: first care met, nothing missing for definitive care). A Likely
card 1 that lacks a definitive capability keeps its route: the Gaya trauma hero stabilises there, then goes on.
Skips when app/facts/out or planner/out is not built.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import itinerary  # noqa: E402
from facts.engine import Engine  # noqa: E402
from services import SERVICES  # noqa: E402

ENGINE = Engine.load()
SVC = itinerary._planner()
BUILT = ENGINE is not None and SVC is not None and SVC.store() is not None
pytestmark = pytest.mark.skipif(not BUILT, reason="app/facts/out or planner/out not built")
SPINE = ("spine", "endospine", "acl ")


def post(service: str, lat: float, lon: float) -> dict:
    return itinerary.attach(ENGINE.plan(service, lat, lon, 40, "gps"), ENGINE)


def route(p: dict, k: int = 0) -> dict:
    return p["itinerary"]["plans"][k]


def test_gaya_csection_shows_no_spine_quote_as_obstetric_evidence():
    p = post("emergency_csection", 24.79, 85.0)
    for r in p["itinerary"]["plans"]:
        for s in r["stops"]:
            assert not any(w in e["quote"].lower() for e in s["evidence"] for w in SPINE), (s["name"], s["evidence"])
            assert s["evidence"] or s["note"], s["name"]
    s1 = route(p)["stops"][0]
    if not s1["evidence"]:  # Vardaan Hospital & Maternity Center: no line of its own about obstetric care
        assert s1["note"] == "No line in its listing names basic emergency obstetric care; ask on the phone."


def test_gaya_csection_route_has_no_stop_with_location_doubt():
    # Typed "Gaya town": the route went on to SDH Pusa, whose map point is 39 km from Pusa (#147 LOC_COORDS_FAR).
    p = itinerary.attach(ENGINE.plan("emergency_csection", 24.79, 84.99, None, "place"), ENGINE)
    assert p["itinerary"]["plans"]
    for r in p["itinerary"]["plans"]:
        for s in r["stops"]:
            assert not ENGINE._doubt(ENGINE.fid[s["facility_id"]]), (r["rank"], s["name"])


def test_gaya_trauma_hero_keeps_its_one_stop_route():
    p = post("trauma_emergency", 24.79, 85.0)
    r, o = route(p), p["options"][0]
    assert o["name"] == "Dr. A Barkat Multispeciality Hospital" and o["band"] == "likely"
    assert r["type"] == "one_stop" and p["itinerary"]["itinerary_note"] is None
    assert [s["name"] for s in r["stops"]] == ["Dr. A Barkat Multispeciality Hospital",
                                              "All India Institute of Medical Sciences Patna"]
    assert r["vs_direct"]["direct_minutes"] and all(s["evidence"] for s in r["stops"])


def test_runner_up_miracare_keeps_its_route():
    p = post("trauma_emergency", 25.42, 86.13)
    r = route(p)
    assert p["options"][0]["name"] == "Miracare Hospital" and p["itinerary"]["itinerary_note"] is None
    assert [s["name"] for s in r["stops"]] == ["Miracare Hospital", "Ganpati Hospital"]


def test_sheohar_csection_stop_1_quotes_its_own_listing():
    # Harsh Hospital (map point in doubt) and SDH Pusa are no route stops, so the route starts at Mishra Hospital
    # and leads the cards (#121); its stop 1 quotes must still name obstetric care.
    p = post("emergency_csection", 26.51, 85.29)
    s1 = route(p)["stops"][0]
    assert s1["name"] == "Mishra Hospital Test Tube Baby Centre" == p["options"][0]["name"]
    assert s1["evidence"] and all(itinerary.stage_pattern(("basic_emoc",)).search(e["quote"]) for e in s1["evidence"])
    assert route(p)["vs_direct"]["direct_minutes"] == 156


def test_lucknow_burns_stop_1_off_the_list_has_a_note():
    p = post("burn_care", 26.85, 80.95)
    it = p["itinerary"]
    s1 = route(p)["stops"][0]
    assert s1["facility_id"] not in {o["facility_id"] for o in p["options"]}
    assert it["fallback"] and it["stop_1_note"].startswith(f"The route starts at {s1['name']}")


def test_patna_dialysis_stop_1_has_a_dialysis_quote():
    p = post("dialysis", 25.6, 85.14)
    s1 = route(p)["stops"][0]
    assert s1["purpose"] == "assess" and s1["evidence"] and s1["note"] is None
    assert all("dialysis" in e["quote"].lower() for e in s1["evidence"])  # haemodialysis implies a nephrologist


def test_a_card_1_with_every_stage_drops_the_far_routes():
    # Bengaluru C-section: card 1 Bowring is Likely with evidence for both stages; the farther route goes.
    p = post("emergency_csection", 13.0, 77.57)
    o, it = p["options"][0], p["itinerary"]
    assert o["band"] == "likely" and it["itinerary_note"] == (
        f"Go straight to {o['name']}; it is nearer than any other place with evidence for every stage.")
    assert all(not itinerary.past_card_1(r, o) for r in it["plans"])


def sweep() -> dict[str, int]:
    """50 PIN centres (seed 140) x every service with a care pathway, through attach() as /api/plan runs it."""
    rng = random.Random(140)
    pins = ENGINE.pins
    pts = [(round(pins["lat"][i], 2), round(pins["lon"][i], 2)) for i in rng.sample(range(len(pins["pin"])), 50)]
    c = dict.fromkeys(("cases", "routes", "stops", "past_card_1", "past_card_1_kept_by_d1", "no_quote_no_note",
                       "stop_1_off_list_no_note", "notes", "itinerary_notes"), 0)
    for la, lo in pts:
        for s in (s for s in SERVICES if SVC.pathway_for(s)):
            p = post(s, la, lo)
            c["cases"] += 1
            it, opts = p["itinerary"], p["options"]
            if not it:
                continue
            c["itinerary_notes"] += bool(it["itinerary_note"])
            for r in it["plans"]:
                c["routes"] += 1
                for st in r["stops"]:
                    c["stops"] += 1
                    c["notes"] += bool(st["note"])
                    c["no_quote_no_note"] += not st["evidence"] and not st["note"]
            if it["plans"] and opts and opts[0]["band"] == "likely" and any(itinerary.past_card_1(r, opts[0])
                                                                         for r in it["plans"]):
                fs = SVC.plan_for_service(s, la, lo, first_stop=opts[0]["facility_id"]).get("first_stop")
                c["past_card_1" if itinerary.covers_every_stage(opts[0], fs) else "past_card_1_kept_by_d1"] += 1
            if it["plans"] and it["plans"][0]["stops"][0]["facility_id"] not in {o["facility_id"] for o in opts}:
                c["stop_1_off_list_no_note"] += not it["stop_1_note"]
    return c


def test_seeded_50_point_sweep():
    c = sweep()
    print("route guard sweep:", c)
    assert c["cases"] == 250 and c["routes"] > 100
    assert c["past_card_1"] == 0 and c["no_quote_no_note"] == 0 and c["stop_1_off_list_no_note"] == 0
