"""Re-score rule R5 on the finder's 47 hand labels using my own pair features (v_pairs.csv)."""
import pandas as pd
V = "/Users/karthikvattem/projects/datathon/audit/identity/verify/"
R = pd.read_csv(V + "v_pairs.csv"); G = pd.read_csv(V + "v_strict_groups.csv")
lab = pd.read_csv("/Users/karthikvattem/projects/datathon/audit/identity/labels/strong_groups_hand.csv")
u2g = dict(zip(G.unique_id, G.grp))
lab["grp"] = lab.unique_id.map(u2g)
assert lab.grp.notna().all() and lab.grp.nunique() == 47
R["grp"] = R.uid_a.map(u2g); R = R[R.strict & (R.grp == R.uid_b.map(u2g))]
R["samecity"] = R.city_a.fillna("").str.lower().str.replace(r"[^a-z]", "", regex=True) == R.city_b.fillna("").str.lower().str.replace(r"[^a-z]", "", regex=True)
R["r5"] = (R.tset >= 95) & (R.phone | R.dom | (R.addr >= 70) | R.samecity)
F = R.groupby("grp").r5.any().rename("pred").reset_index().merge(lab, on="grp")
F["pos"] = F.label.isin(["true_dup", "same_site_unit"])
tp = (F.pred & F.pos).sum(); fp = (F.pred & ~F.pos).sum(); fn = (~F.pred & F.pos).sum()
print("labels", F.label.value_counts().to_dict())
print(f"R5 flagged {tp+fp} TP {tp} FP {fp} FN {fn} precision {tp/(tp+fp):.2f} recall {tp/(tp+fn):.2f}")
print("FP groups:", F[F.pred & ~F.pos].note.tolist())
print("strict-key precision (any key):", F.pos.mean().round(3), F.pos.sum(), "/", len(F))
# claims identical among labelled-positive pairs
pos_g = set(F[F.pos].grp)
print("positive-group pairs", R.grp.isin(pos_g).sum(), "same_claims", R[R.grp.isin(pos_g)].same_claims.sum(), "same_desc", R[R.grp.isin(pos_g)].same_desc.sum())
