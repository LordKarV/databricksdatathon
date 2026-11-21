"""Fusion layer: fit the three heads on dev, choose priors by grouped dev CV, score every pair and facility.

Reads dev labels only (gold.load_gold("dev")). Writes the contract outputs listed in spec 5.8 plus
variant_scores.parquet (baselines B4, B5, M-variants and ablations, scored on all pairs for eval_test.py) and
model.json (everything needed to rescore). Run: /Users/karthikvattem/projects/datathon/.venv/bin/python fit.py
"""
import datetime
import json
import time

import numpy as np
import pandas as pd

import dawid_skene as ds
import design as D
import glm
import model as M
from fcommon import HERE, PTS, ROOT, SEED, SERVICES, dump, sha256_file, sha256_str, sigmoid, wilson
from gold import case_weights, load_gold, overlap_kappa

M0_SD = 2.5
FALLBACK_TL, FALLBACK_TU = 0.70, 0.20
LIKELY_PL, LIKELY_PE = 0.7, 0.7
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


KAPPAS = (1.0, 0.5, 0.25)  # prior-strength multiplier on every non-deviation sd, chosen by dev CV (REPORT.md)


def split_prior(pc):
    src, _, k = pc.partition("@")
    return src, float(k or 1.0)


def priors_vec(terms, source, m1, m2=None):
    source, kappa = split_prior(source)
    mu, sd, src = [], [], []
    for t in terms:
        if t.group == "deviation":
            mu.append(0.0); sd.append(0.5); src.append("contract N(0,0.5^2)")
        elif source == "M1":
            mu.append(m1[t.name]["mu"]); sd.append(m1[t.name]["sd"]); src.append("M1")
        elif source == "M2" and m2 is not None and t.name in m2:
            mu.append(m2[t.name][0]); sd.append(m2[t.name][1]); src.append("M2")
        else:
            mu.append(0.0); sd.append(M0_SD); src.append("M0")
        if t.group != "deviation":
            sd[-1] *= kappa
    return np.array(mu), np.array(sd), [f"{x}@{kappa:g}" if x in ("M0", "M1", "M2") else x for x in src]


def prior_projection(X_cols, mu, sd, A):
    """MAP with zero data: the constrained point closest to the prior mean in the prior metric (used by B4 and
    by prior-only heads, because some expert means break a composite monotonicity constraint)."""
    return glm.fit(np.zeros((1, X_cols)), np.zeros(1), np.zeros(1), mu, sd, A)


def dev_set(pf, ff):
    gold = load_gold("dev")
    sp = json.load(open(ROOT / "model/gold/splits.json"))["pairs"]
    test_uids = {p["unique_id"] for p in sp if p["split"] == "test" and p["version"] == "v2"}
    lg = ff.set_index("unique_id").leakage_group_id
    test_groups = set(lg.reindex(list(test_uids)).dropna())
    gold["leakage_group_id"] = gold.unique_id.map(lg)
    gold["in_test_group"] = gold.leakage_group_id.isin(test_groups)
    gold["w_ipw"] = case_weights(gold)
    key = {(u, s): i for i, (u, s) in enumerate(zip(pf.unique_id, pf.service))}
    gold["row"] = [key[(u, s)] for u, s in zip(gold.unique_id, gold.service)]
    return gold, test_groups


