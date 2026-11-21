"""Missed-signal probe: mappls.com place URLs carry '@zdata=<base64 of "lat+lon+zoom+eloc">'.
Decode them and compare with the record's latitude/longitude and with its PIN centroid."""
import base64
import json
import re
import sys

import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo/verify")
from v_common import ROOT, VER, facilities, hav, pin_of

f = facilities().drop_duplicates("unique_id").reset_index(drop=True)
cen = pd.read_parquet(ROOT + "/audit/geo/pin_centroids.parquet").set_index("pincode")
ZD = re.compile(r"mappls\.com/place-[^@\s\"]*@zdata=([A-Za-z0-9+/]+=*)")


def decode(m: str):
    try:
        t = base64.b64decode(m + "=" * (-len(m) % 4)).decode("ascii", "ignore")
    except Exception:
        return None
    x = re.match(r"(-?\d+\.\d+)\+(-?\d+\.\d+)", t)
    return (float(x.group(1)), float(x.group(2))) if x else None


rows = []
for r in f.itertuples():
    pts = [p for p in (decode(m) for m in ZD.findall(str(r.source_urls))) if p]
    if not pts:
        continue
    pin = pin_of(r.address_zipOrPostcode)
    c = cen.loc[pin] if pin in cen.index else None
    for a, b in pts:
        rows.append({"unique_id": r.unique_id, "d_coords": float(hav(r.latitude, r.longitude, a, b)),
                     "d_zd_pin": float(hav(a, b, c.best_lat, c.best_lon)) if c is not None else None,
                     "d_coords_pin": float(hav(r.latitude, r.longitude, c.best_lat, c.best_lon)) if c is not None else None})
z = pd.DataFrame(rows).sort_values("d_zd_pin").drop_duplicates("unique_id")  # keep the zdata point closest to the PIN
o = {"records_with_mappls_zdata": len(z), "zdata_points": len(rows)}
o["zdata_within_2km_of_coords"] = int((z.d_coords <= 2).sum())
o["zdata_gt50km_from_coords"] = int((z.d_coords > 50).sum())
far = z.d_coords_pin > 50
o["far_gt50_with_zdata"] = int(far.sum())
o["far_gt50_where_zdata_within_25km_of_pin"] = int((far & (z.d_zd_pin <= 25)).sum())
o["far_gt50_where_zdata_within_2km_of_coords"] = int((far & (z.d_coords <= 2)).sum())
json.dump(o, open(VER + "/v_mappls_stats.json", "w"), indent=1)
print(json.dumps(o, indent=1))
