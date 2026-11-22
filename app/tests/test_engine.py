"""Real facilities behind the plan contract (issue #42). Skips when app/facts/out is not built."""
from __future__ import annotations

import json
import math
import random
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


def in_budget(r) -> bool:
    """Spec section 7: plan JSON <= 20 KB gzip on the wire; decoded under 32 KB (the witness ledger made it 29 KB)."""
    return (r.headers.get("content-encoding") == "gzip" and int(r.headers["content-length"]) < 20_000
            and len(r.content) < 32_000)


def plans():
    return {k: ENGINE.plan(s, la, lo, 40, "gps") for k, (s, la, lo) in QUERIES.items()}


@pytest.mark.parametrize("name", QUERIES)
def test_release_queries_answer_from_real_rows(name):
    s, la, lo = QUERIES[name]
    t = time.perf_counter()
    r = client.post("/api/plan", json={"service": s, "lat": la, "lon": lo, "accuracy_m": 40})
    ms = (time.perf_counter() - t) * 1000
    print(f"{name}: {ms:.0f} ms, {len(r.content)} B")
    assert r.status_code == 200 and ms < 500 and in_budget(r)
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


V2_SCORES = APP.parent / "derived" / "v2" / "facility_service_scores.parquet"
TAXONOMY = {"trauma_emergency": "trauma_care"}  # app service id -> derived/v2 service_id where they differ


@pytest.mark.skipif(not V2_SCORES.is_file(), reason="derived/v2 not present")
def test_ledger_rows_are_the_model_terms_and_sum_to_p():
    """The Why page ledger is derived/v2's own: for 100 random pairs, after a JSON round trip, the rows are the base and
    the non-zero terms in the model's order, each within the 0.1 rounding of 10 x its logit share, and they sum to
    10 x logit(p) to the tenth, so the total maps back to p within 0.0013. Every quote a row shows is an app claim."""
    import pandas as pd
    served = [(s, pr) for s, rows in ENGINE.pairs.items() for pr in rows if pr.ledger]
    assert len(served) == sum(len(rows) for rows in ENGINE.pairs.values())  # every served pair carries its ledger
    picks = random.Random(20261122).sample(served, 100)
    v2 = pd.read_parquet(V2_SCORES, columns=["unique_id", "service_id", "p", "base", "contributions"])
    v2 = v2.set_index(["unique_id", "service_id"])
    for s, pr in picks:
        fid = ENGINE.fac["id"][pr.fi]
        _, p, *_, contrib, _ = json.loads(json.dumps(ENGINE.score(fid, s)))
        rows = [c for c in contrib if "family" in c]  # the duplicate-listings row (no family, 0 points) is extra
        assert sum(c["points"] for c in contrib) == pytest.approx(sum(c["points"] for c in rows))
        row = v2.loc[(fid, TAXONOMY.get(s, s))]
        terms = [t for t in json.loads(row.contributions) if t["points"]]
        want = [10 * row.base] + [10 * t["points"] * math.log(2) / 20 for t in terms]
        assert [c["family"] for c in rows] == ["base", *(t["family"] for t in terms)], (fid, s)
        assert all(abs(c["points"] - w) <= 0.1 + 1e-9 for c, w in zip(rows, want, strict=True)), (fid, s)
        total = sum(c["points"] for c in rows)
        assert abs(total / 10 - math.log(p / (1 - p))) <= 0.005 + 1e-9, (fid, s, total, p)
        assert abs(1 / (1 + math.exp(-total / 10)) - p) < 0.0013
        assert all(round(c["points"], 1) == c["points"] for c in rows)
        for c in rows:
            for q in c["quotes"]:
                assert q["claim_id"] in ENGINE.claims and q["quote"] == ENGINE.claims[q["claim_id"]][1]


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
    assert r.status_code == 200 and ms < 500 and in_budget(r), (ms, len(r.content))
    assert it["pathway"] and (it["plans"] or it["abstain"])
    assert "stub" not in it["meta"]
    opts = r.json()["options"]
    if it["plans"] and opts:  # route stop 1 is the list's first choice, or the route is framed as the fallback (#126)
        same = it["plans"][0]["stops"][0]["facility_id"] == opts[0]["facility_id"]
        assert same or it["fallback"]["text"].startswith("If they cannot treat: ")
    for plan in it["plans"]:
        assert plan["stops"][-1]["purpose"] in ("definitive", "recurring")
        for st in plan["stops"]:
            assert st["eta_low"] <= st["eta_high"] and 0 <= st["p"] <= 1
            for e in st["evidence"]:  # quotes are the claim rows' own text, never another facility's sentence
                field, text, nonoffer, attribution = ENGINE.claims[e["claim_id"]]
                assert e["quote"] == redact_names(text) and not nonoffer and attribution != "other_facility"


