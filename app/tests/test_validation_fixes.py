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
from facts import eligibility as el  # noqa: E402, RUF100
from itinerary import place  # noqa: E402, RUF100
from packs import build_packs as bp  # noqa: E402, RUF100

import app as app_module  # noqa: E402, RUF100

V1 = APP.parent / "derived" / "v1"
PACKS = APP / "packs" / "out"
needs_v1 = pytest.mark.skipif(not (V1 / "facility_groups.parquet").is_file(), reason="derived/v1 not present")
needs_packs = pytest.mark.skipif(not (PACKS / "index.json").is_file(), reason="packs not built")
needs_engine = pytest.mark.skipif(app_module._engine() is None, reason="facts not built")
VET = "885c79f6-9f32-4878-8384-5a90259cfae4"  # SKS Veterinary Hospital, trust_level exclude_review


# ---------- the shared rule, on small frames ----------
def test_eligible_drops_excluded_and_unplaced():
    df = pd.DataFrame({"loc_lat": [1.0, 1.0, np.nan], "loc_lon": [2.0, 2.0, 2.0],
                       "trust_level": ["no_concerns", "exclude_review", "minor"]})
    assert el.eligible(df).tolist() == [True, False, False]


def test_representatives_prefers_canonical_then_smallest_id():
    grp = pd.DataFrame({"unique_id": ["a", "b", "c", "d"], "grp": ["g1", "g1", "g2", "g2"],
                        "canonical": [False, True, False, False]})
    pairs = pd.DataFrame({"unique_id": ["a", "b", "a", "d", "c", "e"],
                          "service": ["mri", "mri", "nicu", "mri", "mri", "mri"]}, index=[10, 11, 12, 13, 14, 15])
    keep = el.representatives(pairs, grp)
    # g1/mri -> b (canonical); g1/nicu -> a (only member with it); g2/mri -> c (smallest id); e has no group
    assert keep.to_dict() == {10: False, 11: True, 12: True, 13: False, 14: True, 15: True}


@pytest.mark.parametrize("town,district,want", [
    ("SITAMARHI", float("nan"), "Sitamarhi"), (None, "PATNA", "Patna"), (math.nan, math.nan, ""),
    ("Gaya", "GAYA", "Gaya"), ("  ", "Darbhanga", "Darbhanga")])
def test_stop_place_is_nan_safe(town, district, want):
    assert place(town, district) == want


def test_quote_choice_is_stable_for_equal_lengths():
    joined = "bbbb || aaaa || cc"
    assert bp._two_shortest("u", joined, {}) == [("cc", ""), ("aaaa", "")]
    assert bp._two_shortest("u", "aaaa || bbbb || cc", {}) == [("cc", ""), ("aaaa", "")]


# ---------- on the real builds ----------
def pack_ids(slug: str) -> tuple[dict, list[str]]:
    pack = json.loads(gzip.decompress((PACKS / f"{slug}.json.gz").read_bytes()))
    return pack, pack["fac"]["uid8"]


@needs_v1
@needs_packs
def test_no_excluded_record_in_any_pack():
    tl = pd.read_parquet(V1 / "record_trust.parquet", columns=["unique_id", "trust_level"])
    excluded = {u[:8] for u in tl[tl.trust_level.isin(el.EXCLUDE_LEVELS)].unique_id}
    assert VET[:8] in excluded
    for f in PACKS.glob("*.json.gz"):
        _, uid8 = pack_ids(f.name.removesuffix(".json.gz"))
        assert not excluded & set(uid8), f.name


@needs_v1
@needs_packs
def test_no_pack_list_shows_two_members_of_one_duplicate_group():
    g = el.groups()
    grp8 = dict(zip(g.unique_id.str[:8], g.grp, strict=True))
    bad = 0
    for f in PACKS.glob("*.json.gz"):
        pack, uid8 = pack_ids(f.name.removesuffix(".json.gz"))
        fi = np.cumsum(pack["ev"]["f"])
        for lst in pack["lists"]:
            groups = [grp8.get(uid8[fi[e]], uid8[fi[e]]) for e in lst]
            bad += len(groups) != len(set(groups))
    assert bad == 0


@needs_v1
@needs_engine
def test_engine_serves_one_record_per_duplicate_group_and_no_excluded():
    eng = app_module._engine()
    g = el.groups().set_index("unique_id")
    tl = pd.read_parquet(V1 / "record_trust.parquet", columns=["unique_id", "trust_level"]).set_index("unique_id")
    assert VET not in eng.fid
    assert not tl.loc[[u for u in eng.fac["id"] if u in tl.index]].trust_level.isin(el.EXCLUDE_LEVELS).any()
    for svc, rows in eng.pairs.items():
        grps = [g.grp.get(eng.fac["id"][p.fi], eng.fac["id"][p.fi]) for p in rows]
        assert len(grps) == len(set(grps)), svc


@needs_v1
def test_pack_build_is_deterministic():
    fac, svc, pins = bp.load()
    state = "BIHAR"
    a = bp.encode(bp.build_state(state, pins, fac, svc, "2026-01-01"))[1]
    b = bp.encode(bp.build_state(state, pins, fac.sample(frac=1, random_state=1), svc, "2026-01-01"))[1]
    assert a == b
