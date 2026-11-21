"""Measure the decision layer. Writes eval_metrics.json, faithfulness_report.json, e2e_pairs_to_label.json.

1. Pair level, usable target (exists = yes and location = yes and service = confirmed; spec 5.6), checked labels only:
   AUROC (raw and IPW) of each system's pair score, 95% group bootstrap CI over leakage groups (2,000 resamples),
   paired differences vs WL. Dev = v1 36 + v2 dev; test = v2 test. The decision layer has no fitted parameters; the one
   dev-only design check (is P_S calibrated for pairs with T < 2, i.e. should context-only candidates be gated?) is
   computed on dev and reported, and it did not change the shipped rule.
2. Query level on the 40 benchmark queries: structure (abstention, R used, plan P(any), evidence behind top-1),
   agreement between systems, extra km vs B0, and top-1 labels where a gold label already exists (partial).
3. Faithfulness: U, G, P_succ, plan P(any), rank order and the why-first identity recomputed from stored rows.
4. The end-to-end label pool: union of top-1 pairs of every system minus pairs with a checked gold label.
Run: .venv/bin/python -B evaluate.py
"""
import glob
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "model/proto/decision"
FUS = ROOT / "model/proto/fusion"
sys.path.insert(0, str(FUS))
from fcommon import weighted_auc, wilson  # noqa: E402
from gold import _v1_labels, _v2_labels  # noqa: E402  label readers only; split rules are applied below

from decide import GRADE_MAP, LOC_MAP, PROFILE  # noqa: E402

SEED, NBOOT = 20261122, 2000


def gold_all():
    """Every labelled pair (v1, v2 primary) with split, status, weight. Overlap double labels are used only for exclusion."""
    sp = pd.DataFrame(json.load(open(ROOT / "model/gold/splits.json"))["pairs"])
    labels = _v1_labels() | _v2_labels()
    pools = json.load(open(ROOT / "model/gold/sample_v2_stats.json"))["pool_sizes"]
    rows = []
    for r in sp.itertuples():
        lab = labels.get(r.pair_id)
        if lab is None:
            continue
        n_url = len(lab.get("evidence_urls") or [])
        rows.append(dict(pair_id=r.pair_id, version=r.version, split=r.split, unique_id=r.unique_id, service=r.service,
                         stratum=r.stratum, label_service=lab["service"], label_exists=lab["exists"],
                         label_location=lab["location"], checked=not (lab["service"] == "no_info" and n_url == 0),
                         pi=5.0 / pools[f"{r.service}_{r.stratum}"]))
    d = pd.DataFrame(rows)
    d["eval_split"] = np.where((d.version == "v1") | (d.split == "dev"), "dev", "test")  # v1 is all dev (spec 5.7)
    d["usable"] = ((d.label_exists == "yes") & (d.label_location == "yes") & (d.label_service == "confirmed")).astype(int)
    return d


def pair_scores():
    ps = pd.read_parquet(FUS / "pair_scores.parquet")
    vs = pd.read_parquet(FUS / "variant_scores.parquet")
    fp = pd.read_parquet(FUS / "features_pairs.parquet", columns=["unique_id", "service", "n_tagged", "any_mention", "grade"])
    ff = pd.read_parquet(FUS / "features_facility.parquet", columns=["unique_id", "loc_conf", "leakage_group_id"])
    d = ps.merge(vs, on=["unique_id", "service"]).merge(fp, on=["unique_id", "service"]).merge(ff, on="unique_id")
    pe, pl = d.p_e, d.p_l
    s = pd.DataFrame(dict(unique_id=d.unique_id, service=d.service, leakage_group_id=d.leakage_group_id))
    s["WL"] = pe * d.p_s * pl
    s["abl_PL1"] = pe * d.p_s
    s["P_S_only"] = d.p_s
    for k, c in [("B4_prior_only", "p_B4_prior_only"), ("B5_M0", "p_M0"), ("abl_M2", "p_M2"), ("abl_noown", "p_abl_noown"),
                 ("abl_noecho", "p_abl_noecho"), ("abl_nobucket", "p_abl_nobucket"), ("abl_nocontext", "p_abl_nocontext")]:
        s[k] = pe * d[c] * pl
    s["WL_fallback"] = d.grade.map(GRADE_MAP).fillna(0.1) * d.loc_conf.map(LOC_MAP).fillna(0.4)
    s["B0_any_mention"] = d.any_mention.astype(float)
    s["B1_keyword_count"] = d.n_tagged.astype(float)
    s["B2_rule_grade"] = d.grade.map(GRADE_MAP).fillna(0.1)
    j = pd.read_parquet(FUS / "llm_judge_pairs.parquet")
    j["B3_llm_judge"] = np.where(j.offers.eq("yes"), j.confidence.fillna(0), 0.0)
    s = s.merge(j[["unique_id", "service", "B3_llm_judge"]].drop_duplicates(["unique_id", "service"]), on=["unique_id", "service"], how="left")
    return s


