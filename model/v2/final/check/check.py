"""Independent pre-publication check of model/v2/final (items 1-6 of the check task). Fixes nothing.

Run: .venv-viz/bin/python model/v2/final/check/check.py  -> prints PASS/FAIL lines, writes check/out.json.
Reads TEST ids only (model/gold/v3/test_sample.json); never opens any TEST label.
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit, logit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

ROOT = Path("/Users/karthikvattem/projects/datathon")
D2 = ROOT / "derived/v2"
FIN = ROOT / "model/v2/final"
OUT = FIN / "out"
PTS = 20.0 / math.log(2.0)
RES = {}


def report(item, ok, detail):
    RES[item] = dict(ok=bool(ok), detail=detail)
    print(("PASS" if ok else "FAIL"), item, "|", detail, flush=True)


# ---------- 1. TEST overlap ----------
def item1():
    test = pd.DataFrame(json.load(open(ROOT / "model/gold/v3/test_sample.json")))
    lg = (pd.read_parquet(D2 / "facility_features.parquet", columns=["unique_id", "leakage_group_id"])
          .drop_duplicates("unique_id").set_index("unique_id").leakage_group_id)
    tuid = set(test.unique_id)
    tgrp = set(lg.reindex(list(tuid)))
    assert not any(pd.isna(g) for g in tgrp), "TEST facility without leakage group"
    blocked = set(lg[lg.isin(tgrp)].index)
    tables = {}
    for view in ("cc", "sens"):
        for f in ("gold_dev_pairs", "gold_dev_facility", "pu_labels"):
            tables[f"labels_{view}/{f}"] = pd.read_parquet(OUT / f"labels_{view}/{f}.parquet")
    tables["oof_selected (Platt fit rows)"] = pd.read_parquet(OUT / "oof_selected.parquet")
    pl = pd.read_parquet(OUT / "PL/pl_oof_predictions.parquet")
    tables["PL oof (location EBM rows)"] = pl
    gold = tables["labels_cc/gold_dev_pairs"].set_index("pair_id").unique_id
    for v in ("cc", "sens"):
        b = pd.read_parquet(OUT / f"B_{v}/oof.parquet")
        c = pd.read_parquet(OUT / f"C_{v}/ps_oof.parquet")
        for n, d in ((f"B_{v} oof", b), (f"C_{v} oof", c)):
            u = d.pair_id.map(gold) if "unique_id" not in d else d.unique_id
            assert u.notna().all(), n
            tables[n] = pd.DataFrame(dict(unique_id=u))
    # also the gold rows labels.py built before the primary filter
    tables["labels/out/gold_dev_pairs (all rows)"] = pd.read_parquet(ROOT / "model/v2/labels/out/gold_dev_pairs.parquet")
    tables["labels/out/pu_labels"] = pd.read_parquet(ROOT / "model/v2/labels/out/pu_labels.parquet")
    hits = {}
    for n, d in tables.items():
        u = d.unique_id
        hits[n] = dict(rows=len(d), test_fac=int(u.isin(tuid).sum()), test_group=int(u.map(lg).isin(tgrp).sum()),
                       own_lg_col_hit=int(d.leakage_group_id.isin(tgrp).sum()) if "leakage_group_id" in d else None)
    tot = sum(h["test_fac"] + h["test_group"] + (h["own_lg_col_hit"] or 0) for h in hits.values())
    bl = set(pd.read_parquet(ROOT / "model/v2/labels/out/test_blocked_facilities.parquet").unique_id)
    report("1_overlap", tot == 0 and bl == blocked,
           dict(test_pairs=len(test), test_facilities=len(tuid), test_groups=len(tgrp), blocked_facilities=len(blocked),
                blocked_list_matches=bl == blocked, total_hits=tot, tables=hits))


# ---------- 2. no gold TEST verdict / data_point_scores.score in features ----------
def item2():
    dp = pd.read_parquet(ROOT / "derived/v1/data_point_scores.parquet",
                         columns=["dp_type", "unique_id", "service", "score", "score_model", "gold_split"])
    ov = dp[(dp.score - dp.score_model).abs() > 1e-9]
    ff = pd.read_parquet(D2 / "facility_features.parquet")
    at = pd.read_parquet(D2 / "facility_attributes.parquet")
    flags = []
    for typ in ("location", "existence"):
        o = ov[ov.dp_type == typ].drop_duplicates("unique_id").set_index("unique_id")
        y = (o.score > 0.5).astype(int)
        for src, tab in (("facility_features", ff.drop_duplicates("unique_id")), ("facility_attributes", at)):
            t = tab.set_index("unique_id").reindex(o.index)
            for col in t.columns:
                x = pd.to_numeric(t[col], errors="coerce") if t[col].dtype != bool else t[col].astype(float)
                m = x.notna()
                if m.sum() < 10 or y[m].nunique() < 2 or x[m].nunique() < 2:
                    continue
                eq_score = np.isclose(x[m], o.score[m]).mean()
                auc = roc_auc_score(y[m], x[m])
                if eq_score > 0.5 or auc in (0.0, 1.0):
                    flags.append(dict(type=typ, table=src, col=col, n=int(m.sum()), eq_score=float(eq_score), auc=float(auc)))
    # service_claim overrides (pair level) vs pair-level feature columns
    o = ov[ov.dp_type == "service_claim"].drop_duplicates(["unique_id", "service"])
    t = o.merge(ff, on=["unique_id", "service"], how="inner")
    y = (t.score > 0.5).astype(int)
    for col in ff.columns:
        if col in ("unique_id", "service"):
            continue
        x = pd.to_numeric(t[col], errors="coerce")
        m = x.notna()
        if m.sum() < 10 or y[m].nunique() < 2 or x[m].nunique() < 2:
            continue
        auc = roc_auc_score(y[m], x[m])
        if np.isclose(x[m], t.score[m]).mean() > 0.5 or auc in (0.0, 1.0):
            flags.append(dict(type="service_claim", table="facility_features", col=col, n=int(m.sum()), auc=float(auc)))
    bad_cols = [c for c in ff.columns if c in ("c_location_score_v1", "score", "gold_true", "label_service", "y_S")]
    # code that builds or fits: only score_model may be read from data_point_scores
    code = list((ROOT / "model/v2").rglob("*.py")) + [ROOT / "viz/features/build_features.py"]
    code = [p for p in code if "/check/" not in str(p)]
    refs = []
    for p in code:
        s = p.read_text()
        if "data_point_scores" in s:
            refs.append(str(p.relative_to(ROOT)))
        for bad in ("test_labels", "OPENING_LOG"):
            if bad in s:
                refs.append(f"{p.relative_to(ROOT)} mentions {bad}")
    ok = not flags and not bad_cols and refs == ["viz/features/build_features.py"]
    report("2_no_gold_test_or_dps_score", ok,
           dict(overridden_rows=len(ov), overridden_by_split=ov.gold_split.value_counts(dropna=False).to_dict(),
                separating_or_copied_columns=flags, forbidden_feature_columns=bad_cols, code_refs=refs,
                note="build_features.py reads score_model only; c_location_score_v1 is not copied into derived/v2"))


# ---------- 3. recompute selection headline numbers ----------
def ll(p, y):
    p = np.clip(p, 1e-15, 1 - 1e-15)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def ece5(p, y):
    o = np.argsort(p, kind="mergesort")
    return float(sum(len(b) / len(p) * abs(p[b].mean() - y[b].mean()) for b in np.array_split(o, 5)))


def cluster_se(d, g):
    s = pd.Series(d - d.mean()).groupby(g).sum().to_numpy()
    return float(np.sqrt((s ** 2).sum()) / len(d))


def item3():
    sel = json.load(open(OUT / "select.json"))
    o = pd.read_parquet(OUT / "oof_selected.parquet")
    y, g = o.y_S.to_numpy(), o.leakage_group_id.to_numpy()
    # rebuild candidate predictions from the raw files, not from oof_selected
    sA = pd.read_parquet(OUT / "A/scores_A.parquet", columns=["unique_id", "service", "z_S"])
    z = o[["unique_id", "service"]].merge(sA, how="left", validate="one_to_one").z_S.to_numpy()
    pre = {"A": expit(z)}
    pa = np.zeros(len(o))
    for f in np.unique(o.fold5):
        tr = o.fold5.to_numpy() != f
        m = LogisticRegression(C=1e10, max_iter=5000, tol=1e-10).fit(z[tr, None], y[tr])
        pa[~tr] = m.predict_proba(z[~tr, None])[:, 1]
    pre["A_platt"] = pa
    for v in ("B", "B_platt"):
        b = pd.read_parquet(OUT / "B_cc/oof.parquet")
        pre[v] = b[b.variant == v].set_index("pair_id").p_s.reindex(o.pair_id).to_numpy()
    c = pd.read_parquet(OUT / "C_cc/ps_oof.parquet")
    pre["C"] = c[c.variant == "C1_platt"].set_index("pair_id").p.reindex(o.pair_id).to_numpy()
    tab, mism = {}, []
    for k, p in pre.items():
        r = dict(ll=ll(p, y), auroc=float(roc_auc_score(y, p)), brier=float(np.mean((p - y) ** 2)), ece=ece5(p, y))
        theirs = sel["cc"]["table"][k]
        for mk, tk in (("ll", "log_loss"), ("auroc", "auroc"), ("brier", "brier"), ("ece", "ece")):
            t = theirs[tk][0]
            if abs(r[mk] - t) > 0.0015:
                mism.append(f"{k}.{mk} mine {r[mk]:.4f} theirs {t:.4f}")
        r["max_abs_vs_oof_selected"] = float(np.max(np.abs(p - o[f"p_{k}"].to_numpy())))
        tab[k] = r
    steps, inc = [], "A"
    for cand in ["A_platt", "B", "B_platt", "C"]:
        lc = -(y * np.log(pre[cand]) + (1 - y) * np.log(1 - pre[cand]))
        li = -(y * np.log(pre[inc]) + (1 - y) * np.log(1 - pre[inc]))
        d = lc - li
        se = cluster_se(d, g)
        win = d.mean() <= -se
        steps.append(dict(cand=cand, inc=inc, diff=float(d.mean()), se=se, replaces=bool(win)))
        if win:
            inc = cand
    for s, t in zip(steps, sel["cc"]["selection"]["steps"]):
        if s["inc"] != t["incumbent"] or abs(s["diff"] - t["diff"]) > 1e-4 or abs(s["se"] - t["se"]) > 0.002 \
                or s["replaces"] != t["replaces"]:
            mism.append(f"step {s} vs {t}")
    full = LogisticRegression(C=1e10, max_iter=5000, tol=1e-10).fit(z[:, None], y)
    a, cc = float(full.coef_[0, 0]), float(full.intercept_[0])
    if abs(a - sel["platt_full"]["a"]) > 1e-3 or abs(cc - sel["platt_full"]["c"]) > 1e-3:
        mism.append(f"platt_full mine {a:.4f},{cc:.4f}")
    # public / private
    pub = {}
    for lab, m in (("public", o.operator_public.eq(1)), ("private", o.operator_public.eq(0))):
        m = m.to_numpy()
        pub[lab] = dict(n=int(m.sum()), neg=int((y[m] == 0).sum()), auroc_A_platt=float(roc_auc_score(y[m], pa[m])))
    v3 = (o.version == "v3_dev").to_numpy()
    w = o.ipw.to_numpy()[v3]
    kish = float(w.sum() ** 2 / (w ** 2).sum())
    report("3_selection_recomputed", not mism and inc == sel["cc"]["selection"]["selected"],
           dict(n=len(o), pos=int(y.sum()), table=tab, steps=steps, selected=inc, platt_full=dict(a=a, c=cc),
                operator=pub, ipw_v3_n=int(v3.sum()), kish=round(kish, 1), mismatches=mism))


# ---------- 4. contract ----------
def item4():
    s = pd.read_parquet(D2 / "facility_service_scores.parquet")
    tp = pd.read_parquet(ROOT / "model/v2/test_predictions.parquet")
    card = json.load(open(D2 / "model_card.json"))
    svc = json.load(open(ROOT / "kb/taxonomy/services.json"))
    svc_ids = {sv["id"] for cat in svc["categories"] for sv in cat["services"]}
    rt = pd.read_parquet(ROOT / "derived/v1/record_trust.parquet", columns=["unique_id", "trust_level"])
    excl = set(rt[rt.trust_level == "exclude_review"].unique_id)
    fl = set(pd.read_parquet(ROOT / "derived/v1/facility_location.parquet", columns=["unique_id"]).unique_id)
    elig = fl - excl
    d = {}
    d["unique_key"] = bool(not s.duplicated(["unique_id", "service_id"]).any())
    d["n_services"] = int(s.service_id.nunique())
    d["services_match_taxonomy"] = set(s.service_id) == svc_ids
    have = s[s.unique_id.isin(elig)]
    d["eligible_facilities"] = len(elig)
    d["all_eligible_x_36"] = bool(len(have) == len(elig) * 36 and have.groupby("unique_id").size().eq(36).all()
                                  and set(have.unique_id) == elig)
    d["exclude_review_present"] = int(s.unique_id.isin(excl).sum() // 36)
    rng = s[["lo", "p", "hi"]]
    viol = ~((rng.lo >= 0) & (rng.lo <= rng.p) & (rng.p <= rng.hi) & (rng.hi <= 1))
    d["lo_p_hi_violations"] = int(viol.sum())
    d["lo_p_hi_viol_by_band"] = s.band[viol].value_counts().to_dict()
    d["p_minus_hi_max"] = float((s.p - s.hi).max())
    d["lo_minus_p_max"] = float((s.lo - s.p).max())
    smp = s.sample(2000, random_state=20261121)
    err = []
    for r in smp.itertuples():
        items = json.loads(r.contributions)
        err.append(abs(r.base + sum(i["points"] for i in items) / PTS - logit(r.p)))
    d["additivity_max_err_2000"] = float(max(err))
    # all rows: evidence ids resolve; not_observable families contribute 0
    known = set(pd.read_parquet(D2 / "witnesses.parquet", columns=["evidence_id"]).evidence_id.dropna())
    known |= set(pd.read_parquet(D2 / "claim_atoms.parquet", columns=["atom_id"]).atom_id.dropna())
    w = pd.read_parquet(D2 / "witnesses.parquet", columns=["unique_id", "service", "family", "observability"])
    w = w[w.service != "*"]
    obs = w.groupby(["unique_id", "service", "family"]).observability.agg(lambda x: "not_observable"
                                                                         if (x == "not_observable").all() else "other")
    nobs = set(obs[obs == "not_observable"].index)
    n_ids = bad_ids = nobs_nonzero = nobs_checked = 0
    fams = set()
    bad_ex = []
    for r in s[["unique_id", "service_id", "contributions"]].itertuples(index=False):
        for it in json.loads(r.contributions):
            fams.add(it["family"])
            for e in it["evidence_ids"]:
                n_ids += 1
                if e not in known:
                    bad_ids += 1
            if (r.unique_id, r.service_id, it["family"]) in nobs:
                nobs_checked += 1
                if it["points"] != 0:
                    nobs_nonzero += 1
                    if len(bad_ex) < 5:
                        bad_ex.append((r.unique_id, r.service_id, it["label"], it["points"]))
    d["evidence_ids"] = n_ids
    d["evidence_ids_unresolved"] = bad_ids
    d["contribution_families"] = sorted(fams)
    d["not_observable_triples"] = len(nobs)
    d["not_observable_items_in_contributions"] = nobs_checked
    d["not_observable_nonzero"] = nobs_nonzero
    d["not_observable_examples"] = bad_ex
    mv = set(s.model_version)
    d["model_version_unique"] = len(mv) == 1
    d["model_version_matches_card"] = mv == {card["model_version"]}
    d["model_version_matches_test_predictions"] = set(tp.model_version) == mv
    j = tp.merge(s[["unique_id", "service_id", "p", "band"]], on=["unique_id", "service_id"], suffixes=("", "_s"))
    d["test_predictions_match_scores"] = bool(len(j) == 150 and (j.p == j.p_s).all() and (j.band == j.band_s).all())
    d["bands"] = s.band.value_counts().to_dict()
    ok = (d["unique_key"] and d["n_services"] == 36 and d["all_eligible_x_36"] and d["exclude_review_present"] == 0
          and d["lo_p_hi_violations"] == 0 and d["additivity_max_err_2000"] < 1e-9 and bad_ids == 0
          and nobs_nonzero == 0 and d["model_version_unique"] and d["model_version_matches_card"]
          and d["model_version_matches_test_predictions"] and d["test_predictions_match_scores"])
    report("4_contract", ok, d)


# ---------- 5. faithfulness cases ----------
CASES = [("Wockhardt Hospital Nagpur", "3ac5ae50-9ce2-4de3-a13c-d95a4ef218ee", None),
         ("Aravind Eye Hospital Hyderabad", "b8a5401f-42f1-422a-8cd9-686a15b4cb76", None),
         ("Sadar Hospital Gopalganj, Bihar (public dh)", "1abd52f3-879a-4c54-aba6-d59043d9f601", "dialysis")]


def item5():
    s = pd.read_parquet(D2 / "facility_service_scores.parquet")
    out = {}
    for name, uid, only in CASES:
        f = s[s.unique_id == uid]
        rows = f if only else f[f.service_id.isin(["dialysis", "cataract_surgery", "eye_emergency", "emergency_24x7",
                                                   "cardiac_surgery", "icu"])]
        bands = f.band.value_counts().to_dict()
        det = {}
        for r in rows.itertuples():
            items = json.loads(r.contributions)
            det[r.service_id] = dict(p=round(r.p, 3), band=r.band, overlays=list(r.overlays), p_location=round(r.p_location, 3),
                                     p_exists=round(r.p_exists, 3), base_pts=round(r.base * PTS, 1),
                                     contrib=[(i["label"], round(i["points"], 1), len(i["evidence_ids"])) for i in items])
        out[name] = dict(unique_id=uid, bands_all_36=bands, n_likely=int((f.band == "LIKELY").sum()), detail=det)
    print(json.dumps(out, indent=1, default=str))
    RES["5_faithfulness_raw"] = out


def item6():
    h = hashlib.sha256((ROOT / "model/v2/test_predictions.parquet").read_bytes()).hexdigest()
    stored = (ROOT / "model/v2/test_predictions.sha256").read_text().split()[0]
    report("6_sha256", h == stored, dict(computed=h, stored=stored))


if __name__ == "__main__":
    for f in (item1, item2, item3, item4, item5, item6):
        try:
            f()
        except Exception as e:  # report and continue: a crash is a FAIL of that item, not of the run
            report(f.__name__, False, f"crashed: {type(e).__name__}: {e}")
    (Path(__file__).parent / "out.json").write_text(json.dumps(RES, indent=1, default=str))
