"""GEO-03 verification: in-text PINs from another postal district, and multi-city justdial/practo slugs."""
import json
import re
import sys
from collections import Counter

import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo/verify")
from v_common import VER, facilities, pin_of

f = facilities()
v = pd.read_parquet(VER + "/v_fac.parquet")
f["d"] = v.d_finder.values
f["pin"] = f.address_zipOrPostcode.map(pin_of)
o = {}
txt = f[["address_line1", "address_line2", "address_line3", "description"]].astype(str).agg(" ".join, axis=1)
tp = txt.map(lambda t: {int(x.replace(" ", "")) for x in re.findall(r"(?<![0-9])([1-9][0-9]{2} ?[0-9]{3})(?![0-9])", t)})
f["other3"] = [bool(z == z and any(x // 1000 != int(z) // 1000 for x in s)) for s, z in zip(tp, f.pin)]
o["text_pin_other_prefix3"] = int(f.other3.sum())
# how many of those 'PINs' are phone fragments / years / not real PINs? check against directory
from v_common import directory
real = set(directory().pincode)
f["other3_real"] = [bool(z == z and any(x // 1000 != int(z) // 1000 and x in real for x in s)) for s, z in zip(tp, f.pin)]
o["text_pin_other_prefix3_real_pin"] = int(f.other3_real.sum())


def slugs(s):
    try:
        u = json.loads(s) or []
    except Exception:
        return set()
    out = set()
    for x in u:
        m = re.search(r"(?:justdial\.com|practo\.com)/([A-Za-z\-]+)/", str(x))
        if m:
            out.add(m.group(1).lower())
    return out


f["sl"] = f.source_urls.map(slugs)
allsl = Counter(s for x in f.sl for s in x)
o["top_slugs"] = allsl.most_common(30)
NONCITY = {"doctor", "doctors", "clinic", "hospital", "consult", "search", "providers", "india", "health-wiki", "plus", "healthfeed",
           "jdmart", "medicines", "tests", "order-medicines", "practo-plus", "online-consultation", "covid"}
f["sl2"] = f.sl.map(lambda s: s - NONCITY)
multi = f.sl2.map(len) > 1
o["multi_city_slug"] = int(multi.sum())
METRO = [{"mumbai", "thane", "navi-mumbai", "mira-road", "kalyan", "palghar", "raigad-maharashtra", "raigad"},
         {"delhi", "new-delhi", "noida", "gurgaon", "ghaziabad", "faridabad", "greater-noida", "delhi-ncr"},
         {"bangalore", "bengaluru", "bangalore-rural"}, {"hyderabad", "secunderabad", "rangareddy", "ranga-reddy"},
         {"kolkata", "howrah", "north-24-parganas", "south-24-parganas", "hooghly"}, {"chennai", "kanchipuram", "chengalpattu", "tiruvallur"},
         {"pune", "pimpri-chinchwad"}, {"ahmedabad", "gandhinagar"}, {"chandigarh", "mohali", "panchkula"}]
f["metro_only"] = multi & f.sl2.map(lambda s: any(s <= m for m in METRO))
o["multi_slug_metro_neighbours_only"] = int(f.metro_only.sum())
o["n_slugs_distribution_multi"] = f.sl2[multi].map(len).clip(upper=6).value_counts().sort_index().to_dict()
either = multi | f.other3
hasd = f.d.notna()
for k, m in [("multi", multi), ("multi_not_metro", multi & ~f.metro_only), ("metro_only", f.metro_only), ("either", either),
             ("neither", ~either), ("text_other3", f.other3), ("no_slugs_at_all", f.sl.map(len) == 0)]:
    o["far_rate_" + k] = [int((m & (f.d > 50)).sum()), int((m & hasd).sum()), round(float((m & (f.d > 50)).sum() / max(1, (m & hasd).sum())), 3)]
o["n_source_urls_median_multi_vs_not"] = [float(f.source_urls[multi].map(lambda s: len(json.loads(s) or [])).median()),
                                          float(f.source_urls[~multi].map(lambda s: len(json.loads(s) or []) if isinstance(s, str) else 0).median())]
json.dump(o, open(VER + "/v_merge_stats.json", "w"), indent=1, default=str)
print(json.dumps(o, indent=1, default=str))
