"""Print raw evidence for cited example records: identity fields and sentences matching a pattern.
Usage: v_view.py <uid> [regex]"""
import sys, os
import pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
s = pd.read_parquet(f"{D}/out/sent.parquet")
rec = pd.read_parquet(f"{D}/out/rec.parquet").set_index("unique_id")
dec = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/merge/out/sentence_decisions.parquet")
u = sys.argv[1]; rx = sys.argv[2] if len(sys.argv) > 2 else None
r = rec.loc[u]
print("==", u, "|", r["name"], "|", r.address_city, "|", r.address_stateOrRegion, "| PIN", r.address_zipOrPostcode, "|", r.latitude, r.longitude, "| type", r.facilityTypeId)
x = s[s.unique_id == u].merge(dec, on=["unique_id", "field", "idx"], how="left")
print("sentences", len(x), "quarantined", int(x.quarantine.sum()), "tagged", int(x.tag_only.sum()))
if rx:
    m = x[x.text.str.contains(rx, case=False, regex=True)]
    for t in m.itertuples():
        print(f"  [{t.field[:4]} q={int(t.quarantine)}] {t.text[:220]}")
