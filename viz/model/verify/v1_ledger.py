"""Independent recomputation of story 1 (witness ledger cases). Model outputs only, no labels.

Run: .venv-viz/bin/python viz/model/verify/v1_ledger.py
Does not import the analyst's s1_ledger.py or _inputs.family(); groups terms with its own rules.
"""
import json
import math
from pathlib import Path

import pandas as pd

R = Path("/Users/karthikvattem/projects/datathon")
F = R / "model/proto/fusion"
K = 20 / math.log(2)
CASES = {"S1": "acde9be7-1859-4c30-a5aa-71f18a4f590e", "U1": "830706f4-456c-4a54-8ab3-e9a730f3c531",
         "C1": "3ac5ae50-9ce2-4de3-a13c-d95a4ef218ee"}
SVC = {"S1": "dialysis", "U1": "emergency_csection", "C1": "dialysis"}


def fam(term, group):
    root = term.split("@")[0]
    if group == "base":
        return "base"
    if root[:1] == "t" and root[1:].isdigit() or root in ("tb_mid", "tb_high", "trunc0"):
        return "text"
    if root in ("p1", "p2"):
        return "hints"
    if root in ("c1", "c2", "n1", "s1"):
        return "flags"
    if root in ("g_mid", "g_high"):
        return "web"
    assert group == "context", (term, group)
    return "type_size"


sig = lambda z: 1 / (1 + math.exp(-z))  # noqa: E731
pc = pd.read_parquet(F / "pair_contributions.parquet")
ps = pd.read_parquet(F / "pair_scores.parquet")
fc = pd.read_parquet(F / "facility_contributions.parquet")
fs = pd.read_parquet(F / "facility_scores.parquet").set_index("unique_id")
vs = pd.read_parquet(F / "variant_scores.parquet").set_index(["unique_id", "service"])
cases = {c["case"]: c for c in json.loads((R / "model/review/explain/cases.json").read_text())}
platt = json.loads((F / "platt.json").read_text())["service"]

# points column is (20/ln2) * contribution_logit everywhere
assert (pc.points - K * pc.contribution_logit).abs().max() < 1e-9
print("bands over all pairs:", ps.band.value_counts().to_dict())
lk = ps[ps.band == "Likely"]
print("Likely pairs:", lk[["name", "service", "p_s", "T"]].to_dict("records"))

for cid, uid in CASES.items():
    s = SVC[cid]
    d = pc[(pc.unique_id == uid) & (pc.service == s) & (pc["head"] == "service")]
    d = d.assign(f=[fam(t, g) for t, g in zip(d.term, d.group)])
    by = d.groupby("f").points.sum().round(2).to_dict()
    tot = d.points.sum()
    row = ps[(ps.unique_id == uid) & (ps.service == s)].iloc[0]
    assert abs(tot / K - row.z_cal) < 1e-9 and abs(sig(tot / K) - row.p_s) < 1e-12
    # z_cal = a * z_raw + c
    assert abs(platt["a"] * row.z_raw + platt["c"] - row.z_cal) < 1e-9
    nz = d[d.points.abs() > 0.005][["term", "x_value", "points"]].round(2).values.tolist()
    print(f"\n{cid} {row['name']} {s}: total {tot:.2f} pts, P_S {row.p_s:.4f} [{row.p_s_lo:.2f},{row.p_s_hi:.2f}] "
          f"band {row.band} T {row['T']} C {row.C} S {row.S}")
    print("  families:", by)
    print("  terms:", nz)
    l = fc[(fc.unique_id == uid) & (fc["head"] == "location")]
    zl = l.points.sum() / K
    print(f"  P_L recomputed {sig(zl):.4f} stored {fs.loc[uid, 'p_l']:.4f};",
          l[l.points.abs() > 0.005][["term", "x_value", "points"]].round(1).values.tolist(),
          "| zero-weight votes:", l[(l.points.abs() < 0.005) & l.term.str.startswith("v_")][["term", "x_value"]].values.tolist())
    c = cases[cid]
    print(f"  cases.json rank {c['rank']} of {c['n_candidates']}, d1 {c['d1']}, d2 {c['d2']}; "
          f"U check P_E*P_S*G = {c['P_E'] * c['P_S'] * c['G']:.4f} vs U {c['U']:.4f}; P_E stored {fs.loc[uid, 'p_e']:.4f}")
    print(f"  p_abl_noown {vs.loc[(uid, s), 'p_abl_noown']:.4f}")

# Wockhardt: the rejected sentences, and what the raw record says
at = pd.read_parquet(F / "atoms.parquet")
w = at[(at.unique_id == CASES["C1"]) & (at.service == "dialysis")]
print("\nWockhardt dialysis atoms:", w[["text", "counts_as_own", "rejected_reason", "named_entity"]].to_dict("records"))
u = at[(at.unique_id == CASES["U1"]) & (at.service == "emergency_csection")]
print("Referal emergency_csection atoms:", len(u), u[["text", "counts_as_own"]].to_dict("records"))
raw = pd.read_parquet(R / "data/raw/facilities.parquet").set_index("unique_id")
pin = pd.read_parquet(R / "data/raw/india_post_pincode_directory.parquet")
pcol = [c for c in pin.columns if "pin" in c.lower()][0]
for cid in ("C1", "U1"):
    r = raw.loc[CASES[cid]]
    hits = pin[pin[pcol].astype(str) == str(r.address_zipOrPostcode)]
    dcol = [c for c in pin.columns if "district" in c.lower()]
    print(cid, r.address_city, r.address_stateOrRegion, r.address_zipOrPostcode, (r.latitude, r.longitude),
          "| PIN district:", hits[dcol].drop_duplicates().values.tolist()[:3])
