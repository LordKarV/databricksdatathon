"""Independent recomputation of the headline model metrics from raw label files and prototype outputs.

Adversarial statistical review. Reads only; writes results.json next to this file.
Targets (task rule): confirmed = 1, contradicted = 0, no_info = unlabelled (coverage reported separately).
Also reports the spec primary target (confirmed vs not confirmed, no_info = 0) because that is what P_S is trained on.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python -B recompute.py
"""
import glob
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
G = ROOT / "model/gold"
FUS = ROOT / "model/proto/fusion"
DEC = ROOT / "model/proto/decision"
OUT = Path(__file__).resolve().parent
SEED, NBOOT = 20261121, 2000
GRADE = {"strong": 0.9, "moderate": 0.6, "weak": 0.3, "tag_only": 0.2}
STRATUM_ORD = {"no_mention": 0, "suspect": 1, "weak": 2, "strong": 3}


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def auc(s, y, w=None):
    s, y = np.asarray(s, float), np.asarray(y, int)
    w = np.ones(len(s)) if w is None else np.asarray(w, float)
    pos, neg = y == 1, y == 0
    if pos.sum() == 0 or neg.sum() == 0:
        return float("nan")
    sp, sn = s[pos][:, None], s[neg][None, :]
    k = (sp > sn) + 0.5 * (sp == sn)
    return float((k * w[pos][:, None] * w[neg][None, :]).sum() / (w[pos].sum() * w[neg].sum()))


def ece(p, y, w=None, bins=5):
    p, y = np.asarray(p, float), np.asarray(y, float)
    w = np.ones(len(p)) if w is None else np.asarray(w, float)
    o = np.argsort(p, kind="stable")
    tot = 0.0
    for idx in np.array_split(o, bins):
        if len(idx):
            ww = w[idx]
            tot += ww.sum() / w.sum() * abs((ww * y[idx]).sum() / ww.sum() - (ww * p[idx]).sum() / ww.sum())
    return float(tot)


def reliability(p, y, lab, bins=5):
    o = np.argsort(p, kind="stable")
    rows = []
    for b, idx in enumerate(np.array_split(o, bins)):
        k = int(y[idx].sum())
        rows.append(dict(bin=b, n=len(idx), p_min=round(float(p[idx].min()), 3), p_max=round(float(p[idx].max()), 3),
                         mean_p=round(float(p[idx].mean()), 3), observed=round(k / len(idx), 3), wilson95=wilson(k, len(idx)),
                         k_confirmed=int((lab[idx] == "confirmed").sum()), k_contradicted=int((lab[idx] == "contradicted").sum()),
                         k_no_info=int((lab[idx] == "no_info").sum())))
    return rows


def cluster_boot(df, stat, nboot=NBOOT):
    """Group bootstrap over leakage groups, stratified by sampling cell; returns percentile 95% CI and valid count."""
    rng = np.random.default_rng(SEED)
    g = df.groupby("grp").cell.first()
    by_cell = {c: g[g == c].index.to_numpy() for c in g.unique()}
    rows = {k: np.where(df.grp.to_numpy() == k)[0] for k in g.index}
    vals = []
    for _ in range(nboot):
        pick = np.concatenate([rows[x] for ids in by_cell.values() for x in rng.choice(ids, len(ids), replace=True)])
        v = stat(df.iloc[pick])
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            vals.append(v)
    if not vals:
        return dict(ci95=None, valid=0)
    return dict(ci95=[round(float(np.percentile(vals, 2.5)), 4), round(float(np.percentile(vals, 97.5)), 4)], valid=len(vals))


def load_labels(pattern):
    out = {}
    for f in sorted(glob.glob(str(G / pattern))):
        d = json.load(open(f))
        for r in d["results"]:
            out[r["pair_id"]] = dict(r, batch=Path(f).stem)
    return out


def kappa(a, b):
    cats = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return None if pe == 1 else (po - pe) / (1 - pe), po


def kappa_block(prim, over, ids, field):
    a = [prim[i][field] for i in ids]
    b = [over[i][field] for i in ids]
    k, po = kappa(a, b)
    rng = np.random.default_rng(SEED)
    ks = []
    for _ in range(NBOOT):
        s = rng.integers(0, len(ids), len(ids))
        kk, _ = kappa([a[i] for i in s], [b[i] for i in s])
        if kk is not None:
            ks.append(kk)
    tab = pd.crosstab(pd.Series(a, name="primary"), pd.Series(b, name="overlap")).to_dict()
    return dict(n=len(ids), agreement=round(po, 3), kappa=None if k is None else round(k, 3),
                kappa_boot95=[round(float(np.percentile(ks, 2.5)), 3), round(float(np.percentile(ks, 97.5)), 3)] if ks else None,
                crosstab_overlap_by_primary=tab)


