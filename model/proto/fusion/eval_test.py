"""Sealed test evaluation of the fusion layer (the only code here that reads test labels). One pass, logged.

Headline set: v2 test pairs (71) with label status "checked"; contract-literal (unchecked no_info counted as 0)
reported alongside. Systems: shipped Witness Ledger, baselines B0 to B5, the M-variants and the ablations.
Intervals: 2,000 group-bootstrap resamples over leakage groups, stratified by (service, stratum) cell; Wilson for
single proportions. Writes test_metrics.json, appends test rows to calibration.parquet and band_record.parquet, and
appends one line to test_open_log.jsonl.
Run: FUSION_SEALED_EVAL=1 /Users/karthikvattem/projects/datathon/.venv/bin/python eval_test.py
"""
import datetime
import json
import os

import numpy as np
import pandas as pd

from fcommon import HERE, SEED, ece, sha256_str, weighted_auc, weighted_logloss, wilson
from gold import case_weights, load_gold
import fit as F

GRADE = {"strong": 0.9, "moderate": 0.6, "weak": 0.3, "tag_only": 0.2}
NBOOT = 2000


def auprc(s, y, w):
    o = np.argsort(-s, kind="stable")
    s, y, w = s[o], y[o], w[o]
    tp = np.cumsum(w * y); fp = np.cumsum(w * (1 - y))
    prec, rec = tp / (tp + fp), tp / max((w * y).sum(), 1e-12)
    return float(np.sum(np.diff(np.concatenate([[0], rec])) * prec))


def metrics(s, y, w, prob):
    out = dict(auroc_ipw=weighted_auc(s, y, w), auroc_raw=weighted_auc(s, y, np.ones(len(y))), auprc_ipw=auprc(s, y, w))
    if prob:
        out.update(brier_ipw=float((w * (s - y) ** 2).sum() / w.sum()), logloss_ipw=float(weighted_logloss(s, y, w).sum() / w.sum()),
                   ece_ipw=ece(s, y, w, 5))
    return out


def boot(df, systems, prob_sys, ref="shipped"):
    rng = np.random.default_rng(SEED)
    g = df.groupby("leakage_group_id").cell.first()
    by_cell = {c: g[g == c].index.to_numpy() for c in g.unique()}
    rows = {gid: np.where(df.leakage_group_id.to_numpy() == gid)[0] for gid in g.index}
    res = {k: [] for k in systems}
    diff = {k: [] for k in systems if k != ref}
    for _ in range(NBOOT):
        pick = np.concatenate([rows[x] for c, ids in by_cell.items() for x in rng.choice(ids, len(ids), replace=True)])
        d = df.iloc[pick]
        y, w = d.y.to_numpy(), d.w.to_numpy()
        if y.min() == y.max():
            continue
        m = {k: metrics(d[k].to_numpy(), y, w, k in prob_sys) for k in systems}
        for k in systems:
            res[k].append(m[k])
            if k != ref:
                diff[k].append(m[ref]["auroc_ipw"] - m[k]["auroc_ipw"])
    ci = {}
    for k, lst in res.items():
        ci[k] = {mk: [float(np.nanpercentile([x[mk] for x in lst], 2.5)), float(np.nanpercentile([x[mk] for x in lst], 97.5))] for mk in lst[0]}
    dci = {k: dict(mean=float(np.nanmean(v)), ci95=[float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))]) for k, v in diff.items()}
    return ci, dci, len(res[ref])


