"""Print records for a location hand check: python dump_check.py <flag> <n> <seed>."""
import sys
import pandas as pd
from common import OUT, facilities

flag, n, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
l = pd.read_parquet(OUT / "facility_location.parquet")
f = facilities().set_index("unique_id")
s = l[l.loc_flags.map(lambda x: flag in x)].sample(n, random_state=seed)
for r in s.itertuples():
    x = f.loc[r.unique_id]
    print(f"== {r.unique_id[:8]} {r.name} | city={r.address_city} state={r.address_stateOrRegion} pin={r.pin} -> {r.loc_src}/{r.loc_conf} district={r.district}")
    print("   addr:", " / ".join(str(v) for v in [x.address_line1, x.address_line2, x.address_line3] if v)[:160])
    print("   note:", r.loc_note[:260])
    print("   desc:", str(x.description)[:200])
