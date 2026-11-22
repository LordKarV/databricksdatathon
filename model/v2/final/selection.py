"""Selection on DEV out-of-fold predictions (MODEL_SPEC 3.2 v2 rule), badges, conformal top-k; writes SELECT.md.

Inputs: out/A (run_a.py), out/B_{view} (run_b.py), out/C_{view} (run_c.py), out/PL (run_pl.py), out/labels_{view}.
Order of fit: A < A_platt < B < B_platt < C (C = C1_platt: PU-stage EBM plus a gold Platt step, the analogue of B_platt).
A more-fitted candidate replaces the incumbent only if its OOF log loss is lower by at least one paired cluster SE.
Headline view: cc (confirmed 1 vs contradicted 0). Sensitivity view: sens (MODEL_SPEC 3.2 searched-and-nothing = 0).
Run: python selection.py   -> out/select.json, out/oof_selected.parquet, SELECT.md
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "out"
V2 = HERE.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load("sc_metrics", V2 / "fit_scorecard/metrics.py")       # summary, paired_logloss, wilson (group bootstrap)
EV = _load("a_evaluate", V2 / "fit_prior/evaluate.py")          # platt_oof, thresholds (MODEL_SPEC 3.2 badges)
ORDER = ["A", "A_platt", "B", "B_platt", "C"]
ABLATIONS = ["C3_resid", "C0_gold", "C1_shift", "base_rate"]
URGENCY = {"emergency": ["trauma_care", "emergency_24x7", "emergency_csection", "burn_care", "stemi_thrombolysis", "nicu"],
           "planned": ["dialysis", "mri", "cardiac_surgery"]}
ALPHA = 0.10


def sigmoid(z):
    return 0.5 * (1.0 + np.tanh(0.5 * np.asarray(z, float)))


def load_view(view: str) -> tuple[pd.DataFrame, dict]:
    g = pd.read_parquet(OUT / f"labels_{view}/gold_dev_pairs.parquet")
    g = g[g.y_S.notna()].reset_index(drop=True)
    sc = pd.read_parquet(OUT / "A/scores_A.parquet", columns=["unique_id", "service", "z_S", "P_L", "P_E", "T",
                                                              "operator_public"])
    g = g.merge(sc, on=["unique_id", "service"], how="left", validate="one_to_one")
    assert g.z_S.notna().all()
    y = g.y_S.to_numpy()
    preds = {"A": sigmoid(g.z_S), "A_platt": EV.platt_oof(g.z_S.to_numpy(), y, g.fold5.to_numpy())[0]}
    b = pd.read_parquet(OUT / f"B_{view}/oof.parquet")
    for v in ("B", "B_platt"):
        preds[v] = b[b.variant == v].set_index("pair_id").p_s.reindex(g.pair_id).to_numpy()
    c = pd.read_parquet(OUT / f"C_{view}/ps_oof.parquet")
    for v in ["C1_platt"] + ABLATIONS:
        preds["C" if v == "C1_platt" else v] = c[c.variant == v].set_index("pair_id").p.reindex(g.pair_id).to_numpy()
    for k, p in preds.items():
        assert np.isfinite(p).all() and len(p) == len(g), k
    return g, preds


def kish(w: np.ndarray) -> float:
    return float(w.sum() ** 2 / (w ** 2).sum())


def table(g: pd.DataFrame, preds: dict, names: list) -> dict:
    y, grp = g.y_S.to_numpy(), g.leakage_group_id.to_numpy()
    v3 = (g.version == "v3_dev").to_numpy()
    w = g.ipw.to_numpy()
    out = {}
    for k in names:
        p = preds[k]
        r = M.summary(p, y, grp)
        if k != "A":
            r["minus_A"] = M.paired_logloss(p, preds["A"], y, grp)
        r["ipw_v3"] = {m: M.FUNS[m](p[v3], y[v3], w[v3]) for m in ("log_loss", "auroc", "brier")}
        out[k] = r
    out["_ipw_v3_n"] = dict(n=int(v3.sum()), pos=int(y[v3].sum()), kish_n=round(kish(w[v3]), 1))
    return out


def select(g: pd.DataFrame, preds: dict) -> dict:
    y, grp = g.y_S.to_numpy(), g.leakage_group_id.to_numpy()
    inc, steps = ORDER[0], []
    for cand in ORDER[1:]:
        d = M.paired_logloss(preds[cand], preds[inc], y, grp)
        win = d["diff"] <= -d["cluster_se"]
        steps.append(dict(candidate=cand, incumbent=inc, diff=d["diff"], se=d["cluster_se"], ci95=d["ci95"],
                          replaces=bool(win)))
        if win:
            inc = cand
    return dict(selected=inc, steps=steps)


def by_operator(g: pd.DataFrame, preds: dict, names: list) -> dict:
    y, grp = g.y_S.to_numpy(), g.leakage_group_id.to_numpy()
    res = {}
    for lab, m in [("public", g.operator_public.eq(1).to_numpy()), ("private", g.operator_public.eq(0).to_numpy()),
                   ("unknown", g.operator_public.isna().to_numpy())]:
        r = dict(n=int(m.sum()), confirmed=int(y[m].sum()), contradicted=int((1 - y[m]).sum()))
        if 0 < y[m].sum() < m.sum():
            r["metrics"] = {k: M.summary(preds[k][m], y[m], grp[m]) for k in names}
        res[lab] = r
    return res


def text_only(g: pd.DataFrame) -> np.ndarray:
    """Text-only rule: logistic on 1[T >= 2] fitted on the other four folds (all services pooled)."""
    x, y, f = (g["T"] >= 2).to_numpy(float), g.y_S.to_numpy(), g.fold5.to_numpy()
    p = np.zeros(len(g))
    for k in np.unique(f):
        tr = f != k
        rate = [(y[tr & (x == v)].sum() + 0.5) / ((tr & (x == v)).sum() + 1.0) for v in (0.0, 1.0)]
        p[~tr] = np.where(x[~tr] == 1, rate[1], rate[0])
    return p


def per_service(g: pd.DataFrame, p_sel: np.ndarray, p_txt: np.ndarray) -> list:
    rows = []
    for s, d in g.groupby("service"):
        ix = d.index.to_numpy()
        y, grp = d.y_S.to_numpy(), d.leakage_group_id.to_numpy()
        r = dict(service=s, n=len(ix), confirmed=int(y.sum()), contradicted=int((1 - y).sum()))
        if 0 < y.sum() < len(y):
            pr = M.paired_logloss(p_sel[ix], p_txt[ix], y, grp)
            r.update(ll_selected=M.logloss(p_sel[ix], y), ll_text=M.logloss(p_txt[ix], y), diff=pr["diff"],
                     se=pr["cluster_se"], auroc_selected=M.auroc(p_sel[ix], y), auroc_T=M.auroc(d["T"].to_numpy(float), y),
                     beats_text=bool(pr["diff"] <= -pr["cluster_se"]))
        rows.append(r)
    return rows


def location(g_fac: pd.DataFrame) -> dict:
    """EBM P_L (fold5 OOF, refit on the new facility labels) against the prior location scorecard (A, no fitting)."""
    pl = pd.read_parquet(OUT / "PL/pl_oof_predictions.parquet")
    pl = pl[(pl.cv == "fold5") & (pl.variant == "L_ebm")].reset_index(drop=True)
    a = pd.read_parquet(OUT / "A/facility_contrib_A.parquet", columns=["unique_id", "P_L"])
    pl = pl.merge(a, on="unique_id", how="left", validate="one_to_one")
    y, grp = pl.y_L.to_numpy(), pl.leakage_group_id.to_numpy()
    pe = 1.0 / (1.0 + np.exp(-pl.z.to_numpy()))
    d = M.paired_logloss(pe, pl.P_L.to_numpy(), y, grp)
    return dict(n=len(pl), negatives=int((y == 0).sum()), prior=M.summary(pl.P_L.to_numpy(), y, grp),
                ebm=M.summary(pe, y, grp), ebm_minus_prior=d, ebm_wins=bool(d["diff"] <= -d["cluster_se"]))


def conformal(g: pd.DataFrame, p: np.ndarray) -> dict:
    """Split-conformal k for 'at least one of the top k works' per urgency class, on DEV OOF predictions.

    Pseudo-query = (service, state) among decided DEV pairs with at least one confirmed pair and at least 2 pairs.
    Score = rank (by OOF p, descending, ties broken against the model) of the first confirmed pair. k is the
    ceil((n + 1)(1 - alpha))-th smallest score. Coverage is measured on the same queries (marginal guarantee only);
    random_coverage is the expected coverage at k of a random order.
    """
    d = g.assign(p=p)
    res = {}
    for cls, svcs in URGENCY.items():
        scores, rnd, sizes, n_nopos = [], [], [], 0
        for _, q in d[d.service.isin(svcs)].groupby(["service", "state"]):
            if len(q) < 2:
                continue
            if q.y_S.sum() == 0:
                n_nopos += 1
                continue
            q = q.sort_values(["p", "y_S"], ascending=[False, True])
            scores.append(int(np.argmax(q.y_S.to_numpy() == 1)) + 1)
            sizes.append(len(q))
        n = len(scores)
        if n == 0:
            res[cls] = dict(n_queries=0)
            continue
        level = min(math.ceil((n + 1) * (1 - ALPHA)), n)
        k = int(np.sort(scores)[level - 1])
        cov = int((np.array(scores) <= k).sum())
        rand_cov = []
        for (_, q) in d[d.service.isin(svcs)].groupby(["service", "state"]):
            m, npos = len(q), int(q.y_S.sum())
            if m < 2 or npos == 0:
                continue
            kk = min(k, m)
            rand_cov.append(1 - math.comb(m - npos, kk) / math.comb(m, kk))
        res[cls] = dict(services=svcs, n_queries=n, queries_without_confirmed=n_nopos, alpha=ALPHA, k=k,
                        coverage=cov / n, coverage_k=cov, coverage_wilson95=M.wilson(cov, n),
                        random_order_coverage=float(np.mean(rand_cov)), query_size_median=float(np.median(sizes)),
                        query_size_max=int(max(sizes)))
    return res


def fmt(r: list) -> str:
    return f"{r[0]:.3f} [{r[1]:.3f}, {r[2]:.3f}]"


def md_table(t: dict, names: list) -> list:
    L = ["| candidate | n (pos) | log loss | AUROC | Brier | ECE | LL minus A (cluster SE) | IPW v3 LL / AUROC |",
         "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for k in names:
        r = t[k]
        dd = f"{r['minus_A']['diff']:+.3f} ({r['minus_A']['cluster_se']:.3f})" if "minus_A" in r else "-"
        L.append(f"| {k} | {r['n']} ({r['n_pos']}) | {fmt(r['log_loss'])} | {fmt(r['auroc'])} | {fmt(r['brier'])} | "
                 f"{fmt(r['ece'])} | {dd} | {r['ipw_v3']['log_loss']:.3f} / {r['ipw_v3']['auroc']:.3f} |")
    return L


def main() -> None:
    res = {}
    for view in ("cc", "sens"):
        g, preds = load_view(view)
        res[view] = dict(table=table(g, preds, ORDER + ABLATIONS), selection=select(g, preds))
        if view == "cc":
            gc, pc = g, preds
    sel = res["cc"]["selection"]["selected"]
    res["sens"]["agrees_with_headline"] = res["sens"]["selection"]["selected"] == sel
    res["operator"] = by_operator(gc, pc, ["A", sel] if sel != "A" else ["A", "B_platt"])
    p_txt = text_only(gc)
    res["per_service_text_only"] = per_service(gc, pc[sel], p_txt)
    res["location"] = location(gc)
    res["location_head"] = "EBM_fit_ebm" if res["location"]["ebm_wins"] else "A_prior"
    # badges on DEV OOF: P_L gate uses the shipped location head (prior: no fitting, so OOF = prediction)
    assert res["location_head"] == "A_prior", "EBM P_L would need its OOF values for the gate; not wired"
    elig = ((gc.P_L >= 0.7) & (gc.P_E >= 0.7) & (gc["T"] >= 2)).to_numpy()
    res["thresholds"] = EV.thresholds(pc[sel], gc.y_S.to_numpy(), elig)
    res["conformal"] = conformal(gc, pc[sel])
    if sel == "A_platt":
        res["platt_full"] = EV.platt_full(gc.z_S.to_numpy(), gc.y_S.to_numpy())
    oof = gc[["pair_id", "unique_id", "service", "version", "y_S", "ipw", "leakage_group_id", "fold5", "state",
              "operator_public", "T", "P_L", "P_E", "z_S"]].assign(**{f"p_{k}": v for k, v in pc.items()}, p_text=p_txt)
    oof.to_parquet(OUT / "oof_selected.parquet", index=False)
    json.dump(res, open(OUT / "select.json", "w"), indent=1, default=float)
    write_md(res, sel)
    print(json.dumps(res["cc"]["selection"], indent=1, default=float))
    print("sens", json.dumps(res["sens"]["selection"], indent=1, default=float))


def write_md(res: dict, sel: str) -> None:
    t = res["cc"]["table"]
    L = ["# Model selection on DEV (final refit, v3 labels)", "",
         "All numbers come from selection.py on grouped 5-fold out-of-fold predictions (column fold5, leakage groups).",
         "Labels are agent-labelled, not human-checked. Intervals: 95% group bootstrap over leakage groups (2,000).",
         "TEST facilities and every member of their leakage groups are absent from every training table (asserted in",
         "prep_labels.py, run_b.py and run_c.py). trauma_care PU list rows were dropped; trauma_care trains on v3 gold only.",
         "", f"## Headline: confirmed vs contradicted (n = {t['A']['n']}, {t['A']['n_pos']} confirmed)", ""]
    L += md_table(t, ORDER + ABLATIONS)
    iw = t["_ipw_v3_n"]
    L += ["", f"IPW v3 column: v3 DEV pairs only ({iw['n']} decided, {iw['pos']} confirmed), weighted by 1/pi; "
              f"Kish effective n {iw['kish_n']}. v1/v2 weights are on another frame and e2e has none, so they are not mixed in.",
          "", "Selection steps (replace the incumbent only if LL diff <= -1 cluster SE):", ""]
    for s in res["cc"]["selection"]["steps"]:
        L.append(f"- {s['candidate']} vs {s['incumbent']}: diff {s['diff']:+.4f}, SE {s['se']:.4f}, 95% "
                 f"[{s['ci95'][0]:+.4f}, {s['ci95'][1]:+.4f}] -> {'replaces' if s['replaces'] else 'does not replace'}")
    L += ["", f"**Selected: {sel}.**", ""]
    ts = res["sens"]["table"]
    L += [f"## Sensitivity: MODEL_SPEC 3.2 rule (searched and nothing = 0; n = {ts['A']['n']}, {ts['A']['n_pos']} positive)", ""]
    L += md_table(ts, ORDER + ABLATIONS)
    L += ["", "Selection steps:", ""]
    for s in res["sens"]["selection"]["steps"]:
        L.append(f"- {s['candidate']} vs {s['incumbent']}: diff {s['diff']:+.4f}, SE {s['se']:.4f} -> "
                 f"{'replaces' if s['replaces'] else 'does not replace'}")
    L += ["", f"Sensitivity selects {res['sens']['selection']['selected']} "
              f"({'same as' if res['sens']['agrees_with_headline'] else 'differs from'} the headline).", "",
          "## Public vs private (headline labels)", "",
          "| operator | n | confirmed | contradicted | candidate | log loss | AUROC | Brier | ECE |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for lab, r in res["operator"].items():
        if "metrics" not in r:
            L.append(f"| {lab} | {r['n']} | {r['confirmed']} | {r['contradicted']} | one class only: not run | | | | |")
            continue
        for k, m in r["metrics"].items():
            L.append(f"| {lab} | {r['n']} | {r['confirmed']} | {r['contradicted']} | {k} | {fmt(m['log_loss'])} | "
                     f"{fmt(m['auroc'])} | {fmt(m['brier'])} | {fmt(m['ece'])} |")
    pub = res["operator"]["public"]
    L += ["", f"Public facilities have {pub['contradicted']} contradicted pairs against {pub['confirmed']} confirmed. "
              "With so few negatives the public AUROC interval is too wide to show any ranking ability: the score has no "
              "demonstrated ranking ability for public facilities.", "",
          "## Per service: selected model vs a text-only rule", "",
          "Text-only rule: confirmation rate by 1[T >= 2] fitted on the other four folds. 'beats' = LL diff <= -1 SE.", "",
          "| service | n | conf | contra | LL selected | LL text | diff (SE) | AUROC selected | AUROC of T | beats text |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in res["per_service_text_only"]:
        if "diff" not in r:
            L.append(f"| {r['service']} | {r['n']} | {r['confirmed']} | {r['contradicted']} | one class | | | | | |")
            continue
        L.append(f"| {r['service']} | {r['n']} | {r['confirmed']} | {r['contradicted']} | {r['ll_selected']:.3f} | "
                 f"{r['ll_text']:.3f} | {r['diff']:+.3f} ({r['se']:.3f}) | {r['auroc_selected']:.3f} | "
                 f"{r['auroc_T']:.3f} | {'yes' if r['beats_text'] else 'no'} |")
    nb = sum(r.get("beats_text", False) for r in res["per_service_text_only"])
    L += ["", f"The selected model beats the text-only rule by at least one SE on {nb} of "
              f"{len(res['per_service_text_only'])} services.", ""]
    lo = res["location"]
    L += ["## Location head", "",
          f"{lo['n']} labelled facilities ({lo['negatives']} not at the stated place). Prior scorecard: log loss "
          f"{fmt(lo['prior']['log_loss'])}, AUROC {fmt(lo['prior']['auroc'])}. EBM (fit_pl.py refit, fold5 OOF): log loss "
          f"{fmt(lo['ebm']['log_loss'])}, AUROC {fmt(lo['ebm']['auroc'])}. Paired LL diff "
          f"{lo['ebm_minus_prior']['diff']:+.4f} (SE {lo['ebm_minus_prior']['cluster_se']:.4f}). Shipped: {res['location_head']}.",
          "Existence head: prior-only (decision), expert settings, not learned.", ""]
    th = res["thresholds"]
    L += ["## Badge thresholds (DEV OOF of the selected model)", "",
          f"t_L = {th['t_L']:.4f} ({'fallback' if th['t_L_fallback'] else 'chosen on DEV'}), "
          f"t_U = {th['t_U']:.4f} ({'fallback' if th['t_U_fallback'] else 'chosen on DEV'}). "
          f"LIKELY on DEV: {th['likely']['k_correct']}/{th['likely']['n']} confirmed, Wilson {th['likely']['wilson95']}. "
          f"UNLIKELY on DEV: {th['unlikely']['k_correct']}/{th['unlikely']['n']} contradicted, Wilson {th['unlikely']['wilson95']}.",
          "A fallback applies when fewer than 20 DEV pairs lie beyond a threshold meeting precision 0.85 (t_L) or NPV 0.90 (t_U).", "",
          "## Conformal top-k (alpha 0.10, DEV OOF)", "",
          "| urgency | queries | k | coverage | Wilson 95% | random-order coverage at k | median query size |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for cls, r in res["conformal"].items():
        if r.get("n_queries", 0) == 0:
            L.append(f"| {cls} | 0 | | | | | |")
            continue
        L.append(f"| {cls} | {r['n_queries']} | {r['k']} | {r['coverage']:.3f} | [{r['coverage_wilson95'][0]:.3f}, "
                 f"{r['coverage_wilson95'][1]:.3f}] | {r['random_order_coverage']:.3f} | {r['query_size_median']:.0f} |")
    L += ["", "Pseudo-queries are (service, state) groups of decided DEV pairs with at least one confirmed pair; real queries "
              "rank many more candidates, so k here is a lower bound on what a live query needs. Queries with no confirmed "
              "pair are excluded (counted in select.json).", ""]
    (HERE / "SELECT.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
