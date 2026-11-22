"""Self-checks for candidate C. Run: .venv-viz/bin/python test_fit_ebm.py (pytest is not installed)."""
from __future__ import annotations

import numpy as np
import pandas as pd

import features as F
import glassbox as G

TERMS = (
    F.Term("a_T", "T", 1, "continuous", 0.0),
    F.Term("x_list", "X", 1, "continuous", np.nan),
    F.Term("web_state", "W", 0, "nominal", "none"),
)


def _toy(n: int = 1500, seed: int = 0) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    X = pd.DataFrame({
        "a_T": rng.integers(0, 6, n).astype(float),
        # list present carries no signal, so the fitted present bin can drift below missing
        "x_list": np.where(rng.random(n) < 0.3, 1.0, np.nan),
        "web_state": rng.choice(["alive", "dead", "none"], n),
    })
    y = (rng.random(n) < 1 / (1 + np.exp(-(X.a_T - 2.5)))).astype(int)
    return X, y


def test_layout_missing_first_unseen_last() -> None:
    X, y = _toy()
    ebm = G.fit_ebm(X, y, TERMS)
    ts = ebm.term_scores_[1]
    assert len(ts) == 3  # missing, the single present value, unseen
    pres = ebm.eval_terms(pd.DataFrame({"a_T": [0.0], "x_list": [1.0], "web_state": ["none"]}))
    miss = ebm.eval_terms(G.anchor_row(TERMS))
    assert np.isclose(pres[0, 1], ts[1]) and np.isclose(miss[0, 1], ts[0])


def test_additivity_and_list_clamp() -> None:
    X, y = _toy()
    ebm = G.fit_ebm(X, y, TERMS)
    ebm.term_scores_[1][1] = ebm.term_scores_[1][0] - 0.3   # force a negative list effect
    edits = G.clamp_list_terms(ebm, TERMS)
    assert edits and ebm.term_scores_[1][1] == ebm.term_scores_[1][0]
    led = G.Ledger((G.Stage("pu", ebm, TERMS, 0.7),), -0.2)
    base, contrib = G.contributions(led, X)       # asserts the 1e-9 identity itself
    assert np.allclose(contrib["pu:x_list"], 0.0)  # absent, not observable and present all 0
    gap = base + contrib.sum(axis=1) - (0.7 * ebm.decision_function(X) - 0.2)
    assert np.abs(gap).max() <= G.TOL
    tab = G.shape_table(led, "P_S", "toy")
    assert G.sign_violations(tab).empty
    a_t = tab[(tab.term == "a_T") & ~tab.bin_label.isin(["missing", "unseen"])]
    assert (np.diff(a_t.contribution_logit.to_numpy()) >= -1e-12).all()  # monotone increasing


def test_two_stage_ledger_is_exact() -> None:
    X, y = _toy(seed=1)
    e1 = G.fit_ebm(X, y, TERMS)
    init = 0.5 * e1.decision_function(X) + 0.1
    e2 = G.fit_ebm(X, y, TERMS, init=init)
    led = G.Ledger((G.Stage("pu", e1, TERMS, 0.5), G.Stage("gold", e2, TERMS, 1.0)), 0.1)
    base, contrib = G.contributions(led, X)
    assert np.abs(base + contrib.sum(axis=1) - (init + e2.decision_function(X))).max() <= G.TOL


def test_family_masks_cover_label_lists() -> None:
    plan = pd.read_parquet(f"{F.LABEL_DIR}/crossfit_plan.parquet")
    masks = F.family_mask_columns(plan, F.PS_TERMS)
    assert "x_nabh_service_code" in masks["nabh"] and "k_text_nabh" in masks["nabh"]
    assert masks["eraktkosh"] == ["x_erk_blood_centre_on_site"]
    assert masks["nmc"] == ["x_nmc_course_strong"]
    assert masks["laqshya"] == ["x_laqshya_ot_valid"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
