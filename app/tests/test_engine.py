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
from facts.redact import redact_names  # noqa: E402, RUF100
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
            if pr.model:  # derived/v2: the model's band, mapped (derived/v2/README)
                assert o["band"] == {"LIKELY": "likely", "UNLIKELY": "unlikely"}.get(pr.model[4], "not_verified")
            else:  # interim: Likely only for pairs a second source confirmed
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
                assert e["quote"] == redact_names(text) and e["field"] == field
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
        return "likely", 0.9, 0.8, 0.95, [{"label": "test model", "points": 22}], [next(iter(ENGINE.claims))]

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
    # Whatever the scores: if any Likely listing is in reach, the answer shows one (in the last slot if it did not
    # rank into the top ones) and does not abstain.
    for service in ("dialysis", "nicu", "emergency_csection"):
        for la, lo in [(26.6, 85.48), (25.6, 85.1), (19.9, 83.17), (24.78, 85.0), (26.75, 94.2)]:
            pool, _ = ENGINE._ranked(service, la, lo)
            p = ENGINE.plan(service, la, lo, 40, "gps")
            if any(r[4] == "likely" for r in pool):
                assert any(o["band"] == "likely" for o in p["options"]) and p["abstain"] is None
            else:
                assert p["abstain"] is not None


# ---------- multi-stop route (#47) ----------
ROUTED = itinerary.itinerary(ENGINE, "trauma_emergency", 25.15, 83.68) if ENGINE else None
needs_planner = pytest.mark.skipif(ROUTED is None, reason="planner/out not built (planner/export_v2.py)")


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
    assert "stub" not in it["meta"]
    opts = r.json()["options"]
    if it["plans"] and opts:  # route stop 1 is the list's first choice, or one plain line says why (#86)
        same = it["plans"][0]["stops"][0]["facility_id"] == opts[0]["facility_id"]
        assert same or (it["stop_1_note"] and opts[0]["name"] in it["stop_1_note"])
    for plan in it["plans"]:
        assert plan["stops"][-1]["purpose"] in ("definitive", "recurring")
        for st in plan["stops"]:
            assert st["eta_low"] <= st["eta_high"] and 0 <= st["p"] <= 1
            for e in st["evidence"]:  # quotes are the claim rows' own text, never another facility's sentence
                field, text, nonoffer, attribution = ENGINE.claims[e["claim_id"]]
                assert e["quote"] == redact_names(text) and not nonoffer and attribution != "other_facility"


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


def test_pair_with_no_quote_is_not_offered(monkeypatch):
    # #85: every recommendation cites facility text, so a pair with no usable quote is never an option
    def no_quote(self, facility_id, service_id):
        return "likely", 0.9, 0.8, 0.95, [], []
    monkeypatch.setattr(Engine, "score", no_quote)
    assert ENGINE.plan("dialysis", 25.6, 85.1, 40, "gps")["options"] == []


def test_second_source_outranks_the_grade():
    import dataclasses
    svc = next(iter(ENGINE.index))
    fi, pr = next(iter(ENGINE.index[svc].items()))
    fid = ENGINE._f("id", fi) if isinstance(fi, int) else fi
    saved = ENGINE.index[svc][fi]
    try:
        ENGINE.index[svc][fi] = dataclasses.replace(pr, model=None, status="verified_true", grade="counter_evidence")
        assert ENGINE.score(fid, svc)[0] == "likely"
    finally:
        ENGINE.index[svc][fi] = saved


def test_cards_use_the_route_terrain():
    # #85: a hill-state origin must get the hill constants on the cards too, as the route planner does
    assert ENGINE.origin_state(30.32, 78.03).casefold() == "uttarakhand"  # Dehradun
    hill, plain = ENGINE._travel(30.32, 78.03, 0, "Uttarakhand"), ENGINE._travel(30.32, 78.03, 0, "Bihar")
    if plain["terrain"] is None:
        pytest.skip("geo/ travel constants not available")
    assert hill["terrain"] == "hill" and plain["terrain"] == "plain" and hill["high"] >= plain["high"]


