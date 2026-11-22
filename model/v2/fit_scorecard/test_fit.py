"""Checks on the written outputs: additivity, cross-fit masking, not-observable contributes 0, no fold leakage.

Run after fit.py: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python test_fit.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import core as K
import design as D


def test_additivity() -> None:
    sc = pd.read_parquet(D.OUT / "pair_scores.parquet")
    lg = pd.read_parquet(D.OUT / "pair_contributions.parquet")
    s = lg.groupby(["unique_id", "service"]).contribution_logit.sum()
    j = sc.set_index(["unique_id", "service"])
    err = np.abs(j.base + s.reindex(j.index).fillna(0) - j.z).max()
    assert err < 1e-9 and len(sc) == 358524, err
    loc = pd.read_parquet(D.OUT / "facility_location_scores.parquet")
    lc = pd.read_parquet(D.OUT / "facility_location_contributions.parquet").groupby("unique_id").contribution_logit.sum()
    li = loc.set_index("unique_id")
    assert np.abs(li.base + lc.reindex(li.index).fillna(0) - li.z_l).max() < 1e-9
    oof = pd.read_parquet(D.OUT / "oof_predictions.parquet")
    fam = [c for c in oof.columns if c.startswith("c_")]
    assert np.abs(oof.base + oof[fam].fillna(0).sum(1) - oof.z).max() < 1e-9
    print("additivity ok", float(err))


def test_not_observable_is_zero() -> None:
    lg = pd.read_parquet(D.OUT / "pair_contributions.parquet")
    ff = pd.read_parquet(D.DER / "facility_features.parquet", columns=["unique_id", "service", "obs_W", "obs_X"])
    w = lg[lg.term.isin(["w_ab", "w_c", "w_de", "w_silent", "w_negated"])].merge(ff, on=["unique_id", "service"])
    assert (w.obs_W != "not_observable").all(), "a website term fired where the site is not observable"
    x = lg[lg.term.str.startswith("x_")].merge(ff, on=["unique_id", "service"])
    assert (x.contribution_logit > 0).all() and (x.obs_X == "present").all(), "list term fired without a present list witness"
    print("not-observable ok:", len(w), "website and", len(x), "list contributions, all observable")


def test_crossfit_mask() -> None:
    pairs = D.load_pairs()
    c, _ = K.c_table()
    m = K.pu_rows(pairs, c)
    terms = D.service_terms()
    X = K.pu_design(m, terms, frozenset())
    idx = {t.name: i for i, t in enumerate(terms)}
    for f in D.PU_FAMILIES:
        rows = (m.label_family == f).to_numpy()
        own = [idx[t.name] for t in terms if t.family == "X" and t.source == f]
        assert not X[np.ix_(rows, own)].any(), f
        assert (X[rows, idx[f"off@{f}"]] == 1).all()
    assert not X[(m.label_family == "nabh").to_numpy(), idx["nabh_listed"]].any()
    print("cross-fit mask ok")


def test_folds() -> None:
    oof = pd.read_parquet(D.OUT / "oof_predictions.parquet")
    g = oof[(oof.variant == "B") & (oof.scheme == "group5")]
    assert (g.fold == g.fold5).all() and g.pair_id.is_unique and len(g) == 195
    assert g.groupby("leakage_group_id").fold.nunique().max() == 1
    print("folds ok")


if __name__ == "__main__":
    test_crossfit_mask()
    test_additivity()
    test_not_observable_is_zero()
    test_folds()
