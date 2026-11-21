"""GEO-07 verification: district coverage, PIN-district vs coordinate-district agreement, and an
independent exact-name join of directory districts to NFHS-5 (state-aware)."""
import json
import re
import sys

import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo/verify")
from v_common import ROOT, VER, directory

v = pd.read_parquet(VER + "/v_fac.parquet")
o = {}
o["pin_district_available"] = int(v.p_district.notna().sum())
o["coord_district_available"] = int(v.c_district.notna().sum())
o["any_district"] = int((v.p_district.notna() | v.c_district.notna()).sum())
both = v.p_district.notna() & v.c_district.notna()
dis = both & (v.p_district != v.c_district)
o["pin_vs_coord_district_disagree"] = [int(dis.sum()), int(both.sum())]
o["disagree_within_50km"] = int((dis & (v.d_finder <= 50)).sum())
o["disagree_gt50km"] = int((dis & (v.d_finder > 50)).sum())

n = lambda s: re.sub(r"[^a-z]", "", str(s).lower().replace("&", "and"))
nf = pd.read_parquet(ROOT + "/data/raw/nfhs_5_district_health_indicators.parquet")
st_fix = {"maharastra": "maharashtra", "andamanandnicobarislands": "andamanandnicobarislands", "nctofdelhi": "delhi"}
nf["k"] = nf.state_ut.map(n).map(lambda s: st_fix.get(s, s)) + "|" + nf.district_name.map(n)
o["nfhs_states"] = sorted(nf.state_ut.str.strip().unique().tolist())
p = directory()
dd = p[p.district.ne("NA")].groupby(["statename", "district"]).size().reset_index()
dd["k"] = dd.statename.map(n) + "|" + dd.district.map(n)
o["directory_state_district_pairs"] = len(dd)
o["exact_join_pairs"] = int(dd.k.isin(set(nf.k)).sum())
fk = v.p_state.map(n) + "|" + v.p_district.map(n)
o["facilities_exact_join_via_pin_district"] = [int(fk.isin(set(nf.k)).sum()), len(v)]
o["unjoined_top"] = dd[~dd.k.isin(set(nf.k))].k.head(80).tolist()
fin = pd.read_parquet(ROOT + "/audit/geo/facility_district.parquet")
o["finder_facility_district_cols"] = fin.columns.tolist()
o["finder_district_src"] = fin.district_src.value_counts().to_dict() if "district_src" in fin else None
json.dump(o, open(VER + "/v_district_stats.json", "w"), indent=1)
print(json.dumps(o, indent=1))
