"""app/itinerary.py helpers without the built data: the route guard's words, name stripping and drop rule (#140 2c)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import itinerary  # noqa: E402
from itinerary import (  # noqa: E402
    CAPABILITY_STEMS,
    capability_patterns,
    guard,
    guard_led,
    stage_caps,
    stage_pattern,
    without_name,
)

itinerary._planner()  # puts the repo root on sys.path for planner.implied


def test_every_pathway_capability_has_words():
    import json
    kb = json.loads(itinerary.CAPABILITIES_PATH.read_text())["capabilities"]
    pats = capability_patterns()
    for c in kb:
        assert c["id"] in CAPABILITY_STEMS, c["id"]  # the stems are the main list; the kb phrases only add to them
        for w in c["evidence_words"]:  # each kb phrase matches its own tag
            assert pats[c["id"]].search(w), (c["id"], w)


@pytest.mark.parametrize("cap, yes, no", [
    ("basic_emoc", ["Obstetrics and gynaecology", "Normal delivery", "Labour room open", "Care in pregnancy"],
     ["Destandau Endospine (endoscopic spine) surgery", "Laboratory services", "ACL treatment"]),
    ("emergency_24x7", ["Provides 24/7 emergency care", "Casualty open round the clock", "24x7 Emergency"],
     ["Dental clinic", "Physiotherapy"]),
    ("orthopaedics", ["Orthopaedic surgery", "Fracture management"], ["Orthodontics", "Ophthalmology"]),
    ("comprehensive_emoc", ["Caesarean Section", "C-section", "LSCS"], ["Section of cardiology"]),
    ("ct_scan", ["CT scan", "128-slice CT"], ["Cardiac care"]),
    ("haemodialysis_unit", ["Hemodialysis unit", "Continuous Renal Replacement Therapy (CRRT)"], ["Kidney stones"]),
])
def test_capability_words(cap, yes, no):
    pat = capability_patterns()[cap]
    assert all(pat.search(t) for t in yes), [t for t in yes if not pat.search(t)]
    assert not any(pat.search(t) for t in no), [t for t in no if pat.search(t)]


def test_a_stage_takes_the_tags_that_imply_it():
    # planner.implied: a haemodialysis unit implies nephrology, comprehensive obstetric care implies basic
    assert stage_pattern(("nephrology", "laboratory")).search("Hemodialysis is performed")
    assert stage_pattern(("basic_emoc",)).search("Caesarean Section")
    assert not stage_pattern(("basic_emoc",)).search("Spine surgery")


def test_the_facility_name_is_not_evidence():
    name = "Vardaan Hospital & Maternity Center"
    q = "Destandau Endospine (endoscopic spine) surgery is practiced at Vardaan hospital and maternity centre"
    assert not stage_pattern(("basic_emoc",)).search(without_name(q, name))
    assert stage_pattern(("basic_emoc",)).search(without_name("The Maternity ward has a labour room", name))
    assert without_name("Maternity care at Vardaan", name) == "maternity care at vardaan"  # one name word stays


def test_stage_caps_reads_requires_all_and_any():
    pw = {"stages": [{"id": "d", "requires_all": ["a", "b"], "requires_any": [["c", "a"]]}]}
    assert stage_caps(pw, "d") == ("a", "b", "c") and stage_caps(pw, "x") == ()


def _route(*stops):
    return {"route": {"stops": [{"facility_id": f, "name": f, "purpose": p, "eta_low": t} for f, p, t in stops]}}


CARD = {"facility_id": "c1", "name": "Card One", "band": "likely", "travel": {"minutes": 8, "high": 10}}
COVERS = {"facility_id": "c1", "in_data": True, "first_care": True, "missing_first_care": [], "missing_definitive": []}


def test_a_card_1_with_every_stage_drops_the_far_route():
    far = _route(("c1", "stabilise", 8), ("x", "definitive", 26))  # 26 > 10 + 15
    near = _route(("c1", "definitive", 8))
    kept, note = guard([far], CARD, COVERS)
    assert kept == [] and note == ("Go straight to Card One; it is nearer than any other place with evidence for "
                                   "every stage.")
    kept, note = guard([near, far], CARD, COVERS)
    assert kept == [near] and note.startswith("Go straight to Card One")
    assert guard([_route(("c1", "stabilise", 8), ("x", "definitive", 25))], CARD, COVERS)[1] is None  # 25 = 10 + 15


def test_a_card_1_without_a_definitive_capability_keeps_the_route():
    far = _route(("c1", "stabilise", 1), ("x", "definitive", 107))
    lacks = {**COVERS, "missing_definitive": [["blood_transfusion"], ["ct_scan"]]}  # the Gaya hero's card 1
    assert guard([far], CARD, lacks) == ([far], None)
    assert guard([far], {**CARD, "band": "not_verified"}, COVERS) == ([far], None)
    assert guard([far], CARD, None) == ([far], None)  # no planner view of card 1 (not an emergency)


def test_after_the_lead_alternatives_past_a_direct_card_1_go():
    r1 = {"rank": 1, "stops": [{"facility_id": "c1", "purpose": "definitive", "eta_low": 6}]}
    r2 = {"rank": 2, "stops": [{"facility_id": "y", "purpose": "definitive", "eta_low": 14}]}
    r3 = {"rank": 3, "stops": [{"facility_id": "z", "purpose": "definitive", "eta_low": 62}]}
    plan = {"options": [CARD], "itinerary": {"plans": [r1, r2, r3], "itinerary_note": None}}
    it = guard_led(plan)["itinerary"]
    assert [r["stops"][0]["facility_id"] for r in it["plans"]] == ["c1", "y"]
    assert [r["rank"] for r in it["plans"]] == [1, 2] and it["itinerary_note"].startswith("Go straight to Card One")
    unsure = {**plan, "options": [{**CARD, "band": "not_verified"}]}
    assert guard_led(unsure) == unsure


def test_vs_direct_passes_direct_minutes():
    v = {"text": "t", "direct_minutes": 92, "first_care_alternative": None, "direct_p_objective": 0,
         "plan_p_objective": 0.7, "direct_p_first_care": 0, "plan_p_first_care": 0.9}
    assert itinerary._vs_direct(v, "one_stop")["direct_minutes"] == 92