def service_head(pf, gold, m1, variant=(), weighting=None, prior_choice=None, platt_use=None, ds_cache=None):
    terms = D.service_terms(variant)
    X = D.service_X(pf, terms, variant)
    A = D.constraints(terms)
    tr = gold[(gold.status == "checked") & ~gold.in_test_group].reset_index(drop=True)
    Xg, y = X[tr.row.to_numpy()], tr.y.to_numpy().astype(float)
    groups = tr.leakage_group_id.to_numpy()
    folds = M.folds_for(groups, y)
    w_eval = tr.w_ipw.to_numpy()
    out = dict(terms=terms, X=X, A=A, train=tr, folds=folds)

    def m2_for(fold):
        k = ("all" if fold is None else fold, variant)
        if ds_cache is not None and k in ds_cache:
            return ds_cache[k]
        sel = tr if fold is None else tr[folds != fold]
        res = ds.run(pf if not variant else pf.assign(T=pf["T_noown" if "noown" in variant else "T_noecho" if "noecho" in variant else "T"],
                                                       C=0 if "noown" in variant else pf.C),
                     dict(zip(sel.row, sel.y)))
        pri, W = ds.m2_priors(res, pf)
        if ds_cache is not None:
            ds_cache[k] = (pri, W, res)
        return pri, W, res

    cands = {}
    weightings = [weighting] if weighting else ["ipw", "uniform"]
    priors_list = [prior_choice] if prior_choice else [f"{m}@{k:g}" for m in ("M0", "M1", "M2") for k in KAPPAS]
    for wt in weightings:
        w_fit = w_eval if wt == "ipw" else np.ones(len(y))
        for pc in priors_list:
            fn = (lambda f, pc=pc: priors_vec(terms, pc, m1, m2_for(f)[0] if pc.startswith("M2") else None)[:2])
            z = M.oof_logits(Xg, y, w_fit, fn, A, folds)
            cands[(wt, pc)] = dict(z=z, loss_rows=M.weighted_logloss(sigmoid(z), y, w_eval),
                                   loss=M.mean_loss(sigmoid(z), y, w_eval))
            log(f"  service {variant or 'shipped'} {wt} {pc}: OOF weighted log loss {cands[(wt, pc)]['loss']:.4f}")
    # selection: weighting by M0's loss, then prior with M0 preferred within one paired SE
    m0_keys = [k for k in priors_list if k.startswith("M0")]
    wt = weighting or min(weightings, key=lambda k: min(cands[(k, m)]["loss"] for m in m0_keys))
    m0_best = min(m0_keys, key=lambda m: cands[(wt, m)]["loss"]) if m0_keys else None
    sel_rows = {}
    for pc in priors_list:
        d, se = M.paired(cands[(wt, pc)]["loss_rows"], cands[(wt, m0_best)]["loss_rows"], w_eval) if m0_best else (0.0, 0.0)
        sel_rows[pc] = dict(oof_logloss=cands[(wt, pc)]["loss"], diff_vs_best_M0=d, se_diff=se)
    if prior_choice:
        pc = prior_choice
    else:
        best = min(sel_rows, key=lambda k: sel_rows[k]["oof_logloss"])
        pc = best if best.startswith("M0") or -sel_rows[best]["diff_vs_best_M0"] >= sel_rows[best]["se_diff"] else m0_best
    base = (w_eval * y).sum() / w_eval.sum()
    out.update(constant_rate_oof_logloss=M.mean_loss(np.full(len(y), base), y, w_eval), weighting=wt, prior=pc, selection={f"{a}|{b}": dict(oof_logloss=v["loss"]) for (a, b), v in cands.items()},
               selection_paired=sel_rows)
    z_oof = cands[(wt, pc)]["z"]
    pl = M.platt_decision(z_oof, y, w_eval, folds) if platt_use is None else (
        dict(use=platt_use, **dict(zip(("a", "c"), glm.fit_platt(z_oof, y, w_eval) if platt_use else (1.0, 0.0)))))
    w_fit = w_eval if wt == "ipw" else np.ones(len(y))
    m2p = m2_for(None)[0] if pc.startswith("M2") else None
    mu, sd, src = priors_vec(terms, pc, m1, m2p)
    fit = glm.fit(Xg, y, w_fit, mu, sd, A)
    out.update(m2_for=m2_for, z_oof=z_oof, p_oof=sigmoid(pl["a"] * z_oof + pl["c"]), y=y, w_eval=w_eval, platt=pl, fit=fit, mu=mu, sd=sd,
               prior_src=src, m2_priors=m2p)
    return out


