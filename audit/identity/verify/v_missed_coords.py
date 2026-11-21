"""Missed issue check: low-precision or heavily shared coordinates (city-centroid fallbacks)."""
import sys; sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/identity/verify")
from v_base import *
d = dedup(wellformed(raw()))
def ndec(x):
    s = repr(float(x)); return len(s.split(".")[1].rstrip("0")) if "." in s else 0
lo = d.latitude.map(ndec).clip(upper=d.longitude.map(ndec))
mx = np.maximum(d.latitude.map(ndec), d.longitude.map(ndec))
print("coords with both lat and lon <=2 decimals:", int(((d.latitude.map(ndec) <= 2) & (d.longitude.map(ndec) <= 2)).sum()), "| <=3:", int(((d.latitude.map(ndec) <= 3) & (d.longitude.map(ndec) <= 3)).sum()), "of", len(d))
key = d.latitude.round(4).astype(str) + "," + d.longitude.round(4).astype(str)
vc = key.value_counts()
print("records on a 4-dp coordinate shared by >=3 records:", int(vc[vc >= 3].sum()), "coords", int((vc >= 3).sum()))
print(vc.head(8).to_dict())
for k in vc.head(4).index:
    print(k, d[key == k][["name", "address_city", "address_zipOrPostcode"]].head(5).values.tolist())
