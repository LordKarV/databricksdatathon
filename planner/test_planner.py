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


def test_near_definitive_goes_direct_and_names_the_first_care_stop():
    # direct (40 min) is within the 60-minute window and stopping first reaches definitive care at 70 min, past it:
    # the plan is direct, the stop at the nearest first care (#92) is plan 2, and the sentence names it
    f = [fac("near_d", 40), fac("clinic", 10), fac("other", 20, km_east=5)]
    table = {"near_d": FULL, "clinic": {"first_aid": 0.95}, "other": {"first_aid": 0.95}}
    r = core.plan(O, pathway(gate=60), f, caps(table), travel_60)
    best, second = r["plans"][:2]
    assert [s["facility_id"] for s in best["stops"]] == ["near_d"]
    assert [s["facility_id"] for s in second["stops"]] == ["clinic", "near_d"]
    assert second["stops"][1]["eta_minutes"] == 10 + 30 + 30
    assert all(p["stops"][0]["facility_id"] != "other" for p in r["plans"])
    assert best["vs_direct"]["text"] == ("Going straight to NEAR_D takes 40 min, within the 60-minute window: go there "
                                         "directly, and call ahead. If the patient needs care sooner, CLINIC (10 min) "
                                         "can give first care.")
    assert best["vs_direct"]["first_care_alternative"]["facility_id"] == "clinic"
    # with no first-care stop, the nearest definitive facility is the route
    r = core.plan(O, pathway(gate=60), f[:1], caps(table), travel_60)
    assert [p["type"] for p in r["plans"]] == ["direct"] and r["considered"]["plans"] == 1
    # direct within the window and a stop that adds no more than DIRECT_SLACK_MINUTES: the stop leads
    r = core.plan(O, pathway(gate=60, dwell=5), [fac("near_d", 45), fac("clinic", 2)], caps(table), travel_60)
    assert [s["facility_id"] for s in r["plans"][0]["stops"]] == ["clinic", "near_d"]   # 2 + 5 + 43 = 50 min


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
    assert best["vs_direct"]["text"] == ("Going straight to FAR_D takes 100 min and misses the 60-minute window; "
                                         "stopping first at CLINIC gives first care in about 20 min.")
    assert "0." not in best["vs_direct"]["text"]  # minutes only: the probabilities stay in the fields
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


def test_stop_must_be_on_the_way_unless_it_is_the_nearest_first_care():
    f = [fac("far_d", 100), fac("behind", -40), fac("sideways", 30, km_east=90)]
    table = {"far_d": FULL, "behind": {"first_aid": 0.95}, "sideways": {"first_aid": 0.95}}
    r = core.plan(O, pathway(gate=60), f, caps(table), travel_60)
    # stop 1 is the nearest first care (#92), on the way or not; other stops must be on the way
    assert [s["facility_id"] for s in r["plans"][0]["stops"]] == ["behind", "far_d"]
    assert all(p["stops"][0]["facility_id"] != "sideways" for p in r["plans"])


def test_turned_away_goes_to_the_fallback_and_costs_time():
    f = [fac("d1", 30), fac("d2", 30, km_east=20)]
    table = {"d1": {"surgery": 0.5, "blood": 1.0}, "d2": {"surgery": 0.8, "blood": 1.0}}
    r = core.plan(O, pathway(stages=1), f, caps(table), travel_60)
    d1 = next(p for p in r["plans"] if p["stops"][0]["facility_id"] == "d1")
    fb = d1["stops"][0]["fallback_if_turned_away"]
    assert fb["facility_id"] == "d2"
    assert fb["eta_minutes"] == 30 + core.TURNAWAY_MINUTES + 20
    assert d1["totals"]["p_treated"] == pytest.approx(0.5 + 0.5 * 0.8)
    # nearest plausible first (#92): d2's higher chance does not buy its 6 extra minutes; d2 is the fallback
    assert r["plans"][0]["stops"][0]["facility_id"] == "d1"


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


