"""Pair-level evaluation of the evidence layer against the spec baselines (section 8) on web-checked gold.

Systems (pair-level scores; the query-level distance discount is the decision layer's job):
  B0 any lexicon mention | B1 tagged-sentence count | B2 rule grade map | B3 LLM judge (llama-3-3-70b, cached)
  B4e evidence prior scorecard (prior_scorecard.json, hand-set, no fitting)
  B5e gold-only ridge logistic on the same evidence terms, fitted on dev (M0-style, prior N(0, 2.5^2))
Ablations of B4e: no ownership filter, no echo collapse, no bucket terms, no scope term.
Targets: primary y = confirmed vs not (no_info counts as 0, spec 5.6) and labelled = confirmed vs contradicted
(no_info dropped). Headline = v2 test (71 pairs). v1 pairs (all seen during design) are reported as a secondary set.
Intervals: 2,000-resample cluster bootstrap over leakage groups; Wilson for proportions.
Writes eval_metrics.json and eval_pairs.csv.
"""
import json

import numpy as np
import pandas as pd

from atoms import pair_families
from common import HERE, wilson
from gold import load_gold

RNG = np.random.default_rng(20261122)
GRADE_MAP = {"strong": 0.9, "moderate": 0.6, "weak": 0.3, "tag_only": 0.2}
N_BOOT = 2000


def design(df: pd.DataFrame, bucket_terms=True, scope=True) -> pd.DataFrame:
    T = df["T"]
    x = pd.DataFrame({f"t{v}": (T >= v).astype(float) for v in range(1, 6)}, index=df.index)
    if bucket_terms:
        x["tb_mid"] = ((T >= 2) & (df.bucket == "mid")).astype(float)
        x["tb_high"] = ((T >= 2) & (df.bucket == "high")).astype(float)
    x["c1"], x["c2"] = (df.C >= 1).astype(float), (df.C >= 2).astype(float)
    x["n1"] = df.N.astype(float)
    if scope:
        x["s1"] = df.S.astype(float)
    x["p1"], x["p2"] = (df.P >= 1).astype(float), (df.P >= 2).astype(float)
    return x


def prior_score(df: pd.DataFrame, **kw) -> pd.Series:
    pc = json.load(open(HERE / "prior_scorecard.json"))
    x = design(df, **kw)
    z = pc["intercept"] + sum(pc["weights"][c]["w"] * x[c] for c in x.columns)
    return 1 / (1 + np.exp(-z))


