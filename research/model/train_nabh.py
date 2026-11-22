"""Service-availability scorecard trained on NABH declared-scope codes (weak labels), CPU only.

Population: VF facilities matched to a NABH record that carries at least one of the 7 fully fetched
specialty codes (so "code absent" means "declared scope without this code", a noisy negative).
Label: NABH lists the code mapped to the service. Features: interpretable VF-only terms from
model/proto/evidence/pair_features.parquet. No NABH-derived field is a feature.
Split: 70/30 by sha256(leakage_group_id), so duplicate records never straddle train and test.

Run: .venv-ml/bin/python -B research/model/train_nabh.py
Writes research/model/out/{metrics.json, scores.parquet, coefficients.csv, track_record.csv}.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold

ROOT = Path("/Users/karthikvattem/projects/datathon")
OUT = ROOT / "research/model/out"
SEED = 20261121
# pair_features service key -> NABH spec code. DIA is the direct label; the rest are proxies
# (OBG is obstetrics, not emergency C-section; CAR is cardiology, not cardiac surgery).
# (metrics key, service, NABH codes that count as positive). Only runs whose key equals the service are batch scored;
# the DIA-or-NPH run is a label-definition sensitivity check.
RUNS = [("dialysis", "dialysis", {"DIA"}), ("dialysis_label_dia_or_nph", "dialysis", {"DIA", "NPH"}),
        ("emergency_csection", "emergency_csection", {"OBG"}), ("cardiac_surgery", "cardiac_surgery", {"CAR"}),
        ("trauma_emergency", "trauma_emergency", {"EMD"})]
SERVICES = {r[1] for r in RUNS}
FETCHED = {"DIA", "NPH", "OBG", "EMD", "CAR", "ONC", "TRN"}
CATS = ["T", "P", "facility_type", "public_level", "beds_bin", "doctors_bin", "breadth_bin", "bucket"]
FLAGS = ["S", "N", "operator_public", "list_truncated", "shared_content"]
CS = [0.03, 0.1, 0.3, 1.0, 3.0]
TEXT_COLS = ["specialties", "procedure", "equipment", "capability", "description"]


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def design(df):
    X = pd.get_dummies(df[CATS].astype(str).fillna("nan"), prefix=CATS, dtype=float)
    X = X.drop(columns=[c for c in ["T_0", "P_0", "facility_type_hospital", "public_level_none", "beds_bin_nan",
                                    "doctors_bin_nan", "breadth_bin_5-19", "bucket_low"] if c in X])  # baselines
    for f in FLAGS:
        X[f] = df[f].fillna(False).astype(float)
    X["C_any"] = (df["C"] > 0).astype(float)
    return X


def reliability(y, p, edges=(0, .2, .4, .6, .8, 1.0001)):
    rows, ece = [], 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        n, k = int(m.sum()), int(y[m].sum())
        if n:
            ece += n / len(y) * abs(y[m].mean() - p[m].mean())
        rows.append(dict(bin=f"{lo:.1f}-{min(hi, 1):.1f}", n=n, positives=k, rate=round(k / n, 3) if n else None,
                         wilson95=wilson(k, n), mean_p=round(float(p[m].mean()), 3) if n else None))
    return rows, round(float(ece), 4)


def pr_at(y, p, t):
    pred = p >= t
    tp = int((pred & (y == 1)).sum())
    return dict(threshold=round(float(t), 3), flagged=int(pred.sum()), tp=tp,
                precision=round(tp / pred.sum(), 3) if pred.sum() else None, recall=round(tp / y.sum(), 3))


def thresh_for_precision(y, p, target=0.8):
    for t in np.round(np.arange(0.3, 0.96, 0.01), 2):
        m = p >= t
        if m.sum() >= 10 and y[m].mean() >= target:
            return float(t)
    return None


def fit_cv(X, y, groups):
    """Pick C by grouped 5-fold CV log loss on train; return model, C, out-of-fold probabilities."""
    best = None
    for C in CS:
        oof = np.zeros(len(y))
        for tr, va in GroupKFold(5).split(X, y, groups):
            m = LogisticRegression(C=C, max_iter=2000).fit(X[tr], y[tr])
            oof[va] = m.predict_proba(X[va])[:, 1]
        ll = log_loss(y, oof)
        if best is None or ll < best[0]:
            best = (ll, C, oof)
    return LogisticRegression(C=best[1], max_iter=2000).fit(X, y), best[1], best[2]


def load():
    pf = pd.read_parquet(ROOT / "model/proto/evidence/pair_features.parquet")
    ff = pd.read_parquet(ROOT / "model/proto/evidence/facility_features.parquet", columns=["unique_id", "leakage_group_id"])
    pf = pf.merge(ff, on="unique_id", how="left")
    pf["leakage_group_id"] = pf.leakage_group_id.fillna(pf.unique_id)
    nm = pd.read_parquet(ROOT / "data/external/nabh_accredited/nabh_vf_match.parquet")
    nm = nm[nm.accept].copy()
    nm["codes"] = nm.nabh_specs.apply(lambda v: set(v) if v is not None else set())
    nm = nm[nm.codes.apply(lambda s: bool(s & FETCHED))]
    codes = nm.groupby("unique_id").codes.agg(lambda s: set().union(*s))
    ps = pd.read_parquet(ROOT / "model/proto/fusion/pair_scores.parquet", columns=["unique_id", "service", "p_s"])
    return pf.merge(ps, on=["unique_id", "service"], how="left"), codes


def in_test(gid):
    return int(hashlib.sha256(f"nabh-split-v1:{gid}".encode()).hexdigest(), 16) % 10 < 3


def text_baseline(lab, tr, te):
    """Non-explainable comparator: TF-IDF over all VF text fields + LR. Tells us whether a richer text model
    (the thing a GPU would buy) has headroom over the scorecard on these labels."""
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet", columns=["unique_id", "name"] + TEXT_COLS)
    raw = raw.drop_duplicates("unique_id").set_index("unique_id")
    txt = raw.reindex(lab.unique_id)[["name"] + TEXT_COLS].fillna("").astype(str).agg(" ".join, axis=1).values
    vec = TfidfVectorizer(min_df=3, ngram_range=(1, 2), sublinear_tf=True, max_features=50000)
    Xt = vec.fit_transform(txt[tr])
    y = lab.y.values
    best = None
    for C in [0.3, 1, 3, 10]:
        oof = np.zeros(tr.sum())
        for a, b in GroupKFold(5).split(Xt, y[tr], lab.leakage_group_id.values[tr]):
            oof[b] = LogisticRegression(C=C, max_iter=3000).fit(Xt[a], y[tr][a]).predict_proba(Xt[b])[:, 1]
        ll = log_loss(y[tr], oof)
        best = (ll, C) if best is None or ll < best[0] else best
    m = LogisticRegression(C=best[1], max_iter=3000).fit(Xt, y[tr])
    p = m.predict_proba(vec.transform(txt[te]))[:, 1]
    return dict(C=best[1], auroc=round(roc_auc_score(y[te], p), 3), pr_auc=round(average_precision_score(y[te], p), 3),
                brier=round(brier_score_loss(y[te], p), 4))


def cross_source(scores):
    """Positive-only labels from other lists, restricted to facilities outside the NABH training population."""
    out = {}
    nmc = pd.read_parquet(ROOT / "data/external/nmc_colleges/nmc_vf_matches.parquet")
    lab = pd.read_parquet(ROOT / "data/external/nmc_colleges/nmc_service_labels.parquet")
    dia = set(nmc[nmc.college_id.isin(lab[(lab.service == "dialysis") & (lab.tier == "strong")].college_id)].unique_id)
    lq = pd.read_parquet(ROOT / "data/external/laqshya_master/laqshya_vf_matches.parquet")
    lf = pd.read_parquet(ROOT / "data/external/laqshya_master/laqshya_facilities.parquet")
    mot = set(lq[lq.lq_id.isin(lf[lf["Maternity OT"].notna()].lq_id)].unique_id)
    tcf = set(pd.read_csv(ROOT / "data/external/mohfw_trauma_196/tcf_vf_matches.csv").vf_id)
    for svc, ids, name in [("dialysis", dia, "NMC DM Nephrology"), ("emergency_csection", mot, "LaQshya Maternity OT"),
                           ("trauma_emergency", tcf, "MoHFW trauma care facility")]:
        s = scores[scores.service == svc]
        pos = s[s.unique_id.isin(ids)]
        pub = s[(s.operator_public | (s.public_level != "none")) & ~s.unique_id.isin(ids)]
        t = s.threshold_p80.iloc[0]
        out[svc] = dict(list=name, n_list_positives_scored=len(pos), n_in_nabh_population=int(pos.in_nabh_pop.sum()),
                        median_p_list=round(float(pos.p.median()), 3), median_p_other_public=round(float(pub.p.median()), 3),
                        recall_at_p80_threshold=round(float((pos.p >= t).mean()), 3) if t == t and len(pos) else None,
                        auroc_list_vs_other_public=round(roc_auc_score(
                            np.r_[np.ones(len(pos)), np.zeros(len(pub))], np.r_[pos.p, pub.p]), 3) if len(pos) else None)
    return out


def web_gold(scores):
    """Dev-only web labels (model/gold v2 dev + audit/ground_truth v1). The sealed v2 test split is not opened."""
    sys.path.insert(0, str(ROOT / "model/proto/fusion"))
    from gold import load_gold
    g = load_gold("dev")
    g = g[g.status.eq("checked") & g.service.isin(SERVICES)].merge(scores[["unique_id", "service", "p", "p_s"]],
                                                                   on=["unique_id", "service"], how="left")
    res = {"n": len(g), "positives": int(g.y.sum()), "by_service": g.groupby("service").y.agg(["size", "sum"]).to_dict("index")}
    if g.y.nunique() == 2:
        res["auroc_nabh_model"] = round(roc_auc_score(g.y, g.p), 3)
        res["auroc_fusion_p_s"] = round(roc_auc_score(g.y, g.p_s), 3)
        res["mean_p_confirmed"] = round(float(g[g.y == 1].p.mean()), 3)
        res["mean_p_not_confirmed"] = round(float(g[g.y == 0].p.mean()), 3)
        res["auroc_by_service"] = {s: dict(n=len(x), nabh_model=round(roc_auc_score(x.y, x.p), 3),
                                           fusion_p_s_in_sample=round(roc_auc_score(x.y, x.p_s), 3))
                                   for s, x in g.groupby("service") if x.y.nunique() == 2}
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pf, codes = load()
    metrics, all_scores, coefs, track = {"seed": SEED, "population_facilities": int(len(codes))}, [], [], []
    for key, svc, code in RUNS:
        d = pf[pf.service == svc].reset_index(drop=True)
        X_all = design(d)
        d["in_nabh_pop"] = d.unique_id.isin(codes.index)
        lab = d[d.in_nabh_pop].copy()
        lab["y"] = lab.unique_id.map(lambda u: int(bool(code & codes[u])))
        te = lab.leakage_group_id.map(in_test).values
        tr = ~te
        X = X_all.loc[lab.index].values
        y = lab.y.values
        model, C, oof = fit_cv(X[tr], y[tr], lab.leakage_group_id.values[tr])
        p_te = model.predict_proba(X[te])[:, 1]
        t80 = thresh_for_precision(y[tr], oof, 0.8)
        rel, ece = reliability(y[te], p_te)
        rule = (lab["T"].values[te] >= 2).astype(float)
        fus = lab.p_s.values[te]
        m = dict(nabh_codes=sorted(code), n_train=int(tr.sum()), n_test=int(te.sum()), pos_train=int(y[tr].sum()),
                 pos_test=int(y[te].sum()), base_rate_test=round(float(y[te].mean()), 3), C=C,
                 auroc=round(roc_auc_score(y[te], p_te), 3), pr_auc=round(average_precision_score(y[te], p_te), 3),
                 brier=round(brier_score_loss(y[te], p_te), 4),
                 brier_base_rate=round(brier_score_loss(y[te], np.full(te.sum(), y[tr].mean())), 4),
                 ece_5bin=ece, reliability_test=rel, at_0_5=pr_at(y[te], p_te, 0.5),
                 at_train_p80_threshold=pr_at(y[te], p_te, t80) if t80 else None,
                 baseline_rule_T_ge_2=pr_at(y[te], rule, 0.5),
                 baseline_fusion_p_s=dict(auroc=round(roc_auc_score(y[te], fus), 3),
                                          brier=round(brier_score_loss(y[te], fus), 4)),
                 text_tfidf_comparator=text_baseline(lab, tr, te))
        metrics[key] = m
        if key != svc:
            continue
        names = list(X_all.columns)
        coefs += [dict(service=svc, term=n, weight=round(float(w), 4)) for n, w in zip(names, model.coef_[0])]
        coefs.append(dict(service=svc, term="intercept", weight=round(float(model.intercept_[0]), 4)))
        # Batch score every facility; store per-term contributions so the App can show the arithmetic.
        contrib = X_all.values * model.coef_[0]
        z = model.intercept_[0] + contrib.sum(1)
        p = 1 / (1 + np.exp(-z))
        top = [";".join(f"{names[j]}:{contrib[i, j]:+.2f}" for j in np.argsort(-np.abs(contrib[i]))[:4] if contrib[i, j] != 0)
               for i in range(len(d))]
        split = np.full(len(d), "unlabelled", dtype=object)
        split[lab.index[tr]] = "train"
        split[lab.index[te]] = "test"
        all_scores.append(pd.DataFrame(dict(unique_id=d.unique_id, service=svc, p=p.round(4), z=z.round(4),
                                            intercept=round(float(model.intercept_[0]), 4), top_terms=top,
                                            cited_atom_ids=d.cited_atom_ids, T=d["T"], p_s=d.p_s, in_nabh_pop=d.in_nabh_pop,
                                            nabh_split=split, operator_public=d.operator_public, public_level=d.public_level,
                                            threshold_p80=t80 if t80 else np.nan)))
        for r in rel:
            track.append(dict(service=svc, label=f"NABH lists {'/'.join(sorted(code))}", **{k: (str(v) if k == "wilson95" else v) for k, v in r.items()}))
        assert np.allclose(p[lab.index[te]], p_te), "stored contributions must reproduce the model output"
    scores = pd.concat(all_scores, ignore_index=True)
    metrics["cross_source_positive_only"] = cross_source(scores)
    metrics["web_gold_dev"] = web_gold(scores)
    scores.drop(columns=["operator_public", "public_level"]).to_parquet(OUT / "scores.parquet", index=False)
    pd.DataFrame(coefs).to_csv(OUT / "coefficients.csv", index=False)
    pd.DataFrame(track).to_csv(OUT / "track_record.csv", index=False)
    json.dump(metrics, open(OUT / "metrics.json", "w"), indent=1, default=str)
    print(json.dumps(metrics, indent=1, default=str))


if __name__ == "__main__":
    main()