def build_pairs():
    sp = pd.DataFrame(json.load(open(G / "splits.json"))["pairs"])
    meta = {p["pair_id"]: p for p in json.load(open(G / "sample_v2.json"))}
    pools = json.load(open(G / "sample_v2_stats.json"))["pool_sizes"]
    prim = load_labels("labels_p*.json")
    d = sp[sp.version == "v2"].copy()
    d["label"] = d.pair_id.map(lambda k: prim[k]["service"])
    d["exists"] = d.pair_id.map(lambda k: prim[k]["exists"])
    d["loc"] = d.pair_id.map(lambda k: prim[k]["location_ok"])
    d["n_urls"] = d.pair_id.map(lambda k: len(prim[k].get("evidence_urls") or []))
    d["lab_conf"] = d.pair_id.map(lambda k: prim[k]["confidence"])
    d["batch"] = d.pair_id.map(lambda k: prim[k]["batch"])
    d["ipw"] = [pools[f"{s}_{t}"] / 5 for s, t in zip(d.service, d.stratum)]
    d["cell"] = d.service + "|" + d.stratum
    d["grp"] = d.group
    key = ["unique_id", "service"]
    ps = pd.read_parquet(FUS / "pair_scores.parquet")[key + ["p_s", "band", "T", "C", "P", "bucket", "p_l", "p_e"]]
    var = pd.read_parquet(FUS / "variant_scores.parquet")[key + ["p_B4_prior_only", "p_M0", "p_M2"]]
    pf = pd.read_parquet(FUS / "features_pairs.parquet")[key + ["any_mention", "n_tagged", "grade", "X"]]
    llm = pd.read_parquet(FUS / "llm_judge_pairs.parquet")[["pair_id", "offers", "confidence"]]
    d = d.merge(ps, on=key, how="left").merge(var, on=key, how="left").merge(pf, on=key, how="left").merge(llm, on="pair_id", how="left")
    d["WL_shipped"] = d.p_s
    d["B0_any_mention"] = d.any_mention.astype(float)
    d["B1_keyword_count"] = d.n_tagged.astype(float)
    d["B2_rule_grade"] = d.grade.map(GRADE).fillna(0.1)
    d["B3_llm_judge"] = np.where(d.offers == "yes", d.confidence, np.where(d.offers == "no", 1 - d.confidence, 0.5))
    d["B4_prior_only"] = d.p_B4_prior_only
    d["B5_M0"] = d.p_M0
    d["stratum_only"] = d.stratum.map(STRATUM_ORD).astype(float)
    d["T_only"] = d["T"].astype(float)
    d["y_task"] = d.label.map({"confirmed": 1, "contradicted": 0})
    d["y_primary"] = (d.label == "confirmed").astype(int)
    d["searched"] = ~((d.label == "no_info") & (d.n_urls == 0))
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet", columns=["unique_id", "source_urls", "capacity", "numberDoctors",
                                                                           "officialWebsite", "facilityTypeId"]).drop_duplicates("unique_id")
    raw["n_src"] = raw.source_urls.map(lambda s: len(json.loads(s)) if isinstance(s, str) and s.startswith("[") else 0)
    raw["has_site"] = raw.officialWebsite.notna() & (raw.officialWebsite.astype(str).str.len() > 4)
    d = d.merge(raw[["unique_id", "n_src", "capacity", "numberDoctors", "has_site", "facilityTypeId"]], on="unique_id", how="left")
    return d, prim


SYSTEMS = ["WL_shipped", "B0_any_mention", "B1_keyword_count", "B2_rule_grade", "B3_llm_judge", "B4_prior_only", "B5_M0", "stratum_only", "T_only"]
PROB = {"WL_shipped", "B2_rule_grade", "B3_llm_judge", "B4_prior_only", "B5_M0"}