def test_scheduled_prefers_least_travel_then_fewer_sites():
    f = [fac("all_in_one", 60), fac("near_unit", 10), fac("near_clinic", 5), fac("near_surgery", 8)]
    table = {"all_in_one": {"clinic": 0.8, "surgery": 0.8, "unit": 0.8}, "near_unit": {"unit": 0.9},
             "near_clinic": {"clinic": 0.9}, "near_surgery": {"surgery": 0.9}}
    r = core.plan(O, scheduled_pathway(), f, caps(table), travel_60)
    best = r["plans"][0]
    # sessions three times a week dominate travel, so the near unit wins even though it needs three sites
    assert [s["facility_id"] for s in best["stops"]] == ["near_clinic", "near_surgery", "near_unit"]
    assert best["type"] == "three_sites" and best["stops"][-1]["per_week"] == 3
    assert best["totals"]["travel_minutes_over_planning_weeks"] == 2 * (5 + 8 + 10 * 3 * core.PLANNING_WEEKS)
    single = next(p for p in r["plans"] if p["type"] == "single_site")
    assert {s["facility_id"] for s in single["stops"]} == {"all_in_one"}
    assert single["totals"]["travel_minutes_over_planning_weeks"] == 2 * 60 * (1 + 1 + 3 * core.PLANNING_WEEKS)
    assert "against one site" in best["vs_direct"]["text"]
    # equal travel: the plan with fewer sites comes first
    same = [fac("one", 10), fac("clinic_here", 10, km_east=0.001), fac("unit_here", 10, km_east=0.002)]
    t2 = {"one": {"clinic": 0.9, "surgery": 0.9, "unit": 0.9}, "clinic_here": {"clinic": 0.9}, "unit_here": {"unit": 0.9}}
    r2 = core.plan(O, scheduled_pathway(), same, caps(t2), travel_60)
    assert r2["plans"][0]["type"] == "single_site"


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


# ---- run-time store and the one-call service (issue #47) ----

def synthetic_doc():
    """An export in planner/export_v2.py's shape: emergency_24x7 here is a text tag, icu a model v2 tag."""
    return {"version": 2, "built_utc": "2026-01-01T00:00:00Z", "probabilities": {"source": "test"}, "no_mention_p": 0.02,
            "facilities": {"id": ["a", "b"], "name": ["A", "B"], "lat": [O[0] + 0.1, O[0] + 0.9], "lon": [O[1], O[1]],
                           "town": ["T", "T"], "district": ["D", "D"], "state": ["PLAINS", "SIKKIM"], "flags": [[], ["check"]]},
            "capabilities": {"emergency_24x7": {"source": "own offer sentences", "i": [0], "p": [0.9], "b": ["T"],
                                                "e": [["a:1"]], "n": []},
                             "icu": {"source": "derived/v2 icu", "i": [1], "p": [0.8], "b": ["C"], "e": [["b:1", "b:2"]],
                                     "n": [0]}}}


