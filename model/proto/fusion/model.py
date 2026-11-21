"""Fitting utilities shared by the three heads: grouped folds, out-of-fold logits, paired-SE selection, Platt."""
import numpy as np

import glm
from fcommon import hkey, sigmoid, weighted_logloss


def folds_for(groups, y, k=5):
    """Grouped, label-stratified, deterministic folds: groups sorted by (any positive, sha256), dealt round robin."""
    groups = np.asarray(groups)
    ug = sorted(set(groups), key=lambda g: (-int(np.asarray(y)[groups == g].max()), hkey(g, "vf-fusion-cv")))
    fold_of = {g: i % k for i, g in enumerate(ug)}
    return np.array([fold_of[g] for g in groups])


def oof_logits(X, y, w, prior_fn, A, folds):
    """prior_fn(fold or None) -> (mu, sd); lets M2 recompute its prior without the held-out fold's gold."""
    z = np.zeros(len(y))
    for f in sorted(set(folds)):
        tr, te = folds != f, folds == f
        mu, sd = prior_fn(f)
        fit = glm.fit(X[tr], y[tr], w[tr], mu, sd, A)
        z[te] = X[te] @ fit.beta
    return z


def paired(loss_a, loss_b, w):
    """Weighted mean loss difference a - b and its SE (ratio-estimator linearisation over rows)."""
    W = w.sum()
    d = loss_a - loss_b  # already multiplied by w
    dbar = d.sum() / W
    n = len(d)
    se = np.sqrt(n / max(n - 1, 1) * np.sum((d - w * dbar) ** 2)) / W
    return float(dbar), float(se)


def mean_loss(p, y, w):
    return float(weighted_logloss(p, y, w).sum() / w.sum())


def platt_decision(z, y, w, folds):
    """Platt on only if cross-fitted Platt lowers out-of-fold weighted log loss versus the identity map."""
    zc = np.zeros(len(z))
    for f in sorted(set(folds)):
        tr, te = folds != f, folds == f
        a, c = glm.fit_platt(z[tr], y[tr], w[tr])
        zc[te] = a * z[te] + c
    l_id, l_pl = mean_loss(sigmoid(z), y, w), mean_loss(sigmoid(zc), y, w)
    d, se = paired(weighted_logloss(sigmoid(zc), y, w), weighted_logloss(sigmoid(z), y, w), w)
    use = l_pl < l_id
    a, c = glm.fit_platt(z, y, w) if use else (1.0, 0.0)
    return dict(use=bool(use), a=a, c=c, oof_logloss_identity=l_id, oof_logloss_platt_crossfit=l_pl, diff=d, diff_se=se)


def platt_bootstrap(z, y, w, groups, use, n=200, seed=20261122):
    if not use:
        return np.ones(n), np.zeros(n)
    rng = np.random.default_rng(seed)
    ug = np.array(sorted(set(groups)))
    idx = {g: np.where(groups == g)[0] for g in ug}
    a_b, c_b = np.zeros(n), np.zeros(n)
    for b in range(n):
        pick = np.concatenate([idx[g] for g in rng.choice(ug, len(ug), replace=True)])
        a_b[b], c_b[b] = glm.fit_platt(z[pick], y[pick], w[pick])
    return a_b, c_b
