"""Merges the distance detector cannot see: stated state differs from the PIN state while the
coordinates sit within 50 km of the PIN (PIN and coordinates come from the same wrong place)."""
import json
import sys

import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo/verify")
from v_common import VER

v = pd.read_parquet(VER + "/v_fac.parquet")
m = v.s_state.notna() & v.p_state.notna() & (v.s_state != v.p_state)
o = {"state_vs_pin_mismatch": int(m.sum()), "of_which_coords_within_50km_of_pin": int((m & (v.d_finder <= 50)).sum()),
     "examples": v[m & (v.d_finder <= 50)][["unique_id", "name", "address_city", "s_state", "p_state", "p_district"]].head(12).values.tolist()}
json.dump(o, open(VER + "/v_hidden_merge.json", "w"), indent=1)
print(json.dumps(o, indent=1))