def pair_level(t):
    res = {}
    # 1) task target: confirmed vs contradicted, no_info dropped
    lab = t[t.y_task.notna()].copy()
    lab["y"] = lab.y_task.astype(int)
    res["task_target"] = dict(n_test=len(t), n_labelled=len(lab), n_pos=int(lab.y.sum()), n_neg=int((1 - lab.y).sum()),
                              coverage=dict(k=len(lab), n=len(t), wilson95=wilson(len(lab), len(t))),
                              auroc={s: dict(raw=auc(lab[s], lab.y), boot=cluster_boot(lab.assign(y=lab.y), lambda x, s=s: auc(x[s], x.y)))
                                     for s in SYSTEMS},
                              note="with n_neg this small AUROC is the rank of the negatives among the positives, not a population estimate")
    # 2) spec primary target on all test pairs (no_info = 0), raw and IPW
    a = t.assign(y=t.y_primary)
    res["primary_target_all"] = dict(n=len(a), n_pos=int(a.y.sum()), ess_ipw=round(float(a.ipw.sum() ** 2 / (a.ipw ** 2).sum()), 1),
                                     auroc={s: dict(raw=round(auc(a[s], a.y), 4), raw_boot=cluster_boot(a, lambda x, s=s: auc(x[s], x.y)),
                                                    ipw=round(auc(a[s], a.y, a.ipw), 4), ipw_boot=cluster_boot(a, lambda x, s=s: auc(x[s], x.y, x.ipw)))
                                            for s in SYSTEMS})
    # 3) primary target, searched pairs only (drop never-searched no_info)
    b = a[a.searched]
    res["primary_target_searched"] = dict(n=len(b), n_pos=int(b.y.sum()),
                                          auroc={s: dict(raw=round(auc(b[s], b.y), 4), raw_boot=cluster_boot(b, lambda x, s=s: auc(x[s], x.y)),
                                                         ipw=round(auc(b[s], b.y, b.ipw), 4))
                                                 for s in SYSTEMS})
    # paired differences WL - baseline (primary, all test, raw)
    res["paired_diff_raw_primary"] = {s: dict(point=round(auc(a.WL_shipped, a.y) - auc(a[s], a.y), 4),
                                              boot=cluster_boot(a, lambda x, s=s: auc(x.WL_shipped, x.y) - auc(x[s], x.y)))
                                      for s in SYSTEMS if s != "WL_shipped"}
    # within-stratum discrimination (circularity check)
    ws = {}
    for st, g in a.groupby("stratum"):
        ws[st] = dict(n=len(g), confirmed=int((g.label == "confirmed").sum()), contradicted=int((g.label == "contradicted").sum()),
                      no_info=int((g.label == "no_info").sum()),
                      auroc_WL_primary=round(auc(g.WL_shipped, g.y), 3) if 0 < g.y.sum() < len(g) else None,
                      auroc_B2_primary=round(auc(g.B2_rule_grade, g.y), 3) if 0 < g.y.sum() < len(g) else None,
                      mean_p_s=round(float(g.WL_shipped.mean()), 3))
    res["within_stratum_test"] = ws
    # strata-adjusted (Van Elteren-style) within-stratum pooled AUROC: only pairs compared inside a stratum
    def within_auc(x, s):
        num = den = 0.0
        for _, g in x.groupby("stratum"):
            p, n = g[g.y == 1][s].to_numpy(), g[g.y == 0][s].to_numpy()
            if len(p) and len(n):
                num += ((p[:, None] > n[None, :]) + 0.5 * (p[:, None] == n[None, :])).sum()
                den += len(p) * len(n)
        return num / den if den else float("nan")
    res["within_stratum_pooled_auroc_primary"] = {s: dict(point=round(within_auc(a, s), 4), boot=cluster_boot(a, lambda x, s=s: within_auc(x, s)))
                                                   for s in ["WL_shipped", "B2_rule_grade", "B1_keyword_count", "B3_llm_judge", "B4_prior_only", "B5_M0"]}
    # precision at the confirmed threshold
    pr = {}
    for name, m in [("Likely_band", a.band == "Likely"), ("p_s_ge_0.70", a.WL_shipped >= 0.70), ("p_s_ge_0.50", a.WL_shipped >= 0.50),
                    ("B2_strong_0.9", a.B2_rule_grade >= 0.9), ("B3_yes_conf_ge_0.8", a.B3_llm_judge >= 0.8), ("B0_any_mention", a.B0_any_mention >= 1)]:
        g = a[m]
        k, c = int((g.label == "confirmed").sum()), int((g.label == "contradicted").sum())
        pr[name] = dict(N_called=len(g), k_confirmed=k, k_contradicted=c, k_no_info=len(g) - k - c,
                        precision_task=None if k + c == 0 else round(k / (k + c), 3), wilson95_task=wilson(k, k + c),
                        confirmed_share_of_called=None if not len(g) else round(k / len(g), 3), wilson95_confirmed_share=wilson(k, len(g)))
    res["precision_at_threshold"] = pr
    # calibration of P_S against the target it is trained on (primary) and against task target
    res["calibration_primary_all"] = dict(ece_raw=round(ece(a.WL_shipped, a.y), 4), ece_raw_boot=cluster_boot(a, lambda x: ece(x.WL_shipped, x.y)),
                                          ece_ipw=round(ece(a.WL_shipped, a.y, a.ipw), 4), ece_ipw_boot=cluster_boot(a, lambda x: ece(x.WL_shipped, x.y, x.ipw)),
                                          mean_p=round(float(a.WL_shipped.mean()), 4), obs=round(float(a.y.mean()), 4),
                                          table=reliability(a.WL_shipped.to_numpy(), a.y.to_numpy(), a.label.to_numpy()))
    res["calibration_primary_searched"] = dict(ece_raw=round(ece(b.WL_shipped, b.y), 4), ece_raw_boot=cluster_boot(b, lambda x: ece(x.WL_shipped, x.y)),
                                               ece_ipw=round(ece(b.WL_shipped, b.y, b.ipw), 4),
                                               table=reliability(b.WL_shipped.to_numpy(), b.y.to_numpy(), b.label.to_numpy()))
    res["calibration_task_labelled"] = dict(n=len(lab), ece_raw=round(ece(lab.WL_shipped, lab.y), 4), mean_p=round(float(lab.WL_shipped.mean()), 4),
                                            obs=round(float(lab.y.mean()), 4),
                                            table=reliability(lab.WL_shipped.to_numpy(), lab.y.to_numpy(), lab.label.to_numpy(), bins=min(5, len(lab))))
    res["bands_test"] = a.band.value_counts().to_dict()
    return res


