"""Score duplicate rules against the 47 hand-labelled strong groups (labels/strong_groups_hand.csv).
Positive = same physical facility (true_dup or same_site_unit)."""
import itertools
import pandas as pd
from rapidfuzz import fuzz
from common import load, OUT, haversine, norm_phone, domain

df = load().drop_duplicates("unique_id").reset_index(drop=True)
g = pd.read_csv(OUT + "dup_groups.csv")
df["grp"] = g["grp_strong"]
lab = pd.read_csv("/Users/karthikvattem/projects/datathon/audit/identity/labels/strong_groups_hand.csv")
u2g = dict(zip(df.unique_id, df.grp))
lab["grp"] = lab.unique_id.map(u2g)
assert lab.grp.notna().all() and lab.grp.nunique() == len(lab) == df.grp.nunique(), "labels must cover every strong group"


def phones(r):
    s = set(r.phone_numbers_l) | ({r.officialPhone} if r.officialPhone else set())
    return {norm_phone(p)[0] for p in s if norm_phone(p)[1] != "invalid"}


feat = []
for k, s in df[df.grp.notna()].groupby("grp"):
    best = {}
    for (_, a), (_, b) in itertools.combinations(s.iterrows(), 2):
        f = dict(sort=fuzz.token_sort_ratio(a.nname, b.nname), tset=fuzz.token_set_ratio(a.nname, b.nname),
                 km=haversine(a.latitude, a.longitude, b.latitude, b.longitude),
                 phone=bool(phones(a) & phones(b)),
                 dom=bool(domain(a.officialWebsite)) and domain(a.officialWebsite) == domain(b.officialWebsite),
                 addr=fuzz.token_set_ratio(str(a.address_line1).lower(), str(b.address_line1).lower()),
                 samepin=a.pin == b.pin, samecity=a.ncity == b.ncity)
        for key, v in f.items():
            best[key] = (min if key == "km" else max)(best.get(key, v), v)
    feat.append(dict(grp=k, **best))
F = pd.DataFrame(feat).merge(lab, on="grp")
F["pos"] = F.label.isin(["true_dup", "same_site_unit"])
print("hand-labelled groups:", len(F), "positives:", int(F.pos.sum()), F.label.value_counts().to_dict())

rules = {
    "R0 any strong key": lambda r: True,
    "R1 (tset>=90 or same name) and km<1": lambda r: r.tset >= 90 and r.km < 1,
    "R2 sort>=80": lambda r: r.sort >= 80,
    "R3 tset>=90 and (phone or dom or addr>=80 or samepin)": lambda r: r.tset >= 90 and (r.phone or r.dom or r.addr >= 80 or r.samepin),
    "R4 sort>=70 and (phone or dom or addr>=80)": lambda r: r.sort >= 70 and (r.phone or r.dom or r.addr >= 80),
    "R5 tset>=95 and (phone or dom or addr>=70 or samecity)": lambda r: r.tset >= 95 and (r.phone or r.dom or r.addr >= 70 or r.samecity),
}
for name, fn in rules.items():
    pred = F.apply(fn, axis=1)
    tp, fp = int((pred & F.pos).sum()), int((pred & ~F.pos).sum())
    fn_ = int((~pred & F.pos).sum())
    print(f"{name:60s} flagged {tp + fp:2d}  TP {tp:2d}  FP {fp:2d}  FN {fn_:2d}  precision {tp / max(tp + fp, 1):.2f}  recall {tp / max(tp + fn_, 1):.2f}")
F.to_csv(OUT + "strong_groups_features.csv", index=False)
print(F[["label", "sort", "tset", "km", "phone", "dom", "addr", "samepin", "note"]].sort_values("label").to_string())
