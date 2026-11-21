"""Dump raw rows for hand reading: cited examples plus my own random picks from the far (>50 km)
and 10-50 km bands. Usage: v_dump.py [far|mid|ids] [n|id,id,...] [seed]"""
import json
import sys

import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo/verify")
from v_common import VER, facilities

f = facilities().drop_duplicates("unique_id").set_index("unique_id")
v = pd.read_parquet(VER + "/v_fac.parquet").drop_duplicates("unique_id").set_index("unique_id")
mode, arg = sys.argv[1], sys.argv[2]
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 7
if mode == "far":
    ids = v[v.d_finder > 50].sample(int(arg), random_state=seed).index
elif mode == "mid":
    ids = v[v.d_finder.between(10, 50)].sample(int(arg), random_state=seed).index
else:
    ids = arg.split(",")
for i in ids:
    r, g = f.loc[i], v.loc[i]
    print("=" * 100)
    print(i, "|", r["name"])
    print("addr:", r.address_line1, "|", r.address_line2, "|", r.address_line3, "| city:", r.address_city, "| state:", r.address_stateOrRegion, "| zip:", r.address_zipOrPostcode)
    print(f"coords {r.latitude:.4f},{r.longitude:.4f} -> nearest office {g.c_district}/{g.c_statename} ({g.c_pincode}, {g.c_km:.1f} km) | PIN district {g.p_district}/{g.p_state} | d_pin {g.d_finder:.1f} km")
    print("phones:", r.phone_numbers, "| officialPhone:", r.officialPhone)
    try:
        urls = json.loads(r.source_urls) or []
    except Exception:
        urls = [r.source_urls]
    print("urls:", [str(u)[:110] for u in urls[:6]], f"(+{max(0, len(urls) - 6)})")
    print("desc:", str(r.description)[:500])
