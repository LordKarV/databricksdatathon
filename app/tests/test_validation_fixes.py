"""Fixes from the validation audit (#78): eligibility, one option per real facility, NaN-safe stops, stable packs.

Run from app/: python -m pytest tests -q. Data-dependent tests skip when derived/v1 or the builds are missing.
"""
import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent))
from itinerary import place, stop_1_note  # noqa: E402, RUF100
from packs import build_packs as bp  # noqa: E402, RUF100

import app as app_module  # noqa: E402, RUF100
from common import eligibility as el  # noqa: E402, RUF100

V1 = APP.parent / "derived" / "v1"
PACKS = APP / "packs" / "out"
needs_v1 = pytest.mark.skipif(not (V1 / "facility_groups.parquet").is_file(), reason="derived/v1 not present")
needs_packs = pytest.mark.skipif(not (PACKS / "index.json").is_file(), reason="packs not built")
needs_engine = pytest.mark.skipif(app_module._engine() is None, reason="facts not built")
VET = "885c79f6-9f32-4878-8384-5a90259cfae4"  # SKS Veterinary Hospital, trust_level exclude_review


# ---------- the shared rule, on small frames ----------
def test_eligible_facilities_drops_excluded_and_unplaced_keeps_unassessed():
    df = pd.DataFrame({"loc_lat": [1.0, 1.0, np.nan, 1.0, 95.0], "loc_lon": [2.0, 2.0, 2.0, 2.0, 2.0],
                       "trust_level": ["no_concerns", "exclude_review", "minor", None, "minor"]})
    mask, counts = el.eligible_facilities(df)
    assert mask.tolist() == [True, False, False, True, False]
    assert counts == {"rows": 5, "no_coordinates": 2, "exclude_review": 1, "unassessed_kept": 1, "kept": 2}


def test_eligible_pairs_drops_excluded_grades_and_verified_false():
    df = pd.DataFrame({"grade": ["strong", "counter_evidence", "weak", "attributed_elsewhere"],
                       "status": ["verified_true", "unverified", "verified_false", "verified_false"]})
    mask, counts = el.eligible_pairs(df)
    assert mask.tolist() == [True, False, False, False]
    assert counts == {"rows": 4, "excluded_grade": 2, "verified_false": 1, "kept": 1}


GRP = pd.DataFrame({
    "unique_id": ["a1", "a2", "b1", "b2", "c1", "c2", "x"],
    "dup_group_id": ["A", "A", "B", "B", "C", "C", None],
    "is_canonical": [False, True, True, False, True, False, None],
    "group_location_disagrees": [False, False, False, False, True, True, None]})
# A: same site (about 300 m apart); B: Ludhiana vs Mohali; C: close but flagged as disagreeing
LOC = pd.DataFrame({
    "unique_id": ["a1", "a2", "b1", "b2", "c1", "c2", "x"],
    "loc_lat": [30.9000, 30.9027, 30.9010, 30.7046, 26.85, 26.85, 28.6],
    "loc_lon": [75.85, 75.85, 75.8573, 76.7179, 80.9, 80.9, 77.0]})


def test_same_city_group_collapses_other_city_group_does_not():
    sites, counts = el.same_site_groups(GRP, LOC)
    rep = dict(zip(sites.unique_id, sites.rep_id, strict=True))
    assert rep["a1"] == rep["a2"] == "a2"  # canonical record represents the site
    assert rep["b1"] == "b1" and rep["b2"] == "b2"  # Ludhiana and Mohali stay two hospitals
    assert rep["c1"] == "c1" and rep["c2"] == "c2"  # group_location_disagrees blocks a collapse
    assert rep["x"] == "x"
    assert counts == {"groups": 3, "collapsed": 1, "kept_separate": 2, "records_merged": 1}
    assert dict(zip(sites.unique_id, sites.listings, strict=True))["a1"] == 2


def test_excluded_member_does_not_pull_the_site():
    sites, counts = el.same_site_groups(GRP, LOC[LOC.unique_id != "a2"])
    assert counts["collapsed"] == 0 and set(sites.rep_id) == set(sites.unique_id)


