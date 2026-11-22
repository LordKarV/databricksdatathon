"""Candidate D (issue #79): sign-constrained logistic scorecard with reader soft counts.

Run from the repo root:  python model/v2/fit_reader/fit.py
Needs derived/v2/reader_scores.parquet (from the evidence reader, PR #67).
Reads gold DEV labels and PU labels in model/v2/labels/out/ only. Never opens model/gold.

Every score is base + sum of weight x indicator; the script asserts that identity to 1e-9.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[3]
V2 = ROOT / "derived" / "v2"
LAB = ROOT / "model" / "v2" / "labels" / "out"
OUT = Path(__file__).resolve().parent / "out"
SEED = 79
N_BOOT = 2000
SD_FREE, SD_PU, SD_INTERCEPT = 1.5, 1.0, 5.0     # prior sds: assumptions, not tuned
R_STEPS = (0.5, 1.5, 3.0)                        # soft-count steps, fixed before any fit
PU_FAMILIES = ("nabh", "nmc", "laqshya", "eraktkosh")   # LABELS.md: mohfw_tcf, pmndp_goa, nmc blood_bank are not PU-usable

# name -> sign: +1 weight >= 0, -1 weight <= 0, 0 free
T_TERMS = {f"t{v}": 1 for v in range(1, 6)}
R_TERMS = {f"r{i + 1}": 1 for i in range(len(R_STEPS))}
EVID = {"prereq": 1, "c1": -1, "n1": -1, "s1": -1, "trunc": 0}
CTX = {"public": 0, "hospital": 0, "beds_hi": 0}
LIST = {"x_on": 1, "x_absent": 0}                # dropped whenever a list is the label (cross-fit plan)
VARIANTS = {
    "B_like": {**T_TERMS},
    "D_replace": {**R_TERMS},
    "D_augment": {**T_TERMS, **R_TERMS},
    "D_augment_offers_only": {**T_TERMS, **R_TERMS},   # soft count without p_about_this (ablation)
}


def soft_counts() -> pd.DataFrame:
    """Per (facility, service): sum over echo units of p_about_this x p_offers (max within a unit)."""
    a = pd.read_parquet(V2 / "claim_atoms.parquet", columns=["claim_id", "unique_id", "service", "unit_id"])
    r = pd.read_parquet(V2 / "reader_scores.parquet", columns=["claim_id", "service_id", "p_about_this", "p_offers"])
    about = r[r.service_id == ""].set_index("claim_id").p_about_this
    off = r[r.service_id != ""].rename(columns={"service_id": "service"})[["claim_id", "service", "p_offers"]]
    m = a.merge(off, on=["claim_id", "service"], how="inner")
    m["p_about"] = m.claim_id.map(about)
    m = m.dropna(subset=["p_about", "p_offers"])
    m["full"] = m.p_about.astype(float) * m.p_offers.astype(float)
    m["offers"] = m.p_offers.astype(float)
    u = m.groupby(["unique_id", "service", "unit_id"])[["full", "offers"]].max()
    s = u.groupby(level=[0, 1]).sum().rename(columns={"full": "soft_full", "offers": "soft_offers"}).reset_index()
    s["n_units_scored"] = u.groupby(level=[0, 1]).size().values
    return s


def design(keys: pd.DataFrame, soft_col: str) -> pd.DataFrame:
    """0/1 indicators. Missing or not observable is 0, so it contributes nothing (fairness coding)."""
    cols = ["unique_id", "service", "a_T", "a_prereq", "a_contamination", "a_negation", "a_scope_conflict",
            "a_list_truncated", "x_any_list", "obs_X", "operator_public", "g_type_hospital", "g_log_beds"]
    f = pd.read_parquet(V2 / "facility_features.parquet", columns=cols)
    d = keys.merge(f, on=["unique_id", "service"], how="left", validate="many_to_one")
    assert d.a_T.notna().all(), "a labelled pair is missing from facility_features"
    d = d.merge(SOFT, on=["unique_id", "service"], how="left")
    s = d[soft_col].fillna(0.0)
    x = pd.DataFrame(index=d.index)
    for v in range(1, 6):
        x[f"t{v}"] = (d.a_T >= v).astype(float)
    for i, th in enumerate(R_STEPS):
        x[f"r{i + 1}"] = (s >= th).astype(float)
    x["prereq"] = (d.a_prereq >= 1).astype(float)
    x["c1"] = (d.a_contamination >= 1).astype(float)
    x["n1"] = (d.a_negation >= 1).astype(float)
    x["s1"] = (d.a_scope_conflict >= 1).astype(float)
    x["trunc"] = (d.a_list_truncated >= 1).astype(float)
    x["x_on"] = (d.x_any_list == 1).astype(float)
    x["x_absent"] = (d.obs_X == "absent").astype(float)
    x["public"] = (d.operator_public == 1).astype(float)
    x["hospital"] = (d.g_type_hospital == 1).astype(float)
    x["beds_hi"] = (d.g_log_beds >= 2).astype(float)     # NaN compares False -> 0
    return x


def fit_map(X, y, w, signs, mu, sd):
    """MAP logistic with a Gaussian prior and sign bounds. Returns the weight vector."""
    lo = [0.0 if s > 0 else None for s in signs]
    hi = [0.0 if s < 0 else None for s in signs]

    def f(b):
        z = X @ b
        nll = np.sum(w * (np.logaddexp(0, z) - y * z))
        pen = 0.5 * np.sum(((b - mu) / sd) ** 2)
        g = X.T @ (w * (1 / (1 + np.exp(-z)) - y)) + (b - mu) / sd ** 2
        return nll + pen, g

    b0 = np.clip(mu, [l if l is not None else -np.inf for l in lo], [h if h is not None else np.inf for h in hi])
    r = minimize(f, b0, jac=True, method="L-BFGS-B", bounds=list(zip(lo, hi)), options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-8})
    return r.x


def matrix(x, terms, groups, prefix):
    """Indicator matrix: one intercept column per group value, then the named terms."""
    lv = sorted(groups.unique())
    I = np.stack([(groups == g).to_numpy(float) for g in lv], axis=1)
    names = [f"{prefix}:{g}" for g in lv] + list(terms)
    return np.hstack([I, x[list(terms)].to_numpy(float)]), names, [0] * len(lv) + [terms[t] for t in terms]


def pu_prior(variant_terms, soft_col, exclude_fold):
    """Stage 1: fit 'is on the list' inside each list's scope; its evidence weights become prior means."""
    p = PU[(PU.fold5 != exclude_fold)] if exclude_fold is not None else PU
    x = design(p[["unique_id", "service"]].reset_index(drop=True), soft_col)
    terms = {**variant_terms, **EVID, **CTX}          # no list terms: the list is the label
    X, names, signs = matrix(x, terms, p.label_family.reset_index(drop=True), "family")
    n_i = len(names) - len(terms)
    mu = np.zeros(len(names))
    sd = np.r_[np.full(n_i, SD_INTERCEPT), np.full(len(terms), SD_FREE)]
    b = fit_map(X, (p.label == "positive").to_numpy(float), p.weight.where(p.label == "positive", 1.0).to_numpy(float), signs, mu, sd)
    return {n: float(v) for n, v in zip(names[n_i:], b[n_i:]) if n in variant_terms or n in EVID}