def test_store_roundtrip_without_pandas(tmp_path):
    import gzip
    from planner.store import Store
    path = tmp_path / "p.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(synthetic_doc(), fh)
    st = Store.load(path)
    assert [f["id"] for f in st.facilities()] == ["a", "b"] and st.facilities()[1]["flags"] == ["check"]
    assert st.capability_p("a", "emergency_24x7") == (0.9, ["a:1"])
    assert st.capability_p("b", "emergency_24x7") == (0.02, [])      # no mention
    assert st.capability_p("b", "icu") == (0.8, ["b:1", "b:2"])
    assert st.capability_p("a", "icu") == (0.0, [])  # a v2 pair not offered (NO_SERVICE_TEXT) is never a stop
    assert (st.band("a", "icu"), st.band("b", "icu"), st.band("b", "emergency_24x7")) == ("NO_SERVICE_TEXT", "CALL_FIRST", None)
    with pytest.raises(KeyError):
        st.capability_p("a", "not_a_capability")
    assert st.state_near(O) == "PLAINS" and st.state_near((O[0] + 1.0, O[1])) == "SIKKIM"   # no PINs: nearest facility
    doc = synthetic_doc()
    doc["pins"] = {"states": ["BIHAR", "SIKKIM"], "lat": [O[0], O[0] + 1.0], "lon": [O[1], O[1]], "s": [0, 1]}
    with_pins = Store(doc)
    assert with_pins.state_near((O[0] + 0.2, O[1])) == "BIHAR" and with_pins.state_near((O[0] + 0.9, O[1])) == "SIKKIM"
    assert Store.load(tmp_path / "missing.json.gz") is None
    # the run-time path must not pull in pandas; checked in a fresh interpreter because other tests
    # in the same process may already have imported it
    import subprocess
    code = ("import sys; sys.path.insert(0, %r); "
            "from planner.store import Store; from planner import service, core, app_contract; "
            "st = Store.load(%r); assert st.capability_p('a', 'emergency_24x7')[0] == 0.9; "
            "bad = [m for m in ('pandas', 'numpy', 'pyarrow') if m in sys.modules]; assert not bad, bad"
            % (str(ROOT), str(path)))
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_service_maps_app_services_and_passes_other_services_through():
    from planner import service
    assert service.plan_for_service("mri", 20.0, 78.0) == {"pathway": None}
    assert service.plan_for_service("cardiac_surgery", 20.0, 78.0) == {"pathway": None}
    for app_id, pid in service.SERVICE_TO_PATHWAY.items():
        assert pid in service.pathways(), app_id
    everything = {c: 0.9 for p in service.pathways().values() for s in p["stages"]
                  for c in s["requires_all"] + [x for g in s["requires_any"] for x in g]}
    f = [fac("big", 140), fac("small", 15)]
    only_first = {"emergency_24x7": 0.9}
    out = service.plan_for_service("trauma_emergency", O[0], O[1], capability_p=caps({"big": everything, "small": only_first}),
                                   facilities=f, travel_fn=travel_60)
    assert out["pathway"] == "major_trauma" and "stub" not in out["meta"] and out["abstain"] is None
    o = out["options"][0]
    assert o["route"]["type"] == "one_stop" and [s["facility_id"] for s in o["route"]["stops"]] == ["small", "big"]
    assert out["thresholds"]["add_stop_only_if_definitive_beyond_minutes"] == 60
    assert any(i["type"] == "never_delay" for i in out["instructions"])
    json.dumps(out)


def test_service_says_when_the_export_is_missing(monkeypatch):
    from planner import service
    monkeypatch.setitem(service._cache, "store", None)
    with pytest.raises(RuntimeError, match="export_v2"):
        service.plan_for_service("dialysis", 20.0, 78.0)


def v2_doc(facilities, rows, silent=None):
    """A planner_v2 export: rows {cap: {fid: (p, band)}}, silent {cap: [fid]} (NO_SERVICE_TEXT)."""
    caps_doc = json.loads((ROOT / "kb" / "pathways" / "capabilities.json").read_text())["capabilities"]
    ids = [f["id"] for f in facilities]
    out = {}
    for c in caps_doc:
        r = rows.get(c["id"], {})
        out[c["id"]] = {"source": f"derived/v2 {c['v2_service']}" if c["v2_service"] else "own offer sentences",
                        "i": [ids.index(f) for f in r], "p": [v[0] for v in r.values()], "b": [v[1] for v in r.values()],
                        "e": [[f"{f}:1"] for f in r], "n": [ids.index(f) for f in (silent or {}).get(c["id"], [])]}
    return {"version": 2, "built_utc": "t", "probabilities": {"source": "test"}, "no_mention_p": 0.02,
            "facilities": {k: [f.get(k, []) if k == "flags" else f[k] for f in facilities]
                           for k in ("id", "name", "lat", "lon", "town", "district", "state", "flags")},
            "capabilities": out}