def visibility(v2):
    """Web-visibility bias on all 140 v2 labels (descriptive of the labels, not of the model)."""
    out = {}
    q = v2.n_src.quantile([1 / 3, 2 / 3]).to_numpy()
    v2 = v2.assign(src_tercile=np.digitize(v2.n_src, q))
    for col in ["src_tercile", "has_site", "stratum", "service", "batch"]:
        tab = {}
        for k, g in v2.groupby(col):
            n = len(g)
            c = int((g.label == "confirmed").sum())
            tab[str(k)] = dict(n=n, confirmed=c, contradicted=int((g.label == "contradicted").sum()), no_info=int((g.label == "no_info").sum()),
                               never_searched=int((~g.searched).sum()), confirmed_rate=round(c / n, 3), wilson95=wilson(c, n))
        out[col] = tab
    out["src_tercile_cuts"] = q.tolist()
    # within strong stratum only: visibility vs confirmation, searched pairs
    s = v2[(v2.stratum == "strong") & v2.searched]
    out["strong_searched_auc_nsrc_predicts_confirmed"] = dict(n=len(s), n_pos=int(s.y_primary.sum()), auc=round(auc(s.n_src, s.y_primary), 3))
    out["searched_auc_nsrc_predicts_confirmed"] = dict(n=int(v2.searched.sum()), auc=round(auc(v2[v2.searched].n_src, v2[v2.searched].y_primary), 3))
    # position within batch (search budget ran out mid-batch)
    v2 = v2.assign(pos=v2.groupby("batch").cumcount())
    out["never_searched_by_batch_half"] = {h: dict(n=len(g), never_searched=int((~g.searched).sum()))
                                           for h, g in v2.assign(half=np.where(v2.pos < 10, "first10", "last10")).groupby("half")}
    return out


def kappa_all(prim):
    over = load_labels("labels_o*.json")
    sp = {p["pair_id"]: p["split"] for p in json.load(open(G / "splits.json"))["pairs"]}
    ids = sorted(i for i in over if i in prim)
    res = {"all": {f: kappa_block(prim, over, ids, f) for f in ["service", "exists", "location_ok"]}}
    for split in ["dev", "test"]:
        sub = [i for i in ids if sp[i] == split]
        res[split] = {f: kappa_block(prim, over, sub, f) for f in ["service", "exists", "location_ok"]}
    both = [i for i in ids if (prim[i].get("evidence_urls") or []) and (over[i].get("evidence_urls") or [])]
    res["both_searched"] = {f: kappa_block(prim, over, both, f) for f in ["service", "exists", "location_ok"]}
    # task-relevant: among pairs both labelled confirmed/contradicted, how often do they disagree on the sign
    sign = [(prim[i]["service"], over[i]["service"]) for i in ids if prim[i]["service"] != "no_info" and over[i]["service"] != "no_info"]
    res["both_decisive_service"] = dict(n=len(sign), agree=sum(a == b for a, b in sign), pairs=sign)
    res["primary_decisive_overlap_no_info"] = sum(1 for i in ids if prim[i]["service"] != "no_info" and over[i]["service"] == "no_info")
    res["overlap_decisive_primary_no_info"] = sum(1 for i in ids if prim[i]["service"] == "no_info" and over[i]["service"] != "no_info")
    return res


