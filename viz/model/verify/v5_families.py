"""Independent recomputation of story 5 (family contributions by own-text level, prior vs fitted).

Model outputs and the fitted weight table only; no labels. Own term grouping (not _inputs.family).
Run: .venv-viz/bin/python viz/model/verify/v5_families.py
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

R = Path("/Users/karthikvattem/projects/datathon")
F = R / "model/proto/fusion"
K = 20 / math.log(2)
pc = pd.read_parquet(F / "pair_contributions.parquet", columns=["unique_id", "service", "head", "term", "group", "points"])
assert (pc["head"] == "service").all()
root = pc.term.str.split("@").str[0]
fam = np.select(
    [pc.group.eq("base"), root.str.fullmatch(r"t[1-5]|tb_mid|tb_high|trunc0"), root.isin(["p1", "p2"]),
     root.isin(["c1", "c2", "n1", "s1"]), root.isin(["g_mid", "g_high"]), pc.group.eq("context")],
    ["base", "text", "hints", "flags", "web", "type_size"], default="UNMAPPED")
assert (fam != "UNMAPPED").all()
wide = pc.assign(f=fam).groupby(["unique_id", "service", "f"]).points.sum().unstack(fill_value=0.0)
ps = pd.read_parquet(F / "pair_scores.parquet").set_index(["unique_id", "service"])
d = ps[["T", "p_s", "z_cal"]].join(wide, how="left").fillna(0.0)
print("pairs", len(d), "max |sum/K - z_cal|", (d[["base", "text", "hints", "flags", "web", "type_size"]].sum(axis=1) / K - d.z_cal).abs().max())
g = d.groupby("T")
t = g[["text", "hints", "web", "type_size", "flags"]].mean().round(2)
t["n"] = g.size()
t["p_s_med"] = g.p_s.median().round(3)
t["p_s_p10"] = g.p_s.quantile(.1).round(3)
t["p_s_p90"] = g.p_s.quantile(.9).round(3)
print(t.to_string())
# Mean vs typical: how many pairs at each level have hints > text? (distribution, not just means)
d["hints_gt_text"] = d.hints > d.text
print("share of pairs with hints > text, by T:", g.apply(lambda x: round((x.hints > x.text).mean(), 3)).to_dict())
print("share of pairs with any hint (hints>0), by T:", g.apply(lambda x: round((x.hints > 0.01).mean(), 3)).to_dict())
print("text points distinct values by T:", {k: sorted(set(np.round(v.text, 2)))[:8] for k, v in g})
# within T=1..4, text points by service (t2/t4 cancelled for some services)
tt = d.reset_index()
print("T=4 mean text by service:", tt[tt["T"] == 4].groupby("service").text.mean().round(2).to_dict())
print("T=0 pairs share of all:", round((d["T"] == 0).mean(), 4))

w = pd.read_parquet(F / "weights.parquet")
w = w[w["head"] == "service"].set_index("term")
a = json.loads((F / "platt.json").read_text())["service"]["a"]
for term in ["t1", "t2", "t3", "t4", "t5", "tb_mid", "tb_high", "c2", "g_mid", "g_high", "level_dh", "breadth_20p"]:
    r = w.loc[term]
    print(f"{term:12s} prior {r.prior_mean * K:+6.1f}  post {r.post_mean * K:+6.1f} [{r.ci90_lo * K:+.1f}, {r.ci90_hi * K:+.1f}]"
          f"  shipped {r.post_mean * K * a:+.1f}  at_bound {r.at_bound}  dev n {r.n_fired_dev}")
print("platt a", round(a, 3))
print("at_bound terms:", sorted(w.index[w.at_bound.astype(bool)].tolist()))