# ---------- emergency order: nearest plausible first (#92) ----------
def test_emergency_order_is_nearest_plausible_first():
    from facts.engine import NEAREST_FIRST, RANK_RULE, TIE_MIN

    for service in [s for s, v in SERVICES.items() if v["profile"] in NEAREST_FIRST]:
        for la, lo in [(26.6, 85.48), (25.6, 85.1), (19.9, 83.17), (27.57, 81.6), (26.75, 94.2)]:
            p = ENGINE.plan(service, la, lo, 40, "gps")
            mins = [o["travel"]["minutes"] for o in p["options"]]
            pool, _ = ENGINE._ranked(service, la, lo)
            # Every option before the last is no farther (to TIE_MIN) than every pool row it was chosen over; the
            # last slot may be a confirmed listing pulled in so it is never hidden.
            for k in range(len(mins) - 1):
                assert mins[k] <= mins[k + 1] + TIE_MIN
            if p["options"]:
                assert p["options"][0]["why_first_text"] == RANK_RULE["nearest_plausible"]
                assert p["rank_rule"]["code"] == "nearest_plausible" and 0 <= p["rank_rule"]["expected_in_window"] <= 1
                assert mins[0] <= min(r[1] for r in pool) + TIE_MIN


def test_planned_care_keeps_evidence_and_time():
    p = ENGINE.plan("dialysis", 25.6, 85.1, 40, "gps")
    assert p["rank_rule"]["code"] == "evidence_and_time" and p["rank_rule"]["expected_in_window"] is None


def test_expected_in_window_counts_calls_in_order():
    from facts.engine import expected_in_window

    assert expected_in_window([(0.5, 20), (0.5, 20)], 60, 5) == 0.75
    assert expected_in_window([(0.5, 20), (0.5, 58)], 60, 5) == 0.5  # the second is past the window after 2 calls
    assert expected_in_window([], 60) == 0.0


def test_nearest_plausible_ties_have_no_bucket_edge():
    from facts.engine import nearest_plausible

    rows = [(0.38, 102, "a"), (0.79, 102, "b"), (0.95, 103, "c"), (0.9, 130, "d"), (0.2, 20, "e")]
    assert [r[2] for r in nearest_plausible(rows)] == ["e", "c", "b", "a", "d"]
    # a tie never pulls the first choice out of the window
    assert [r[2] for r in nearest_plausible([(0.7, 60, "in"), (0.9, 63, "out")], 60)] == ["in", "out"]


def test_toll_free_numbers_are_dialable():
    from facts.build import e164

    assert e164("1800 313 1714") == "18003131714"  # shown as a call link, not "no phone number in our data"
    assert e164("98765 43210") == "+919876543210" and e164("12345") is None


def test_every_planner_route_type_has_words() -> None:
    """A route heading never shows a raw planner key such as 'three_sites' (#113 review)."""
    import itinerary
    for key in ("direct", "one_stop", "two_stop", "single_site", "two_sites", "three_sites"):
        assert key in itinerary.TYPE and "_" not in itinerary.TYPE[key]


def test_ownership_line_only_when_the_operator_is_unknown():
    """#121: "our data does not say if it is public or private" sat on a card labelled Government, and on every card.
    Pusa trauma option 1 is Sub Divisional Hospital Pusa (public)."""
    seen = set()
    for svc, la, lo in [("trauma_emergency", 25.6, 85.95), *QUERIES.values()]:
        for o in ENGINE.plan(svc, la, lo, 40, "gps")["options"]:
            seen.add(o["operator"])
            reasons = [c["asked_because"] for c in o["call_ahead"]]
            unknown = "our data does not say if it is public or private" in reasons
            if o["operator"] != "unknown":
                assert not unknown, (o["name"], o["operator"], reasons)
            if o["operator"] == "public":
                assert not any("cost" in c["question"] for c in o["call_ahead"]), (o["name"], o["call_ahead"])
    assert {"public", "private"} <= seen
