"""Truth scenarios (issue #92): shape, common random numbers, S2 against the DEV labels, S3 rules, S0 blind to text."""
from __future__ import annotations

import math
import re

import numpy as np
import pytest

from sim import truth as T
from sim.interface import ROOT, TRUTH_COLUMNS


@pytest.fixture(scope="module")
def tables() -> dict[str, object]:
    return {sc: T.build_truth(sc, 3) for sc in T.SCENARIOS}


def test_columns_and_keys(tables: dict) -> None:
    for t in tables.values():
        assert list(t.columns) == list(TRUTH_COLUMNS)
        assert not t.duplicated(["unique_id", "service"]).any()
        assert t.open_now_p.isin([0.95, 0.6]).all()
        assert t.true_lat.notna().all()


def test_common_random_numbers(tables: dict) -> None:
    """Scenarios share existence and phone draws; only offer rates (and S3 locations) differ."""
    s0, s2 = tables["S0"], tables["S2"]
    assert (s0.exists == s2.exists).all() and (s0.phone_ok == s2.phone_ok).all()
    assert (T.build_truth("S2", 3).offers == s2.offers).all()  # same seed, same world


def test_s1_follows_model_p(tables: dict) -> None:
    f = T.base_frame()
    f = f[f.service.isin(T.SERVICES)]
    assert abs(tables["S1"].offers.mean() - f.p.mean()) < 0.01


def test_s2_reproduces_dev_label_rates() -> None:
    """S2's expected P(offers) over the decided DEV pairs matches the weighted label rate, per service and overall,
    within two standard errors (Kish effective n)."""
    f = T.base_frame()
    p = T.offer_p("S2")
    lab = T.dev_labels().merge(f.assign(p_s2=p)[["unique_id", "service", "p_s2"]], on=["unique_id", "service"])
    assert len(lab) == len(T.dev_labels())  # every decided label is in the frame
    groups = [("all", lab), *lab.groupby("service")]
    for name, d in groups:
        w = d.w.to_numpy()
        rate = (w * d.y).sum() / w.sum()
        expected = (w * d.p_s2).sum() / w.sum()
        n_eff = w.sum() ** 2 / (w**2).sum()
        se = math.sqrt(max(rate * (1 - rate), 0.05) / n_eff)
        assert abs(expected - rate) <= 2 * se, (name, round(rate, 3), round(expected, 3), round(se, 3))


def test_s3_other_facility_sentences_false() -> None:
    f = T.base_frame()
    p3, p2 = T.offer_p("S3"), T.offer_p("S2")
    only_else = (f.attr_other & ((f.n_own_distinct == 0) | (f.grade == "attributed_elsewhere"))).to_numpy()
    assert only_else.any() and (p3[only_else] == 0).all()
    clean = ~f.attr_other.to_numpy()
    assert np.allclose(p3[clean], p2[clean])


def test_s3_moves_conflicting_map_points(tables: dict) -> None:
    f = T.base_frame()
    f = f[f.service.isin(T.SERVICES)].reset_index(drop=True)
    moved = f.loc_conflict.to_numpy(dtype=bool)
    s3, s2 = tables["S3"], tables["S2"]
    assert np.allclose(s3.true_lat[moved], f.alt_lat[moved])
    assert np.allclose(s3.true_lat[~moved], s2.true_lat[~moved])


def test_s0_ignores_text_and_p() -> None:
    """Within a service and operator group every pair has the same P(offers)."""
    f = T.base_frame().assign(p0=T.offer_p("S0"))
    assert (f.groupby(["service", "group"]).p0.nunique() == 1).all()


def test_shrinkage_pulls_thin_cells_to_service_rate() -> None:
    t = T.rate_table(["grade", "attr_other"])
    lo, hi = np.minimum(t.rate_raw, t.r_service), np.maximum(t.rate_raw, t.r_service)
    assert ((t.rate >= lo - 1e-9) & (t.rate <= hi + 1e-9)).all()


def test_never_reads_test_labels() -> None:
    """No sim module names the sealed TEST labels or the custodian's cache (#51)."""
    bad = re.compile(r"test_labels|test_sample|referral-saathi-gold-v3|\.cache/")
    for path in (ROOT / "sim").glob("*.py"):
        assert not bad.search(path.read_text()), path.name
