"""Print raw evidence for records: v_show.py SERVICE_REGEX uidprefix [uidprefix ...]
Shows identity fields and every list item / description sentence matching the regex, plus the finder's grade rows."""
import re, sys
import pandas as pd
from v_common import load
pat = re.compile(sys.argv[1], re.I); ids = sys.argv[2:]
df = load(); g = pd.read_parquet("../out/grades.parquet")
for p in ids:
    for r in df[df.unique_id.str.startswith(p)].to_dict("records"):
        print(f"### {r['unique_id'][:8]} | {r['name']} | {r['address_city']}, {r['address_stateOrRegion']} {r['address_zipOrPostcode']} | type={r['facilityTypeId']} cap={r['capacity']} docs={r['numberDoctors']} | lens p{len(r['procedure'])} e{len(r['equipment'])} c{len(r['capability'])} s{len(r['specialties'])}")
        gg = g[g.unique_id == r["unique_id"]]
        print("   finder grades:", dict(zip(gg.service, gg.grade)))
        for f in ["procedure", "equipment", "capability"]:
            for s in r[f]:
                if pat.search(s): print(f"   [{f[:4]}] {s[:230]}")
        for s in re.split(r"(?<=[.!?])\s+", r["description"]):
            if pat.search(s): print(f"   [desc] {s[:230]}")
