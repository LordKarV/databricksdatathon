"""Fusion tests (spec 5.9). Writes tests_report.json and exits non-zero on any failure.

1 additivity: every row of every head, |base + sum(contributions) - z_cal| < 1e-9 and |sigmoid(z_cal) - p| < 1e-12
2 deletion: zero one family with the real design code; the logit change equals minus the displayed contribution
  of that family's terms (1,000 random pairs plus all dev gold pairs; T is zeroed only where C and trunc0 cannot
  change with it, because those terms are defined on T)
3 monotonicity: raising T by one level never lowers z; adding foreign evidence (C) never raises it; turning a
  location vote from -1 to +1 never lowers P_L
4 Wockhardt Hospital Nagpur dialysis and Aravind Eye Hospital (every service) are never Likely
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python tests_fusion.py
"""
import json
import sys

import numpy as np
import pandas as pd

import design as D
from fcommon import HERE, SEED, sigmoid
from gold import load_gold

FAM_TERMS = {"T": {"t1", "t2", "t3", "t4", "t5", "tb_mid", "tb_high", "t2@", "t4@"}, "C": {"c1", "c2"}, "N": {"n1"},
             "S": {"s1"}, "P": {"p1", "p2", "p1@"}}


def in_family(term, fam):
    return term in FAM_TERMS[fam] or any(term.startswith(t) for t in FAM_TERMS[fam] if t.endswith("@"))


def main():
    m = json.load(open(HERE / "model.json"))
    pf = pd.read_parquet(HERE / "features_pairs.parquet")
    ps = pd.read_parquet(HERE / "pair_scores.parquet")
    pc = pd.read_parquet(HERE / "pair_contributions.parquet")
    fs = pd.read_parquet(HERE / "facility_scores.parquet")
    fc = pd.read_parquet(HERE / "facility_contributions.parquet")
    terms = D.service_terms()
    beta, (a, c) = np.array(m["beta"]), m["platt"]
    assert [t.name for t in terms] == [t["name"] for t in m["terms"]]
    rep = {}

    # 1 additivity
    tot = pc.groupby(["unique_id", "service"]).contribution_logit.sum()
    j = ps.set_index(["unique_id", "service"]).join(tot.rename("sum_contrib"))
    err = (j.sum_contrib - j.z_cal).abs()
    perr = (sigmoid(j.z_cal) - j.p_s).abs()
    rep["additivity_service"] = dict(rows=len(j), max_abs_err=float(err.max()), max_prob_err=float(perr.max()),
                                     passed=bool(err.max() < 1e-9 and perr.max() < 1e-12))
    for head, col in (("location", "p_l"), ("existence", "p_e")):
        t = fc[fc["head"] == head].groupby("unique_id").contribution_logit.sum()
        jj = fs.set_index("unique_id").join(t.rename("s"))
        e = (jj.s - jj[f"z_cal_{head}"]).abs()
        pe = (sigmoid(jj[f"z_cal_{head}"]) - jj[col]).abs()
        rep[f"additivity_{head}"] = dict(rows=len(jj), max_abs_err=float(e.max()), max_prob_err=float(pe.max()),
                                         passed=bool(e.max() < 1e-9 and pe.max() < 1e-12))

    # 2 deletion
    rng = np.random.default_rng(SEED)
    gold = load_gold("dev")
    key = {(u, s): i for i, (u, s) in enumerate(zip(pf.unique_id, pf.service))}
    rows = sorted(set(rng.choice(len(pf), 1000, replace=False).tolist()) | {key[(u, s)] for u, s in zip(gold.unique_id, gold.service)})
    sub = pf.iloc[rows].reset_index(drop=True)
    z0 = a * (D.service_X(sub, terms) @ beta) + c
    shown = pc.set_index(["unique_id", "service"])
    dels = {}
    for fam, zero in [("C", 0), ("N", 0), ("S", 0), ("P", 0), ("T", 0)]:
        mod = sub.assign(**{fam: zero})
        ok = np.ones(len(sub), bool)
        if fam == "T":
            ok = (sub.n_rejected == 0).to_numpy() & ~sub.list_truncated.to_numpy(bool)
        z1 = a * (D.service_X(mod, terms) @ beta) + c
        disp = np.zeros(len(sub))
        for i, (u, s) in enumerate(zip(sub.unique_id, sub.service)):
            r = shown.loc[(u, s)]
            r = r if isinstance(r, pd.DataFrame) else r.to_frame().T
            disp[i] = r[[in_family(t, fam) for t in r.term]].contribution_logit.sum()
        err = np.abs((z1 - z0) + disp)[ok]
        dels[fam] = dict(pairs=int(ok.sum()), changed=int((np.abs(disp[ok]) > 0).sum()), max_abs_err=float(err.max()), passed=bool(err.max() < 1e-9))
    rep["deletion"] = dels

    # 3 monotonicity
    T = pf["T"].to_numpy()
    up = pf.assign(T=np.minimum(T + 1, 5), C=np.where(pf.C > 0, np.where(np.minimum(T + 1, 5) >= 2, 1, 2), 0))
    zb = D.service_X(pf, terms) @ beta
    zu = D.service_X(up, terms) @ beta
    cu = pf.assign(C=np.where(pf.C == 0, np.where(T >= 2, 1, 2), pf.C))
    zc = D.service_X(cu, terms) @ beta
    rep["monotone_T"] = dict(pairs=int((T < 5).sum()), min_delta=float((zu - zb)[T < 5].min()), passed=bool((zu - zb)[T < 5].min() >= -1e-12))
    rep["monotone_C"] = dict(pairs=int((pf.C == 0).sum()), max_delta=float((zc - zb)[pf.C.to_numpy() == 0].max()),
                             passed=bool((zc - zb)[pf.C.to_numpy() == 0].max() <= 1e-12))
    lt = {t["name"]: b for t, b in zip(m["location"]["terms"], m["location"]["beta"])}
    rep["monotone_location_votes"] = dict(min_vote_weight=float(min(lt[v] for v in ["v_coords", "v_pin", "v_city", "v_name", "v_state"])),
                                          passed=bool(min(lt[v] for v in ["v_coords", "v_pin", "v_city", "v_name", "v_state"]) >= 0))

    # 4 contaminated records
    w = ps[ps.unique_id.str.startswith("3ac5ae50") & (ps.service == "dialysis")]
    ar = ps[ps.unique_id.str.startswith("b8a5401f")]
    rep["wockhardt_dialysis_not_likely"] = dict(band=w.band.iloc[0], reason=w.band_reason.iloc[0], p_s=float(w.p_s.iloc[0]),
                                                p_l=float(w.p_l.iloc[0]), passed=bool((w.band != "Likely").all()))
    rep["aravind_never_likely"] = dict(bands=dict(zip(ar.service, ar.band)), passed=bool((ar.band != "Likely").all()))
    rep["likely_pairs_total"] = int((ps.band == "Likely").sum())
    rep["note"] = ("Test 4 is weak evidence when few pairs are Likely at all: it holds for every model whose P_S stays below t_L. "
                   "The informative check is which rule blocks each case (band_reason).")
    rep["all_passed"] = all(v["passed"] for k, v in rep.items() if isinstance(v, dict) and "passed" in v) and all(
        v["passed"] for v in dels.values())
    (HERE / "tests_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    sys.exit(0 if rep["all_passed"] else 1)


if __name__ == "__main__":
    main()