def facility_head(ff, head, rows, m1):
    terms, X = D.facility_X(ff, head)
    A = D.constraints(terms)
    out = dict(terms=terms, X=X, A=A)
    idx = rows.idx.to_numpy()
    y = rows.y.to_numpy().astype(float)
    w = np.ones(len(y))
    m1h = m1[head]
    mu1 = np.array([m1h[t.name]["mu"] for t in terms]); sd1 = np.array([m1h[t.name]["sd"] for t in terms])
    mu0, sd0 = np.zeros(len(terms)), np.full(len(terms), M0_SD)
    n_neg = int((y == 0).sum())
    out.update(n_train=len(y), n_pos=int(y.sum()), n_neg=n_neg)
    if n_neg < 15:  # contract: ship prior-only
        fit = prior_projection(len(terms), mu1, sd1, A)
        prior_cov = glm.Fit(beta=fit.beta, cov=np.diag(sd1 ** 2), active=fit.active, basis=fit.basis,
                            chol=np.linalg.cholesky(fit.basis.T @ np.diag(sd1 ** 2) @ fit.basis), rounds=0, converged=True)
        out.update(fitted=False, prior="M1", fit=prior_cov, mu=mu1, sd=sd1, platt=dict(use=False, a=1.0, c=0.0), selection={})
        return out
    Xg = X[idx]
    folds = M.folds_for(rows.group.to_numpy(), y)
    sel = {}
    for pc, (mu, sd) in {"M0": (mu0, sd0), "M1": (mu1, sd1)}.items():
        z = M.oof_logits(Xg, y, w, lambda f, mu=mu, sd=sd: (mu, sd), A, folds)
        sel[pc] = dict(z=z, rows=M.weighted_logloss(sigmoid(z), y, w), loss=M.mean_loss(sigmoid(z), y, w))
    d, se = M.paired(sel["M1"]["rows"], sel["M0"]["rows"], w)
    pc = "M1" if -d >= se else "M0"
    mu, sd = (mu1, sd1) if pc == "M1" else (mu0, sd0)
    pl = M.platt_decision(sel[pc]["z"], y, w, folds)
    fit = glm.fit(Xg, y, w, mu, sd, A)
    out.update(fitted=True, prior=pc, fit=fit, mu=mu, sd=sd, platt=pl, z_oof=sel[pc]["z"], y=y, folds=folds,
               groups=rows.group.to_numpy(),
               selection={k: dict(oof_logloss=v["loss"]) for k, v in sel.items()} | dict(diff_M1_minus_M0=d, se=se))
    return out


def location_rows(ff, gold, test_groups):
    """Training rows for P_L (within 25 km of p1): dev gold location labels, the 40 geo hand verdicts mapped to the
    source behind p1, and the cleaning hand check of the chosen point. Training only; test facilities excluded."""
    fi = {u: i for i, u in enumerate(ff.unique_id)}
    lg = ff.leakage_group_id.to_numpy()
    rows = []
    for r in gold.itertuples():
        if r.label_location in ("yes", "no") and not r.in_test_group:
            rows.append(dict(uid=r.unique_id, y=int(r.label_location == "yes"), src="gold_dev"))
    hv = pd.read_csv(ROOT / "audit/geo/hand_check_verdicts.csv")
    srcmap = {"listing_coordinates": "coords_ok", "postcode_centre": "pin_ok", "address_city_centre": "stated_state_ok"}
    p1src = ff.set_index("unique_id").p1_src
    for r in hv.itertuples():
        col = srcmap.get(p1src.get(r.unique_id))
        v = getattr(r, col) if col else None
        if v in ("yes", "no"):
            rows.append(dict(uid=r.unique_id, y=int(v == "yes"), src="geo_hand_check"))
    hc = pd.read_csv(HERE / "inputs_snapshot/handcheck_location.csv")
    pre = {u[:8]: u for u in ff.unique_id}
    for r in hc.itertuples():
        if r.chosen_right in ("yes", "no") and r.uid8 in pre:
            rows.append(dict(uid=pre[r.uid8], y=int(r.chosen_right == "yes"), src="cleaning_hand_check"))
    d = pd.DataFrame(rows).drop_duplicates("uid", keep="first")
    d["idx"] = d.uid.map(fi)
    d["group"] = lg[d.idx.to_numpy()]
    d = d[~d.group.isin(test_groups)]
    return d.reset_index(drop=True)


def existence_rows(ff, gold):
    fi = {u: i for i, u in enumerate(ff.unique_id)}
    g = gold[(gold.status == "checked") & ~gold.in_test_group].drop_duplicates("unique_id")
    return pd.DataFrame(dict(idx=g.unique_id.map(fi).to_numpy(), y=(g.label_exists == "yes").astype(int).to_numpy(),
                             group=g.leakage_group_id.to_numpy()))


def score_with_draws(X, h, A, n=200, a_b=None, c_b=None):
    pl = h["platt"]
    z_raw = X @ h["fit"].beta
    z_cal = pl["a"] * z_raw + pl["c"]
    dr, rate = glm.draws(h["fit"], A, n=n, seed=SEED)
    a_b = np.full(n, pl["a"]) if a_b is None else a_b
    c_b = np.full(n, pl["c"]) if c_b is None else c_b
    lo, hi = np.zeros(len(X)), np.zeros(len(X))
    for s in range(0, len(X), 5000):
        zz = (X[s:s + 5000] @ dr.T) * a_b[None, :] + c_b[None, :]
        pp = sigmoid(zz)
        lo[s:s + 5000], hi[s:s + 5000] = np.percentile(pp, 5, axis=1), np.percentile(pp, 95, axis=1)
    return z_raw, z_cal, lo, hi, dr, rate


