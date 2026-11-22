"""#86 stand-out features on real rows: why not the nearest, flagged citations with doctor names redacted, and the
data gap vs care gap split. The page side (every new value shown and marked) is in test_faithfulness.py."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import itinerary  # noqa: E402, RUF100
from facts.engine import LOC_DOUBT, QUOTE_FLAGS, WINDOW, Engine  # noqa: E402, RUF100
from facts.redact import redact_names  # noqa: E402, RUF100
from services import SERVICES  # noqa: E402, RUF100

ENGINE = Engine.load()
needs_data = pytest.mark.skipif(ENGINE is None, reason="facility data not built (app/facts/build.py)")
NAMED = re.compile(r"\b(?:Dr|DR|Prof)\b\.?\s*[A-Z][a-z]+\s+[A-Z][a-z]+\b(?!\s+(?:Hospital|Memorial|Medical|Institute))")
PROBES = [("trauma_emergency", 25.6, 85.95), ("dialysis", 26.6, 85.48), ("emergency_csection", 19.88, 75.34),
          ("trauma_emergency", 25.15, 83.68), ("mri", 21.15, 79.09), ("cardiac_surgery", 18.52, 73.86),
          ("nicu", 24.0, 84.0), ("burn_care", 23.02, 72.57), ("mri", 19.07, 72.88)]
# Places for data-driven checks: the cases below are searched for, not hard-coded, so a model refit cannot break them.
GRID = [(25.6, 85.1), (28.6, 77.2), (18.52, 73.86), (21.15, 79.09), (26.85, 80.95), (22.57, 88.36), (19.07, 72.88),
        (12.97, 77.59), (25.6, 85.95), (26.6, 85.48)]
GRID_PROBES = [(s, la, lo) for s in sorted(SERVICES) for la, lo in GRID]


# ---------- doctor names ----------
@pytest.mark.parametrize("raw, shown", [
    ("Has on-site dental surgeon Dr. Arvind Kumar Yadav", "Has on-site dental surgeon a doctor"),
    ("Dr. Ganesh Deshmukh specializes in Orthopedics.", "A doctor specializes in Orthopedics."),
    ("Has Dr. Satish V. Kamat, Cancer Specialist and Surgeon", "Has a doctor, Cancer Specialist and Surgeon"),
    ("established in 1967 by Dr N N Asokan with 20 beds", "established in 1967 by a doctor with 20 beds"),
    ("consultant (Dr. Manish Nanda) specializing", "consultant (a doctor) specializing"),
    ("Dr.A.K. Singh heads the ICU. He operates daily", "A doctor heads the ICU. He operates daily"),
    ("Dr. Tarkit Modi’s team does joint surgery", "A doctor's team does joint surgery"),
    # places and institutions named after someone are not a person on staff
    ("Blood bank at Dr. Imkongliba Memorial Hospital", "Blood bank at Dr. Imkongliba Memorial Hospital"),
    ("Dr Ram Manohar Lohia Hospital runs trauma care", "Dr Ram Manohar Lohia Hospital runs trauma care"),
    ("Has a doctor on call 24x7", "Has a doctor on call 24x7"),
])
def test_doctor_names_are_redacted(raw, shown):
    assert redact_names(raw) == shown
    assert redact_names(shown) == shown  # idempotent: the test can redact the claim text again


@needs_data
def test_no_named_doctor_in_any_quote_and_the_claim_id_stays():
    for s, la, lo in PROBES:
        p = itinerary.attach(ENGINE.plan(s, la, lo, 40, "gps"), ENGINE)
        quotes = [e for o in p["options"] for e in o["evidence"]]
        quotes += [e for r in (p["itinerary"] or {}).get("plans", []) for st in r["stops"] for e in st["evidence"]]
        for e in quotes:
            assert not NAMED.search(e["quote"]), e
            assert e["claim_id"] in ENGINE.claims
        assert not any(NAMED.search(f) for o in p["options"] for f in o["flags"])
    shown = [(e, ENGINE.claims[e["claim_id"]][1]) for s, la, lo in GRID_PROBES
             for o in ENGINE.plan(s, la, lo, 40, "gps")["options"] for e in o["evidence"]]
    named = [e for e, raw in shown if NAMED.search(raw)]
    assert named and all(e["quote"] == redact_names(raw) != raw for e, raw in shown if NAMED.search(raw)
                         and redact_names(raw) != raw)  # real named-doctor sentences are shown redacted


def test_offline_pack_quotes_are_redacted():
    bp = pytest.importorskip("packs.build_packs")
    got = bp._site_quotes("abcd1234-x", [("abcd1234-x", "Dr. Ram Kumar Singh does dialysis || Dialysis unit")], {})
    assert all("Ram Kumar" not in t for t, _ in got) and any(t == "A doctor does dialysis" for t, _ in got)


# ---------- flagged citations ----------
@needs_data
def test_source_is_a_page_about_the_facility_not_another_town():
    i = ENGINE.fid["61731339-a1d6-4384-92ee-fce2d11b3338"]  # SDH Pusa: the audit's Rajauli Wikipedia citation
    assert "wikipedia.org/wiki/Rajauli" not in (ENGINE.fac["url"][i] or "")
    assert ENGINE.fac["url_kind"][i] == "about"


@needs_data
def test_quote_flags_come_from_pipeline_fields_and_weak_quotes_come_last():
    seen = set()
    for s, la, lo in PROBES + GRID_PROBES:
        for o in ENGINE.plan(s, la, lo, 40, "gps")["options"]:
            i = ENGINE.fid[o["facility_id"]]
            for e in o["evidence"]:
                for f in e["flags"]:
                    seen.add(f["code"])
                    assert f["text"] == QUOTE_FLAGS[f["code"]][0] and f["weak"] == QUOTE_FLAGS[f["code"]][1]
                    if f["code"].startswith("src_"):
                        kind, place = ENGINE.fac["url_kind"][i], ENGINE.fac["url_place"][i]
                        assert f["code"] == ("src_other_place" if place else "src_" + kind)
                    else:
                        assert f["code"] in {c for c, _ in ENGINE.claim_flags[e["claim_id"]]}
            weak = [sum(f["weak"] for f in e["flags"]) for e in o["evidence"]]
            assert weak == sorted(weak)
            flagged = any(f["weak"] for e in o["evidence"] for f in e["flags"])
            row = [c for c in o["contributions"] if c["label"].startswith("quoted sentences with a warning")]
            assert bool(row) == flagged and all(c["points"] == 0 for c in row)
    assert {"src_list", "src_unverified"} <= seen


@needs_data
def test_demoted_not_hidden(monkeypatch):
    s, la, lo = "mri", 21.15, 79.09
    before = {o["facility_id"]: {e["claim_id"] for e in o["evidence"]} for o in ENGINE.plan(s, la, lo, 40, "gps")
              ["options"]}
    cid = next(iter(next(iter(before.values()))))
    monkeypatch.setitem(ENGINE.claim_flags, cid, [["ambiguous", None]])
    after = {o["facility_id"]: [e["claim_id"] for e in o["evidence"]] for o in ENGINE.plan(s, la, lo, 40, "gps")
             ["options"]}
    fid = next(f for f, ids in before.items() if cid in ids)
    assert set(after[fid]) == before[fid] and after[fid][-1] == cid  # still shown, now last


# ---------- why not the nearest ----------
@needs_data
@pytest.mark.parametrize("s, la, lo", PROBES)
def test_why_not_rows_rest_on_engine_fields(s, la, lo):
    p = ENGINE.plan(s, la, lo, 40, "gps")
    opts, rows = p["options"], p["why_not"]
    if len(opts) < 2:
        return
    assert rows, "every answer with more than one candidate explains why not the nearest"  # abstaining ones too
    first = opts[0]
    assert all(w["facility_id"] != first["facility_id"] for w in rows)
    assert [w["travel"]["minutes"] for w in rows] == sorted(w["travel"]["minutes"] for w in rows)
    for w in rows:
        i = ENGINE.fid[w["facility_id"]]
        pr = ENGINE.index[s][i]
        assert w["band"] == ENGINE.score(w["facility_id"], s)[0]
        assert w["minutes_vs_first"] == w["travel"]["minutes"] - first["travel"]["minutes"]
        # The only number a reason may hold is the "Likely, but N min farther" lead (#140 2d), and it is the row's own
        # minutes_vs_first; every other number on the row comes from a marked field.
        lead = w["reason"].startswith("It is rated Likely, but it is ")
        assert 1 <= len(w["basis"]) <= 2 and w["reason"]
        assert re.findall(r"\d+", w["reason"]) == ([str(w["minutes_vs_first"])] if lead else [])
        assert not lead or (w["basis"][0] == {"code": "farther", "field": "minutes_vs_first",
                                              "value": w["minutes_vs_first"]} and w["band"] == "likely" != first["band"])
        for b in w["basis"]:
            c = b["code"]
            if c == "location":
                assert ENGINE.fac["loc_rule"][i] == b["value"] in LOC_DOUBT
            elif c == "shared_phone":
                assert ENGINE.fac["phone_shared"][i] == b["value"] >= 3
            elif c == "missing":
                top = ENGINE.index[s][ENGINE.fid[first["facility_id"]]]
                assert b["value"] in pr.missing and b["value"] not in top.missing
            elif c == "evidence_kind":
                assert pr.rule == b["value"]
            elif c == "outside_window":
                assert b["window_min"] == WINDOW[SERVICES[s]["profile"]] < b["value"] == w["travel"]["minutes"]
            elif c == "no_quote":
                assert not ENGINE.score(w["facility_id"], s)[5]
    assert p["time_window"]["first_outside"] == (first["travel"]["minutes"] > p["time_window"]["window_min"])


@needs_data
def test_what_would_change_is_a_phone_call_that_really_changes_the_order(monkeypatch):
    s, la, lo = next(q for q in GRID_PROBES
                     if (ENGINE.plan(*q, 40, "gps")["what_would_change"] or {}).get("kind") == "confirm_nearer")
    c = ENGINE.plan(s, la, lo, 40, "gps")["what_would_change"]
    assert c["minutes_vs_first"] < 0
    # Re-run with that pair confirmed at the confirmed-pair score: it must now rank first.
    pr = ENGINE.index[s][ENGINE.fid[c["facility_id"]]]
    monkeypatch.setattr(pr, "status", "verified_true")
    monkeypatch.setattr(pr, "score", ENGINE.p_confirmed)
    if pr.model:
        monkeypatch.setattr(pr, "model", ["likely", ENGINE.p_confirmed, *pr.model[2:4], "LIKELY"])
    assert ENGINE.plan(s, la, lo, 40, "gps")["options"][0]["facility_id"] == c["facility_id"]


@needs_data
def test_change_falls_back_to_option_two_when_no_call_can_flip_it():
    p = next(x for x in (ENGINE.plan(*q, 40, "gps") for q in GRID_PROBES)
             if (x["what_would_change"] or {}).get("kind") == "first_says_no")
    c = p["what_would_change"]
    assert c["kind"] == "first_says_no" and c["facility_id"] == p["options"][1]["facility_id"]
    assert c["minutes_vs_first"] == p["options"][1]["travel"]["minutes"] - p["options"][0]["travel"]["minutes"]


@needs_data
def test_first_choice_outside_the_window_is_flagged():
    plans = [ENGINE.plan(*q, 40, "gps") for q in PROBES + GRID_PROBES]
    for p in plans:
        first = p["options"][0] if p["options"] else None
        if first:
            assert p["time_window"]["first_outside"] == (first["travel"]["minutes"] > p["time_window"]["window_min"])
        if p["abstain"]:
            assert p["public_option"] == p["abstain"]["outside_option"]  # abstaining: the same public hospital
    assert any(p["time_window"]["first_outside"] for p in plans if p["options"])  # the case occurs in the data


@needs_data
def test_likely_option_too_far_names_the_public_standard_hospital_without_abstaining():
    p = ENGINE.plan("emergency_csection", 20.8, 85.01, 40, "gps")  # Odisha: a Likely option 1 beyond 60 min
    first, po = p["options"][0], p["public_option"]
    assert p["abstain"] is None and first["band"] == "likely" and first["travel"]["minutes"] > 60
    assert p["time_window"]["first_outside"] and po and po["label"] == "by public standard, not verified"
    i = ENGINE.fid[po["facility_id"]]
    assert "emergency_csection" in ENGINE.fac["public_standard"][i]  # IPHS expects it at this level (#85 H2)
    assert po["facility_id"] not in {o["facility_id"] for o in p["options"]} | {w["facility_id"] for w in p["why_not"]}
    # nearest such hospital within the search radius
    km = ENGINE._public_near("emergency_csection", p["location"]["lat"], p["location"]["lon"])[0]
    assert abs(po["travel"]["km"] - km) < km * 0.6 + 1
    assert {"108"} <= {n["number"] for n in p["emergency_numbers"]}
    inside = ENGINE.plan("mri", 28.6, 77.2, 40, "gps")
    assert not inside["time_window"]["first_outside"] and inside["public_option"] is None


@needs_data
def test_area_names_public_standard_hospitals_where_there_is_no_public_evidence():
    a = ENGINE.area("trauma_emergency", 25.15, 83.68)
    none = [r for r in a["pins"] if r["first"] is None]
    # where no public facility's level is expected to offer trauma care (IPHS 2022), none is named (#85 H2)
    assert none and all(r["public"] is None or r["public"]["label"] == "by public standard, not verified" for r in none)
    assert all(r["public"] is None for r in a["pins"] if r["first"])
    for r in none:
        assert r["public"] is None or "trauma_emergency" in ENGINE.fac["public_standard"][ENGINE.fid[r["public"]["facility_id"]]]
    g = ENGINE.area("trauma_emergency", 25.6, 85.95)["gap"]  # Darbhanga
    for h in g["public_standard"]:
        i = ENGINE.fid[h["facility_id"]]
        assert "trauma_emergency" in ENGINE.fac["public_standard"][i] and ENGINE.fac["district"][i] == "DARBHANGA"


# ---------- data gap vs care gap ----------
@needs_data
@pytest.mark.parametrize("s, la, lo", [("trauma_emergency", 25.6, 85.95), ("burn_care", 34.1, 77.5),
                                       ("nicu", 25.15, 83.68), ("cardiac_surgery", 22.0, 82.0)])
def test_gap_split_adds_up_and_matches_the_pins(s, la, lo):
    a = ENGINE.area(s, la, lo)
    g = a["gap"]
    assert g["covered"] + g["not_confirmed"] + g["far"] + g["no_claim"] == g["pins_sampled"] == len(a["pins"])
    assert g["pins_sampled"] <= g["pins_in_district"] and g["district_confirmed"] <= g["district_claiming"]
    for r in a["pins"]:
        if r["gap"] == "covered":
            assert r["first"] is not None
        if r["gap"] in ("far", "no_claim"):
            assert r["first"] is None


@needs_data
def test_ladakh_burns_is_a_data_gap_not_a_care_gap():
    g = ENGINE.area("burn_care", 34.1, 77.5)["gap"]
    assert g["no_claim"] == g["pins_sampled"] > 0 and g["district_claiming"] == 0


@needs_data
def test_outside_option_follows_the_public_standard_per_service():
    """#85 H2: no AYUSH college, and no cardiac surgery claim for a district hospital."""
    for s, la, lo in [("trauma_emergency", 28.61, 77.21), ("burn_care", 26.76, 83.37)]:  # were homeopathic / ayurvedic
        po = ENGINE._outside(s, la, lo)
        assert po is None or not re.search(r"ayurved|homoeo|homeo|unani|siddha", po["name"], re.I)
    levels = {ENGINE.fac["public_level"][i] for i, svcs in enumerate(ENGINE.fac["public_standard"]) if "cardiac_surgery" in svcs}
    assert levels and levels <= {"mc"}


