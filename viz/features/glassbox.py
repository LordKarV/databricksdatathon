"""Quick glass-box fits to show shape functions. Gold DEV only; never touches TEST.

1. EBM on gold DEV (61 searched pairs, 22 confirmed), interactions off. Out-of-fold AUROC from
   5-fold GroupKFold over gold split groups (DEV only). With 61 rows the shapes are mostly flat;
   that is the finding, not a bug.
2. Monotone logistic scorecard on gold DEV: same features scaled to [0, 1], weights sign-constrained
   by the expected direction in catalogue_meta (+ >= 0, - <= 0), L2 penalty LAMBDA, fitted with
   L-BFGS-B. Intervals: 500 cluster-bootstrap refits over gold split groups.
3. EBM on the NABH-codes PU population (4,216 pairs, 1,054 facilities), NABH-derived features
   excluded, service as a feature, interactions off; out-of-fold AUROC within service from 5-fold
   GroupKFold by state (held-out states). This is "what facilities declare to NABH", not truth.

Writes out/glassbox.json, out/ebm_dev_shapes.json, out/ebm_pu_shapes.json, out/scorecard.csv.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from interpret.glassbox import ExplainableBoostingClassifier
from scipy.optimize import minimize
from sklearn.model_selection import GroupKFold

import catalogue_meta as M
import labels as L
from univariate import auc, auc_strat

warnings.filterwarnings("ignore")
OUT = Path(__file__).parent / "out"
RNG = np.random.default_rng(7)
LAMBDA = 1.0
POINTS = 20 / np.log(2)

# DEV set: one or two features per redundancy cluster, coverage >= 40%, no gold-fitted composites.
DEV_FEATURES = ["a_T", "a_n_fields_own", "a_prereq", "a_quarantine_share", "k_text_24x7_any",
                "b_coords_far_50km", "b_merge_bucket", "c_n_urls", "c_share_official",
                "d_nabh_listed", "e_has_website", "e_web_service", "f_osm_match",
                "g_type_hospital", "g_n_specialties"]
# scale caps for the scorecard: x -> min(x, cap) / cap; NaN -> 0 (absent)
CAPS = {"a_T": 5, "a_n_fields_own": 3, "a_prereq": 2, "b_merge_bucket": 2, "c_n_urls": 30, "g_n_specialties": 30}
PU_FEATURES = ["a_T", "a_n_fields_own", "a_n_units_own", "a_prereq", "a_negation", "a_quarantine_share",
               "a_m_specialties", "k_text_24x7_any", "k_text_pmjay", "k_text_blood_bank", "b_coords_far_50km",
               "b_votes_against", "b_merge_bucket", "b_directory_phone", "c_n_urls", "c_share_official",
               "c_share_aggregator", "d_nmc_college", "d_erk_blood_centre_on_site", "d_erk_nearest_km",
               "e_site_alive", "e_web_service", "e_web_service_page", "f_osm_match", "g_type_hospital",
               "g_public", "g_log_beds", "g_log_doctors", "g_n_specialties", "service"]


def scale(d: pd.DataFrame, feats: list[str]) -> np.ndarray:
    cols = []
    for f in feats:
        x = d[f].astype(float).fillna(0).values
        cols.append(np.minimum(x, CAPS[f]) / CAPS[f] if f in CAPS else x)
    return np.column_stack(cols)


def fit_scorecard(X, y, signs):
    k = X.shape[1]

    def nll(p):
        z = p[0] + X @ p[1:]
        return np.sum(np.logaddexp(0, z) - y * z) + LAMBDA * np.sum(p[1:] ** 2), np.concatenate(
            [[np.sum(1 / (1 + np.exp(-z)) - y)], X.T @ (1 / (1 + np.exp(-z)) - y) + 2 * LAMBDA * p[1:]])
    bounds = [(None, None)] + [(0, None) if s == "+" else (None, 0) if s == "-" else (None, None) for s in signs]
    r = minimize(nll, np.zeros(k + 1), jac=True, method="L-BFGS-B", bounds=bounds)
    return r.x


def ebm(**kw):
    return ExplainableBoostingClassifier(interactions=0, random_state=7, n_jobs=1, **kw)


def shapes(model, feats):
    out = {}
    for i, f in enumerate(model.term_names_):
        sc = model.term_scores_[i][1:-1]  # drop missing and unseen bins
        sd = model.standard_deviations_[i][1:-1]
        b = model.bins_[i][0]
        edges = list(b.keys()) if isinstance(b, dict) else [float(v) for v in b]
        out[f] = dict(edges=edges, scores=[float(v) for v in sc], sd=[float(v) for v in sd],
                      missing_score=float(model.term_scores_[i][0]), importance=float(model.term_importances()[i]),
                      categorical=isinstance(b, dict))
    return out


def dev_models(dev):
    d = dev[dev.y.notna()].reset_index(drop=True)
    y, g = d.y.values.astype(int), d.group.values
    folds = list(GroupKFold(n_splits=5).split(d, groups=g))
    Xe = d[DEV_FEATURES].astype(float)
    kw = dict(outer_bags=50, min_samples_leaf=3, max_bins=16, learning_rate=0.02)
    oof = np.zeros(len(d))
    for tr, te in folds:
        oof[te] = ebm(**kw).fit(Xe.iloc[tr], y[tr]).predict_proba(Xe.iloc[te])[:, 1]
    full = ebm(**kw).fit(Xe, y)
    signs = [M.META[f][2] for f in DEV_FEATURES]
    X = scale(d, DEV_FEATURES)
    oof_sc = np.zeros(len(d))
    for tr, te in folds:
        p = fit_scorecard(X[tr], y[tr], signs)
        oof_sc[te] = p[0] + X[te] @ p[1:]
    p = fit_scorecard(X, y, signs)
    gi = pd.Series(np.arange(len(d))).groupby(g).apply(np.array).tolist()
    bs = []
    for _ in range(500):
        idx = np.concatenate([gi[i] for i in RNG.integers(0, len(gi), len(gi))])
        bs.append(fit_scorecard(X[idx], y[idx], signs))
    bs = np.array(bs)
    sc = pd.DataFrame({"feature": ["intercept"] + DEV_FEATURES, "sign": ["free"] + signs,
                       "cap": [None] + [CAPS.get(f, 1) for f in DEV_FEATURES], "weight": p,
                       "lo": np.percentile(bs, 2.5, axis=0), "hi": np.percentile(bs, 97.5, axis=0),
                       "share_boot_zero": (np.abs(bs) < 1e-6).mean(axis=0)})
    sc["points_full_scale"] = sc.weight * POINTS
    sc.to_csv(OUT / "scorecard.csv", index=False)
    ga = pd.Series(np.arange(len(d))).groupby(g).apply(np.array).tolist()

    def boot_auc(score):
        v = []
        for _ in range(2000):
            idx = np.concatenate([ga[i] for i in RNG.integers(0, len(ga), len(ga))])
            v.append(auc(score[idx], y[idx]))
        return [float(auc(score, y))] + [float(q) for q in np.nanpercentile(v, [2.5, 97.5])]
    base = d.a_T.values.astype(float)
    res = dict(n=int(len(d)), n_pos=int(y.sum()), features=DEV_FEATURES,
               ebm_oof_auc=boot_auc(oof), scorecard_oof_auc=boot_auc(oof_sc), text_level_alone_auc=boot_auc(base),
               ebm_params=kw, scorecard_lambda=LAMBDA)
    return res, shapes(full, DEV_FEATURES)


def pu_model(feat):
    pu = feat.join(L.pu_labels(feat)[["pu_nabh"]])
    d = pu[pu.pu_nabh.notna()].reset_index(drop=True)
    for f in PU_FEATURES:
        assert f == "service" or M.leakage(f)["nabh_codes"] != "direct", f
    X = d[PU_FEATURES].copy()
    y, st, s = d.pu_nabh.values.astype(int), d.state.fillna("unknown").values, d.service.values
    kw = dict(outer_bags=14, min_samples_leaf=10, max_bins=32)
    oof = np.zeros(len(d))
    folds = list(GroupKFold(n_splits=5).split(d, groups=st))
    fold_auc = []
    for tr, te in folds:
        oof[te] = ebm(**kw).fit(X.iloc[tr], y[tr]).predict_proba(X.iloc[te])[:, 1]
        fold_auc.append(float(auc_strat(oof[te], y[te], s[te])))
    full = ebm(**kw).fit(X, y)
    txt = auc_strat(d.a_T.values.astype(float), y, s)
    res = dict(n=int(len(d)), n_pos=int(y.sum()), n_states=int(len(set(st))), features=PU_FEATURES,
               oof_auc_within_service=float(auc_strat(oof, y, s)), fold_auc=fold_auc,
               text_level_alone_auc=float(txt), ebm_params=kw)
    return res, shapes(full, PU_FEATURES)


def main():
    feat = pd.read_parquet(OUT / "features_pairs.parquet")
    dev = L.gold_dev().merge(feat, on=["unique_id", "service"], how="left")
    dres, dshape = dev_models(dev)
    pres, pshape = pu_model(feat)
    (OUT / "glassbox.json").write_text(json.dumps(dict(dev=dres, pu_nabh=pres), indent=1))
    (OUT / "ebm_dev_shapes.json").write_text(json.dumps(dshape, indent=1))
    (OUT / "ebm_pu_shapes.json").write_text(json.dumps(pshape, indent=1))
    print(json.dumps(dict(dev=dres, pu_nabh=pres), indent=1))
    print(pd.read_csv(OUT / "scorecard.csv").round(3).to_string())
    for name, sh in [("dev", dshape), ("pu", pshape)]:
        print(name, sorted(((round(v["importance"], 3), k) for k, v in sh.items()), reverse=True))


if __name__ == "__main__":
    main()