def test_call_first_wording_and_what_would_change(monkeypatch):
    from planner import service
    from planner.store import Store
    f = [fac("near", 10), fac("stop", 20), fac("far", 100)]
    rows = {"emergency_24x7": {"stop": (0.8, "C"), "far": (0.95, "L")}, "general_surgery_ot": {"far": (0.78, "T")},
            **{c: {"far": (0.95, "L")} for c in ("blood_transfusion", "ct_scan", "icu", "trauma_centre")}}
    monkeypatch.setitem(service._cache, "store", Store(v2_doc(f, rows, {"emergency_24x7": ["near"]})))
    out = service.plan_for_service("trauma_emergency", O[0], O[1], travel_fn=travel_60)
    o = out["options"][0]
    stop = o["route"]["stops"][0]
    assert o["route"]["type"] == "one_stop" and stop["facility_id"] == "stop" and stop["call_first"] and o["call_first"]
    assert "Call first to check: emergency 24x7 is not confirmed in our data." in stop["flags"]
    assert "placeholder" not in " ".join(o["flags"])
    # near is NO_SERVICE_TEXT for the stage: p 0, never a stop, but a phone "yes" from it would change the answer
    assert o["route"]["vs_direct"]["what_would_change"] == "A 'yes' from NEAR on the phone would change this."
    assert o["route"]["vs_direct"]["text"] == ("Going straight to FAR takes 100 min and misses the 60-minute window; "
                                               "stopping first at STOP gives first care in about 20 min.")


def test_callers_first_choice_is_stop_1_when_it_can_give_first_care():
    # #92: the app's list #1 leads even though the planner's objective prefers the likelier clinic
    f = [fac("far_d", 100), fac("list_one", 30), fac("likelier", 25), fac("no_aid", 10)]
    table = {"far_d": FULL, "list_one": {"first_aid": 0.5}, "likelier": {"first_aid": 0.99}, "no_aid": {"surgery": 0.9}}
    r = core.plan(O, pathway(gate=60), f, caps(table), travel_60, first_stop="list_one")
    assert [s["facility_id"] for s in r["plans"][0]["stops"]] == ["list_one", "far_d"]
    assert r["first_stop"]["first_care"] and r["first_stop"]["missing_first_care"] == []
    # a first choice that cannot give first care is not stop 1, and the result names what it lacks
    r = core.plan(O, pathway(gate=60), f, caps(table), travel_60, first_stop="no_aid")
    assert r["plans"][0]["stops"][0]["facility_id"] == "likelier"
    assert r["first_stop"] == {"facility_id": "no_aid", "in_data": True, "first_care": False,
                               "missing_first_care": [["first_aid"]], "missing_definitive": [["blood", "icu"]]}


def test_definitive_care_is_nearest_first_and_p_does_not_buy_minutes():
    # #92: near_d (50 min, p 0.27) is the definitive facility over sure_d (70 min, p 1.0), direct and after the stop
    f = [fac("near_d", 50), fac("clinic", 10), fac("sure_d", 70, km_east=5)]
    table = {"near_d": {"surgery": 0.3, "blood": 0.9}, "sure_d": {"surgery": 1.0, "blood": 1.0},
             "clinic": {"first_aid": 0.9}}
    plans = core.plan(O, pathway(gate=60), f, caps(table), travel_60)["plans"]
    assert [s["facility_id"] for s in plans[0]["stops"]] == ["near_d"]   # 50 min direct, within the window
    assert [s["facility_id"] for s in plans[1]["stops"]] == ["clinic", "near_d"]
    # nothing within the window: the nearest beyond it, and the sentence says the window is missed
    f = [fac("far_d", 100), fac("farther_sure", 120), fac("clinic", 20)]
    table = {"far_d": {"surgery": 0.3, "blood": 0.9}, "farther_sure": FULL, "clinic": {"first_aid": 0.9}}
    best = core.plan(O, pathway(gate=60), f, caps(table), travel_60)["plans"][0]
    assert [s["facility_id"] for s in best["stops"]] == ["clinic", "far_d"]
    assert best["vs_direct"]["text"] == ("Going straight to FAR_D takes 100 min and misses the 60-minute window; "
                                         "stopping first at CLINIC gives first care in about 20 min.")
    # a stop that reaches first care no sooner than going direct inside the window is not offered
    f = [fac("near_d", 50), fac("clinic", 55, km_east=5), fac("far_d", 100)]
    table = {"near_d": {"surgery": 0.3, "blood": 0.9}, "far_d": FULL, "clinic": {"first_aid": 0.95}}
    r = core.plan(O, pathway(gate=60), f, caps(table), travel_60, first_stop="clinic")
    assert r["plans"][0]["type"] == "direct" and all(p["type"] == "direct" for p in r["plans"])