def fit_ridge(x: np.ndarray, y: np.ndarray, sd=2.5, iters=50) -> np.ndarray:
    """MAP logistic regression, Gaussian prior N(0, sd^2) on slopes, flat intercept; Newton steps."""
    X = np.column_stack([np.ones(len(x)), x])
    w = np.zeros(X.shape[1])
    P = np.diag([0.0] + [1 / sd ** 2] * x.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (y - p) - P @ w
        H = X.T @ (X * (p * (1 - p))[:, None]) + P
        step = np.linalg.solve(H, g)
        w += step
        if np.abs(step).max() < 1e-8:
            break
    return w


def auroc(s, y, w=None) -> float:
    s, y = np.asarray(s, float), np.asarray(y, int)
    w = np.ones(len(s)) if w is None else np.asarray(w, float)
    pos, neg = y == 1, y == 0
    if pos.sum() == 0 or neg.sum() == 0:
        return float("nan")
    sp, sn, wp, wn = s[pos][:, None], s[neg][None, :], w[pos][:, None], w[neg][None, :]
    return float(((sp > sn) + 0.5 * (sp == sn)).astype(float).__mul__(wp * wn).sum() / (wp.sum() * wn.sum()))


def boot(df: pd.DataFrame, fn, n=N_BOOT) -> list:
    groups = df.leakage_group_id.to_numpy()
    ug = np.unique(groups)
    idx_by = {g: np.where(groups == g)[0] for g in ug}
    vals = []
    for _ in range(n):
        pick = RNG.choice(ug, size=len(ug), replace=True)
        ii = np.concatenate([idx_by[g] for g in pick])
        v = fn(df.iloc[ii])
        if np.isfinite(v):
            vals.append(v)
    return [round(float(np.quantile(vals, 0.025)), 4), round(float(np.quantile(vals, 0.975)), 4)] if vals else [None, None]


def precision_at(df: pd.DataFrame, call: pd.Series) -> dict:
    """Among pairs the system calls positive: confirmed / (confirmed + contradicted), and no_info share."""
    c = df[call]
    k, m = int((c.label == 1).sum()), int(c.label.notna().sum())
    lo, hi = wilson(k, m)
    return dict(called=int(len(c)), confirmed=k, contradicted=m - k, no_info=int(c.label.isna().sum()),
                precision=round(k / m, 4) if m else None, wilson=[lo, hi])


def main():
    pf = pd.read_parquet(HERE / "pair_features.parquet")
    ff = pd.read_parquet(HERE / "facility_features.parquet", columns=["unique_id", "leakage_group_id"])
    atoms = pd.read_parquet(HERE / "claim_atoms.parquet")
    g = load_gold().merge(pf, on=["unique_id", "service"], how="left").merge(ff, on="unique_id", how="left")
    assert g["T"].notna().all()
    # ablation family values for the gold facilities only (same code, switches off)
    uids = pd.Series(sorted(g.unique_id.unique()))
    sub = atoms[atoms.unique_id.isin(uids)]
    fams = {"no_ownership_filter": pair_families(sub, uids, ownership_filter=False),
            "no_echo_collapse": pair_families(sub, uids, echo=False)}
    for k, fam in fams.items():
        g = g.merge(fam[["unique_id", "service", "T", "C"]].rename(columns={"T": f"T_{k}", "C": f"C_{k}"}), on=["unique_id", "service"])

    llm = pd.read_parquet(HERE / "llm_cache.parquet")
    llm = llm[llm.kind == "pair"].assign(r=lambda d: d.response.map(json.loads)).set_index("id")
    key = g.unique_id + "|" + g.service
    g["b3_offers"] = key.map(lambda k: llm.at[k, "r"]["offers"] if k in llm.index else None)
    g["b3_conf"] = key.map(lambda k: float(llm.at[k, "r"]["confidence"]) if k in llm.index else np.nan)
    g["B0"] = (g.n_atoms > 0).astype(float)
    g["B1"] = g.n_tagged_sentences.astype(float)
    g["B2"] = g.grade.map(GRADE_MAP).fillna(0.1)
    g["B3"] = np.where(g.b3_offers == "yes", g.b3_conf, 0.0)
    g.loc[g.b3_offers.isna(), "B3"] = np.nan
    g["B4e"] = prior_score(g)
    g["abl_no_ownership_filter"] = prior_score(g.assign(T=g.T_no_ownership_filter, C=g.C_no_ownership_filter))
    g["abl_no_echo_collapse"] = prior_score(g.assign(T=g.T_no_echo_collapse, C=g.C_no_echo_collapse))
    g["abl_no_bucket_terms"] = prior_score(g, bucket_terms=False)
    g["abl_no_scope_term"] = prior_score(g, scope=False)
    g["T_only"] = g["T"].astype(float)
    dev = g[(g.split == "dev")]
    xd = design(dev).to_numpy()
    w = fit_ridge(xd, dev.y_primary.to_numpy().astype(float))
    g["B5e"] = 1 / (1 + np.exp(-(np.column_stack([np.ones(len(g)), design(g).to_numpy()]) @ w)))
    b5_weights = dict(zip(["intercept"] + list(design(dev).columns), np.round(w, 3).tolist()))

    systems = ["B0", "B1", "B2", "B3", "B4e", "B5e", "T_only", "abl_no_ownership_filter", "abl_no_echo_collapse",
               "abl_no_bucket_terms", "abl_no_scope_term"]
    calls = {"B0": g.B0 > 0, "B1": g.B1 > 0, "B2": g.grade.isin(["strong", "moderate"]), "B3": g.b3_offers == "yes",
             "B4e": g.B4e >= 0.5, "B5e": g.B5e >= 0.5, "T_only": g["T"] >= 2,
             "abl_no_ownership_filter": g.abl_no_ownership_filter >= 0.5, "abl_no_echo_collapse": g.abl_no_echo_collapse >= 0.5,
             "abl_no_bucket_terms": g.abl_no_bucket_terms >= 0.5, "abl_no_scope_term": g.abl_no_scope_term >= 0.5}
    sets = {"v2_test": g[(g.version == "v2") & (g.split == "test")], "v2_dev": g[(g.version == "v2") & (g.split == "dev")],
            "v1_all": g[g.version == "v1"], "test_v2_plus_v1test": g[g.split == "test"]}
    out = {"b5e_weights_fit_on_dev": b5_weights, "n_dev_fit": int(len(dev)), "n_dev_pos": int(dev.y_primary.sum())}
    for name, d in sets.items():
        res = {"n": len(d), "confirmed": int((d.label == 1).sum()), "contradicted": int((d.label == 0).sum()),
               "no_info": int(d.label.isna().sum())}
        for s in systems:
            dd = d[d[s].notna()]
            lab = dd[dd.label.notna()]
            r = {"n_scored": len(dd),
                 "auroc_primary": round(auroc(dd[s], dd.y_primary), 4),
                 "auroc_primary_ci": boot(dd, lambda x: auroc(x[s], x.y_primary)),
                 "auroc_labelled": round(auroc(lab[s], lab.label), 4) if len(lab) else None,
                 "auroc_labelled_ci": boot(lab, lambda x: auroc(x[s], x.label)) if len(lab) else None,
                 "precision_of_positive_calls": precision_at(dd, calls[s].loc[dd.index])}
            if name.startswith("v2") and dd.ipw.notna().all():
                r["auroc_primary_ipw"] = round(auroc(dd[s], dd.y_primary, dd.ipw), 4)
                r["auroc_primary_ipw_ci"] = boot(dd, lambda x: auroc(x[s], x.y_primary, x.ipw))
            if s != "B4e" and dd.B4e.notna().all():
                r["diff_vs_B4e_auroc_primary_ci"] = boot(dd, lambda x: auroc(x.B4e, x.y_primary) - auroc(x[s], x.y_primary))
            res[s] = r
        out[name] = res
    (HERE / "eval_metrics.json").write_text(json.dumps(out, indent=1, default=float))
    keep = ["pair_id", "version", "split", "stratum", "unique_id", "service", "service_label", "label", "y_primary", "ipw",
            "T", "C", "N", "S", "P", "bucket", "grade", "b3_offers", "b3_conf"] + systems
    g[keep].to_csv(HERE / "eval_pairs.csv", index=False)
    for name in sets:
        print(f"== {name}: n={out[name]['n']} conf={out[name]['confirmed']} contra={out[name]['contradicted']} no_info={out[name]['no_info']}")
        for s in systems:
            r = out[name][s]
            p = r["precision_of_positive_calls"]
            print(f"  {s:26s} AUROC(primary) {r['auroc_primary']} {r['auroc_primary_ci']}  ipw {r.get('auroc_primary_ipw')} "
                  f"| labelled {r['auroc_labelled']} | calls {p['called']}: {p['confirmed']}c/{p['contradicted']}x/{p['no_info']}u "
                  f"prec {p['precision']} {p['wilson']} | B4e-minus {r.get('diff_vs_B4e_auroc_primary_ci')}")
    print("B5e weights:", b5_weights)


if __name__ == "__main__":
    main()
