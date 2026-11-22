"""The app against the derived/v2 contract (#63), with a small generated scores file until #11 publishes.

Contract: derived/v2/facility_service_scores.parquet has unique_id, service_id (kb/taxonomy ids), band, p, lo, hi
(and more columns the engine reads later). Skips when derived/v1 is not present.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from facts import build  # noqa: E402, RUF100

pytestmark = pytest.mark.skipif(not (build.V1 / "grades.parquet").is_file(), reason="derived/v1 not present")
TAXONOMY = {"burn_care", "cardiac_surgery", "dialysis", "emergency_csection", "mri", "nicu", "trauma_care"}


def test_every_app_service_has_a_taxonomy_id():
    assert set(build.TAXONOMY_TO_V1) == TAXONOMY
    assert build.APP_TO_TAXONOMY["trauma_emergency"] == "trauma_care"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Run pairs() with a fixture v2 file scoring every v1 grade row under its taxonomy id."""
    _, fidx = build.facilities()
    g = pd.read_parquet(build.V1 / "grades.parquet", columns=["unique_id", "service"])
    v1_to_tax = {v: k for k, v in build.TAXONOMY_TO_V1.items()}
    g = g[g.service.isin(v1_to_tax) & g.unique_id.isin(fidx)]
    fx = pd.DataFrame({"unique_id": g.unique_id, "service_id": g.service.map(v1_to_tax), "band": "CALL_FIRST",
                       "p": 0.5, "lo": 0.3, "hi": 0.7})
    fx = pd.concat([fx, fx.head(3).assign(service_id="snakebite")])  # a taxonomy service with no app tile
    path = tmp_path_factory.mktemp("v2") / "facility_service_scores.parquet"
    fx.to_parquet(path)
    old = build.V2
    build.V2 = path
    try:
        out, _ = build.pairs(fidx)
    finally:
        build.V2 = old
    return out


def test_every_app_service_gets_v2_scores(built):
    for svc, rows in built.items():
        assert rows, svc
        share = sum(r[14] is not None for r in rows) / len(rows)
        assert share > 0.9, (svc, share)  # trauma used to get 0: the join silently fell back to interim scores


def test_track_bins_read_from_model_card_and_drop_incomplete(tmp_path):
    card = {"calibration": {"bins": [
        {"lo": 0.0, "hi": 0.5, "n": 40, "k_confirmed": 5, "k_contradicted": 10, "k_no_info": 25, "split": "dev"},
        {"lo": 0.5, "hi": 1.0, "n": 30, "k_confirmed": 20, "k_contradicted": 3}]}}  # no k_no_info: dropped
    path = tmp_path / "model_card.json"
    path.write_text(__import__("json").dumps(card))
    assert build.track_bins(path) == [card["calibration"]["bins"][0]]
    assert build.track_bins(tmp_path / "missing.json") == []


def test_engine_track_record_three_outcomes_or_none():
    from facts.engine import Engine
    eng = Engine.__new__(Engine)
    rule = {"n": 12, "k_confirmed": 9, "k_contradicted": 3}
    eng.track_bins = []
    assert Engine._track(eng, 0.7, rule)["k_no_info"] is None  # interim: not recorded, never a made-up 0
    eng.track_bins = [{"lo": 0.5, "hi": 1.0, "n": 50, "k_confirmed": 20, "k_contradicted": 5, "k_no_info": 25,
                       "split": "dev"}]
    tr = Engine._track(eng, 1.0, rule)
    assert (tr["n"], tr["k_no_info"], tr["basis"]) == (50, 25, "score 0.50 to 1.00")


def test_v2_bands_map_to_the_app_bands(built):
    bands = {r[14][0] for rows in built.values() for r in rows if r[14]}
    assert bands == {"not_verified"} and all(r[14][4] == "CALL_FIRST" for rows in built.values() for r in rows)


def test_unscored_pairs_are_dropped_and_low_coverage_fails():
    m = pd.DataFrame({"service": ["dialysis"] * 10, "m_band": ["LIKELY"] * 9 + [None]})
    assert len(build.v2_only(m)) == 9
    with pytest.raises(SystemExit):
        build.v2_only(pd.DataFrame({"service": ["dialysis"] * 10, "m_band": ["LIKELY"] * 5 + [None] * 5}))


def test_track_bins_that_do_not_tile_take_the_nearest_bin():
    # equal-count bins (MODEL_SPEC 4.3) have data-dependent edges with gaps and no 0 or 1 at the ends
    from facts.engine import Engine
    eng = Engine.__new__(Engine)
    eng.track_bins = [{"lo": 0.12, "hi": 0.30, "n": 30, "k_confirmed": 3, "k_contradicted": 9, "k_no_info": 18,
                       "split": "dev"},
                      {"lo": 0.41, "hi": 0.88, "n": 30, "k_confirmed": 18, "k_contradicted": 2, "k_no_info": 10,
                       "split": "dev"}]
    rule = {"n": 12, "k_confirmed": 9, "k_contradicted": 3}
    assert Engine._track(eng, 0.05, rule)["basis"] == "score 0.12 to 0.30"   # below the lowest edge
    assert Engine._track(eng, 0.95, rule)["basis"] == "score 0.41 to 0.88"   # above the highest
    assert Engine._track(eng, 0.33, rule)["basis"] == "score 0.12 to 0.30"   # in the gap, nearer the first
    assert Engine._track(eng, 0.60, rule)["k_confirmed"] == 18


def test_operator_comes_from_v2_attributes():
    if not build.ATTRS.is_file():
        pytest.skip("derived/v2 facility_attributes not present")
    f, _ = build.facilities()
    assert set(f.operator) <= {"public", "private", "unknown"} and (f.operator == "public").sum() > 100