def e2e():
    ba = pd.read_parquet(DEC / "benchmark_answers.parquet")
    to = pd.DataFrame(json.load(open(DEC / "e2e_pairs_to_label.json")))
    lab = load_labels("labels_e*.json")
    not_run = set()
    for f in glob.glob(str(G / "labels_e*.json")):
        not_run |= set(json.load(open(f)).get("not_run", []))
    to["label"] = to.pair_id.map(lambda k: lab[k]["service"] if k in lab else None)
    to["exists"] = to.pair_id.map(lambda k: lab[k]["exists"] if k in lab else None)
    to["loc"] = to.pair_id.map(lambda k: lab[k]["location_ok"] if k in lab else None)
    to["conf"] = to.pair_id.map(lambda k: lab[k]["confidence"] if k in lab else None)
    to["n_urls"] = to.pair_id.map(lambda k: len(lab[k].get("evidence_urls") or []) if k in lab else 0)
    to["batch"] = to.pair_id.map(lambda k: lab[k]["batch"] if k in lab else "not_run")
    top = ba[ba["rank"] == 1][["query_id", "system", "unique_id", "service", "band", "abstained", "d1_km"]]
    m = top.merge(to[["unique_id", "service", "pair_id", "label", "exists", "loc", "conf", "n_urls", "batch"]], on=["unique_id", "service"], how="left")
    out = {"n_pairs_to_label": len(to), "n_labelled": int(to.label.notna().sum()), "n_not_run": len(not_run),
           "labelled_no_urls": int(((to.label.notna()) & (to.n_urls == 0)).sum()),
           "label_counts": to.label.value_counts(dropna=False).to_dict(), "per_system": {}}
    for sysname, g in m.groupby("system"):
        n_q = 40  # spec 9.2: every benchmark query is in the denominator; no top-1 or unjudged = not verified
        labd = g[g.label.notna()]
        k = int((labd.label == "confirmed").sum())
        c = int((labd.label == "contradicted").sum())
        usable = int(((labd.label == "confirmed") & (labd.exists == "yes") & (labd["loc"] == "yes")).sum())
        unsafe = int(((labd.label == "contradicted") | (labd.exists == "no") | (labd["loc"] == "no")).sum())
        out["per_system"][sysname] = dict(
            queries_with_top1=g.query_id.nunique(), top1_with_label=len(labd), top1_unlabelled=int(g.label.isna().sum()),
            confirmed=k, contradicted=c, no_info=len(labd) - k - c,
            precision1_task=None if k + c == 0 else round(k / (k + c), 3), wilson95_task=wilson(k, k + c),
            confirmed_share_of_40=round(k / n_q, 3), wilson95_confirmed_share_of_40=wilson(k, n_q),
            usable_success_of_40=usable, wilson95_usable_of_40=wilson(usable, n_q),
            unsafe_of_40=unsafe, wilson95_unsafe_of_40=wilson(unsafe, n_q),
            abstained_flag=int(g.abstained.fillna(False).astype(bool).sum()))
    # paired WL vs B0 on queries where both top-1 carry a decisive label
    piv = m.pivot_table(index="query_id", columns="system", values="label", aggfunc="first")
    pair = {}
    for b in ["B0_nearest_mention", "B1_keyword_count", "B2_rule_grade", "B3_llm_judge", "B4_prior_only", "WL_fallback", "WLpost_T2gate"]:
        if b in piv and "WL" in piv:
            both = piv[["WL", b]].dropna()
            dec = both[both.isin(["confirmed", "contradicted"]).all(axis=1)]
            wl_only = int(((dec.WL == "confirmed") & (dec[b] != "confirmed")).sum())
            b_only = int(((dec.WL != "confirmed") & (dec[b] == "confirmed")).sum())
            nd = wl_only + b_only
            p = 1.0 if nd == 0 else min(1.0, 2 * sum(math.comb(nd, i) for i in range(0, min(wl_only, b_only) + 1)) / 2 ** nd)
            pair[b] = dict(queries_both_labelled=len(both), queries_both_decisive=len(dec), wl_confirmed_only=wl_only,
                           base_confirmed_only=b_only, mcnemar_exact_p=round(p, 4))
    out["paired_vs_WL"] = pair
    conf = (piv == "confirmed").reindex(sorted(set(top.query_id)), fill_value=False)
    allq = {}
    for b in conf.columns:
        if b == "WL":
            continue
        wl_only, b_only = int((conf.WL & ~conf[b]).sum()), int((~conf.WL & conf[b]).sum())
        nd = wl_only + b_only
        p = 1.0 if nd == 0 else min(1.0, 2 * sum(math.comb(nd, i) for i in range(0, min(wl_only, b_only) + 1)) / 2 ** nd)
        allq[b] = dict(wl_confirmed_only=wl_only, base_confirmed_only=b_only, mcnemar_exact_p=round(p, 4))
    out["paired_vs_WL_all40_unlabelled_as_not_confirmed"] = allq
    to_c = to[to.label == "contradicted"]
    out["contradicted_labels_without_url"] = dict(n_contradicted=len(to_c), no_url=int((to_c.n_urls == 0).sum()))
    ident = top.pivot_table(index="query_id", columns="system", values="unique_id", aggfunc="first")
    out["top1_identical_to_WL"] = {s: int((ident[s] == ident["WL"]).sum()) for s in ident.columns if s != "WL"}
    # how the e2e labels were produced
    out["labels_by_batch_and_urls"] = to.groupby("batch").apply(lambda g: dict(n=len(g), no_urls=int((g.n_urls == 0).sum()),
                                                                               low_conf=int((g.conf == "low").sum()),
                                                                               confirmed=int((g.label == "confirmed").sum()),
                                                                               contradicted=int((g.label == "contradicted").sum()))).to_dict()
    return out


