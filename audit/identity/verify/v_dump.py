"""Dump raw rows for the strict group containing each given unique_id (or a raw uid list with --raw)."""
import sys; sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/identity/verify")
from v_base import *
d = dedup(wellformed(raw()))
g = pd.read_csv("/Users/karthikvattem/projects/datathon/audit/identity/verify/v_strict_groups.csv")
d = d.merge(g, on="unique_id")
args = sys.argv[1:]
rawmode = args and args[0] == "--raw"
if rawmode: args = args[1:]
for u in args:
    if rawmode:
        s = d[d.unique_id.isin(u.split(","))]
    else:
        k = d.loc[d.unique_id == u, "grp"].iat[0]
        s = d[d.grp == k] if pd.notna(k) else d[d.unique_id == u]
    print("=" * 30, u)
    for _, x in s.iterrows():
        cl = jlist(x.procedure) + jlist(x.capability) + jlist(x.equipment)
        print(f"- {x.unique_id} | {x['name']} | type {x.facilityTypeId} | {x.address_line1} / {x.address_line2} | city {x.address_city} | st {x.address_stateOrRegion} | pin {x.address_zipOrPostcode} | {x.latitude:.4f},{x.longitude:.4f}")
        print(f"  phone {x.officialPhone} | list {jlist(x.phone_numbers)[:4]} | web {x.officialWebsite} | email {x.email}")
        print(f"  desc: {str(x.description)[:260]}")
        print(f"  claims({len(cl)}): {' || '.join(c[:110] for c in cl[:4])}")
        print(f"  urls: {[u2[:90] for u2 in jlist(x.source_urls)[:3]]}")
