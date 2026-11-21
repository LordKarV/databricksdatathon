"""GEO-05 side check: facility PINs that are valid-looking but absent from the directory. Are they
plausible (coordinates near a PIN with the same 3-digit prefix) or junk?"""
import json
import sys

import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo/verify")
from v_common import ROOT, VER, directory

v = pd.read_parquet(VER + "/v_fac.parquet")
known = set(directory().pincode)
m = v[v.pin.notna() & ~v.pin.isin(known)]
o = {"missing": len(m), "distinct": int(m.pin.nunique()),
     "prefix3_exists_in_directory": int((m.pin // 1000).isin({k // 1000 for k in known}).sum()),
     "coords_nearest_pin_same_prefix3": int(((m.c_pincode // 1000) == (m.pin // 1000)).sum()),
     "coords_nearest_pin_same_prefix2": int(((m.c_pincode // 10000) == (m.pin // 10000)).sum()),
     "top": m.pin.astype(int).value_counts().head(10).to_dict()}
json.dump(o, open(VER + "/v_missing_pins.json", "w"), indent=1)
print(json.dumps(o, indent=1))