def gold_fit(train_idx, variant_terms, soft_col, prior):
    terms = {**variant_terms, **EVID, **LIST, **CTX}
    x = design(G[["unique_id", "service"]], soft_col)
    X, names, signs = matrix(x, terms, G.service, "service")
    n_i = len(names) - len(terms)
    mu = np.r_[np.zeros(n_i), [prior.get(t, 0.0) for t in terms]]
    sd = np.r_[np.full(n_i, SD_INTERCEPT), [SD_PU if t in prior else SD_FREE for t in terms]]
    b = fit_map(X[train_idx], G.y_S.to_numpy(float)[train_idx], np.ones(len(train_idx)), signs, mu, sd)
    return X, names, b


def additivity(X, names, b):
    n_i = sum(n.startswith("service:") for n in names)
    base = X[:, :n_i] @ b[:n_i]
    contrib = X[:, n_i:] * b[n_i:]
    z = X @ b
    err = float(np.max(np.abs(base + contrib.sum(axis=1) - z)))
    assert err < 1e-9, err
    return err


def ece5(y, p):
    order = np.argsort(p, kind="stable")
    return float(sum(len(ix) / len(y) * abs(y[ix].mean() - p[ix].mean()) for ix in np.array_split(order, 5)))


def metrics(y, p):
    pc = np.clip(p, 1e-9, 1 - 1e-9)
    out = {"n": int(len(y)), "pos": int(y.sum()), "log_loss": float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))),
           "brier": float(np.mean((p - y) ** 2)), "ece5": ece5(y, p)}
    out["auroc"] = float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else None
    return out