@needs_data
@pytest.mark.parametrize("s", ["emergency_csection", "nicu", "trauma_emergency", "burn_care"])
def test_bahraich_is_a_care_gap_with_the_nearest_public_hospital_or_none(s):
    """#86 item 3: the Bahraich cases with nothing in reach read as a care gap in our data, say how many listings the
    district has, and name the nearest public-standard hospital we have, or say there is none within the radius."""
    a = ENGINE.area(s, 27.57, 81.6)
    g = a["gap"]
    assert a["area"]["district"] == "Bahraich" and g["covered"] == 0 and g["no_claim"] == 0 and g["pins_sampled"] > 0
    assert a["summary"]["n_without_option"] == g["far"]  # burns: some PINs have unconfirmed listings in reach
    assert g["district_listings"] >= 0 and not g["public_standard"]
    pn = g["public_nearest"]
    if pn is not None:
        assert pn["label"] == "by public standard, not verified" and pn["km"] <= g["radius_km"]
        assert s in ENGINE.fac["public_standard"][ENGINE.fid[pn["facility_id"]]]


@needs_data
def test_public_nearest_only_when_the_district_names_no_public_hospital():
    for s, la, lo in [("trauma_emergency", 25.6, 85.95), ("nicu", 25.15, 83.68), ("burn_care", 27.57, 81.6)]:
        g = ENGINE.area(s, la, lo)["gap"]
        assert (g["public_nearest"] is None) or not g["public_standard"]