def _post(s: str, la: float, lo: float) -> dict:
    return client.post("/api/plan", json={"service": s, "lat": la, "lon": lo, "accuracy_m": 40}).json()


@needs_planner
def test_route_changes_the_options_only_by_leading_with_its_first_stop():
    plain = [o["facility_id"] for o in ENGINE.plan("trauma_emergency", 25.6, 85.14, 40, "gps")["options"]]
    routed = _post("trauma_emergency", 25.6, 85.14)
    ids = [o["facility_id"] for o in routed["options"]]
    assert ids[0] == routed["itinerary"]["plans"][0]["stops"][0]["facility_id"]
    rest = [i for i in plain if i in ids[1:]]
    assert ids[1:1 + len(rest)] == rest  # the others keep their order


# #126: a route stop beyond the window and farther than card 1 never displaces it; the route becomes the fallback
FAR_ROUTES = {"banda_trauma": ("trauma_emergency", 25.48, 80.33, "Ask: do you take accident patients now?"),
              "banda_csection": ("emergency_csection", 25.48, 80.33, "Ask: can you do an emergency C-section now?")}


@needs_planner
@pytest.mark.parametrize("name", FAR_ROUTES)
def test_far_route_stop_leaves_card_1_and_is_the_fallback(name):
    s, la, lo, ask = FAR_ROUTES[name]
    plain = ENGINE.plan(s, la, lo, 40, "gps")["options"]
    p = _post(s, la, lo)
    o, it = p["options"], p["itinerary"]
    assert [x["facility_id"] for x in o] == [x["facility_id"] for x in plain] and o[0]["call_first"]
    stop = it["plans"][0]["stops"][0]
    assert stop["facility_id"] != o[0]["facility_id"] and not any(x.get("route_reason") for x in o)
    assert it["fallback"]["ask"] == ask and it["stop_1_note"] is None
    assert it["fallback"]["text"].startswith("If they cannot treat: ") and stop["name"] in it["fallback"]["text"]


# #121: in an emergency with a route, card 1 is the route's first stop and says why; the former first says what it lacks
LEADS = {"patna_trauma": ("trauma_emergency", 25.6, 85.14, "Medifino Hospital"),
         "bahraich_csection": ("emergency_csection", 27.57, 81.6, "Krishna Medical Centre")}


@needs_planner
@pytest.mark.parametrize("name", LEADS)
def test_emergency_card_1_is_the_route_first_stop_with_its_reason(name):
    s, la, lo, before = LEADS[name]
    assert ENGINE.plan(s, la, lo, 40, "gps")["options"][0]["name"] == before  # what the engine alone ranks first
    p = _post(s, la, lo)
    o, it = p["options"], p["itinerary"]
    assert o[0]["facility_id"] == it["plans"][0]["stops"][0]["facility_id"] and o[0]["call_first"]
    assert o[0]["route_reason"] == o[0]["why_first_text"]
    assert o[0]["route_reason"].startswith("First: it has evidence of ") and before in o[0]["route_reason"]
    old = next(x for x in o if x["name"] == before)
    assert old["rank"] == 2 and not old["call_first"] and "no evidence of" in old["route_reason"]
    assert [x["rank"] for x in o] == list(range(1, len(o) + 1)) and it["stop_1_note"] is None
    assert p["what_would_change"]["first_name"] == o[0]["name"]  # "if the first says no" follows the new order
    assert all(w["facility_id"] != o[0]["facility_id"] for w in p["why_not"])
    assert "first_stop" not in it