def test_near_equal_chances_go_to_the_nearer_stop():
    # 0.83 against 0.82 is inside MARGIN, so the 20 km clinic leads the 40 km one
    f = [fac("far_d", 100), fac("near_s", 20), fac("farther_s", 40)]
    table = {"far_d": FULL, "near_s": {"first_aid": 0.82}, "farther_s": {"first_aid": 0.83}}
    r = core.plan(O, pathway(gate=60, dwell=30), f, caps(table), travel_60)
    assert r["plans"][0]["stops"][0]["facility_id"] == "near_s"


def test_service_applies_the_origin_state_to_travel():
    from planner import service
    everything = {c: 0.9 for p in service.pathways().values() for s in p["stages"]
                  for c in s["requires_all"] + [x for g in s["requires_any"] for x in g]}
    f = [fac("d", 40, state="SIKKIM")]
    kw = dict(capability_p=caps({"d": everything}), facilities=f)
    hill = service.plan_for_service("burn_care", O[0], O[1], state="Sikkim", **kw)
    plain = service.plan_for_service("burn_care", O[0], O[1], state="Bihar", **kw)
    derived = service.plan_for_service("burn_care", O[0], O[1], **kw)
    leg = lambda out: out["options"][0]["travel"]  # noqa: E731
    assert leg(hill)["terrain"] == "hill" and leg(plain)["terrain"] == "plain"
    assert leg(hill)["minutes"] > leg(plain)["minutes"]
    assert (hill["meta"]["origin_state"], hill["meta"]["origin_state_source"], hill["meta"]["terrain"]) == ("Sikkim", "caller", "hill")
    assert (derived["meta"]["origin_state"], derived["meta"]["origin_state_source"]) == ("SIKKIM", "nearest facility")
    assert leg(derived)["terrain"] == "hill"


