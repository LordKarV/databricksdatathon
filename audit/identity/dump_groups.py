"""Print readable record cards for groups from dup_groups.csv, for hand checking.
usage: dump_groups.py <grp column> <n groups> [seed]"""
import sys
import pandas as pd
from common import load, OUT, haversine

col, n = sys.argv[1], int(sys.argv[2])
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 0
df = load().drop_duplicates("unique_id").reset_index(drop=True)
g = pd.read_csv(OUT + "dup_groups.csv")
df["grp"] = g[col]
ids = df.grp.dropna().drop_duplicates().sample(frac=1, random_state=seed).head(n)
for k in ids:
    s = df[df.grp == k]
    print("=" * 100, f"\nGROUP {int(k)} size {len(s)}")
    a0 = s.iloc[0]
    for r in s.itertuples():
        print(f"- {r.unique_id} | {r.name} | {r.facilityTypeId} | {r.address_line1} | {r.address_city} | {r.pin} "
              f"| ({r.latitude:.5f},{r.longitude:.5f}) {haversine(a0.latitude, a0.longitude, r.latitude, r.longitude):.2f}km "
              f"| ph {r.officialPhone} | web {r.officialWebsite} | docs {r.numberDoctors} beds {r.capacity}")
        print("    desc:", str(r.description)[:220].replace("\n", " "))
        print("    cap :", " || ".join(r.capability_l[:3])[:300])