@needs_planner
def test_route_that_already_agrees_and_planned_care_are_unchanged():
    for s, la, lo in (("trauma_emergency", 25.6, 85.95), ("dialysis", 24.79, 85.0)):  # Pusa trauma; Gaya dialysis
        plain = ENGINE.plan(s, la, lo, 40, "gps")["options"]
        p = _post(s, la, lo)
        assert [o["facility_id"] for o in p["options"]] == [o["facility_id"] for o in plain]
        assert not any(o.get("route_reason") for o in p["options"])
    p = _post("trauma_emergency", 25.6, 85.95)
    assert p["options"][0]["facility_id"] == p["itinerary"]["plans"][0]["stops"][0]["facility_id"]


@pytest.mark.skipif(ENGINE is None or ENGINE.pin_where == list(zip(ENGINE.pins["district"], ENGINE.pins["state"])),
                    reason="pin_districts.json not built (needs data/external/lgd_district_polygons)")
def test_area_names_the_district_the_point_lies_in():
    # (25.6, 85.95), the Pusa demo point, lies in Begusarai (LGD district and PIN 851128 polygons); the nearest PIN
    # centre is 847428, a Darbhanga PIN placed there (validation C4).
    a = client.post("/api/area", json={"service": "emergency_csection", "lat": 25.6, "lon": 85.95}).json()
    assert a["area"]["district"] == "Begusarai"


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


def test_uncapped_p_breaks_an_equal_capped_tie():
    """#140 2a: inside the 5-minute tie, rows capped at the same rank_p go by their uncapped p, then nearer first."""
    from facts.engine import nearest_plausible

    rows = [(0.5, 2, None, None, "not_verified", 0.56, "clinic"), (0.5, 2.4, None, None, "not_verified", 0.98, "hosp")]
    assert [r[6] for r in nearest_plausible(rows)] == ["hosp", "clinic"]
    rows = [(0.5, 2, None, None, "not_verified", 0.7, "near"), (0.5, 3, None, None, "not_verified", 0.7, "far")]
    assert [r[6] for r in nearest_plausible(rows)] == ["near", "far"]


def test_gaya_trauma_children_clinic_is_not_an_option():
    """#140 2a: Baibhav Shishu Care (a children's clinic, p 0.56) led Arsh Superspeciality (p 0.98) as option 2 at
    Gaya because both NO_SERVICE_TEXT scores were capped at the Likely threshold and the clinic was nearer."""
    pool, _ = ENGINE._ranked("trauma_emergency", 24.79, 85.0)
    assert all(len(r) == 6 and r[5] >= r[0] for r in pool)  # the uncapped p rides along and is never below rank_p
    names = [o["name"] for o in ENGINE.plan("trauma_emergency", 24.79, 85.0, 40, "gps")["options"]]
    assert names[:2] == ["Dr. A Barkat Multispeciality Hospital", "Arsh Superspeciality Hospital"]
    assert "Baibhav Shishu Care" not in names


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


def test_first_is_nearest_when_no_listing_is_nearer():
    """#121: "Why not the nearest?" listed only farther places when option 1 was already the nearest. The payload
    says so (first_is_nearest), and never while a nearer listing is shown under "why not"."""
    sitamarhi = ("dialysis", 26.5951, 85.4808)  # Prasad Hospital first; the rest are 1 to 4 min farther
    mohania_cs = ("emergency_csection", 25.15, 83.68)  # two why-not listings are nearer than option 1
    seen = {}
    for q in [sitamarhi, mohania_cs, *QUERIES.values()]:
        p = ENGINE.plan(*q, 40, "gps")
        assert p["first_is_nearest"] == all(w["minutes_vs_first"] >= 0 for w in p["why_not"]), (q, p["why_not"])
        seen[q] = p["first_is_nearest"]
    assert seen[sitamarhi] is True and seen[mohania_cs] is False