def numbers_in(text):
    import re
    return sorted(float(x) for x in re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", text))


def test_every_number_in_the_comparison_sentence_is_a_field():
    # emergency: stop wins on care in time; stop wins only on first care; a different direct facility
    f = [fac("far_d", 100), fac("clinic", 20), fac("other_d", 110, km_east=30)]
    table = {"far_d": FULL, "clinic": {"first_aid": 0.9}, "other_d": {"surgery": 0.6, "blood": 0.9}}
    cases = [core.plan(O, pathway(gate=60), f, caps(table), travel_60),
             core.plan(O, pathway(gate=60, t2=30), f, caps(table), travel_60),
             core.plan(O, scheduled_pathway(), [fac("all_in_one", 60), fac("near_unit", 10), fac("near_clinic", 5), fac("near_surgery", 8)],
                       caps({"all_in_one": {"clinic": 0.8, "surgery": 0.8, "unit": 0.8}, "near_unit": {"unit": 0.9},
                             "near_clinic": {"clinic": 0.9}, "near_surgery": {"surgery": 0.9}}), travel_60)]
    seen = set()
    for r in cases:
        for p in r["plans"]:
            vs = p["vs_direct"]
            text = vs["text"].replace(vs.get("direct_name") or "\0", "")
            assert numbers_in(text) == sorted(float(v) for v in vs["text_numbers"].values()), vs
            seen.add(tuple(sorted(vs["text_numbers"])))
    assert len(seen) >= 4   # the sentence variants were all exercised


def test_gold_eval_summary_counts():
    from planner import eval_gold_dev as ev
    assert ev.wilson(0, 0) == [None, None] and ev.rate(1, 4)["share"] == 0.25
    base = {"baseline_pick": None, "baseline_is_gold": False, "baseline_verdict": None, "pathway": "p"}
    rows = [
        {**base, "gold_verdict": "confirmed", "planner_pick": "a", "planner_is_gold": True, "planner_verdict": "confirmed", "why_not_gold": None},
        {**base, "gold_verdict": "confirmed", "planner_pick": "b", "planner_is_gold": False, "planner_verdict": "unknown",
         "why_not_gold": {"was_candidate": False, "weakest_capability": "blood_transfusion"}},
        {**base, "gold_verdict": "contradicted", "planner_pick": "c", "planner_is_gold": False, "planner_verdict": "contradicted",
         "why_not_gold": {"was_candidate": True, "weakest_capability": "icu"}},
        {**base, "gold_verdict": "no_info", "planner_pick": None, "planner_is_gold": False, "planner_verdict": None,
         "why_not_gold": {"was_candidate": False, "weakest_capability": "icu"}},
    ]
    s = ev.summarise(rows, "planner")
    assert (s["queries"], s["abstained"]) == (4, 1)
    assert s["picked_verdict"]["confirmed"]["k"] == 1 and s["picked_verdict"]["unknown"]["k"] == 1
    assert s["picks_gold_facility_by_gold_verdict"]["confirmed"] == {"k": 1, "n": 2, "share": 0.5, "ci95": ev.wilson(1, 2)}
    assert s["confirmed_among_picks_with_a_clear_label"]["k"] == 1 and s["confirmed_among_picks_with_a_clear_label"]["n"] == 2
    m = ev.missed_summary(rows)
    assert (m["n"], m["not_a_candidate"], m["candidate_but_outranked"]) == (1, 1, 0)
    assert m["not_a_candidate_by_missing_capability"] == {"p: blood_transfusion": 1}


# ---- implied capabilities and list-based blood (issue #70) ----

def test_strong_source_implies_a_weaker_probability_without_evidence():
    from planner.implied import IMPLIES, STRONG, with_implications
    base = caps({"unit": {"haemodialysis_unit": 0.9}, "weak": {"haemodialysis_unit": 0.5},
                 "own": {"haemodialysis_unit": 0.9, "nephrology": 0.95}})
    cp = with_implications(base)
    p, ids = cp("unit", "nephrology")
    assert p == pytest.approx(0.8 * 0.9) and ids == []                 # discounted, and no quote attached
    note = cp.explain("unit", "nephrology")
    assert note["basis"] == "implied" and note["implied_by"] == "haemodialysis_unit"
    assert note["text"] == "implied by a strongly evidenced haemodialysis unit" and note["own_p"] == 0.0
    assert cp("weak", "nephrology") == (0.0, []) and cp.explain("weak", "nephrology") is None     # source below STRONG
    assert cp("own", "nephrology") == (0.95, ["own:nephrology"]) and cp.explain("own", "nephrology") is None
    assert cp("unit", "haemodialysis_unit") == (0.9, ["unit:haemodialysis_unit"])                 # sources are untouched
    assert 0 < STRONG < 1 and all(0 < s < 1 for rules in IMPLIES.values() for _, s, _ in rules)
    assert cp.describe()["blood_from_list"] is False


def test_implication_is_one_level_only():
    from planner.implied import with_implications
    cp = with_implications(caps({"n": {"nicu": 0.9}}))
    assert cp("n", "sncu")[0] == pytest.approx(0.72)                   # nicu -> sncu
    assert cp("n", "neonatal_stabilisation")[0] == pytest.approx(0.81)  # from nicu directly, not via the implied sncu


def test_blood_comes_from_the_list_when_list_facts_are_given():
    from planner.implied import P_LIST_MATCH, P_LIST_NEAR, P_LIST_NONE, with_implications
    base = caps({"says_blood": {"blood_transfusion": 0.9}, "matched": {}, "near": {}, "far": {},
                 "fru": {"comprehensive_emoc": 0.9}})
    dist = {"near": (2.0, "City Blood Centre"), "far": (40.0, "Far Blood Centre"), "says_blood": (30.0, "Far Blood Centre")}
    blood = {"matched": {"matched": {"name": "District Hospital Blood Centre", "type": "Blood Bank"}}, "nearest": dist.get}
    cp = with_implications(base, blood=blood)
    assert cp("matched", "blood_transfusion") == (P_LIST_MATCH, []) and cp.explain("matched", "blood_transfusion")["basis"] == "list"
    assert cp("near", "blood_transfusion")[0] == P_LIST_NEAR and "2.0 km away" in cp.explain("near", "blood_transfusion")["text"]
    assert cp("far", "blood_transfusion")[0] == P_LIST_NONE
    assert cp("says_blood", "blood_transfusion")[0] == P_LIST_NONE      # record text is not used once the list is there
    p, ids = cp("fru", "blood_transfusion")                              # no list fact, but a strong caesarean service
    assert p == pytest.approx(0.6 * 0.9) and ids == [] and cp.explain("fru", "blood_transfusion")["basis"] == "implied"
    without = with_implications(base)
    assert without("says_blood", "blood_transfusion") == (0.9, ["says_blood:blood_transfusion"])   # no list: text as before


def test_planner_uses_and_reports_implied_capabilities():
    from planner import service
    pw = service.pathways()["dialysis_start"]
    f = [fac("unit_only", 10), fac("full", 120)]
    table = {"unit_only": {"haemodialysis_unit": 0.9, "vascular_access_surgery": 0.8},
             "full": {"haemodialysis_unit": 0.9, "nephrology": 0.9, "laboratory": 0.9, "vascular_access_surgery": 0.9}}
    plain = core.plan(O, pw, f, caps(table), travel_60)
    assert {s["facility_id"] for s in plain["plans"][0]["stops"]} == {"full", "unit_only"}       # assessment must go far
    out = service.plan_for_service("dialysis", O[0], O[1], capability_p=caps(table), facilities=f, travel_fn=travel_60)
    best = out["options"][0]["route"]
    assert {s["facility_id"] for s in best["stops"]} == {"unit_only"}
    notes = best["stops"][0]["capability_notes"]
    assert {n["capability"] for n in notes} == {"nephrology", "laboratory"} and all(n["basis"] == "implied" for n in notes)
    assert best["stops"][0]["evidence_ids"] == []                       # implied capabilities bring no quotes
    assert out["meta"]["implications"]["blood_from_list"] is False
    off = service.plan_for_service("dialysis", O[0], O[1], capability_p=caps(table), facilities=f, travel_fn=travel_60,
                                   implications=False)
    assert off["meta"]["implications"] is None
    assert all(s["capability_notes"] == [] for s in off["options"][0]["route"]["stops"])


def test_store_blood_facts_from_an_export_with_a_blood_list():
    from planner.store import Store
    doc = synthetic_doc()
    assert Store(doc).blood_facts() is None
    doc["blood"] = {"source": "test", "matched": {"a": {"name": "A Blood Centre", "type": "Blood Bank"}},
                    "centres": {"lat": [O[0] + 0.9], "lon": [O[1]], "name": ["North Blood Centre"]}}
    b = Store(doc).blood_facts()
    assert b["matched"]["a"]["name"] == "A Blood Centre"
    km, name = b["nearest"]("b")
    assert name == "North Blood Centre" and km < 1.0 and b["nearest"]("missing") is None
