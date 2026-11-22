"""Candidate B: fitted monotone logistic scorecard for P_S (and P_L), evaluated only on gold DEV out of fold.

Run: /Users/karthikvattem/projects/datathon/.venv-viz/bin/python fit.py   (about 30 minutes; writes out/)
Never opens model/gold/v3 TEST labels. Gold DEV comes from model/v2/labels/out (which picks up v3 dev_labels.json on
its own rerun). Every published score is asserted equal to base + sum of named contributions to 1e-9.
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

import core as K
import design as D
import metrics as M
from fcommon import sigmoid  # noqa: E402  (path added by core)

VARIANTS = {  # name: (use PU rows, dropped columns, drop the 9 gold pairs that cite a list site from training, PU weight scale)
    "B": (True, frozenset(), False, 1.0),
    "B_gold_only": (False, frozenset(), False, 1.0),
    "B_no_web": (True, frozenset(D.WEB_COLS), False, 1.0),
    "B_no_k_text_nabh": (True, frozenset({"k_text_nabh"}), False, 1.0),
    "B_no_list_cited_gold": (True, frozenset(), True, 1.0),
    # added after the first smoke run showed B ranking below A_prior (disclosed in FIT.md): PU rows at 1/10 weight
    "B_pu_w0.1": (True, frozenset(), False, 0.1),
}
STATE_CV = ("B", "B_gold_only", "B_pu_w0.1")
T_L_FALLBACK, T_U_FALLBACK, MIN_BEYOND = 0.70, 0.20, 20


def log(*a: object) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def state_folds(gold: pd.DataFrame) -> dict:
    """Greedy balanced assignment of gold states to 5 folds (largest state first, ties by name)."""
    cnt = gold.groupby("state").size().sort_values(ascending=False, kind="stable")
    cnt = cnt.reset_index().sort_values([0, "state"], ascending=[False, True])
    load, out = [0] * 5, {}
    for st, n in zip(cnt.state, cnt[0]):
        k = int(np.argmin(load))
        out[st], load[k] = k, load[k] + n
    return out


class Ctx:
    """Everything loaded once: pairs, terms, gold and PU design matrices."""

    def __init__(self) -> None:
        self.pairs = D.load_pairs()
        self.terms = D.service_terms()
        self.names = [t.name for t in self.terms]
        self.mu = np.array([t.mu for t in self.terms])
        self.sd = np.array([t.sd for t in self.terms])
        self.A = D.service_constraints(self.terms)
        self.c, self.c_raised = K.c_table()
        g = pd.read_parquet(D.LAB / "gold_dev_pairs.parquet")
        g = g[g.y_S.notna()].reset_index(drop=True)
        self.gold = g.merge(self.pairs, on=["unique_id", "service"], how="left", suffixes=("", "_ff"))
        assert len(self.gold) == len(g) and self.gold.a_T.notna().all()
        sf = state_folds(self.gold)
        self.gold["fold_state"] = self.gold.state.map(sf)
        self.state_fold = sf
        self.pu = K.pu_rows(self.pairs, self.c)
        self.pu["fold_state"] = self.pu.state.map(sf).fillna(-1).astype(int)  # states without gold pairs never held out

    def Xg(self, drop: frozenset) -> np.ndarray:
        return K.zero_cols(D.service_X(self.gold, self.terms), self.terms, drop)


def fit_variant(ctx: Ctx, name: str, gold_mask: np.ndarray, pu_mask: np.ndarray) -> dict:
    use_pu, drop, no_cited, pu_scale = VARIANTS[name]
    gm = gold_mask & ~(ctx.gold.gold_cites_list.to_numpy() if no_cited else np.zeros(len(ctx.gold), bool))
    Xg = ctx.Xg(drop)[gm]
    m = ctx.pu[pu_mask] if use_pu else ctx.pu.iloc[:0]
    Xp = K.pu_design(m, ctx.terms, drop) if len(m) else np.zeros((0, len(ctx.terms)))
    data = K.assemble(Xg, ctx.gold.y_S.to_numpy()[gm], Xp, m, pu_scale)
    mu = ctx.mu.copy()
    res = K.fit(data, mu, ctx.sd, ctx.A)
    for i, t in enumerate(ctx.terms):  # a dropped column has no weight (it never enters any score)
        if t.name in drop:
            res["beta"][i] = 0.0
    res["beta"][np.abs(res["beta"]) < 1e-12] = 0.0  # a weight held at its bound is exactly 0, not 1e-17
    res["n_rows"] = int(len(data.y))
    return res


def predict(ctx: Ctx, beta: np.ndarray, drop: frozenset, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    X = ctx.Xg(drop)[rows]
    base, contrib, z = K.contributions(X, beta, ctx.terms)
    return base, contrib, z


def cross_validate(ctx: Ctx, name: str, scheme: str) -> pd.DataFrame:
    """Out-of-fold predictions for every gold pair. scheme: group5 (fold5) or state5 (held-out states)."""
    col = "fold5" if scheme == "group5" else "fold_state"
    gf, pf = ctx.gold[col].to_numpy(), ctx.pu[col].to_numpy()
    drop = VARIANTS[name][1] if name in VARIANTS else frozenset()
    out = []
    for k in range(5):
        test = gf == k
        held = ctx.gold.leakage_group_id[test].unique()
        g_tr = (gf != k) & ~ctx.gold.leakage_group_id.isin(held).to_numpy()
        p_tr = (pf != k) & ~ctx.pu.leakage_group_id.isin(held).to_numpy()  # a chain can span states
        if scheme == "group5":
            assert g_tr.sum() == (gf != k).sum() and p_tr.sum() == (pf != k).sum(), "leakage group spans folds"
        if name == "A_prior":
            beta = ctx.mu.copy()
            info = {}
        else:
            r = fit_variant(ctx, name, g_tr, p_tr)
            beta, info = r["beta"], dict(em_iters=r["em_iters"], converged=r["converged"], n_rows=r["n_rows"],
                                         dropped_gold=int((gf != k).sum() - g_tr.sum()), dropped_pu=int((pf != k).sum() - p_tr.sum()))
        base, contrib, z = predict(ctx, beta, drop, test)
        fam = family_sums(ctx, contrib)
        d = pd.DataFrame(dict(pair_id=ctx.gold.pair_id[test], variant=name, scheme=scheme, fold=k, z=z, p_s=sigmoid(z), base=base))
        out.append(pd.concat([d.reset_index(drop=True), fam.reset_index(drop=True)], axis=1))
        log(name, scheme, "fold", k, info)
    return pd.concat(out, ignore_index=True)


def family_sums(ctx: Ctx, contrib: np.ndarray) -> pd.DataFrame:
    fams = [t.family for t in ctx.terms if t.family not in ("base", "offset")]
    df = pd.DataFrame(contrib, columns=[f"c_{f}" for f in fams])
    return df.T.groupby(level=0).sum().T


def evaluate(ctx: Ctx, oof: pd.DataFrame) -> dict:
    g = ctx.gold.set_index("pair_id")
    res = {}
    for (v, s), d in oof.groupby(["variant", "scheme"]):
        gg = g.loc[d.pair_id]
        y, p, grp = gg.y_S.to_numpy(), d.p_s.to_numpy(), gg.leakage_group_id.to_numpy()
        pub = gg.operator_public.to_numpy()
        r = {"all": M.summary(p, y, grp)}
        for lab, mask in [("public", pub == 1), ("private", pub == 0), ("operator_unknown", np.isnan(pub))]:
            r[lab] = M.summary(p[mask], y[mask], grp[mask])
        iw = gg.ipw.notna().to_numpy()
        w = gg.ipw.to_numpy()[iw]
        r["ipw_v1v2"] = {"n": int(iw.sum()), "log_loss": M.logloss(p[iw], y[iw], w), "auroc": M.auroc(p[iw], y[iw], w),
                         "note": "point only; IPW on v1 and v2 strata (e2e pairs have no inclusion probability)"}
        nc = ~gg.gold_cites_list.to_numpy()
        r["without_9_list_cited"] = {"log_loss": M.logloss(p[nc], y[nc]), "auroc": M.auroc(p[nc], y[nc]), "n": int(nc.sum())}
        res[f"{v}|{s}"] = r
        log("eval", v, s, {k: [round(x, 3) for x in r["all"][k]] for k in ("log_loss", "auroc", "brier", "ece")})
    return res


def paired_vs(ctx: Ctx, oof: pd.DataFrame, ref: str = "A_prior") -> dict:
    g = ctx.gold.set_index("pair_id")
    out = {}
    for s in oof.scheme.unique():
        r = oof[(oof.variant == ref) & (oof.scheme == s)].set_index("pair_id")
        for v in oof[oof.scheme == s].variant.unique():
            if v == ref:
                continue
            d = oof[(oof.variant == v) & (oof.scheme == s)].set_index("pair_id").loc[r.index]
            gg = g.loc[r.index]
            out[f"{v} - {ref}|{s}"] = M.paired_logloss(d.p_s.to_numpy(), r.p_s.to_numpy(), gg.y_S.to_numpy(), gg.leakage_group_id.to_numpy())
    return out


def platt_check(ctx: Ctx, oof: pd.DataFrame, scheme: str) -> tuple[dict, pd.DataFrame]:
    """Cross-fitted Platt on B's out-of-fold z: fit on 4 folds' z, apply to the fifth. Used only if the gain is >= 1 SE.

    Returns the decision and the cross-fitted predictions as variant B_platt (contributions scaled by the fold's a).
    """
    import glm
    d = oof[(oof.variant == "B") & (oof.scheme == scheme)].set_index("pair_id")
    g = ctx.gold.set_index("pair_id").loc[d.index]
    y, z, f = g.y_S.to_numpy(), d.z.to_numpy(), d.fold.to_numpy()
    out = d.copy()
    fam = [c for c in d.columns if c.startswith("c_")]
    for k in range(5):
        a, c = glm.fit_platt(z[f != k], y[f != k], np.ones((f != k).sum()))
        ix = f == k
        out.loc[ix, "z"] = a * z[ix] + c
        out.loc[ix, "base"] = a * d.base.to_numpy()[ix] + c
        out.loc[ix, fam] = a * d.loc[ix, fam].to_numpy()
    out["p_s"] = sigmoid(out.z.to_numpy())
    assert np.max(np.abs(out.base + out[fam].sum(axis=1) - out.z)) < 1e-9
    out["variant"] = "B_platt"
    a_all, c_all = glm.fit_platt(z, y, np.ones(len(z)))
    pr = M.paired_logloss(out.p_s.to_numpy(), d.p_s.to_numpy(), y, g.leakage_group_id.to_numpy())
    gain = -pr["diff"]
    dec = dict(scheme=scheme, a_full=a_all, c_full=c_all, gain=gain, se=pr["cluster_se"], ci95_of_diff=pr["ci95"],
               used=bool(gain >= pr["cluster_se"]), rule="Platt used only when the out-of-fold gain is at least one SE")
    return dec, out.reset_index()


def thresholds(ctx: Ctx, oof: pd.DataFrame, gold_pl: pd.DataFrame, variant: str) -> dict:
    """MODEL_SPEC 3.2 badge thresholds on the primary out-of-fold P_S. Likely gate: T >= 2 and out-of-fold P_L >= 0.7.

    The P_E >= 0.7 gate is not applied: P_E is candidate A's prior-only head and has no out-of-fold values here.
    """
    d = oof[(oof.variant == variant) & (oof.scheme == "group5")].set_index("pair_id")
    g = ctx.gold.set_index("pair_id").loc[d.index]
    pl = g.unique_id.map(gold_pl.set_index("unique_id").p_l_oof).to_numpy()
    y, p = g.y_S.to_numpy(), d.p_s.to_numpy()
    gate = (g.a_T.to_numpy() >= 2) & (pl >= 0.7)
    t_l = None
    for t in np.sort(np.unique(p[gate])):
        sel = gate & (p >= t)
        if sel.sum() >= MIN_BEYOND and y[sel].mean() >= 0.85:
            t_l = float(t)
            break
    t_u = None
    for t in np.sort(np.unique(p))[::-1]:
        sel = p <= t
        if sel.sum() >= MIN_BEYOND and (1 - y[sel]).mean() >= 0.90:
            t_u = float(t)
            break

    def at(t: float, use_gate: bool) -> dict:
        sel = (gate if use_gate else np.ones(len(p), bool)) & (p >= t)
        k, n = int(y[sel].sum()), int(sel.sum())
        return dict(threshold=t, n=n, k=k, precision=k / n if n else None, wilson95=M.wilson(k, n))

    tl = t_l if t_l is not None else T_L_FALLBACK
    tu = t_u if t_u is not None else T_U_FALLBACK
    un = p <= tu
    return dict(t_L=tl, t_L_fallback=t_l is None, t_U=tu, t_U_fallback=t_u is None, gate_n=int(gate.sum()),
                likely_at_t_L=at(tl, True), likely_at_0_70=at(0.70, True), ps_only_at_0_70=at(0.70, False),
                ps_only_at_0_50=at(0.50, False), likely_at_0_50=at(0.50, True),
                unlikely_at_t_U=dict(n=int(un.sum()), k_neg=int((1 - y[un]).sum()),
                                     npv=float((1 - y[un]).mean()) if un.any() else None, wilson95=M.wilson(int((1 - y[un]).sum()), int(un.sum()))),
                note="P_E gate not applied (candidate A prior-only head); P_L gate uses out-of-fold P_L from location.py")


def family_summary(ctx: Ctx, oof: pd.DataFrame, variant: str) -> pd.DataFrame:
    d = oof[(oof.variant == variant) & (oof.scheme == "group5")].set_index("pair_id")
    g = ctx.gold.set_index("pair_id").loc[d.index]
    rows = []
    groups = {"all": np.ones(len(d), bool), "public": g.operator_public.to_numpy() == 1, "private": g.operator_public.to_numpy() == 0}
    for c in [c for c in d.columns if c.startswith("c_")]:
        v = d[c].to_numpy()
        for gn, gm in groups.items():
            y = g.y_S.to_numpy()[gm]
            vv = v[gm]
            rows.append(dict(family=c[2:], group=gn, n=int(gm.sum()), share_nonzero=float((vv != 0).mean()),
                             mean_contrib=float(vv.mean()), mean_abs=float(np.abs(vv).mean()),
                             mean_if_confirmed=float(vv[y == 1].mean()) if (y == 1).any() else None,
                             mean_if_not=float(vv[y == 0].mean()) if (y == 0).any() else None))
    return pd.DataFrame(rows)


def params_table(ctx: Ctx, name: str, res: dict, Xg: np.ndarray, Xp_n: np.ndarray) -> pd.DataFrame:
    beta = res["beta"]
    sd = K.laplace_sd(res)
    t = ctx.terms
    df = pd.DataFrame(dict(variant=name, head="service", term=ctx.names, family=[x.family for x in t], sign=[x.sign for x in t],
                           prior_mean=ctx.mu, prior_sd=ctx.sd, derivation=[x.why for x in t], post_mean=beta, laplace_sd=sd,
                           ci90_lo=beta - 1.645 * sd, ci90_hi=beta + 1.645 * sd, n_fired_gold=(Xg != 0).sum(0), n_fired_pu=Xp_n))
    df["at_bound"] = [x.sign != 0 and abs(b) < 1e-9 for x, b in zip(t, beta)]
    df["dropped"] = [x.name in VARIANTS[name][1] for x in t]
    df["published"] = df.family != "offset"
    return df


def full_grid(ctx: Ctx, beta: np.ndarray, plat: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scores and non-zero contributions for all 358,524 (facility, service) pairs; identity asserted per chunk."""
    names = [t.name for t in ctx.terms if t.family not in ("base", "offset")]
    a, c = (plat["a_full"], plat["c_full"]) if plat["used"] else (1.0, 0.0)
    scores, longs = [], []
    for s in range(0, len(ctx.pairs), 40000):
        chunk = ctx.pairs.iloc[s:s + 40000]
        base, contrib, z = K.contributions(D.service_X(chunk, ctx.terms), beta, ctx.terms)
        zc, basec, cc = a * z + c, a * base + c, a * contrib
        assert np.max(np.abs(basec + cc.sum(1) - zc)) < 1e-9
        scores.append(pd.DataFrame(dict(unique_id=chunk.unique_id.to_numpy(), service=chunk.service.to_numpy(), z=zc, p_s=sigmoid(zc),
                                        base=basec, T=chunk.a_T.to_numpy())))
        nz = np.nonzero(cc)
        longs.append(pd.DataFrame(dict(unique_id=chunk.unique_id.to_numpy()[nz[0]], service=chunk.service.to_numpy()[nz[0]],
                                       term=np.array(names)[nz[1]], contribution_logit=cc[nz], points=cc[nz] * D.PTS)))
    sc, lg = pd.concat(scores, ignore_index=True), pd.concat(longs, ignore_index=True)
    chk = lg.groupby(["unique_id", "service"]).contribution_logit.sum()
    j = sc.set_index(["unique_id", "service"])
    tot = j.base + chk.reindex(j.index).fillna(0.0)
    assert np.max(np.abs(tot.to_numpy() - j.z.to_numpy())) < 1e-9, "stored contributions do not sum to the score"
    return sc, lg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="primary variant only (smoke test)")
    args = ap.parse_args()
    D.OUT.mkdir(exist_ok=True)
    t0 = time.time()
    ctx = Ctx()
    log("gold", len(ctx.gold), "pos", int(ctx.gold.y_S.sum()), "PU rows", len(ctx.pu), "terms", len(ctx.terms))
    names = ["B"] if args.quick else list(VARIANTS)
    oofs = [cross_validate(ctx, "A_prior", "group5"), cross_validate(ctx, "A_prior", "state5")]
    for v in names:
        oofs.append(cross_validate(ctx, v, "group5"))
        if v in STATE_CV:
            oofs.append(cross_validate(ctx, v, "state5"))
    oof = pd.concat(oofs, ignore_index=True)
    plat, pl_rows = platt_check(ctx, oof, "group5")
    plat_s, pl_rows_s = platt_check(ctx, oof, "state5")
    log("platt", plat, plat_s)
    oof = pd.concat([oof, pl_rows, pl_rows_s], ignore_index=True)
    ev = evaluate(ctx, oof)
    pv = paired_vs(ctx, oof)
    import location as L
    loc = L.run(ctx.pairs, ctx.gold[["unique_id", "fold5", "leakage_group_id"]])
    log("P_L", {k: [round(x, 3) for x in v["auroc"]] for k, v in loc["metrics"].items() if "auroc" in v})
    shipped = "B_platt" if plat["used"] else "B"
    thr = {v: thresholds(ctx, oof, loc["gold_pl"], v) for v in ["B", "B_platt", "A_prior", "B_gold_only"] if v in set(oof.variant)}
    thr["shipped"] = shipped
    log("thresholds", thr)
    fam = pd.concat([family_summary(ctx, oof, v).assign(variant=v) for v in ["B", "B_platt", "A_prior"]], ignore_index=True)
    params, prim = [], None
    for v in names:
        r = fit_variant(ctx, v, np.ones(len(ctx.gold), bool), np.ones(len(ctx.pu), bool))
        Xp = K.pu_design(ctx.pu, ctx.terms, VARIANTS[v][1])
        params.append(params_table(ctx, v, r, ctx.Xg(VARIANTS[v][1]), (Xp != 0).sum(0)))
        log("full fit", v, dict(em_iters=r["em_iters"], converged=r["converged"], active=len(r["active"])))
        if v == "B":
            prim = r
    sc, lg = full_grid(ctx, prim["beta"], plat)
    ctx_g = ctx.gold[["pair_id", "unique_id", "service", "y_S", "version", "stratum", "state", "leakage_group_id", "fold5",
                      "fold_state", "operator_public", "a_T", "gold_cites_list", "ipw"]]
    oof.merge(ctx_g, on="pair_id", how="left").to_parquet(D.OUT / "oof_predictions.parquet", index=False)
    pd.concat(params + [loc["params"].assign(variant="B")], ignore_index=True).to_parquet(D.OUT / "params.parquet", index=False)
    sc.to_parquet(D.OUT / "pair_scores.parquet", index=False)
    lg.to_parquet(D.OUT / "pair_contributions.parquet", index=False)
    fam.to_parquet(D.OUT / "family_summary.parquet", index=False)
    loc["scores"].to_parquet(D.OUT / "facility_location_scores.parquet", index=False)
    loc["contrib"].to_parquet(D.OUT / "facility_location_contributions.parquet", index=False)
    loc["oof"].to_parquet(D.OUT / "location_oof.parquet", index=False)
    res = dict(created=time.strftime("%Y-%m-%dT%H:%M:%S"), runtime_s=round(time.time() - t0), n_gold=len(ctx.gold),
               n_gold_pos=int(ctx.gold.y_S.sum()), n_pu_rows=len(ctx.pu), pu_by_family=ctx.pu.groupby("label_family").size().to_dict(),
               c_raised_to_positive_rate=ctx.c_raised, state_folds=ctx.state_fold, metrics=ev, paired_logloss=pv, platt=plat, platt_state5=plat_s,
               thresholds=thr, location=dict(metrics=loc["metrics"], n_labels=loc["n_labels"], n_neg=loc["n_neg"], converged=loc["converged"]),
               full_grid=dict(pairs=len(sc), contribution_rows=len(lg), additivity_tol=1e-9, p_s_quantiles=sc.p_s.quantile([.5, .9, .99]).to_dict()))
    (D.OUT / "results.json").write_text(json.dumps(res, indent=1, default=float))
    log("done", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