def test_to_sites_keeps_best_member_and_all_members_and_ignores_the_index():
    sites, _ = el.same_site_groups(GRP, LOC)
    pairs = pd.DataFrame({"unique_id": ["a1", "a2", "a2", "b1", "b2"],
                          "service": ["mri", "mri", "nicu", "mri", "mri"],
                          "score": [0.9, 0.4, 0.5, 0.3, 0.6]}).set_index(pd.Index([7, 3, 9, 1, 2], name="named"))
    out, counts = el.to_sites(pairs, sites)
    got = {(r.unique_id, r.service): (r.member_id, r.members, r.score, r.listings) for r in out.itertuples()}
    assert got[("a2", "mri")] == ("a1", ["a1", "a2"], 0.9, 2)  # canonical name, best member's score, both members
    assert got[("a2", "nicu")] == ("a2", ["a2"], 0.5, 2)
    assert got[("b1", "mri")][0] == "b1" and got[("b2", "mri")][0] == "b2"
    assert counts == {"rows": 5, "merged_into_site": 1, "kept": 4, "rep_is_not_best": 1}


def test_site_quotes_keep_each_members_claim_id():
    cid = {("rep", "short one"): "rep00000:svc:0", ("dup", "tiny"): "dup00000:svc:3"}
    got = bp._site_quotes("rep", [("rep", "short one || a much longer sentence"), ("dup", "tiny")], cid)
    assert got == [("tiny", "=dup00000:svc:3"), ("short one", "svc:0")]


@pytest.mark.parametrize("town,district,want", [
    ("SITAMARHI", float("nan"), "Sitamarhi"), (None, "PATNA", "Patna"), (math.nan, math.nan, ""),
    ("Gaya", "GAYA", "Gaya"), ("  ", "Darbhanga", "Darbhanga")])
def test_stop_place_is_nan_safe(town, district, want):
    assert place(town, district) == want


def test_stop_1_note_names_what_the_first_option_lacks():
    """#92: stop 1 is the list's first choice unless it lacks a capability; the note says which, in plain words."""
    one = {"facility_id": "a", "name": "Alpha Hospital", "travel": {"minutes": 9}}
    stab = {"facility_id": "b", "name": "Beta Hospital", "purpose": "stabilise", "eta_minutes": 20}
    dfn = {"facility_id": "c", "name": "Gamma Hospital", "purpose": "definitive", "eta_minutes": 45}
    info = {"facility_id": "a", "in_data": True, "first_care": False, "missing_first_care": [["emergency_24x7"]],
            "missing_definitive": [["ct_scan"], ["icu"]]}
    assert stop_1_note({"stops": [stab, dfn]}, one, info) == (
        "The route starts at Beta Hospital: the best option Alpha Hospital has no evidence of 24x7 emergency care "
        "in our data, which first care needs.")
    direct = {"stops": [dfn]}
    assert stop_1_note(direct, one, {**info, "first_care": True}) == (
        "The route goes straight to Gamma Hospital, about 45 min away, for definitive care: the best option "
        "Alpha Hospital has no evidence of a CT scanner or an ICU in our data.")
    assert stop_1_note({"stops": [{**stab, "facility_id": "a"}, dfn]}, one, info) is None
    alt = {"stops": [dfn], "vs_direct": {"first_care_alternative": {"facility_id": "a", "eta_minutes": 9}}}
    assert stop_1_note(alt, one, {**info, "first_care": True}) == (
        "The route goes straight to Gamma Hospital, about 45 min away, for definitive care in time; the best option "
        "Alpha Hospital (9 min) can give first care if it is needed sooner.")


def test_quote_choice_is_stable_for_equal_lengths():
    joined = "bbbb || aaaa || cc"
    assert bp._two_shortest("u", joined, {}) == [("cc", ""), ("aaaa", "")]
    assert bp._two_shortest("u", "aaaa || bbbb || cc", {}) == [("cc", ""), ("aaaa", "")]


# ---------- on the real builds ----------
def pack_ids(slug: str) -> tuple[dict, list[str]]:
    pack = json.loads(gzip.decompress((PACKS / f"{slug}.json.gz").read_bytes()))
    return pack, pack["fac"]["uid8"]


