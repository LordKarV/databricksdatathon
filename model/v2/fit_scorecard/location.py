"""Candidate B location head P_L: sign-constrained MAP logistic on facility location labels, grouped 5-fold CV.

P_E is not fitted: gold DEV has 10 existence negatives (none strict) against the 15 MODEL_SPEC 3.3 asks for, so it
stays candidate A's prior-only head.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import core as K
import design as D
import metrics as M
from fcommon import sigmoid

ABLATE = frozenset({"nabh_listed", "f_osm_conflict"})  # crossfit plan: matcher gates ("selection")


def facilities(pairs: pd.DataFrame) -> pd.DataFrame:
    return pairs.drop_duplicates("unique_id").reset_index(drop=True)


def labels() -> pd.DataFrame:
    f = pd.read_parquet(D.LAB / "gold_dev_facility.parquet")
    return f[f.y_L.notna()].drop_duplicates("unique_id").reset_index(drop=True)


def _fit(X: np.ndarray, y: np.ndarray, terms: list, drop: frozenset) -> tuple[np.ndarray, dict]:
    X = K.zero_cols(X.copy(), terms, drop)
    data = K.Data(X=X, y=y, w=np.ones(len(y)), wpos=np.zeros(len(y)), nunl=np.zeros(len(y)), c=np.full(len(y), np.nan),
                  is_pu=np.zeros(len(y), bool))
    mu, sd = np.array([t.mu for t in terms]), np.array([t.sd for t in terms])
    r = K.fit(data, mu, sd, D.sign_rows(terms))
    beta = r["beta"]
    beta[[t.name in drop for t in terms]] = 0.0
    return beta, r


def score(X: np.ndarray, beta: np.ndarray, terms: list) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    C = X * beta[None, :]
    is_base = np.array([t.family == "base" for t in terms])
    z = X @ beta
    base, contrib = C[:, is_base].sum(1), C[:, ~is_base]
    assert np.max(np.abs(base + contrib.sum(1) - z)) < 1e-9, "P_L additivity broken"
    return base, contrib, z


def run(pairs: pd.DataFrame, gold_uids: pd.DataFrame) -> dict:
    """gold_uids: unique_id, fold5, leakage_group_id of every facility in a gold pair. Returns OOF, metrics, params."""
    terms = D.location_terms()
    fac = facilities(pairs)
    lab = labels().merge(fac, on="unique_id", how="left", suffixes=("", "_ff"))
    assert lab.p1_src.notna().all()
    Xl, yl = D.location_X(lab, terms), lab.y_L.to_numpy()
    mu = np.array([t.mu for t in terms])
    gu = gold_uids.drop_duplicates("unique_id").merge(fac, on="unique_id", how="left", suffixes=("", "_ff"))
    Xu = D.location_X(gu, terms)
    oof = {v: np.zeros(len(lab)) for v in ("B", "B_ablate", "A_prior")}
    gold_pl = np.zeros(len(gu))
    for k in range(5):
        te = lab.fold5.to_numpy() == k
        held = lab.leakage_group_id[te].unique()
        tr = ~te & ~lab.leakage_group_id.isin(held).to_numpy()
        b, _ = _fit(Xl[tr], yl[tr], terms, frozenset())
        ba, _ = _fit(Xl[tr], yl[tr], terms, ABLATE)
        oof["B"][te] = sigmoid(Xl[te] @ b)
        oof["B_ablate"][te] = sigmoid(K.zero_cols(Xl[te].copy(), terms, ABLATE) @ ba)
        oof["A_prior"][te] = sigmoid(Xl[te] @ mu)
        gk = gu.fold5.to_numpy() == k
        gold_pl[gk] = sigmoid(Xu[gk] @ b)
    grp = lab.leakage_group_id.to_numpy()
    met = {v: M.summary(p, yl, grp) for v, p in oof.items()}
    met["B - A_prior"] = M.paired_logloss(oof["B"], oof["A_prior"], yl, grp)
    beta, r = _fit(Xl, yl, terms, frozenset())
    sd = K.laplace_sd(r)
    Xf = D.location_X(fac, terms)
    base, contrib, z = score(Xf, beta, terms)
    params = pd.DataFrame(dict(head="location", term=[t.name for t in terms], family=[t.family for t in terms],
                               sign=[t.sign for t in terms], prior_mean=mu, prior_sd=[t.sd for t in terms], derivation=[t.why for t in terms],
                               post_mean=beta, laplace_sd=sd, n_fired_labels=(Xl != 0).sum(0), n_fired_all=(Xf != 0).sum(0)))
    params["at_bound"] = [t.sign != 0 and abs(b) < 1e-9 for t, b in zip(terms, beta)]
    scores = pd.DataFrame(dict(unique_id=fac.unique_id, z_l=z, p_l=sigmoid(z), base=base))
    long = pd.DataFrame(contrib, columns=[t.name for t in terms if t.family != "base"])
    long["unique_id"] = fac.unique_id
    long = long.melt(id_vars="unique_id", var_name="term", value_name="contribution_logit")
    long = long[long.contribution_logit != 0]
    oof_df = lab[["unique_id", "src", "y_L", "fold5", "leakage_group_id"]].assign(**{f"p_l_{v}": p for v, p in oof.items()})
    gold_df = gu[["unique_id"]].assign(p_l_oof=gold_pl)
    return dict(metrics=met, params=params, scores=scores, contrib=long, oof=oof_df, gold_pl=gold_df,
                n_labels=int(len(yl)), n_neg=int((yl == 0).sum()), converged=bool(r["converged"]))
