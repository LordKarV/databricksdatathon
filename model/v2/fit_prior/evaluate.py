"""Evaluate candidate A (prior-only v2) on gold DEV only: grouped 5-fold CV, held-out states, intervals.

A has no fitted parameter, so its out-of-fold prediction equals its prediction. The only fitted variant is
A_platt (z* = a z + c, two parameters per fold), fitted on the training folds of fold5 (leakage groups) and of
held-out-state folds. Intervals: 2,000-replicate cluster bootstrap over leakage groups; Wilson for proportions.
Writes out/oof_A.parquet, out/metrics_A.json, out/badges_A.json.
Run after prior_a.py: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python evaluate.py
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

ROOT = Path("/Users/karthikvattem/projects/datathon")
OUT = ROOT / "model/v2/fit_prior/out"
LABELS = ROOT / "model/v2/labels/out"
B = 2000
SEED = 20261121
EPS = 1e-12
TOL = 1e-9
FALLBACK_TL, FALLBACK_TU = 0.70, 0.20


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * np.asarray(z, float)))


def wilson(k: float, n: float, z: float = 1.959964) -> list:
    if n == 0:
        return [float("nan"), float("nan")]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [c - h, c + h]


def metrics(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> dict:
    p = np.clip(p, EPS, 1 - EPS)
    ll = -np.sum(w * (y * np.log(p) + (1 - y) * np.log(1 - p))) / w.sum()
    br = np.sum(w * (p - y) ** 2) / w.sum()
    auc = roc_auc_score(y, p, sample_weight=w) if 0 < y.sum() < len(y) else float("nan")
    order = np.argsort(p, kind="stable")
    ece = 0.0
    for b in np.array_split(order, 5):
        if len(b):
            ece += w[b].sum() / w.sum() * abs(np.sum(w[b] * p[b]) / w[b].sum() - np.sum(w[b] * y[b]) / w[b].sum())
    return dict(logloss=ll, auroc=auc, brier=br, ece=ece, mean_p=float(np.sum(w * p) / w.sum()),
                mean_y=float(np.sum(w * y) / w.sum()))


def boot_index(groups: np.ndarray, rng: np.random.Generator) -> list:
    ug, inv = np.unique(groups, return_inverse=True)
    members = [np.flatnonzero(inv == i) for i in range(len(ug))]
    reps = []
    for _ in range(B):
        pick = rng.integers(0, len(ug), len(ug))
        reps.append(np.concatenate([members[i] for i in pick]))
    return reps


def with_ci(y, preds: dict, w, reps, ref: str = None) -> dict:
    """Point metrics and 95% bootstrap intervals per prediction; paired differences against ref."""
    out = {}
    for name, p in preds.items():
        pt = metrics(y, p, w)
        bs = {k: [] for k in pt}
        dif = {"logloss": [], "auroc": []}
        for ix in reps:
            if y[ix].sum() in (0, len(ix)):
                continue
            m = metrics(y[ix], p[ix], w[ix])
            for k in bs:
                bs[k].append(m[k])
            if ref and name != ref:
                r = metrics(y[ix], preds[ref][ix], w[ix])
                dif["logloss"].append(m["logloss"] - r["logloss"])
                dif["auroc"].append(m["auroc"] - r["auroc"])
        res = {k: dict(value=round(float(v), 4), ci95=[round(float(np.nanpercentile(bs[k], q)), 4) for q in (2.5, 97.5)])
               for k, v in pt.items()}
        if ref and name != ref:
            r = metrics(y, preds[ref], w)
            res["minus_ref"] = {k: dict(value=round(float(pt[k] - r[k]), 4),
                                        ci95=[round(float(np.nanpercentile(dif[k], q)), 4) for q in (2.5, 97.5)],
                                        se=round(float(np.nanstd(dif[k])), 4)) for k in dif}
        out[name] = res
    return out


def platt_oof(z: np.ndarray, y: np.ndarray, folds: np.ndarray) -> tuple:
    p, ab = np.zeros(len(z)), {}
    for f in np.unique(folds):
        tr = folds != f
        m = LogisticRegression(C=1e6, max_iter=1000).fit(z[tr, None], y[tr])
        a, c = float(m.coef_[0, 0]), float(m.intercept_[0])
        p[~tr] = sigmoid(a * z[~tr] + c)
        ab[int(f)] = dict(a=round(a, 4), c=round(c, 4), n_train=int(tr.sum()))
    return p, ab


def platt_full(z: np.ndarray, y: np.ndarray) -> dict:
    """Platt on all gold DEV pairs, for the selection step if it ships A_platt. z* = a z + c, so every contribution
    scales by a and the base gains c; the identity base + sum = z* is asserted."""
    m = LogisticRegression(C=1e6, max_iter=1000).fit(z[:, None], y)
    a, c = float(m.coef_[0, 0]), float(m.intercept_[0])
    assert np.max(np.abs(sigmoid(a * z + c) - m.predict_proba(z[:, None])[:, 1])) < TOL
    return dict(a=a, c=c, n=int(len(y)), positives=int(y.sum()), max_p_on_all_pairs_note="see FIT.md")


def thresholds(p: np.ndarray, y: np.ndarray, eligible: np.ndarray) -> dict:
    """MODEL_SPEC 3.2: t_L smallest threshold with precision >= 0.85 among eligible pairs, t_U largest with
    NPV >= 0.90, each needing >= 20 dev pairs beyond it; else the fallbacks."""
    tl = None
    for t in np.sort(np.unique(p[eligible])):
        sel = eligible & (p >= t)
        if sel.sum() >= 20 and y[sel].mean() >= 0.85:
            tl = float(t)
            break
    tu = None
    for t in np.sort(np.unique(p))[::-1]:
        sel = p <= t
        if sel.sum() >= 20 and (1 - y[sel]).mean() >= 0.90:
            tu = float(t)
            break
    res = dict(t_L=tl if tl is not None else FALLBACK_TL, t_L_fallback=tl is None,
               t_U=tu if tu is not None else FALLBACK_TU, t_U_fallback=tu is None)
    for name, sel in [("likely", eligible & (p >= res["t_L"])), ("unlikely", p <= res["t_U"])]:
        k = int(y[sel].sum()) if name == "likely" else int((1 - y[sel]).sum())
        res[name] = dict(n=int(sel.sum()), k_correct=k, rate=round(k / sel.sum(), 4) if sel.sum() else None,
                         wilson95=[round(v, 4) for v in wilson(k, int(sel.sum()))])
    # diagnostic: precision curve over eligible pairs at fixed cut-offs
    res["eligible_curve"] = [dict(t=t, n=int((eligible & (p >= t)).sum()), k=int(y[eligible & (p >= t)].sum()))
                             for t in (0.3, 0.5, 0.6, 0.7, 0.8, 0.9)]
    return res


def state_fold(state: pd.Series) -> np.ndarray:
    return np.array([int(hashlib.sha256(f"state-v2:{s}".encode()).hexdigest(), 16) % 5 for s in state.fillna("NA")])


def main() -> None:
    params = json.load(open(OUT / "params_A.json"))
    sterms = params["service"]
    names = [t["name"] for t in sterms]
    fam_of = {t["name"]: t["family"] for t in sterms}
    gold = pd.read_parquet(LABELS / "gold_dev_pairs.parquet")
    gold = gold[gold.y_S.notna()].reset_index(drop=True)
    cg = pd.read_parquet(OUT / "contrib_gold_A.parquet")
    sc = pd.read_parquet(OUT / "scores_A.parquet")
    g = gold.merge(cg, on=["unique_id", "service"], how="left", validate="one_to_one")
    g = g.merge(sc[["unique_id", "service", "P_S", "P_L", "P_E", "T", "operator_public"]], on=["unique_id", "service"],
                how="left", validate="one_to_one")
    C = g[names].to_numpy()
    z = g.z_S.to_numpy()
    assert np.max(np.abs(C.sum(1) - z)) < TOL
    assert np.max(np.abs(sigmoid(z) - g.P_S.to_numpy())) < TOL
    y = g.y_S.to_numpy()
    n_all, w1 = len(y), np.ones(len(y))
    print(f"gold DEV pairs with y_S: {n_all}, positives {int(y.sum())}, leakage groups {g.leakage_group_id.nunique()}")
    g["state_fold"] = state_fold(g.state)
    rng = np.random.default_rng(SEED)

    # ---- predictions: A, Platt OOF, ablations
    p_f5, ab_f5 = platt_oof(z, y, g.fold5.to_numpy())
    p_st, ab_st = platt_oof(z, y, g.state_fold.to_numpy())
    preds = {"A": sigmoid(z), "A_platt_fold5": p_f5, "A_platt_heldout_state": p_st}

    def drop(cols: list) -> np.ndarray:
        return sigmoid(z - C[:, [names.index(c) for c in cols]].sum(1))

    fams = {"X": [n for n in names if fam_of[n] == "X"], "W": [n for n in names if fam_of[n] == "W"],
            "O": [n for n in names if fam_of[n] == "O"], "D": ["d_unit"], "K": ["k_iphs"],
            "C_prior": [n for n in names if fam_of[n] == "C_prior"], "P": ["p1", "p2"], "S": ["s1"],
            "context": [n for n in names if fam_of[n] == "context"]}
    for f, cols in fams.items():
        preds[f"A_minus_{f}"] = drop(cols)
    # specialty weights off: t1 counts a specialties-only mention as a full mention (x = 1)
    spec_only = (g["x:t1"] > 0) & (g["x:t1"] < 1)
    t1w = next(t["weight"] for t in sterms if t["name"] == "t1")
    preds["A_minus_spec_weights"] = sigmoid(z + np.where(spec_only, t1w * (1 - g["x:t1"]), 0.0))
    # crossfit_plan gold_web_check ablation: website and cited-source columns
    preds["A_minus_gold_web_ablate"] = drop(fams["W"] + ["tb_mid", "tb_high", "tw_none"])
    preds["A_new_families_off"] = drop(fams["X"] + fams["W"] + fams["O"] + ["d_unit", "k_iphs", "tp_public", "tw_none"])

    reps = boot_index(g.leakage_group_id.to_numpy(), rng)
    res = dict(n=n_all, positives=int(y.sum()), leakage_groups=int(g.leakage_group_id.nunique()),
               note="A is not fitted, so its out-of-fold predictions equal its predictions under any fold scheme")
    res["all"] = with_ci(y, preds, w1, reps, ref="A")

    subsets = {"public": g.operator_public == 1, "private": g.operator_public == 0,
               "operator_unknown": g.operator_public.isna(), "v1_v2": g.version.isin(["v1", "v2"]),
               "e2e": g.version == "e2e", "no_gold_cites_list": ~g.gold_cites_list}
    main_preds = {k: preds[k] for k in ["A", "A_platt_fold5", "A_platt_heldout_state", "A_new_families_off",
                                        "A_minus_W", "A_minus_X"]}
    res["subsets"] = {}
    for sname, mask in subsets.items():
        m = mask.to_numpy()
        if y[m].sum() in (0, m.sum()) or m.sum() < 5:
            res["subsets"][sname] = dict(n=int(m.sum()), positives=int(y[m].sum()), note="one class only: not run")
            continue
        sub_reps = boot_index(g.leakage_group_id.to_numpy()[m], rng)
        res["subsets"][sname] = dict(n=int(m.sum()), positives=int(y[m].sum()),
                                     metrics=with_ci(y[m], {k: v[m] for k, v in main_preds.items()}, w1[m], sub_reps,
                                                     ref="A"))
    # IPW on v1 + v2 (e2e has no inclusion probability)
    m = g.version.isin(["v1", "v2"]).to_numpy() & g.ipw.notna().to_numpy()
    sub_reps = boot_index(g.leakage_group_id.to_numpy()[m], rng)
    res["ipw_v1_v2"] = dict(n=int(m.sum()), ess=round(float(g.ipw[m].sum() ** 2 / (g.ipw[m] ** 2).sum()), 1),
                            metrics=with_ci(y[m], {k: v[m] for k, v in main_preds.items()}, g.ipw.to_numpy()[m],
                                            sub_reps, ref="A"))
    # Platt rule: use only if its OOF log-loss gain is at least one paired SE
    for scheme in ("A_platt_fold5", "A_platt_heldout_state"):
        d = res["all"][scheme]["minus_ref"]["logloss"]
        res[f"platt_rule_{scheme}"] = dict(gain=-d["value"], se=d["se"], use=bool(-d["value"] >= d["se"]),
                                           per_fold=ab_f5 if scheme.endswith("fold5") else ab_st)
    res["state_folds"] = {int(f): dict(pairs=int((g.state_fold == f).sum()), states=int(g.state[g.state_fold == f].nunique()))
                          for f in range(5)}

    # ---- thresholds and Likely precision (MODEL_SPEC 3.2)
    eligible = ((g.P_L >= 0.7) & (g.P_E >= 0.7) & (g["T"] >= 2)).to_numpy()
    res["thresholds"] = {k: thresholds(preds[k], y, eligible) for k in ["A", "A_platt_fold5", "A_platt_heldout_state"]}

    # ---- per-family contribution summaries on gold
    fam_rows = []
    for f in sorted(set(fam_of.values())):
        cols = [names.index(n) for n in names if fam_of[n] == f]
        v = C[:, cols].sum(1)
        for grp, mask in [("all", np.ones(n_all, bool)), ("public", (g.operator_public == 1).to_numpy()),
                          ("private", (g.operator_public == 0).to_numpy())]:
            fam_rows.append(dict(family=f, group=grp, n=int(mask.sum()), n_nonzero=int((v[mask] != 0).sum()),
                                 mean_pos=round(float(v[mask & (y == 1)].mean()), 3),
                                 mean_neg=round(float(v[mask & (y == 0)].mean()), 3)))
    res["family_contrib_gold"] = fam_rows
    sf = [c for c in sc.columns if c.startswith("fam_")]
    pub = sc.operator_public
    res["family_contrib_all_pairs"] = [
        dict(family=c[4:], group=grp, share_nonzero=round(float((sc.loc[m, c] != 0).mean()), 4),
             mean=round(float(sc.loc[m, c].mean()), 4), mean_abs=round(float(sc.loc[m, c].abs().mean()), 4))
        for c in sf for grp, m in [("all", np.ones(len(sc), bool)), ("public", pub == 1), ("private", pub == 0)]]

    # ---- location and existence heads
    fl = pd.read_parquet(OUT / "facility_contrib_A.parquet")
    fac = pd.read_parquet(LABELS / "gold_dev_facility.parquet").merge(fl, on="unique_id", how="left")
    opmap = sc.drop_duplicates("unique_id").set_index("unique_id").operator_public
    fac["operator_public"] = fac.unique_id.map(opmap)
    res["location"], res["existence"] = {}, {}
    for head, col, abl in [("location", "y_L", ["L:l_d_nabh_listed", "L:l_osm_conflict"]),
                           ("existence", "y_E", ["E:e_nabh_listed", "E:e_osm_high", "E:e_osm_medium"])]:
        d = fac[fac[col].notna()].reset_index(drop=True)
        zc = "z_L" if head == "location" else "z_E"
        hp = {"A": sigmoid(d[zc]), "A_minus_ablate_columns": sigmoid(d[zc] - d[abl].sum(1))}
        yy = d[col].to_numpy()
        for name, mask in [("all", np.ones(len(d), bool)), ("gold_dev_only", (d.src == "gold_dev").to_numpy()),
                           ("public", (d.operator_public == 1).to_numpy()), ("private", (d.operator_public == 0).to_numpy())]:
            if yy[mask].sum() in (0, mask.sum()):
                res[head][name] = dict(n=int(mask.sum()), negatives=int((1 - yy[mask]).sum()), note="one class only: not run")
                continue
            rr = boot_index(d.leakage_group_id.to_numpy()[mask], rng)
            res[head][name] = dict(n=int(mask.sum()), negatives=int((1 - yy[mask]).sum()),
                                   metrics=with_ci(yy[mask], {k: np.asarray(v)[mask] for k, v in hp.items()},
                                                   np.ones(mask.sum()), rr, ref="A"))
        pr = sigmoid(d[zc].to_numpy())
        sel = pr >= 0.7
        k = int(yy[sel].sum())
        res[head]["at_0.7"] = dict(n=int(sel.sum()), k_yes=k, wilson95=[round(v, 4) for v in wilson(k, int(sel.sum()))])

    # ---- badges on all pairs, under A's thresholds
    th = res["thresholds"]["A"]
    elig_all = (sc.P_L >= 0.7) & (sc.P_E >= 0.7) & (sc["T"] >= 2)
    likely = elig_all & (sc.P_S >= th["t_L"])
    unlikely = sc.P_S <= th["t_U"]
    badge = np.where(likely, "LIKELY", np.where(unlikely, "UNLIKELY", np.where(sc["T"] >= 2, "CALL_FIRST", "NO_SERVICE_TEXT")))
    bc = pd.Series(badge).value_counts().to_dict()
    bpub = pd.Series(badge[(sc.operator_public == 1).to_numpy()]).value_counts().to_dict()
    json.dump(dict(t_L=th["t_L"], t_U=th["t_U"], all=bc, public=bpub,
                   likely_by_service=sc[likely].service.value_counts().to_dict()), open(OUT / "badges_A.json", "w"), indent=1)

    oof = g[["pair_id", "unique_id", "service", "version", "stratum", "y_S", "ipw", "leakage_group_id", "state",
             "fold5", "state_fold", "gold_cites_list", "operator_public", "T", "P_L", "P_E", "z_S"]].copy()
    for k, v in preds.items():
        oof[f"p_{k}"] = v
    gb = np.where(eligible & (preds["A"] >= th["t_L"]), "LIKELY", np.where(preds["A"] <= th["t_U"], "UNLIKELY",
                  np.where(g["T"] >= 2, "CALL_FIRST", "NO_SERVICE_TEXT")))
    oof["badge_A"] = gb
    oof.to_parquet(OUT / "oof_A.parquet", index=False)
    json.dump(platt_full(z, y), open(OUT / "platt_full_A.json", "w"), indent=1)
    json.dump(res, open(OUT / "metrics_A.json", "w"), indent=1, default=float)
    a = res["all"]
    for k in a:
        print(f"{k:28s} LL {a[k]['logloss']['value']:.3f} {a[k]['logloss']['ci95']} AUC {a[k]['auroc']['value']:.3f} "
              f"{a[k]['auroc']['ci95']} Brier {a[k]['brier']['value']:.3f} ECE {a[k]['ece']['value']:.3f} "
              f"{a[k]['ece']['ci95']} " + (f"dLL {a[k]['minus_ref']['logloss']['value']:+.3f} "
                                            f"{a[k]['minus_ref']['logloss']['ci95']} dAUC {a[k]['minus_ref']['auroc']['value']:+.3f} "
                                            f"{a[k]['minus_ref']['auroc']['ci95']}" if "minus_ref" in a[k] else ""))
    print(json.dumps({k: res[k] for k in res if k.startswith("platt_rule")}, indent=0)[:800])
    print(json.dumps(res["thresholds"], indent=0)[:2500])
    print("badges", bc, "public", bpub)


if __name__ == "__main__":
    main()