def test_call_ahead_never_says_not_mentioned_next_to_a_quote_naming_it():
    """#121: Pusa dialysis asked "Do you have dialysis unit or machine on site? (our data does not mention it)" next
    to the quote "Advanced Kidney Dialysis". A quote naming it leaves only today's availability unknown."""
    from facts.engine import NEED_WORDS

    for svc, la, lo in [("dialysis", 25.6, 85.95), *QUERIES.values()]:
        for o in ENGINE.plan(svc, la, lo, 40, "gps")["options"]:
            pr = ENGINE.index[svc][ENGINE.fid[o["facility_id"]]]
            quotes = [e["quote"] for e in o["evidence"]]
            for c in o["call_ahead"]:
                if c["asked_because"] == "our data does not mention it":
                    words = NEED_WORDS.get(pr.missing[0])
                    assert not (words and any(words.search(q) for q in quotes)), (o["name"], c, quotes)
            if svc == "dialysis" and any("dialys" in q.lower() for q in quotes):
                assert not any("on site" in c["question"] for c in o["call_ahead"]), (o["name"], o["call_ahead"])
    pusa = ENGINE.plan("dialysis", 25.6, 85.95, 40, "gps")["options"]
    assert any(c["asked_because"] == "its listing names it, but not whether it is free today"
               for o in pusa for c in o["call_ahead"])


def test_likely_options_show_the_values_the_band_rule_tested() -> None:
    """#121: a Likely card showed location 0.34 (derived/v1 facility trust) while the model's own P_L was above 0.7.
    Over every served pair, a LIKELY pair's p, p_l and p_e meet derived/v2 model_card band_thresholds.likely."""
    import json

    from facts.build import MODEL_CARD
    t = json.loads(MODEL_CARD.read_text())["band_thresholds"]["likely"]
    n, bad = 0, []
    for svc, rows in ENGINE.pairs.items():
        for pr in rows:
            if ENGINE.model_band(pr) != "LIKELY":
                continue
            n += 1
            shown = ENGINE._exists_where(pr, pr.fi)
            assert (shown["p_l"], shown["p_e"]) == (pr.model[5], pr.model[6])
            if pr.model[1] < t["p"] or shown["p_l"] < t["p_location"] or shown["p_e"] < t["p_exists"]:
                bad.append((svc, ENGINE.fac["name"][pr.fi], pr.model[1], shown["p_l"], shown["p_e"]))
    assert n > 1000 and not bad, bad[:5]


def test_option_p_l_is_the_model_value_not_the_v1_trust_score() -> None:
    plan = ENGINE.plan("trauma_emergency", 25.6, 85.95, 40, "gps")  # the Pusa demo query from #121
    assert plan["options"]
    for o in plan["options"]:
        pr = ENGINE.index["trauma_emergency"][ENGINE.fid[o["facility_id"]]]
        assert (o["p_l"], o["p_e"]) == (pr.model[5], pr.model[6])
        if o["model_band"] == "LIKELY":
            assert o["p_l"] >= 0.7 and o["p_e"] >= 0.7


def test_interim_pairs_keep_the_v1_trust_scores() -> None:
    pr = ENGINE.pairs["dialysis"][0]
    old = pr.model
    try:
        pr.model = None
        assert ENGINE._exists_where(pr, pr.fi) == {"p_e": ENGINE.fac["p_e"][pr.fi], "p_l": ENGINE.fac["p_l"][pr.fi]}
    finally:
        pr.model = old


# #126 item 4 (lead): a direct route to definitive care inside the window leads; the nearer former first is framed as
# first care if needed sooner, never as the best option, and "Nearer" only when it really is nearer
@needs_planner
def test_direct_definitive_leads_and_the_nearer_first_care_place_says_so():
    p = _post("trauma_emergency", 26.15, 85.9)  # Darbhanga
    o, w = p["options"], p["time_window"]["window_min"]
    assert o[0]["route_reason"].startswith(f"Go here directly: definitive care within the {w}-minute window")
    near = next(x for x in o[1:] if (x.get("route_reason") or "").startswith("Nearer: can give first care in about"))
    assert near["travel"]["minutes"] < o[0]["travel"]["minutes"]
    assert f"about {near['travel']['minutes']} min" in near["route_reason"]
    assert not any("best option" in (x.get("route_reason") or "") for x in o[1:])
    patna = _post("trauma_emergency", 25.6, 85.14)["options"]  # the former first is farther: no "Nearer" line
    assert not any((x.get("route_reason") or "").startswith("Nearer") for x in patna)