def contributions_long(keys: pd.DataFrame, X, terms, beta, a, c, head, extra=None):
    nz = np.nonzero(X)
    r, j = nz
    grp = np.array(["base" if t.group == "intercept" else ("evidence" if t.group in ("evidence", "deviation") else "context") for t in terms])
    df = pd.DataFrame({**{k: keys[k].to_numpy()[r] for k in keys.columns}, "head": head,
                       "term": np.array([t.name for t in terms])[j], "x_value": X[r, j], "weight": beta[j],
                       "contribution_logit": a * beta[j] * X[r, j], "group": grp[j]})
    off = pd.DataFrame({**{k: keys[k].to_numpy() for k in keys.columns}, "head": head, "term": "platt_offset",
                        "x_value": 1.0, "weight": c, "contribution_logit": c, "group": "base"})
    df = pd.concat([df, off], ignore_index=True)
    df["points"] = df.contribution_logit * PTS
    if extra is not None:
        df = df.merge(extra, on=list(keys.columns), how="left")
    return df


def thresholds(p_oof, y, w, T, pl, pe):
    """t_L: smallest t with OOF IPW precision >= 0.85 over pairs meeting the other Likely rules, needing >= 20 such
    pairs; t_U: largest t with OOF NPV >= 0.90 over pairs with p <= t, needing >= 20. Else the fallbacks."""
    elig = (T >= 2) & (pl >= LIKELY_PL) & (pe >= LIKELY_PE)
    tl, tu, info = None, None, {}
    for t in np.unique(np.round(p_oof, 4)):
        m = elig & (p_oof >= t)
        if m.sum() >= 20 and (w[m] * y[m]).sum() / w[m].sum() >= 0.85:
            tl = float(t); break
    for t in sorted(np.unique(np.round(p_oof, 4)), reverse=True):
        m = p_oof <= t
        if m.sum() >= 20 and (w[m] * (1 - y[m])).sum() / w[m].sum() >= 0.90:
            tu = float(t); break
    info = dict(n_eligible_T2_PL_PE=int(elig.sum()), tl_estimated=tl, tu_estimated=tu)
    return (tl if tl is not None else FALLBACK_TL), (tu if tu is not None else FALLBACK_TU), info


def bands(p_s, p_l, p_e, T, C, tl, tu):
    likely = (p_s >= tl) & (p_l >= LIKELY_PL) & (p_e >= LIKELY_PE) & (T >= 2)
    unl_p, unl_c = p_s <= tu, (C == 2) & (T <= 1)
    band = np.where(likely, "Likely", np.where(unl_p | unl_c, "Unlikely", "Unverified"))
    reason = np.select(
        [likely, unl_c, unl_p, T < 2, p_s < tl, p_l < LIKELY_PL, p_e < LIKELY_PE],
        ["all four Likely rules hold", "only evidence names another facility or place (C = 2, T <= 1)",
         f"P_S <= t_U ({tu:.2f})", "no cited own unit (T < 2): context or tags only", f"P_S below t_L ({tl:.2f})",
         "location uncertain (P_L < 0.7)", "existence uncertain (P_E < 0.7)"], default="other")
    return band, reason


def three_outcome(df, label_col="label_service"):
    return dict(k_confirmed=int((df[label_col] == "confirmed").sum()), k_contradicted=int((df[label_col] == "contradicted").sum()),
                k_no_info=int((df[label_col] == "no_info").sum()))


def calib_rows(p, d, split, head="service", bins=5):
    rows = []
    o = np.argsort(p, kind="stable")
    for b, idx in enumerate(np.array_split(o, bins)):
        if len(idx) == 0:
            continue
        sub = d.iloc[idx]
        y, w = sub.y.to_numpy(), sub.w.to_numpy()
        lo, hi = wilson(int(y.sum()), len(y))
        rows.append(dict(head=head, split=split, bin=b, n=len(idx), mean_p=float(p[idx].mean()), p_min=float(p[idx].min()),
                         p_max=float(p[idx].max()), obs_raw=float(y.mean()), obs_ipw=float((w * y).sum() / w.sum()),
                         wilson_lo=lo, wilson_hi=hi, **three_outcome(sub)))
    return rows