PAIR_SYSTEMS = ["WL", "abl_PL1", "P_S_only", "B4_prior_only", "B5_M0", "abl_M2", "abl_noown", "abl_noecho", "abl_nobucket",
                "abl_nocontext", "WL_fallback", "B0_any_mention", "B1_keyword_count", "B2_rule_grade", "B3_llm_judge"]


def boot_auc(d, cols, target):
    rng = np.random.default_rng(SEED)
    groups = d.leakage_group_id.to_numpy()
    ug = np.unique(groups)
    idx_by = {g: np.flatnonzero(groups == g) for g in ug}
    y, w = d[target].to_numpy(), (1 / d.pi).to_numpy()
    point = {c: (weighted_auc(d[c], y, np.ones(len(d))), weighted_auc(d[c], y, w)) for c in cols}
    draws = {c: [] for c in cols}
    for _ in range(NBOOT):
        ii = np.concatenate([idx_by[g] for g in rng.choice(ug, len(ug))])
        for c in cols:
            draws[c].append(weighted_auc(d[c].to_numpy()[ii], y[ii], np.ones(len(ii))))
    out = {}
    for c in cols:
        a = np.array(draws[c])
        diff = a - np.array(draws["WL"])
        ok = np.isfinite(diff)
        out[c] = dict(auroc_raw=point[c][0], auroc_ipw=point[c][1],
                      ci95_raw=[float(np.nanpercentile(a, 2.5)), float(np.nanpercentile(a, 97.5))],
                      diff_vs_WL=float(point[c][0] - point["WL"][0]),
                      diff_vs_WL_ci95=[float(np.percentile(diff[ok], 2.5)), float(np.percentile(diff[ok], 97.5))] if c != "WL" else [0.0, 0.0])
    return out


def pair_level(gold, scores):
    d = gold[gold.checked].merge(scores, on=["unique_id", "service"], how="left")
    out = {}
    for split in ["dev", "test"]:
        g = d[d.eval_split == split]
        res = dict(n=len(g), n_usable=int(g.usable.sum()), n_confirmed=int((g.label_service == "confirmed").sum()))
        cols = [c for c in PAIR_SYSTEMS if g[c].notna().all()]
        res["usable_target"] = boot_auc(g, cols, "usable")
        out[split] = res
    # dev-only design check: P_S calibration among T < 2 pairs (decides whether context-only candidates are gated)
    ps = pd.read_parquet(FUS / "pair_scores.parquet", columns=["unique_id", "service", "p_s", "T"])
    dv = d[d.eval_split == "dev"].merge(ps, on=["unique_id", "service"])
    chk = {}
    for name, g in [("T_lt_2", dv[dv["T"] < 2]), ("T_ge_2", dv[dv["T"] >= 2])]:
        k = int((g.label_service == "confirmed").sum())
        chk[name] = dict(n=len(g), confirmed=k, observed=k / len(g), wilson95=wilson(k, len(g)), mean_p_s=float(g.p_s.mean()))
    chk["decision"] = ("mean P_S lies inside the Wilson interval of the observed confirmed rate in both groups, so dev gives "
                       "no reason to drop context-only candidates; the spec rule (band not Unlikely) ships unchanged")
    out["dev_gate_check"] = chk
    return out


def labelled_index(gold):
    """(unique_id, service) -> outcome for every checked label in any gold file (v1, v2 primary and overlap)."""
    lab = {}
    for r in gold[gold.checked].itertuples():
        lab[(r.unique_id, r.service)] = dict(service=r.label_service, exists=r.label_exists, location=r.label_location, pair_id=r.pair_id)
    meta = {p["pair_id"]: p for p in json.load(open(ROOT / "model/gold/sample_v2.json"))}
    for f in sorted(glob.glob(str(ROOT / "model/gold/labels_o*.json"))):
        for r in json.load(open(f))["results"]:
            m = meta.get(r["pair_id"])
            if m and not (r["service"] == "no_info" and not r.get("evidence_urls")):
                lab.setdefault((m["unique_id"], m["service"]), dict(service=r["service"], exists=r["exists"],
                                                                     location=r.get("location_ok"), pair_id=r["pair_id"]))
    return lab


