"""Tests for the planner core with hand-built fixtures. No data files, no network, no pandas.
Run: .venv/bin/python -m pytest planner/test_planner.py -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner import core  # noqa: E402
from planner.app_contract import to_options  # noqa: E402

O = (20.0, 78.0)
KM = 1 / 111.19  # degrees of latitude per km


def fac(fid, km_north, km_east=0.0, **extra):
    return {"id": fid, "name": fid.upper(), "lat": O[0] + km_north * KM, "lon": O[1] + km_east * KM / 0.94,
            "town": "T", "district": "D", "state": "S", **extra}


def travel_60(origin, destinations):
    """1 km of straight line = 1 minute; low and high are 0.8x and 1.5x."""
    rows = []
    for d in destinations:
        m = core.hav_km(origin, d)
        rows.append({"minutes": round(m), "low": round(m * 0.8), "high": round(m * 1.5), "km": round(m, 1),
                     "method": "test", "cached": False, "factor": 1.0, "kmh": 60.0, "terrain": "plain", "label": "test"})
    return rows


def caps(table):
    def fn(fid, cap):
        p = table.get(fid, {}).get(cap, 0.0)
        return p, ([f"{fid}:{cap}"] if p else [])
    return fn


def pathway(gate=60, t1=None, t2=None, dwell=30, after=None, stages=2):
    st = []
    if stages == 2:
        st.append({"id": "stab", "name": "s", "purpose": "stabilise", "actions": ["x"], "requires_all": ["first_aid"],
                   "requires_any": [], "facility_levels": [],
                   "window": None if t1 is None else {"minutes": t1, "from": "x", "kind": "target", "basis": "assumption", "why": "test value"},
                   "dwell_minutes": {"typical": dwell, "basis": "assumption", "why": "test value"}, "repeat": None})
    st.append({"id": "def", "name": "d", "purpose": "definitive", "actions": ["x"], "requires_all": ["surgery"],
               "requires_any": [["blood", "icu"]], "facility_levels": [],
               "window": None if t2 is None else {"minutes": t2, "from": "x", "kind": "target", "basis": "assumption", "why": "test value"},
               "dwell_minutes": None, "repeat": None})
    rules = [{"id": "gate", "type": "add_stop_only_if", "stage": "stab", "when": "w", "then": "t",
              "condition": {"definitive_travel_minutes_gt": gate}, "basis": "assumption", "why": "test value"}] if stages == 2 else []
    rules.append({"id": "note", "type": "never_delay", "stage": "def", "when": "w", "then": "t", "condition": None,
                  "basis": "assumption", "why": "test value"})
    if after:
        rules.append({"id": "after", "type": "refer_if", "stage": "def", "when": "w", "then": "t",
                      "condition": {"after_stabilise_minutes_min": after[0], "after_stabilise_minutes_max": after[1]},
                      "basis": "assumption", "why": "test value"})
    return {"id": "test", "name": "test", "service": "x", "urgency": "emergency", "objective": "time_critical",
            "clock_start": "x", "sources": [], "stages": st, "rules": rules, "open_questions": []}


FULL = {"surgery": 0.9, "blood": 0.9, "icu": 0.5}


def test_stage_probability_is_product_with_best_of_any_group():
    stage = pathway()["stages"][1]
    p, ev, weak, weak_p = core.stage_p("a", stage, caps({"a": {"surgery": 0.8, "blood": 0.5, "icu": 0.7}}))
    assert p == pytest.approx(0.8 * 0.7)          # icu beats blood inside the any-group
    assert ev == ["a:surgery", "a:icu"]
    assert (weak, weak_p) == ("icu", 0.7)


def test_near_definitive_goes_direct_and_no_stop_is_considered():
    f = [fac("near_d", 40), fac("clinic", 10)]
    r = core.plan(O, pathway(gate=60), f, caps({"near_d": FULL, "clinic": {"first_aid": 0.95}}), travel_60)
    assert [p["type"] for p in r["plans"]] == ["direct"]
    assert r["plans"][0]["stops"][0]["facility_id"] == "near_d"
    assert r["plans"][0]["stops"][0]["eta_minutes"] == 40
    assert r["considered"]["plans"] == 1          # the gate kept every stop plan out


def test_far_definitive_adds_a_stop_and_explains_it():
    f = [fac("far_d", 100), fac("clinic", 20)]
    r = core.plan(O, pathway(gate=60, dwell=30), f, caps({"far_d": FULL, "clinic": {"first_aid": 0.9}}), travel_60)
    best = r["plans"][0]
    assert best["type"] == "one_stop"
    stab, definitive = best["stops"]
    assert (stab["facility_id"], stab["purpose"], stab["eta_minutes"], stab["dwell_minutes"]) == ("clinic", "stabilise", 20, 30)
    assert definitive["eta_minutes"] == 20 + 30 + 80
    # first care in time needs the clinic to deliver (0.9); definitive has no window, so it is delivery (0.81)
    assert best["totals"]["p_objective"] == pytest.approx(0.9 * 0.81, abs=1e-4)
    direct = next(p for p in r["plans"] if p["type"] == "direct")
    assert direct["totals"]["p_objective"] == 0   # 100 min is past the 60 min first-care limit
    assert best["vs_direct"]["gain"] == pytest.approx(0.729, abs=1e-3)
    assert "beyond the 60 min threshold" in best["vs_direct"]["text"]
    assert best["window_checks"][0]["met"] and not direct["window_checks"][0]["met"]


def test_stop_that_does_not_beat_direct_by_the_margin_is_dropped():
    f = [fac("far_d", 100), fac("clinic", 20)]
    r = core.plan(O, pathway(gate=60), f, caps({"far_d": FULL, "clinic": {"first_aid": 0.03}}), travel_60)
    assert [p["type"] for p in r["plans"]] == ["direct"]   # clinic is below MIN_P, never a candidate
    # first-care limit of 200 min and a certain definitive facility: going direct (100 min) already
    # gives first care in time with probability 1, so even a good clinic adds nothing
    table = {"far_d": {"surgery": 1.0, "blood": 1.0}, "clinic": {"first_aid": 0.9}}
    r = core.plan(O, pathway(gate=60, t1=200), f, caps(table), travel_60)
    assert [p["type"] for p in r["plans"]] == ["direct"]
    assert r["considered"]["stop_plans_dropped_below_margin"] == 1


def test_stop_must_be_on_the_way():
    f = [fac("far_d", 100), fac("behind", -40), fac("sideways", 30, km_east=90)]
    table = {"far_d": FULL, "behind": {"first_aid": 0.95}, "sideways": {"first_aid": 0.95}}
    r = core.plan(O, pathway(gate=60), f, caps(table), travel_60)
    assert all(p["type"] == "direct" for p in r["plans"])


def test_turned_away_goes_to_the_fallback_and_costs_time():
    f = [fac("d1", 30), fac("d2", 30, km_east=20)]
    table = {"d1": {"surgery": 0.5, "blood": 1.0}, "d2": {"surgery": 0.8, "blood": 1.0}}
    r = core.plan(O, pathway(stages=1), f, caps(table), travel_60)
    d1 = next(p for p in r["plans"] if p["stops"][0]["facility_id"] == "d1")
    fb = d1["stops"][0]["fallback_if_turned_away"]
    assert fb["facility_id"] == "d2"
    assert fb["eta_minutes"] == 30 + core.TURNAWAY_MINUTES + 20
    assert d1["totals"]["p_treated"] == pytest.approx(0.5 + 0.5 * 0.8)
    assert r["plans"][0]["stops"][0]["facility_id"] == "d2"   # higher chance, same distance


def test_definitive_window_and_elapsed_time():
    f = [fac("d", 50)]
    r = core.plan(O, pathway(stages=1, t2=60), f, caps({"d": FULL}), travel_60)
    assert r["plans"][0]["totals"]["p_objective"] == pytest.approx(0.81)
    assert r["plans"][0]["window_checks"][0]["met"]
    assert not r["plans"][0]["window_checks"][0]["met_at_high_estimate"]   # 75 min at the high end
    late = core.plan(O, pathway(stages=1, t2=60), f, caps({"d": FULL}), travel_60, elapsed_minutes=20)
    assert late["plans"][0]["totals"]["p_objective"] == 0
    assert not late["plans"][0]["window_checks"][0]["met"]


def test_after_stabilise_rule_moves_the_definitive_deadline_and_waits():
    # definitive window 120 from now; after stabilising, definitive is due between 180 and 1440 min later
    f = [fac("far_d", 140), fac("clinic", 20)]
    pw = pathway(gate=120, t1=720, t2=120, dwell=90, after=(180, 1440))
    r = core.plan(O, pw, f, caps({"far_d": FULL, "clinic": {"first_aid": 0.9}}), travel_60)
    best = r["plans"][0]
    assert best["type"] == "one_stop"
    assert best["stops"][0]["dwell_minutes"] == 90            # 90 + 120 min leg already clears the 180 minimum
    assert best["totals"]["p_objective"] == pytest.approx(0.9 * 0.81, abs=1e-4)
    assert best["window_checks"][1]["limit_minutes"] == 20 + 1440
    direct = next(p for p in r["plans"] if p["type"] == "direct")
    assert direct["totals"]["p_objective"] == 0               # 140 min misses the 120 min window


def test_abstains_when_nothing_qualifies():
    r = core.plan(O, pathway(), [fac("x", 10)], caps({}), travel_60)
    assert r["plans"] == [] and "Call the emergency number" in r["abstain"]["text"]
    r = core.plan(O, pathway(), [fac("too_far", 300)], caps({"too_far": FULL}), travel_60)
    assert r["plans"] == []


def test_alternatives_differ_and_are_at_most_three():
    f = [fac(f"d{i}", 20 + 5 * i, km_east=3 * i) for i in range(6)]
    r = core.plan(O, pathway(stages=1), f, caps({x["id"]: FULL for x in f}), travel_60)
    ids = [p["stops"][-1]["facility_id"] for p in r["plans"]]
    assert len(ids) == 3 and len(set(ids)) == 3 and ids[0] == "d0"


def scheduled_pathway():
    def st(i, purpose, cap, dwell, repeat=None):
        return {"id": i, "name": i, "purpose": purpose, "actions": ["x"], "requires_all": [cap], "requires_any": [],
                "facility_levels": [], "window": None,
                "dwell_minutes": None if dwell is None else {"typical": dwell, "basis": "assumption", "why": "test value"},
                "repeat": repeat}
    return {"id": "sched", "name": "s", "service": "x", "urgency": "scheduled", "objective": "fewest_trips", "clock_start": "x",
            "sources": [], "rules": [], "open_questions": [],
            "stages": [st("assess", "assess", "clinic", 60), st("access", "access", "surgery", 600),
                       st("sessions", "recurring", "unit", None, {"per_week": 3, "basis": "assumption", "why": "test value"})]}


def test_scheduled_prefers_one_site_then_least_travel():
    f = [fac("all_in_one", 60), fac("near_unit", 10), fac("near_clinic", 5), fac("near_surgery", 8)]
    table = {"all_in_one": {"clinic": 0.8, "surgery": 0.8, "unit": 0.8}, "near_unit": {"unit": 0.9},
             "near_clinic": {"clinic": 0.9}, "near_surgery": {"surgery": 0.9}}
    r = core.plan(O, scheduled_pathway(), f, caps(table), travel_60)
    best = r["plans"][0]
    assert best["type"] == "single_site" and {s["facility_id"] for s in best["stops"]} == {"all_in_one"}
    assert best["totals"]["travel_minutes_over_planning_weeks"] == 2 * 60 * (1 + 1 + 3 * core.PLANNING_WEEKS)
    assert best["stops"][-1]["per_week"] == 3
    other = r["plans"][1]
    assert other["totals"]["distinct_sites"] > 1 and "against one site" in other["vs_direct"]["text"]
    assert other["totals"]["travel_minutes_over_planning_weeks"] < best["totals"]["travel_minutes_over_planning_weeks"]


def test_scheduled_abstains_and_names_the_missing_stage():
    f = [fac("near_unit", 10), fac("near_clinic", 5)]
    r = core.plan(O, scheduled_pathway(), f, caps({"near_unit": {"unit": 0.9}, "near_clinic": {"clinic": 0.9}}), travel_60)
    assert r["plans"] == [] and "access" in r["abstain"]["text"]


def test_app_options_shape():
    f = [fac("far_d", 100, flags=["location confidence is low: confirm the address by phone"]), fac("clinic", 20)]
    r = core.plan(O, pathway(gate=60), f, caps({"far_d": FULL, "clinic": {"first_aid": 0.9}}), travel_60)
    opts = to_options(r)
    o = opts[0]
    assert o["rank"] == 1 and o["facility_id"] == "far_d" and o["route"]["type"] == "one_stop"
    assert set(o["travel"]) >= {"minutes", "low", "high", "km", "method"}
    assert o["p"] == r["plans"][0]["totals"]["p_objective"]
    assert o["evidence"][0] == {"claim_id": "far_d:surgery"}
    assert [q["facility_id"] for q in o["call_ahead"]] == ["clinic", "far_d"]
    assert o["call_first"] is True
    assert any("location confidence is low" in x for x in o["flags"])
    json.dumps(opts)   # serialisable


def test_real_pathways_load_and_plan_with_fixtures():
    doc = json.loads((ROOT / "kb" / "pathways" / "care_pathways.json").read_text())
    by_id = {p["id"]: p for p in doc["pathways"]}
    assert core.gate_minutes(by_id["stemi"])[0] == 120          # the caution rule is not a gate
    assert core.gate_minutes(by_id["snakebite"]) == (None, None)
    everything = {c: 0.9 for p in doc["pathways"] for s in p["stages"] for c in s["requires_all"] + [x for g in s["requires_any"] for x in g]}
    f = [fac("big", 140), fac("small", 15)]
    for pid, pw in by_id.items():
        r = core.plan(O, pw, f, caps({"big": everything, "small": everything}), travel_60)
        assert r["plans"], pid
        assert all(s["evidence_ids"] for p in r["plans"] for s in p["stops"]), pid
        json.dumps(r)
    # STEMI: PCI centre 140 min away is past the 120 min rule, so thrombolyse at the near one first... but the
    # near facility can also do PCI here, so direct to it wins
    r = core.plan(O, by_id["stemi"], f, caps({"big": everything, "small": everything}), travel_60)
    assert r["plans"][0]["type"] == "direct" and r["plans"][0]["stops"][0]["facility_id"] == "small"
    only_lysis = {"ecg": 0.9, "thrombolysis": 0.9, "emergency_24x7": 0.9}
    r = core.plan(O, by_id["stemi"], f, caps({"big": everything, "small": only_lysis}), travel_60)
    assert r["plans"][0]["type"] == "one_stop"
    assert r["plans"][0]["stops"][0]["dwell_minutes"] == 90
    assert any(i["type"] == "caution" for i in r["instructions"])