def excluded_ids() -> set[str]:
    tl = pd.read_parquet(V1 / "record_trust.parquet", columns=["unique_id", "trust_level"])
    return set(tl[tl.trust_level.isin(el.EXCLUDE_LEVELS)].unique_id)


@needs_v1
@needs_packs
def test_no_excluded_record_in_any_pack():
    excluded = {u[:8] for u in excluded_ids()}
    assert len(excluded) == 12 and VET[:8] in excluded
    for f in PACKS.glob("*.json.gz"):
        _, uid8 = pack_ids(f.name.removesuffix(".json.gz"))
        assert not excluded & set(uid8), f.name


@needs_v1
@needs_engine
@needs_packs
def test_facts_and_packs_agree_on_eligible_facilities():
    """Facts carry exactly the eligible set; every pack facility is in it (packs keep only those with evidence)."""
    eng = app_module._engine()
    excluded = excluded_ids()
    assert len(excluded) == 12 and not excluded & set(eng.fac["id"])
    loc = pd.read_parquet(V1 / "facility_location.parquet", columns=["unique_id", "loc_lat", "loc_lon"])
    tl = pd.read_parquet(V1 / "record_trust.parquet", columns=["unique_id", "trust_level"])
    f = loc.merge(tl, on="unique_id", how="left")
    assert set(eng.fac["id"]) == set(f[el.eligible_facilities(f)[0]].unique_id)
    facts8 = {u[:8] for u in eng.fac["id"]}
    for p in PACKS.glob("*.json.gz"):
        assert set(pack_ids(p.name.removesuffix(".json.gz"))[1]) <= facts8, p.name


def real_sites() -> pd.DataFrame:
    loc = pd.read_parquet(V1 / "facility_location.parquet", columns=["unique_id", "loc_lat", "loc_lon"])
    return el.same_site_groups(el.groups(), loc)[0]


@needs_v1
@needs_packs
def test_no_pack_list_shows_two_listings_of_one_site():
    sites = real_sites()
    site8 = dict(zip(sites.unique_id.str[:8], sites.rep_id, strict=True))
    merged8 = set(sites[sites.rep_id != sites.unique_id].unique_id.str[:8])
    for f in PACKS.glob("*.json.gz"):
        pack, uid8 = pack_ids(f.name.removesuffix(".json.gz"))
        assert not merged8 & set(uid8), f.name  # only the representative is in a pack
        fi = np.cumsum(pack["ev"]["f"])
        for lst in pack["lists"]:
            reps = [site8[uid8[fi[e]]] for e in lst]
            assert len(reps) == len(set(reps)), f.name


@needs_v1
@needs_engine
def test_engine_one_option_per_site_branches_kept_and_merge_stated():
    eng = app_module._engine()
    sites = real_sites()
    merged = set(sites[sites.rep_id != sites.unique_id].unique_id)
    assert VET not in eng.fid
    stated = 0
    for svc, rows in eng.pairs.items():
        ids = [eng.fac["id"][p.fi] for p in rows]
        assert not merged & set(ids), svc
        for p in rows:
            if p.listings > 1:
                contrib = eng.score(eng.fac["id"][p.fi], svc)[4]
                assert contrib[-1] == {"label": f"best evidenced record of {p.listings} duplicate listings",
                                       "points": 0}
                stated += 1
    assert stated > 0
    # A group split across cities keeps both records: some kept-separate group has 2+ members with pairs.
    g = el.groups()
    split = g[g.dup_group_id.notna() & ~g.unique_id.isin(merged)]
    with_pairs = {eng.fac["id"][p.fi] for rows in eng.pairs.values() for p in rows}
    multi = split[split.unique_id.isin(with_pairs)].groupby("dup_group_id").size()
    assert (multi >= 2).any()


@needs_v1
def test_pack_build_is_deterministic():
    fac, svc, pins = bp.load()
    state = "BIHAR"
    a = bp.encode(bp.build_state(state, pins, fac, svc, "2026-01-01"))[1]
    b = bp.encode(bp.build_state(state, pins, fac.sample(frac=1, random_state=1), svc, "2026-01-01"))[1]
    assert a == b
