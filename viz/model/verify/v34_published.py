"""Check stories 3 and 4 against the published files, plus dev-only recounts.

Sealed test rule: test numbers are only READ from results.json / test_metrics.json and checked by
arithmetic (sums, Wilson on published counts, kappa from the published crosstab). Label VALUES are read
only for dev-split pairs; for test pairs only pair_id order is read (no label fields).
Run: .venv-viz/bin/python viz/model/verify/v34_published.py
"""
import glob
import json
import math
from pathlib import Path

R = Path("/Users/karthikvattem/projects/datathon")
res = json.loads((R / "model/review/stats/results.json").read_text())
tm = json.loads((R / "model/proto/fusion/test_metrics.json").read_text())
pt = res["pair_level_test"]


def wilson(k, n, z=1.959964):
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0, c - h), 3), round(min(1, c + h), 3)


# --- story 3: AUROC table, paired diffs, calibration, location
a, s, dif = pt["primary_target_all"]["auroc"], pt["primary_target_searched"]["auroc"], pt["paired_diff_raw_primary"]
for k in a:
    print(f"{k:16s} all71 {a[k]['raw']:.3f} {a[k]['raw_boot']['ci95']}  ipw71 {a[k]['ipw']:.3f}  searched39 {s[k]['raw']:.3f}"
          + (f"  WL-minus {dif[k]['point']:+.3f} {dif[k]['boot']['ci95']}" if k in dif else ""))
print("n/pos:", pt["primary_target_all"]["n"], pt["primary_target_all"]["n_pos"], "ess", pt["primary_target_all"]["ess_ipw"])
ipw39 = tm["headline_checked"]["auroc_ipw_shipped_minus_system"]
print("IPW searched-39 WL minus:", {k: (round(v["mean"], 3), [round(x, 3) for x in v["ci95"]]) for k, v in ipw39.items()})
print("IPW searched-39 WL point:", round(tm["headline_checked"]["point"]["shipped"]["auroc_ipw"], 3),
      [round(x, 3) for x in tm["headline_checked"]["ci95"]["shipped"]["auroc_ipw"]])
c = pt["calibration_primary_all"]
print("calib mean_p", c["mean_p"], "obs", c["obs"], "ece raw", c["ece_raw"], c["ece_raw_boot"]["ci95"], "ipw", c["ece_ipw"],
      c["ece_ipw_boot"]["ci95"])
for b in c["table"]:
    assert b["k_confirmed"] + b["k_contradicted"] + b["k_no_info"] == b["n"]
    assert abs(b["observed"] - b["k_confirmed"] / b["n"]) < 1e-3
    print("  bin", b["bin"], f"{b['k_confirmed']}/{b['n']}", "mean_p", b["mean_p"], "wilson", b["wilson95"], "mine", wilson(b["k_confirmed"], b["n"]))
assert sum(b["n"] for b in c["table"]) == 71 and sum(b["k_confirmed"] for b in c["table"]) == 17
L = tm["location_head"]
print("location: n (yes/no labels only)", L["n"], "yes", L["n_yes"], "neg", L["n"] - L["n_yes"], "auroc", round(L["auroc_raw"], 3),
      "| P_L>=0.7", L["p_l_ge_0_7"], wilson(L["p_l_ge_0_7"]["yes"], L["p_l_ge_0_7"]["n"]),
      "| P_L<0.7", L["n"] - L["p_l_ge_0_7"]["n"], "yes", L["n_yes"] - L["p_l_ge_0_7"]["yes"],
      wilson(L["n_yes"] - L["p_l_ge_0_7"]["yes"], L["n"] - L["p_l_ge_0_7"]["n"]))

# --- story 4: counts
inp = res["inputs"]
vis = res["visibility_bias_all_v2"]
ns_all = sum(v["never_searched"] for v in vis["stratum"].values())
ns_svc = sum(v["never_searched"] for v in vis["service"].values())
ns_batch = sum(v["never_searched"] for v in vis["batch"].values())
print("\nnever searched all v2 by stratum/service/batch:", ns_all, ns_svc, ns_batch, "| test", inp["test_never_searched"])
print("test counts", inp["test_label_counts"], "dev counts", inp["dev_label_counts"])
h = vis["never_searched_by_batch_half"]
print("batch half", h, wilson(h["first10"]["never_searched"], 70), wilson(h["last10"]["never_searched"], 70))
print("per batch never searched:", {k: (v["n"], v["never_searched"]) for k, v in vis["batch"].items()})
print("has_site:", {k: (v["confirmed"], v["n"]) for k, v in vis["has_site"].items()})

# kappa from the published crosstab (arithmetic on published counts)
ct = res["kappa"]["all"]["service"]["crosstab_overlap_by_primary"]  # {second: {first: n}} per pandas to_dict()
cats = ["confirmed", "contradicted", "no_info"]
m = [[ct.get(col, {}).get(row, 0) for col in cats] for row in cats]  # m[first][second]
n = sum(map(sum, m))
po = sum(m[i][i] for i in range(3)) / n
pe = sum(sum(m[i]) * sum(m[j][i] for j in range(3)) for i in range(3)) / n / n
print("kappa from crosstab", round((po - pe) / (1 - pe), 3), "agreement", round(po, 3), "n", n, "published",
      res["kappa"]["all"]["service"]["kappa"], res["kappa"]["all"]["service"]["kappa_boot95"])
print("both decisive:", res["kappa"].get("both_decisive_service"), "| crosstab m[first][second]:", m)
dec = [(i, j) for i in range(2) for j in range(2)]
print("  recount both decisive: agree", sum(m[i][j] for i, j in dec if i == j), "of", sum(m[i][j] for i, j in dec),
      "| off-diagonal involving no_info", m[0][2] + m[1][2] + m[2][0] + m[2][1], "of", n - sum(m[i][i] for i in range(3)))

# --- dev-only recount from the label files (values read only for dev pairs)
sp = json.loads((R / "model/gold/splits.json").read_text())["pairs"]
split = {p["pair_id"]: p["split"] for p in sp if p["version"] == "v2"}
order_ok, dev = [], []
sp_order = [p["pair_id"] for p in sp if p["version"] == "v2"]
for f in sorted(glob.glob(str(R / "model/gold/labels_p*.json"))):
    rs = json.loads(Path(f).read_text())["results"]
    ids = [r["pair_id"] for r in rs]
    sub = [p for p in sp_order if p in set(ids)]
    order_ok.append(sub == ids)
    for pos, r in enumerate(rs):
        if split.get(r["pair_id"]) == "dev":
            dev.append(dict(pos=pos, label=r["service"], searched=not (r["service"] == "no_info" and not (r.get("evidence_urls") or []))))
print("\nsplits.json order == label-file order within each batch:", order_ok)
from collections import Counter  # noqa: E402
print("dev n", len(dev), Counter(d["label"] for d in dev), "dev never searched", sum(not d["searched"] for d in dev))
f10 = [d for d in dev if d["pos"] < 10]
l10 = [d for d in dev if d["pos"] >= 10]
print("dev-only never searched: first10", sum(not d["searched"] for d in f10), "of", len(f10),
      wilson(sum(not d["searched"] for d in f10), len(f10)), "| last10", sum(not d["searched"] for d in l10), "of", len(l10),
      wilson(sum(not d["searched"] for d in l10), len(l10)))