def main():
    assert os.environ.get("FUSION_SEALED_EVAL") == "1", "run with FUSION_SEALED_EVAL=1"
    ps = pd.read_parquet(HERE / "pair_scores.parquet")
    var = pd.read_parquet(HERE / "variant_scores.parquet")
    pf = pd.read_parquet(HERE / "features_pairs.parquet")
    ff = pd.read_parquet(HERE / "features_facility.parquet").set_index("unique_id")
    fs = pd.read_parquet(HERE / "facility_scores.parquet").set_index("unique_id")
    llm = pd.read_parquet(HERE / "llm_judge_pairs.parquet")
    ms = json.load(open(HERE / "model_selection.json"))
    model_hash = ps.model_hash.iloc[0]
    test = load_gold("test")
    labels_sha = sha256_str(test[["pair_id", "label_service", "label_exists", "label_location"]].to_json())
    with open(HERE / "test_open_log.jsonl", "a") as f:
        f.write(json.dumps(dict(opened_at=datetime.datetime.now().isoformat(timespec="seconds"), model_hash=model_hash,
                                labels_sha256=labels_sha, note="sealed evaluation run")) + "\n")
    key = ["unique_id", "service"]
    d = test.merge(ps, on=key, how="left", suffixes=("", "_ps")).merge(var.drop(columns=["p_shipped"]), on=key, how="left").merge(
        pf[key + ["any_mention", "n_tagged", "grade"]], on=key, how="left")
    d = d.merge(llm[["pair_id", "offers", "confidence"]], on="pair_id", how="left")
    d["leakage_group_id"] = d.unique_id.map(ff.leakage_group_id)
    d["cell"] = d.service + "|" + d.stratum
    d["shipped"] = d.p_s
    d["B0_any_mention"] = d.any_mention.astype(float)
    d["B1_keyword_count"] = d.n_tagged.astype(float)
    d["B2_rule_grade"] = d.grade.map(GRADE).fillna(0.1)
    d["B3_llm_judge"] = np.where(d.offers == "yes", d.confidence, np.where(d.offers == "no", 1 - d.confidence, 0.5))
    d["B4_prior_only"] = d.p_B4_prior_only
    d["B5_M0"] = d.p_M0
    d["usable_y"] = ((d.label_exists == "yes") & (d.label_location == "yes") & (d.label_service == "confirmed")).astype(int)
    d["usable_p"] = d.p_s * d.p_l * d.p_e
    systems = ["shipped", "B0_any_mention", "B1_keyword_count", "B2_rule_grade", "B3_llm_judge", "B4_prior_only", "B5_M0",
               "p_M1", "p_M2", "p_M1_k1", "p_M2_k1", "p_abl_noown", "p_abl_noecho", "p_abl_nobucket", "p_abl_nocontext"]
    prob = {s for s in systems if s not in ("B0_any_mention", "B1_keyword_count")}
    out = dict(model_hash=model_hash, labels_sha256=labels_sha, n_test_pairs=len(d), label_status=d.status.value_counts().to_dict(),
               label_counts=d.label_service.value_counts().to_dict(), shipped_prior=ms["service"]["prior"])
    for setname, mask, wfun in [("headline_checked", d.status == "checked", lambda x: case_weights(x)),
                                ("contract_literal_all", pd.Series(True, index=d.index), lambda x: case_weights(x, checked_only=False))]:
        sub = d[mask].copy()
        sub["w"] = wfun(d)[mask].to_numpy()
        y, w = sub.y.to_numpy(), sub.w.to_numpy()
        point = {k: metrics(sub[k].to_numpy(), y, w, k in prob) for k in systems}
        ci, dci, nb = boot(sub, systems, prob)
        out[setname] = dict(n=len(sub), n_pos=int(y.sum()), n_neg=int((1 - y).sum()), ess=float(w.sum() ** 2 / (w ** 2).sum()),
                            point=point, ci95=ci, auroc_ipw_shipped_minus_system=dci, bootstrap_valid=nb)
        if setname == "headline_checked":
            head = sub
    # bands on the headline set: three outcomes, Wilson, weighted
    tl, tu = ms["thresholds"]["t_L"], ms["thresholds"]["t_U"]
    bt = {}
    for name, pl in [("shipped", head.p_l.to_numpy()), ("abl_PL_equals_1", np.ones(len(head)))]:
        band, _ = F.bands(head.p_s.to_numpy(), pl, head.p_e.to_numpy(), head["T"].to_numpy(), head.C.to_numpy(), tl, tu)
        rows = F.band_rows(band, head.reset_index(drop=True), "test", model_hash, labels_sha)
        for r in rows:
            m = band == r["band"]
            ww = head.w.to_numpy()[m]
            yy = head.y.to_numpy()[m]
            r["precision_ipw"] = float(((ww * yy).sum() if r["band"] != "Unlikely" else (ww * (1 - yy)).sum()) / ww.sum()) if m.any() else None
        bt[name] = rows
        bt[name + "_coverage"] = dict(not_unverified=int((band != "Unverified").sum()), n=len(band),
                                      wilson=wilson(int((band != "Unverified").sum()), len(band)))
    out["bands_test"] = bt
    br = pd.read_parquet(HERE / "band_record.parquet")
    pd.concat([br[br.split != "test"], pd.DataFrame(bt["shipped"])], ignore_index=True).to_parquet(HERE / "band_record.parquet", index=False)
    cal = pd.read_parquet(HERE / "calibration.parquet")
    pd.concat([cal[cal.split != "test"], pd.DataFrame(F.calib_rows(head.p_s.to_numpy(), head.reset_index(drop=True), "test"))],
              ignore_index=True).to_parquet(HERE / "calibration.parquet", index=False)
    # secondary target, location head, usable product, subgroups
    sec = head[head.y2.notna()]
    out["secondary_confirmed_vs_contradicted"] = dict(n=len(sec), n_pos=int(sec.y2.sum()),
                                                      auroc_raw=weighted_auc(sec.p_s.to_numpy(), sec.y2.to_numpy().astype(int), np.ones(len(sec))))
    loc = d[d.label_location.isin(["yes", "no"])]
    yl = (loc.label_location == "yes").astype(int).to_numpy()
    out["location_head"] = dict(n=len(loc), n_yes=int(yl.sum()), auroc_raw=weighted_auc(loc.p_l.to_numpy(), yl, np.ones(len(loc))),
                                mean_p_l=float(loc.p_l.mean()), obs_yes=float(yl.mean()),
                                p_l_ge_0_7=dict(n=int((loc.p_l >= 0.7).sum()), yes=int(yl[loc.p_l.to_numpy() >= 0.7].sum())))
    out["usable_product"] = dict(n=len(head), n_pos=int(head.usable_y.sum()),
                                 auroc_raw=weighted_auc(head.usable_p.to_numpy(), head.usable_y.to_numpy(), np.ones(len(head))),
                                 auroc_raw_PL_equals_1=weighted_auc((head.p_s * head.p_e).to_numpy(), head.usable_y.to_numpy(), np.ones(len(head))))
    focus = {"BIHAR", "JHARKHAND", "ODISHA", "ASSAM", "CHHATTISGARH"}
    st = head.unique_id.map(ff.state)
    out["subgroup_focus_states"] = {k: dict(n=int(m.sum()), n_pos=int(head.y[m].sum()),
                                            auroc_raw=weighted_auc(head.p_s[m].to_numpy(), head.y[m].to_numpy(), np.ones(int(m.sum()))))
                                    for k, m in [("focus", st.isin(focus)), ("rest", ~st.isin(focus))]}
    out["llm_judge_on_contaminated"] = None
    out["per_pair"] = head[["pair_id", "service", "stratum", "label_service", "y", "w", "T", "C", "S", "p_s", "p_l", "p_e", "band",
                            "B2_rule_grade", "B3_llm_judge", "offers"]].round(4).to_dict(orient="records")
    (HERE / "test_metrics.json").write_text(json.dumps(out, indent=1, default=float))
    h = out["headline_checked"]
    print("headline n", h["n"], "pos", h["n_pos"], "ess", round(h["ess"], 1))
    for k in systems:
        p, c = h["point"][k], h["ci95"][k]
        print(f"{k:18s} AUROC_ipw {p['auroc_ipw']:.3f} [{c['auroc_ipw'][0]:.3f}, {c['auroc_ipw'][1]:.3f}]  raw {p['auroc_raw']:.3f}"
              + (f"  ECE {p['ece_ipw']:.3f} [{c['ece_ipw'][0]:.3f}, {c['ece_ipw'][1]:.3f}]  Brier {p['brier_ipw']:.3f}" if k in prob else ""))
    print(json.dumps({k: out[k] for k in ["bands_test", "secondary_confirmed_vs_contradicted", "location_head", "usable_product",
                                           "subgroup_focus_states"]}, indent=1, default=float)[:4000])


if __name__ == "__main__":
    main()
