"""Independent recomputation of stories 1, 2, 3 and 6 from data/plans_raw.json.gz (the planner's own output),
without using plans_best.csv or the analyst's scripts. Also compares against verify/out/rerun_best.parquet
(independent planner re-run) when present.
"""
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.stats.proportion import proportion_confint

H = Path(__file__).resolve().parent.parent
raw = json.load(gzip.open(H / "data/plans_raw.json.gz", "rt"))["runs"]


def ci(k, n):
    lo, hi = proportion_confint(k, n, method="wilson")
    return f"{k}/{n} = {100*k/n:.1f}% ({100*lo:.1f} to {100*hi:.1f})"


rows = []
for x in raw:
    o, r = x["origin"], x["result"]
    d = {"set": o["origin_set"], "oid": o["origin_id"], "pw": x["pathway"]}
    if r["abstain"]:
        d["best"] = "abstain"
    else:
        b = r["plans"][0]
        d.update(best=b["type"], first=b["stops"][0]["eta_minutes"], defn=b["stops"][-1]["eta_minutes"],
                 def_name=b["stops"][-1]["name"], def_id=b["stops"][-1]["facility_id"],
                 pobj=b["totals"].get("p_objective"), pfirst=b["totals"].get("p_first_care"))
        vs = b.get("vs_direct") or {}
        d.update(dmin=vs.get("direct_minutes"), dpfirst=vs.get("direct_p_first_care"), dpobj=vs.get("direct_p_objective"))
        # fastest definitive arrival among all returned plans (best + alternatives)
        d["fastest_def_any_plan"] = min(p["stops"][-1]["eta_minutes"] for p in r["plans"])
    rows.append(d)
df = pd.DataFrame(rows)
print("runs", len(df), "origins", df[["set", "oid"]].drop_duplicates().shape[0])
states = ["Bihar", "Uttar Pradesh", "Maharashtra"]
S3 = df[df.set.isin(states)]

print("\n== Story 1: plan mix ==")
for pw in ["major_trauma", "obstetric_emergency", "burns", "sick_newborn", "stemi", "snakebite"]:
    for s in ["Benchmark (40 queries)"] + states:
        g = df[(df.pw == pw) & (df.set == s)]
        print(pw, s, g.best.value_counts().to_dict())
tr = S3[S3.pw == "major_trauma"]
print("trauma one_stop states:", ci(int((tr.best == "one_stop").sum()), len(tr)))
for pw in ["major_trauma", "obstetric_emergency"]:
    g = df[(df.pw == pw) & (df.best == "one_stop")]
    delta = g.defn - g.dmin
    print(pw, "n", len(g), "mean p_first direct", round(g.dpfirst.mean(), 3), "stop", round(g.pfirst.mean(), 3),
          "mean pobj direct", round(g.dpobj.mean(), 3), "stop", round(g.pobj.mean(), 3),
          "median first", g["first"].median(), "def direct", g.dmin.median(), "def stop", g.defn.median(),
          "median delta", delta.median(), "share delta<=0", round((delta <= 0).mean(), 3))
    rng = np.random.default_rng(1)
    bm = [np.median(rng.choice(delta.values, len(delta))) for _ in range(4000)]
    print("   delta median bootstrap 95%", np.percentile(bm, [2.5, 97.5]))
    print("   direct-plan definitive ETA <= 60 among these:", ci(int((g.dmin <= 60).sum()), len(g)))
st = df[df.pw == "stemi"]
print("stemi best types all", st.best.value_counts().to_dict(), "max defn", st.defn.max())

print("\n== Story 2: within 60 min, state samples ==")
for pw in ["major_trauma", "obstetric_emergency", "stemi", "burns", "sick_newborn"]:
    for s in states:
        g = df[(df.pw == pw) & (df.set == s)]
        print(pw, s, "def<=60", ci(int((g.defn <= 60).sum()), len(g)),
              "| first<=60", ci(int((g["first"] <= 60).sum()), len(g)),
              "| any returned plan def<=60", ci(int((g.fastest_def_any_plan <= 60).sum()), len(g)),
              "| best-direct def<=60", ci(int((g.dmin.fillna(g.defn) <= 60).sum()), len(g)),
              "| median defn (planned)", g.defn.median(), "abstain", int((g.best == "abstain").sum()))

print("\n== Story 6: funnel (state samples, abstain excluded) ==")
for pw in ["obstetric_emergency", "major_trauma", "dialysis_start", "burns", "stemi", "sick_newborn"]:
    for s in states:
        g = df[(df.pw == pw) & (df.set == s) & (df.best != "abstain")]
        vc = g.def_id.value_counts()
        top = g[g.def_id == vc.index[0]].def_name.iloc[0]
        print(pw, s, top, ci(int(vc.iloc[0]), len(g)), "destinations", len(vc))

print("\n== Story 3: three itineraries ==")
for qid, pw in [("q05", "major_trauma"), ("q22", "obstetric_emergency"), ("q20", "dialysis_start")]:
    x = next(x for x in raw if x["origin"]["origin_id"] == qid and x["pathway"] == pw)
    b = x["result"]["plans"][0]
    print(qid, pw, b["type"], {k: v for k, v in b["totals"].items()})
    print("   vs_direct", {k: b["vs_direct"].get(k) for k in ("direct_name", "direct_minutes", "direct_p_objective", "plan_p_objective", "plan_p_first_care")} if b.get("vs_direct") else None)
    for s in b["stops"]:
        print("   ", s["name"], s.get("town"), "eta", s["eta_minutes"], s["eta_low"], s["eta_high"], "p", s["p"],
              "km", s["leg"]["km"], "legmin", s["leg"]["minutes"], s["leg"]["low"], s["leg"]["high"], "flags", s["flags"], s["evidence_ids"][:4])

rb = H / "verify/out/rerun_best.parquet"
if rb.exists():
    rr = pd.read_parquet(rb)
    m = df.merge(rr, left_on=["set", "oid", "pw"], right_on=["origin_set", "origin_id", "pathway"], how="outer", indicator=True)
    print("\n== independent re-run vs plans_raw ==", m._merge.value_counts().to_dict())
    m = m[m._merge == "both"]
    print("best type agree", round((m.best_x == m.best_y).mean(), 4), "def facility agree",
          round((m.def_id_x.fillna("") == m.def_id_y.fillna("")).mean(), 4),
          "def eta abs diff max", np.nanmax(np.abs(m.defn - m.def_eta)))
    dis = m[(m.best_x != m.best_y) | (m.def_id_x.fillna("") != m.def_id_y.fillna(""))]
    print(dis[["set", "oid", "pw", "best_x", "best_y", "def_name_x", "def_name_y"]].to_string())