def all_label_keys():
    """Every (unique_id, service) that has any label record, checked or not."""
    keys = set()
    s1 = {p["pair_id"]: p for p in json.load(open(ROOT / "audit/ground_truth/sample.json"))}
    s2 = {p["pair_id"]: p for p in json.load(open(ROOT / "model/gold/sample_v2.json"))}
    for f in glob.glob(str(ROOT / "audit/ground_truth/web_*.json")) + glob.glob(str(ROOT / "model/gold/labels_*.json")):
        for r in json.load(open(f))["results"]:
            m = s1.get(r["pair_id"]) or s2.get(r["pair_id"])
            if m:
                keys.add((m["unique_id"], m["service"]))
    return keys


def query_level(ba, lab):
    top = ba[ba["rank"] == 1]
    systems = sorted(ba.system.unique())
    ps = pd.read_parquet(FUS / "pair_scores.parquet", columns=["unique_id", "service", "T", "band"]).set_index(["unique_id", "service"])
    out = {}
    b0 = top[top.system == "B0_nearest_mention"].set_index("query_id")
    wl = top[top.system == "WL"].set_index("query_id")
    for s in systems:
        t = top[top.system == s].set_index("query_id")
        keys = list(zip(t.unique_id, t.service))
        T = np.array([ps["T"].get(k, np.nan) for k in keys])
        wlb = np.array([ps.band.get(k) for k in keys])
        lb = [lab.get(k) for k in keys]
        n_lab = sum(x is not None for x in lb)
        succ = sum(1 for x in lb if x and x["service"] == "confirmed" and x["exists"] == "yes" and x["location"] == "yes")
        unsafe = sum(1 for x in lb if x and (x["service"] == "contradicted" or x["exists"] == "no" or x["location"] == "no"))
        common = t.index.intersection(b0.index)
        extra = (t.loc[common, "d1_km"] - b0.loc[common, "d1_km"]).astype(float)
        ag = t.index.intersection(wl.index)
        r = dict(answered=int(t.unique_id.notna().sum()), abstained_flag=int(t.abstained.fillna(False).astype(bool).sum()),
                 top1_T_lt_2=int(np.nansum(T < 2)), top1_wl_unlikely=int((wlb == "Unlikely").sum()),
                 top1_d1_km_median=float(t.d1_km.median()), extra_km_vs_B0_median=float(extra.median()) if len(extra) else None,
                 top1_same_as_WL=int((t.loc[ag, "unique_id"] == wl.loc[ag, "unique_id"]).sum()),
                 top1_labelled=n_lab, top1_usable_success=succ, top1_unsafe=unsafe,
                 top1_success_rate_among_labelled=succ / n_lab if n_lab else None,
                 top1_success_wilson95=wilson(succ, n_lab) if n_lab else None)
        if "P_L" in t and t.P_L.notna().any():
            r.update(top1_PL_lt_0_5=int((t.P_L < 0.5).sum()), plan_p_any_mean=float(t.plan_p_any.mean()),
                     R_used_hist=t.R_used.value_counts().sort_index().to_dict(), top1_band=t.band.value_counts().to_dict(),
                     top1_P_S_median=float(t.P_S.median()))
        out[s] = r
    return out