def main():
    d, prim = build_pairs()
    test = d[d.split == "test"].reset_index(drop=True)
    res = {"inputs": dict(n_v2=len(d), n_test=len(test), n_dev=int((d.split == "dev").sum()),
                          test_label_counts=test.label.value_counts().to_dict(), dev_label_counts=d[d.split == "dev"].label.value_counts().to_dict(),
                          test_never_searched=int((~test.searched).sum()), model_hash=str(pd.read_parquet(FUS / "pair_scores.parquet").model_hash.iloc[0]))}
    # leakage: dev/test facility and group overlap
    sp = pd.DataFrame(json.load(open(G / "splits.json"))["pairs"])
    ff = pd.read_parquet(FUS / "features_facility.parquet")[["unique_id", "leakage_group_id"]]
    sp = sp.merge(ff, on="unique_id", how="left")
    tr = sp[(sp.version == "v1") | (sp.split == "dev")]
    te = sp[(sp.version == "v2") & (sp.split == "test")]
    res["leakage"] = dict(train_test_shared_unique_ids=sorted(set(tr.unique_id) & set(te.unique_id)),
                          train_test_shared_leakage_groups=len(set(tr.leakage_group_id) & set(te.leakage_group_id)),
                          v1_test_pairs_used_as_training=int(((sp.version == "v1") & (sp.split == "test")).sum()))
    res["pair_level_test"] = pair_level(test)
    res["visibility_bias_all_v2"] = visibility(d)
    res["kappa"] = kappa_all(prim)
    res["e2e_benchmark"] = e2e()
    # global band distribution of the shipped model
    res["band_counts_all_pairs"] = pd.read_parquet(FUS / "pair_scores.parquet").band.value_counts().to_dict()
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=lambda o: None if isinstance(o, float) and math.isnan(o) else str(o)))
    test[["pair_id", "service", "stratum", "label", "searched", "n_urls", "ipw", "WL_shipped", "band", "T", "C", "P", "B2_rule_grade",
          "B3_llm_judge", "n_src", "has_site"]].to_csv(OUT / "test_pairs_scored.csv", index=False)
    print(json.dumps(res["inputs"]))


if __name__ == "__main__":
    # self-check of the metric helpers
    assert auc([3, 2, 1], [1, 0, 0]) == 1.0 and auc([1, 2], [1, 0]) == 0.0
    assert abs(ece([0.2, 0.2, 0.8, 0.8], [0, 0, 1, 1], bins=2) - 0.2) < 1e-12
    assert wilson(34, 40)[0] == 0.7092 or abs(wilson(34, 40)[0] - 0.71) < 0.01
    main()
