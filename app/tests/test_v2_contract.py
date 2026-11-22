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
    fx = pd.DataFrame({"unique_id": g.unique_id, "service_id": g.service.map(v1_to_tax), "band": "not_verified",
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
    assert (tr["n"], tr["k_no_info"], tr["basis"]) == (50, 25, "score 0.5 to 1.0")