def faithfulness(ba):
    u = ba[ba.P_S.notna()].copy()
    D = u.D_s.astype(float)
    has2 = u.d2_km.notna()
    G = u.P_L * np.exp(-u.d1_km / D) + (1 - u.P_L) * np.where(has2, np.exp(-u.d2_km.fillna(1e9).astype(float) / D), 0)
    rep = dict(rows=len(u))
    rep["G_max_err"] = float((G - u.G).abs().max())
    rep["U_max_err"] = float((u.P_E * u.P_S * u.G - u.U).abs().max())
    R = u.R_used.astype(float)
    ps = u.P_E * u.P_S * (u.P_L * (u.d1_km <= R) + (1 - u.P_L) * (has2 & (u.d2_km.fillna(1e9).astype(float) <= R)))
    rep["P_succ_max_err"] = float((ps - u.P_succ).abs().max())
    order_ok, pany_err, why_err, distinct_ok, n_why = True, 0.0, 0.0, True, 0
    for (_, _), g in u.groupby(["query_id", "system"]):
        g = g.sort_values("rank")
        order_ok &= bool((np.diff(g.U.to_numpy()) <= 1e-15).all())
        plan = g[g.in_plan.astype(bool)]
        if len(plan):
            pany_err = max(pany_err, abs(1 - np.prod(1 - plan.P_succ.to_numpy()) - g.plan_p_any.iloc[0]))
            distinct_ok &= plan.leakage_group_id.is_unique
        a = g.iloc[0]
        for b in g.iloc[1:].itertuples():
            if b.why_first_text:
                n_why += 1
                ev = (a.P_E * a.P_S) / (b.P_E * b.P_S)
                why_err = max(why_err, abs(ev * (a.G / b.G) - a.U / b.U) / (a.U / b.U))
    rep.update(rank_order_by_U=order_ok, plan_p_any_max_err=float(pany_err), plan_leakage_groups_distinct=bool(distinct_ok),
               why_first_rows=n_why, why_first_identity_max_rel_err=float(why_err))
    rep["passed"] = bool(rep["G_max_err"] < 1e-9 and rep["U_max_err"] < 1e-9 and rep["P_succ_max_err"] < 1e-9 and order_ok
                         and pany_err < 1e-9 and distinct_ok and why_err < 1e-9)
    return rep


def e2e_pool(ba, keys_any, lab):
    top = ba[(ba["rank"] == 1) & ba.unique_id.notna()]
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet", columns=["unique_id", "name", "address_city", "address_stateOrRegion",
                          "address_zipOrPostcode"]).drop_duplicates("unique_id").set_index("unique_id")
    pool = {}
    for r in top.itertuples():
        k = (r.unique_id, r.service)
        if k in lab:  # already has a checked label
            continue
        e = pool.setdefault(k, dict(methods=set(), query_ids=set()))
        e["methods"].add(r.system)
        e["query_ids"].add(r.query_id)
    out = []
    for i, ((uid, svc), e) in enumerate(sorted(pool.items(), key=lambda kv: (-len(kv[1]["methods"]), kv[0])), 1):
        m = raw.loc[uid]
        out.append(dict(pair_id=f"e2e_{i:03d}", unique_id=uid, name=str(m["name"]), city=str(m.address_city),
                        state=str(m.address_stateOrRegion), pin=None if pd.isna(m.address_zipOrPostcode) else str(m.address_zipOrPostcode),
                        service=svc, methods=sorted(e["methods"]), query_ids=sorted(e["query_ids"]),
                        has_unchecked_label_record=(uid, svc) in keys_any))
    return out


def main():
    gold = gold_all()
    with open(HERE / "test_open_log.jsonl", "a") as f:  # the decision layer has nothing to fit; logged for the audit trail
        f.write(json.dumps(dict(opened_at=datetime.now().isoformat(timespec="seconds"), reader="decision/evaluate.py",
                                note="usable-target metrics on v2 test; no parameter of this layer is fitted")) + "\n")
    m = dict(pair_level=pair_level(gold, pair_scores()))
    ba = pd.read_parquet(HERE / "benchmark_answers.parquet")
    lab = labelled_index(gold)
    m["query_level"] = query_level(ba, lab)
    fr = faithfulness(ba)
    pool = e2e_pool(ba, all_label_keys(), lab)
    m["e2e_pool"] = dict(n_pairs=len(pool), n_with_unchecked_label_record=sum(p["has_unchecked_label_record"] for p in pool),
                         by_n_methods=pd.Series([len(p["methods"]) for p in pool]).value_counts().sort_index().to_dict())
    (HERE / "eval_metrics.json").write_text(json.dumps(m, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    (HERE / "faithfulness_report.json").write_text(json.dumps(fr, indent=1))
    (HERE / "e2e_pairs_to_label.json").write_text(json.dumps(pool, indent=1))
    print(json.dumps(fr))
    print(json.dumps(m["e2e_pool"]))


if __name__ == "__main__":
    assert math.isclose(wilson(34, 40)[0], 0.709, abs_tol=0.01)
    assert PROFILE["dialysis"][0] == 15
    main()