def band_rows(band, d, split, model_hash, labels_sha):
    rows = []
    for b in ["Likely", "Unverified", "Unlikely"]:
        sub = d[band == b]
        k3 = three_outcome(sub)
        n = len(sub)
        good = k3["k_confirmed"] if b != "Unlikely" else n - k3["k_confirmed"]
        lo, hi = wilson(good, n)
        rows.append(dict(band=b, split=split, N=n, **k3, precision=good / n if n else float("nan"),
                         precision_meaning="confirmed share" if b != "Unlikely" else "not-confirmed share (NPV)",
                         wilson_lo=lo, wilson_hi=hi, labels_sha256=labels_sha, model_hash=model_hash,
                         computed_at=datetime.datetime.now().isoformat(timespec="seconds")))
    return rows


def main():
    pf = pd.read_parquet(HERE / "features_pairs.parquet")
    ff = pd.read_parquet(HERE / "features_facility.parquet")
    m1 = json.load(open(HERE / "priors_M1.json"))["priors"]
    gold, test_groups = dev_set(pf, ff)
    log("dev pairs", len(gold), "checked", int((gold.status == "checked").sum()), "in test leakage groups", int(gold.in_test_group.sum()))
    ds_cache = {}

    # ---- service head: selection, final fit
    S = service_head(pf, gold, m1["service"], ds_cache=ds_cache)
    log("service head:", S["weighting"], S["prior"], "platt", S["platt"])
    terms, X, A, fit = S["terms"], S["X"], S["A"], S["fit"]
    tr = S["train"]

    # ---- location and existence heads
    lrows = location_rows(ff, gold, test_groups)
    Lh = facility_head(ff, "location", lrows, m1)
    log("location head:", Lh["n_train"], "rows", Lh["n_pos"], "pos", Lh["prior"], Lh["platt"]["use"], Lh.get("selection"))
    Eh = facility_head(ff, "existence", existence_rows(ff, gold), m1)
    log("existence head: negatives", Eh["n_neg"], "fitted", Eh["fitted"])

    # ---- facility scores
    fkeys = ff[["unique_id"]]
    fs = ff[["unique_id", "p1_lat", "p1_lon", "p2_lat", "p2_lon", "loc_radius_km"]].copy()
    fcontrib = []
    m2_all = S["m2_for"](None)[0]
    for name, h in (("location", Lh), ("existence", Eh)):
        a_b, c_b = (M.platt_bootstrap(h["z_oof"], h["y"], np.ones(len(h["y"])), h["groups"], h["platt"]["use"])
                    if h.get("fitted") else (None, None))
        z_raw, z_cal, lo, hi, _, rate = score_with_draws(h["X"], h, h["A"], a_b=a_b, c_b=c_b)
        col = "p_l" if name == "location" else "p_e"
        fs[col], fs[col + "_lo"], fs[col + "_hi"], fs[f"z_cal_{name}"] = sigmoid(z_cal), lo, hi, z_cal
        h["draw_rate"] = rate
        fcontrib.append(contributions_long(fkeys, h["X"], h["terms"], h["fit"].beta, h["platt"]["a"], h["platt"]["c"], name))
    fs["existence_fitted"] = Eh["fitted"]
    fc = pd.concat(fcontrib, ignore_index=True)

    # ---- service scores with intervals (Laplace draws + Platt group bootstrap)
    a_b, c_b = M.platt_bootstrap(S["z_oof"], S["y"], S["w_eval"], tr.leakage_group_id.to_numpy(), S["platt"]["use"])
    z_raw, z_cal, lo, hi, dr, rate = score_with_draws(X, S, A, a_b=a_b, c_b=c_b)
    a, c = S["platt"]["a"], S["platt"]["c"]
    p_s = sigmoid(z_cal)
    pf2 = pf.assign(T=pf.t_without_cited, C=pf.c_without_cited)
    p_wo = sigmoid(a * (D.service_X(pf2, terms) @ fit.beta) + c)
    fsi = fs.set_index("unique_id")
    p_l = fsi.p_l.reindex(pf.unique_id).to_numpy()
    p_e = fsi.p_e.reindex(pf.unique_id).to_numpy()

    # ---- bands from dev out-of-fold predictions
    trow = tr.row.to_numpy()
    tl, tu, tinfo = thresholds(S["p_oof"], S["y"], S["w_eval"], pf["T"].to_numpy()[trow], p_l[trow], p_e[trow])
    band, reason = bands(p_s, p_l, p_e, pf["T"].to_numpy(), pf.C.to_numpy(), tl, tu)
    log("thresholds", tl, tu, tinfo)

    # ---- model hash
    code = {f: sha256_file(HERE / f) for f in ["features.py", "gold.py", "design.py", "glm.py", "model.py", "fit.py", "dawid_skene.py", "fcommon.py"]}
    feat_hash = sha256_file(HERE / "features_pairs.parquet")
    core = dict(service_beta=fit.beta.round(12).tolist(), platt=[a, c], loc_beta=Lh["fit"].beta.round(12).tolist(),
                loc_platt=[Lh["platt"]["a"], Lh["platt"]["c"]], ex_beta=Eh["fit"].beta.round(12).tolist(), tl=tl, tu=tu,
                code=code, features=feat_hash, priors_m1=json.load(open(HERE / "priors_M1.json"))["sha256"])
    model_hash = sha256_str(json.dumps(core, sort_keys=True))[:16] + "-fallback"
    labels_sha = sha256_str(gold[["pair_id", "label_service", "label_exists", "label_location"]].to_json())

    ps = pf[["unique_id", "service"]].assign(
        name=pf.name, z_raw=z_raw, z_cal=z_cal, p_s=p_s, p_s_lo=lo, p_s_hi=hi, band=band, band_reason=reason,
        p_s_without_cited=p_wo, T=pf["T"], C=pf.C, N=pf.N, S=pf.S, P=pf.P, bucket=pf.bucket, p_l=p_l, p_e=p_e,
        model_hash=model_hash)
    ps.to_parquet(HERE / "pair_scores.parquet", index=False)
    pc = contributions_long(pf[["unique_id", "service"]], X, terms, fit.beta, a, c, "service",
                            extra=pf[["unique_id", "service", "cited_atom_ids", "rejected_atom_ids"]])
    pc.to_parquet(HERE / "pair_contributions.parquet", index=False)
    fs.to_parquet(HERE / "facility_scores.parquet", index=False)
    fc.to_parquet(HERE / "facility_contributions.parquet", index=False)
    log("wrote scores", len(ps), "pairs,", len(pc), "contribution rows;", len(fs), "facilities")

    # ---- weights table
    wrows = []
    for hname, h, Xh in (("service", S, X), ("location", Lh, Lh["X"]), ("existence", Eh, Eh["X"])):
        drh, _ = glm.draws(h["fit"], h["A"], n=200, seed=SEED)
        fired_dev = (Xh[tr.row.to_numpy()] != 0).sum(0) if hname == "service" else np.full(len(h["terms"]), -1)
        m1h = m1[hname]
        active_terms = set()
        for i in h["fit"].active:
            active_terms |= {h["terms"][j].name for j in np.nonzero(h["A"][i])[0]}
        for j, t in enumerate(h["terms"]):
            post = float(h["fit"].beta[j])
            m1mu = m1h.get(t.name, {}).get("mu")
            m2mu = m2_all.get(t.name, (None,))[0] if hname == "service" else None
            wrows.append(dict(head=hname, term=t.name, service=t.service, group=t.group, family=t.family,
                              prior_source=h["prior_src"][j] if hname == "service" else h["prior"], prior_mean=float(h["mu"][j]),
                              prior_sd=float(h["sd"][j]), post_mean=post, post_sd=float(np.sqrt(max(h["fit"].cov[j, j], 0))),
                              ci90_lo=float(np.percentile(drh[:, j], 5)), ci90_hi=float(np.percentile(drh[:, j], 95)),
                              sign_constraint={1: ">= 0", -1: "<= 0", 0: "free"}[t.sign], at_bound=t.name in active_terms,
                              m1_mean=m1mu, m2_mean=m2mu,
                              sign_flip_vs_m1=bool(m1mu is not None and abs(m1mu) > 1e-9 and abs(post) > 1e-6 and np.sign(m1mu) != np.sign(post)),
                              sign_flip_vs_m2=bool(m2mu is not None and abs(m2mu) > 1e-9 and abs(post) > 1e-6 and np.sign(m2mu) != np.sign(post)),
                              n_fired_dev=int(fired_dev[j]), n_fired_all=int((Xh[:, j] != 0).sum()), fitted=bool(h.get("fitted", True))))
    for t in D.ABSTAIN:
        wrows.append(dict(head="service", term=t.name, service="*", group="evidence", family=t.family, prior_source="abstain",
                          sign_constraint={1: ">= 0", -1: "<= 0"}[t.sign], n_fired_all=0, fitted=False))
    pd.DataFrame(wrows).to_parquet(HERE / "weights.parquet", index=False)

    # ---- reliability table: agreement (Dawid-Skene, all pairs) vs dev gold weight of evidence (IPW)
    _, W2, res = S["m2_for"](None)
    rel = ds.reliability_rows(res, pf)
    gd = tr.assign(w=tr.w_ipw)
    for k in ds.FAMILIES:
        gd[k] = pf[k].to_numpy()[trow]
    gd["bucket"] = pf.bucket.to_numpy()[trow]
    pooled = []
    for k, nv in ds.FAMILIES.items():
        for g in ["*"]:
            Wk = W2[(k, g)]
            for v in range(nv):
                pooled.append(dict(family=k, value=v, bucket="*", service="*", n_all=float(Wk["n1"][v] + Wk["n0"][v]),
                                   agree_p_v_offers=float(Wk["n1"][v] / Wk["n1"].sum()), agree_p_v_not=float(Wk["n0"][v] / Wk["n0"].sum()),
                                   agree_woe=float(Wk["w"][v]), agree_woe_raw=float(Wk["w_raw"][v])))
    rel = pd.concat([rel, pd.DataFrame(pooled)], ignore_index=True)
    dev_cols = []
    for r in rel.itertuples():
        cell = np.ones(len(gd), bool)
        if r.service != "*":
            cell &= (gd.service == r.service).to_numpy()
        if r.bucket != "*":
            cell &= (gd.bucket == r.bucket).to_numpy()
        sub, alls = gd[cell & (gd[r.family] == r.value).to_numpy()], gd[cell]
        wc, wn = alls[alls.y == 1].w.sum(), alls[alls.y == 0].w.sum()
        pc_, pn_ = (sub[sub.y == 1].w.sum() + 0.25) / (wc + 0.5), (sub[sub.y == 0].w.sum() + 0.25) / (wn + 0.5)
        dev_cols.append(dict(dev_n_conf=int((sub.y == 1).sum()), dev_n_not=int((sub.y == 0).sum()), dev_p_v_conf=pc_, dev_p_v_not=pn_,
                             dev_woe=float(np.log(pc_ / pn_)) if len(alls) else None))
    rel = pd.concat([rel, pd.DataFrame(dev_cols)], axis=1)
    ref = {("N", 1): "nonoffer cue precision v2 34/40; support for nonoffer atoms 6/40",
           ("C", 1): "named-other v3 9/40; cleaning other_facility 17/25; cross-state place 8/14",
           ("C", 2): "named-other v3 9/40; cleaning other_facility 17/25", ("T", 2): "core topic 196/200 (sentence is about the service)",
           ("S", 1): "no hand check (expert)"}
    rel["hand_check_ref"] = [ref.get((f, v)) for f, v in zip(rel.family, rel.value)]
    rel.to_parquet(HERE / "reliability.parquet", index=False)

    # ---- calibration and band record on dev out-of-fold
    dd = tr.assign(w=tr.w_ipw)
    calib = pd.DataFrame(calib_rows(S["p_oof"], dd.reset_index(drop=True), "dev_oof"))
    calib.to_parquet(HERE / "calibration.parquet", index=False)
    band_oof, _ = bands(S["p_oof"], p_l[trow], p_e[trow], pf["T"].to_numpy()[trow], pf.C.to_numpy()[trow], tl, tu)
    br = pd.DataFrame(band_rows(band_oof, dd.reset_index(drop=True), "dev_oof", model_hash, labels_sha))
    br.to_parquet(HERE / "band_record.parquet", index=False)

    # ---- variants for eval: B4 prior-only M1, B5 = M0, M1, M2, ablations (shipped prior and weighting)
    var = pf[["unique_id", "service"]].copy()
    var["p_shipped"] = p_s
    mu1, sd1, _ = priors_vec(terms, "M1@1", m1["service"])
    b4 = prior_projection(len(terms), mu1, sd1, A)
    var["p_B4_prior_only"] = sigmoid(X @ b4.beta)
    var_info = {"B4_prior_only": dict(active_constraints=len(b4.active))}
    kap = split_prior(S["prior"])[1]
    for src_ in ["M0", "M1", "M2"]:
        pc_ = f"{src_}@{kap:g}"  # B5 = M0 at the shipped prior strength; M0 at sd 2.5 is p_M0_sd2.5
        h = service_head(pf, gold, m1["service"], weighting=S["weighting"], prior_choice=pc_, platt_use=None, ds_cache=ds_cache)
        var[f"p_{src_}"] = sigmoid(h["platt"]["a"] * (h["X"] @ h["fit"].beta) + h["platt"]["c"])
        var_info[src_] = dict(prior=pc_, oof_logloss=h["selection_paired"][pc_]["oof_logloss"], platt=[h["platt"]["a"], h["platt"]["c"]])
    h = service_head(pf, gold, m1["service"], weighting=S["weighting"], prior_choice="M0@1", platt_use=None, ds_cache=ds_cache)
    var["p_M0_sd2.5"] = sigmoid(h["platt"]["a"] * (h["X"] @ h["fit"].beta) + h["platt"]["c"])
    var_info["M0_sd2.5"] = dict(prior="M0@1", oof_logloss=h["selection_paired"]["M0@1"]["oof_logloss"], platt=[h["platt"]["a"], h["platt"]["c"]])
    for v in [("noown",), ("noecho",), ("nobucket",), ("nocontext",)]:
        h = service_head(pf, gold, m1["service"], variant=v, weighting=S["weighting"], prior_choice=S["prior"],
                         platt_use=S["platt"]["use"], ds_cache=ds_cache)
        var[f"p_abl_{v[0]}"] = sigmoid(h["platt"]["a"] * (h["X"] @ h["fit"].beta) + h["platt"]["c"])
        var[f"T_abl_{v[0]}"] = pf["T_noown" if v[0] == "noown" else "T_noecho" if v[0] == "noecho" else "T"]
        var[f"C_abl_{v[0]}"] = 0 if v[0] == "noown" else pf.C
        var_info[f"abl_{v[0]}"] = dict(oof_logloss=h["selection_paired"][S["prior"]]["oof_logloss"])
        log("ablation", v[0], var_info[f"abl_{v[0]}"])
    var.to_parquet(HERE / "variant_scores.parquet", index=False)

    # ---- json outputs
    dump(dict(service=dict(use=S["platt"]["use"], a=a, c=c, detail=S["platt"], bootstrap_a_p5_p95=np.percentile(a_b, [5, 95]).tolist(),
                           bootstrap_c_p5_p95=np.percentile(c_b, [5, 95]).tolist()),
              location=Lh["platt"], existence=Eh["platt"]), HERE / "platt.json")
    dump(dict(model_hash=model_hash, labels_sha256=labels_sha, created_at=datetime.datetime.now().isoformat(timespec="seconds"),
              service=dict(weighting=S["weighting"], prior=S["prior"], constant_rate_logloss_in_sample=S["constant_rate_oof_logloss"], candidates=S["selection"], paired_vs_M0=S["selection_paired"],
                           rule="lowest OOF IPW log loss; M0 unless another prior beats it by >= 1 paired SE; weighting chosen by M0's OOF loss",
                           n_train=len(tr), n_pos=int(S["y"].sum()), ess=float(S["w_eval"].sum() ** 2 / (S["w_eval"] ** 2).sum()),
                           folds=5, draw_acceptance=rate, active_constraints=[[terms[j].name for j in np.nonzero(A[i])[0]] for i in fit.active]),
              location=dict(prior=Lh["prior"], fitted=Lh["fitted"], n_train=Lh["n_train"], n_pos=Lh["n_pos"], selection=Lh["selection"],
                            sources=lrows.src.value_counts().to_dict(), draw_acceptance=Lh["draw_rate"]),
              existence=dict(prior=Eh["prior"], fitted=Eh["fitted"], n_train=Eh["n_train"], n_neg=Eh["n_neg"],
                             note="fewer than 15 negatives: existence weights are expert settings, not learned" if not Eh["fitted"] else ""),
              thresholds=dict(t_L=tl, t_U=tu, **tinfo, fallback_used=dict(t_L=tinfo["tl_estimated"] is None, t_U=tinfo["tu_estimated"] is None)),
              variants=var_info, kappa_dev_overlap=overlap_kappa(gold),
              dev_label_status=gold.status.value_counts().to_dict(),
              dropped_dev_rows_in_test_leakage_groups=gold[gold.in_test_group].pair_id.tolist(),
              band_counts_all_pairs=pd.Series(band).value_counts().to_dict()), HERE / "model_selection.json")
    dump(dict(model_hash=model_hash, terms=[t.__dict__ for t in terms], beta=fit.beta.tolist(), platt=[a, c], t_L=tl, t_U=tu,
              location=dict(terms=[t.__dict__ for t in Lh["terms"]], beta=Lh["fit"].beta.tolist(), platt=[Lh["platt"]["a"], Lh["platt"]["c"]]),
              existence=dict(terms=[t.__dict__ for t in Eh["terms"]], beta=Eh["fit"].beta.tolist(), platt=[Eh["platt"]["a"], Eh["platt"]["c"]])),
         HERE / "model.json")
    log("done", model_hash, "bands", pd.Series(band).value_counts().to_dict())


if __name__ == "__main__":
    main()
