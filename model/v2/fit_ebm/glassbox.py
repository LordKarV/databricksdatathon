"""EBM fits published as exact additive ledgers.

A ledger is z = offset + sum_k scale_k * (intercept_k + sum_j f_kj(x_j)) over one or two EBMs
(the PU stage, and optionally a gold residual stage fitted with init_score). Each published term is
contrib_kj(x) = scale_k * (f_kj(x_j) - f_kj(anchor_j)), and base = offset + sum_k scale_k *
(intercept_k + sum_j f_kj(anchor_j)). base + sum contrib equals the model score exactly; the
assertion tolerance is 1e-9 on the logit.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from interpret.glassbox import ExplainableBoostingClassifier

from features import Term, anchor_row, matrix

TOL = 1e-9
# Fixed before any gold metric was read; not tuned.
EBM_PARAMS = dict(interactions=0, outer_bags=8, max_bins=256, max_rounds=5000, learning_rate=0.04,
                  early_stopping_rounds=50, random_state=20261121, n_jobs=-2)


@dataclass(frozen=True)
class Stage:
    prefix: str
    ebm: ExplainableBoostingClassifier
    terms: tuple[Term, ...]
    scale: float


@dataclass(frozen=True)
class Ledger:
    stages: tuple[Stage, ...]
    offset: float


def fit_ebm(X: pd.DataFrame, y: np.ndarray, terms: tuple[Term, ...],
            weight: np.ndarray | None = None,
            init: np.ndarray | None = None) -> ExplainableBoostingClassifier:
    ebm = ExplainableBoostingClassifier(
        feature_names=[t.name for t in terms],
        feature_types=["nominal" if t.kind == "nominal" else "continuous" for t in terms],
        monotone_constraints=[t.sign for t in terms], **EBM_PARAMS)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # interpret warns about NaN bins; we use them
        ebm.fit(X, y, sample_weight=weight, init_score=init)
    return ebm


def clamp_list_terms(ebm: ExplainableBoostingClassifier, terms: tuple[Term, ...]) -> list[dict]:
    """Absence from a list is never negative: raise any present bin of an X term to its NaN bin.

    term_scores_[j][0] is the missing bin and [-1] the unseen-value bin (interpret 0.7 layout,
    checked in test_fit_ebm.py). Returns one record per edited bin, for FIT.md.
    """
    edits = []
    for j, t in enumerate(terms):
        if t.family != "X":
            continue
        ts = ebm.term_scores_[j]
        for i in range(1, len(ts) - 1):
            if ts[i] < ts[0]:
                edits.append(dict(term=t.name, bin=i, before=float(ts[i] - ts[0]), after=0.0))
                ts[i] = ts[0]
    return edits


def stage_raw(stage: Stage, X: pd.DataFrame) -> np.ndarray:
    return stage.ebm.decision_function(matrix(X, stage.terms))


def score(ledger: Ledger, X: pd.DataFrame) -> np.ndarray:
    """Model logit computed directly from the EBMs, not from the ledger columns."""
    z = np.full(len(X), ledger.offset, dtype=float)
    for st in ledger.stages:
        z += st.scale * stage_raw(st, X)
    return z


def contributions(ledger: Ledger, X: pd.DataFrame) -> tuple[float, pd.DataFrame]:
    """(base, one column per named term). Asserts base + row sum == score to 1e-9."""
    base = ledger.offset
    cols = {}
    for st in ledger.stages:
        et = st.ebm.eval_terms(matrix(X, st.terms))
        ref = st.ebm.eval_terms(anchor_row(st.terms))[0]
        base += st.scale * (float(st.ebm.intercept_[0]) + float(ref.sum()))
        for j, t in enumerate(st.terms):
            cols[f"{st.prefix}:{t.name}"] = st.scale * (et[:, j] - ref[j])
    contrib = pd.DataFrame(cols, index=X.index)
    gap = np.abs(base + contrib.to_numpy().sum(axis=1) - score(ledger, X))
    assert gap.max(initial=0.0) <= TOL, f"additivity broken: max gap {gap.max()}"
    return base, contrib


def shape_table(ledger: Ledger, head: str, variant: str) -> pd.DataFrame:
    """Every bin of every term as published (contribution relative to the anchor), plus base."""
    rows = []
    base = ledger.offset
    for st in ledger.stages:
        ref = st.ebm.eval_terms(anchor_row(st.terms))[0]
        base += st.scale * (float(st.ebm.intercept_[0]) + float(ref.sum()))
        for j, t in enumerate(st.terms):
            ts, bins = st.ebm.term_scores_[j], st.ebm.bins_[j][0]
            if isinstance(bins, dict):
                labels = ["missing"] + [k for k, _ in sorted(bins.items(), key=lambda kv: kv[1])]
            else:
                edges = [-np.inf, *list(bins), np.inf]
                labels = ["missing"] + [f"[{edges[i]:.6g}, {edges[i + 1]:.6g})"
                                        for i in range(len(edges) - 1)]
            labels = labels + ["unseen"]
            assert len(labels) == len(ts), (t.name, len(labels), len(ts))
            for i, (lab, val) in enumerate(zip(labels, ts)):
                rows.append(dict(head=head, variant=variant, stage=st.prefix, term=t.name,
                                 family=t.family, sign=t.sign, anchor=str(t.anchor), bin=i,
                                 bin_label=lab, raw_score=float(val), scale=st.scale,
                                 contribution_logit=st.scale * (float(val) - float(ref[j]))))
    rows.append(dict(head=head, variant=variant, stage="base", term="base", family="base",
                     sign=0, anchor="", bin=0, bin_label="", raw_score=base, scale=1.0,
                     contribution_logit=base))
    return pd.DataFrame(rows)


def sign_violations(table: pd.DataFrame) -> pd.DataFrame:
    """Bins that break a signed term's constraint: a step against the monotone direction between
    adjacent ordered bins (missing and unseen excluded), or an X (list) bin below 0."""
    t = table[(table.sign != 0) & ~table.bin_label.isin(["missing", "unseen"])
              & (table.stage != "base")].sort_values(["variant", "stage", "term", "bin"])
    step = t.groupby(["variant", "stage", "term"]).contribution_logit.diff()
    bad_step = (t.sign * step) < -1e-12
    bad_list = (t.family == "X") & (t.contribution_logit < -1e-12)
    return t[bad_step | bad_list]