def boot(y, cols, groups, rng):
    """Group bootstrap over leakage groups: 95% intervals per model and for each paired difference vs B_like."""
    gids = groups.unique()
    idx = {g: np.flatnonzero(groups.to_numpy() == g) for g in gids}
    draws = {k: {m: [] for m in ("log_loss", "brier", "ece5", "auroc")} for k in cols}
    diff = {k: [] for k in cols}
    for _ in range(N_BOOT):
        take = np.concatenate([idx[g] for g in rng.choice(gids, len(gids))])
        ms = {k: metrics(y[take], v[take]) for k, v in cols.items()}
        for k in cols:
            for m in draws[k]:
                if ms[k][m] is not None:
                    draws[k][m].append(ms[k][m])
            diff[k].append(ms[k]["log_loss"] - ms[next(iter(cols))]["log_loss"])
    ci = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if len(v) else None  # noqa: E731
    return {k: {m: ci(v) for m, v in d.items()} for k, d in draws.items()}, {k: ci(v) for k, v in diff.items()}


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    SOFT = soft_counts()
    g = pd.read_parquet(LAB / "gold_dev_pairs.parquet")
    assert (g.split == "dev").all()
    G = g[g.y_S.notna()].reset_index(drop=True)
    PU = pd.read_parquet(LAB / "pu_labels.parquet")
    PU = PU[PU.label_family.isin(PU_FAMILIES) & PU.label.isin(["positive", "unlabeled"])
            & ~((PU.label_family == "nmc") & (PU.service == "blood_bank"))].reset_index(drop=True)
    y = G.y_S.to_numpy(float)
    oof = G[["pair_id", "unique_id", "service", "version", "y_S", "fold5", "leakage_group_id"]].copy()
    pub = design(G[["unique_id", "service"]], "soft_full").public.to_numpy()
    oof["operator_public"] = pub
    oof = oof.merge(SOFT, on=["unique_id", "service"], how="left")
    params, add_err = {}, 0.0
    for prior_mode in ("gold_only", "pu_prior"):
        for name, vt in VARIANTS.items():
            soft_col = "soft_offers" if name.endswith("offers_only") else "soft_full"
            key = f"{name}__{prior_mode}"
            p = np.full(len(G), np.nan)
            for k in sorted(G.fold5.unique()):
                tr, te = np.flatnonzero(G.fold5 != k), np.flatnonzero(G.fold5 == k)
                prior = pu_prior(vt, soft_col, k) if prior_mode == "pu_prior" else {}
                X, names, b = gold_fit(tr, vt, soft_col, prior)
                add_err = max(add_err, additivity(X, names, b))
                p[te] = 1 / (1 + np.exp(-(X[te] @ b)))
            oof[key] = p
            prior = pu_prior(vt, soft_col, None) if prior_mode == "pu_prior" else {}
            X, names, b = gold_fit(np.arange(len(G)), vt, soft_col, prior)
            add_err = max(add_err, additivity(X, names, b))
            params[key] = {"weights": {n: round(float(v), 6) for n, v in zip(names, b)}, "pu_prior_means": {a: round(v, 6) for a, v in prior.items()}}
            print(key, "fitted")
    base = float(np.mean(y))
    oof["base_rate_by_fold"] = [float(y[G.fold5 != k].mean()) for k in G.fold5]
    order = ["B_like__gold_only"] + [c for c in oof.columns if "__" in c and c != "B_like__gold_only"] + ["base_rate_by_fold"]
    cols = {c: oof[c].to_numpy(float) for c in order}
    rng = np.random.default_rng(SEED)
    res = {"n_pairs": int(len(G)), "positives": int(y.sum()), "base_rate": base, "max_additivity_error": add_err,
           "pu_rows_used": int(len(PU)), "soft_count_pairs": int(len(SOFT)), "bootstrap": N_BOOT, "seed": SEED, "models": {}, "by_operator": {}}
    ci, dci = boot(y, cols, G.leakage_group_id, rng)
    for c in order:
        res["models"][c] = {**metrics(y, cols[c]), "ci95": ci[c], "log_loss_minus_B_like_gold_only": float(metrics(y, cols[c])["log_loss"] - metrics(y, cols[order[0]])["log_loss"]), "diff_ci95": dci[c]}
    for lab, mask in (("public", pub == 1), ("not_public_or_unknown", pub != 1)):
        ci_o, _ = boot(y[mask], {c: v[mask] for c, v in cols.items()}, G.leakage_group_id[mask].reset_index(drop=True), rng)
        res["by_operator"][lab] = {c: {**metrics(y[mask], cols[c][mask]), "ci95": ci_o[c]} for c in order}
    oof.to_parquet(OUT / "oof_predictions.parquet", index=False)
    (OUT / "params.json").write_text(json.dumps(params, indent=1, allow_nan=False))
    (OUT / "metrics.json").write_text(json.dumps(res, indent=1, allow_nan=False))
    for c in order:
        m = res["models"][c]
        print(f"{c:38s} ll {m['log_loss']:.4f} {np.round(m['ci95']['log_loss'], 3)} auroc {m['auroc']:.3f} {np.round(m['ci95']['auroc'], 3)} brier {m['brier']:.4f} ece {m['ece5']:.3f} d_ll {m['log_loss_minus_B_like_gold_only']:+.4f} {np.round(m['diff_ci95'], 3)}")
    print("max additivity error", add_err)
