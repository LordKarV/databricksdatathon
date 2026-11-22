"""sim/execute.py: the step loop on hand-built truth, plus one run on the real world (#92)."""
from collections import namedtuple

from sim import execute as ex
from sim import policies_baseline as pb
from sim import world

T = namedtuple("T", "exists offers phone_ok open_now_p accept_p true_lat true_lon")
HERE = (26.0, 85.0)
LISTED = {"near": (26.05, 85.0), "mid": (26.1, 85.0), "far": (26.2, 85.0), "x4": (26.3, 85.0), "x5": (26.4, 85.0)}
KN = {**world.MID, "wrong_yes": 0.0}


def good(fid):
    return T(True, True, True, 1.0, 1.0, *LISTED[fid])


def case(**kw):
    c = {"seed": 1, "case_id": "c1", "service": "dialysis", "lat": HERE[0], "lon": HERE[1], "state": "BIHAR",
         "urgency": "planned", "window_min": 120, "has_data": True, "has_phone_signal": True}
    return {**c, **kw}


def steps(*fids, call=False):
    return [{"facility_id": f, "call_first": call, "note": ""} for f in fids]


def run(truth, st, c=None):
    return ex.run_case(c or case(), st, {(f, "dialysis"): t for f, t in truth.items()}, LISTED, KN)


def kinds(ev):
    return [(e[1], e[2], e[4]) for e in ev]


def test_treated_at_a_good_first_stop():
    ev = run({"near": good("near")}, steps("near"))
    assert kinds(ev) == [("travel", "near", ""), ("arrive", "near", ""), ("treated", "near", "in_window")]
    assert ev[-1][3] > 0


def test_not_there_then_next_stop_costs_the_turn_away():
    gone = good("near")._replace(exists=False)
    ev = run({"near": gone, "mid": good("mid")}, steps("near", "mid"))
    assert ("turned_away", "near", "not_there") in kinds(ev) and kinds(ev)[-1] == ("treated", "mid", "in_window")
    wrong_point = good("near")._replace(true_lat=27.0)
    assert ("turned_away", "near", "not_there") in kinds(run({"near": wrong_point, "mid": good("mid")},
                                                             steps("near", "mid")))


def test_call_first_no_skips_the_trip_and_no_signal_goes_anyway():
    no = good("near")._replace(offers=False)
    ev = run({"near": no, "mid": good("mid")}, steps("near", "mid", call=True))
    assert kinds(ev)[:2] == [("call", "near", "no"), ("call", "mid", "yes")]
    assert ("travel", "near", "") not in kinds(ev)
    ev = run({"near": no, "mid": good("mid")}, steps("near", "mid", call=True), case(has_phone_signal=False))
    assert kinds(ev)[0] == ("outage", "near", "no_signal") and ("turned_away", "near", "no_service") in kinds(ev)
    dead = good("near")._replace(phone_ok=False)
    assert kinds(run({"near": dead}, steps("near", call=True)))[0] == ("call", "near", "no_answer")


def test_at_most_three_steps_then_gives_up():
    bad = {f: good(f)._replace(accept_p=0.0) for f in LISTED}
    ev = run(bad, steps(*LISTED))
    assert [k for k in kinds(ev) if k[0] == "turned_away"] == [("turned_away", f, "refused") for f in
                                                                ("near", "mid", "far")]
    assert kinds(ev)[-1] == ("gave_up", None, "no_options_left")


def test_time_limit_and_late_care():
    bad = {f: good(f)._replace(accept_p=0.0) for f in LISTED}
    ev = run(bad, steps(*LISTED), case(urgency="emergency", lat=20.0))  # 6 degrees away: hours per leg
    assert kinds(ev)[-1] == ("gave_up", None, "time_limit")
    assert kinds(run({"near": good("near")}, steps("near"), case(window_min=1)))[-1] == ("treated", "near", "late")


def test_draws_are_common_across_policies():
    assert ex.draw(1, "c", "f", "open") == ex.draw(1, "c", "f", "open")
    assert ex.draw(1, "c", "f", "open") != ex.draw(1, "c", "f", "accept")
    half = {"near": good("near")._replace(accept_p=0.5)}
    seen = set()
    for i in range(20):  # the same patient at the same place gets the same answer, called first or not
        c = case(case_id=f"c{i}")
        went = kinds(run(half, steps("near"), c))[-2]
        called = kinds(run(half, steps("near", call=True), c))[0]
        assert (went == ("turned_away", "near", "refused")) == (called == ("call", "near", "no"))
        seen.add(went[0])
    assert seen == {"arrive", "turned_away"}


def test_execute_on_the_real_world_ends_every_case_once():
    cases = world.cases(11, n=5)
    ctx = pb.context()
    st = {c["case_id"]: pb.nearest_call_first(c, ctx) for c in cases.to_dict("records")}
    ev = ex.execute(cases, st, world.truth_table("S3", 11), scenario="S3", policy="nearest_call_first", run_id="t")
    assert list(ev.columns) == ex.EVENT_COLS
    ends = ev[ev.kind.isin(["treated", "gave_up"])]
    assert sorted(ends.case_id) == sorted(cases.case_id)
    assert set(ev.kind) <= {"call", "travel", "arrive", "turned_away", "treated", "gave_up", "outage", "report"}
    assert ev.groupby("case_id").step.max().max() < ex.MAX_STEPS + 1
