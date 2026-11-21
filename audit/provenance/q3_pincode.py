"""Q3: india_post_pincode_directory quality and facility PIN coverage.
Outputs q3_results.json, pin_centroids.parquet (pincode -> robust centroid, n offices,
district/state sets, quality flags), handcheck_q3_*.csv."""
import json
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/provenance")
from common import OUT, facilities, norm_pin, pincodes  # noqa: E402

LAT, LON = (6.0, 37.6), (68.0, 97.5)  # India bounding box
CIRCLE_STATES = {
    "GUJARAT": {"GUJARAT", "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU"},
    "JAMMU KASHMIR": {"JAMMU AND KASHMIR", "LADAKH"},
    "KERALA": {"KERALA", "LAKSHADWEEP", "PUDUCHERRY"},  # Mahe
    "MAHARASHTRA": {"MAHARASHTRA", "GOA"},
    "NORTH EASTERN": {"ARUNACHAL PRADESH", "MEGHALAYA", "MANIPUR", "TRIPURA", "MIZORAM",
                      "NAGALAND"},
    "PUNJAB": {"PUNJAB", "CHANDIGARH"},
    "TAMILNADU": {"TAMIL NADU", "PUDUCHERRY"},
    "WEST BENGAL": {"WEST BENGAL", "SIKKIM", "ANDAMAN AND NICOBAR ISLANDS"},
    "ANDHRA PRADESH": {"ANDHRA PRADESH", "PUDUCHERRY"},  # Yanam
    "ASSAM": {"ASSAM", "MEGHALAYA"},
    "CHATTISGARH": {"CHHATTISGARH"},
    "APS": set(),  # Army Postal Service: any state is unexpected
}


def to_num(s):
    if s is None or not re.fullmatch(r"\s*-?\d+(\.\d+)?\s*", str(s)):
        return np.nan
    return float(s)


def hav_km(lat1, lon1, lat2, lon2):
    p = np.pi / 180
    a = (np.sin((lat2 - lat1) * p / 2) ** 2 + np.cos(lat1 * p) * np.cos(lat2 * p)
         * np.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def main():
    p = pincodes()
    n = len(p)
    res = {"rows": n, "distinct_pincodes": int(p.pincode.nunique())}
    lat, lon = p.latitude.map(to_num), p.longitude.map(to_num)
    res["lat_lon"] = {
        "lat_literal_NA": int((p.latitude == "NA").sum()),
        "lon_literal_NA": int((p.longitude == "NA").sum()),
        "lat_null": int(p.latitude.isna().sum()),
        "lat_unparseable_non_NA": int((lat.isna() & p.latitude.notna() & (p.latitude != "NA")).sum()),
        "lon_unparseable_non_NA": int((lon.isna() & p.longitude.notna() & (p.longitude != "NA")).sum()),
        "both_numeric": int((lat.notna() & lon.notna()).sum()),
        "zero_coords": int(((lat == 0) | (lon == 0)).sum()),
    }
    num = lat.notna() & lon.notna()
    inbox = num & lat.between(*LAT) & lon.between(*LON)
    swapped = num & lon.between(*LAT) & lat.between(*LON) & ~inbox
    res["lat_lon"].update({
        "in_india_bbox": int(inbox.sum()), "swapped_lat_lon": int(swapped.sum()),
        "numeric_outside_bbox_not_swapped": int((num & ~inbox & ~swapped).sum()),
    })
    dec = p.latitude.where(num).astype(str).str.extract(r"\.(\d*)$")[0].str.len().fillna(0)
    res["lat_lon"]["numeric_lat_with_le2_decimals"] = int((num & (dec <= 2)).sum())
    # fixed coords: swap the swapped ones, drop the rest outside the box
    flat = np.where(swapped, lon, np.where(inbox, lat, np.nan))
    flon = np.where(swapped, lat, np.where(inbox, lon, np.nan))
    p = p.assign(flat=flat, flon=flon)
    # NA placeholders in admin columns
    res["admin_NA"] = {c: int((p[c] == "NA").sum()) for c in ("district", "statename")}
    # multi-district / multi-state PINs (excluding NA placeholders)
    q = p[(p.district != "NA") & (p.statename != "NA")]
    g = q.groupby("pincode")
    nd, ns = g.district.nunique(), g.statename.nunique()
    res["pins_multi_district"] = int((nd > 1).sum())
    res["pins_multi_state"] = int((ns > 1).sum())
    res["pins_only_NA_admin"] = int(p.pincode.nunique() - q.pincode.nunique())
    res["multi_state_examples"] = {
        str(k): sorted(v) for k, v in g.statename.agg(set)[ns > 1].head(10).items()}
    # postal circle vs state: each circle serves a known set of states/UTs
    q = q.assign(circ=q.circlename.str.replace(" Circle", "", regex=False).str.upper())
    bad = q[[st not in CIRCLE_STATES.get(ci, {ci}) for ci, st in zip(q.circ, q.statename)]]
    strong = bad
    res["circle_state_mismatch_rows"] = int(len(bad))
    res["circle_state_mismatch_pins"] = int(bad.pincode.nunique())
    res["circle_state_mismatch_by_pair"] = {f"{a} -> {b}": int(n) for (a, b), n in
                                            bad.groupby(["circ", "statename"]).size().items()}
    bad[["pincode", "officename", "district", "statename", "circlename"]].to_csv(
        f"{OUT}/handcheck_q3_circle_mismatch.csv", index=False)
    # coordinate spread within a PIN
    c = p[p.flat.notna()].groupby("pincode").agg(
        lat=("flat", "median"), lon=("flon", "median"), n_coord=("flat", "size"))
    pp = p[p.flat.notna()].merge(c, left_on="pincode", right_index=True)
    pp["d"] = hav_km(pp.flat, pp.flon, pp.lat, pp.lon)
    spread = pp.groupby("pincode").d.max()
    res["pins_with_coords"] = int(len(c))
    res["pins_without_any_coord"] = int(p.pincode.nunique() - len(c))
    res["pins_office_gt_50km_from_pin_median"] = int((spread > 50).sum())
    res["office_rows_gt_50km_from_pin_median"] = int((pp.d > 50).sum())
    res["office_rows_gt_200km_from_pin_median"] = int((pp.d > 200).sum())
    pp[pp.d > 200].sort_values("d", ascending=False)[
        ["pincode", "officename", "district", "statename", "latitude", "longitude", "d"]].head(40).to_csv(
        f"{OUT}/handcheck_q3_far_offices.csv", index=False)
    # centroid table for other steps: median of offices within 50 km of the raw median
    good = pp[pp.d <= 50]
    cent = good.groupby("pincode").agg(lat=("flat", "median"), lon=("flon", "median"),
                                       n_offices_used=("flat", "size"))
    adm = q.groupby("pincode").agg(districts=("district", lambda s: "|".join(sorted(set(s)))),
                                   states=("statename", lambda s: "|".join(sorted(set(s)))))
    cent = adm.join(cent, how="outer")
    cent["circle_state_mismatch"] = cent.index.isin(strong.pincode)
    cent.reset_index().to_parquet(f"{OUT}/pin_centroids.parquet", index=False)
    # facility PIN coverage
    f = facilities()
    pins = f.address_zipOrPostcode.map(norm_pin)
    raw = f.address_zipOrPostcode
    nullish = raw.isna() | raw.isin(["null", "", "000000"])
    known = set(p.pincode.unique())
    res["facility_pins"] = {
        "rows": int(len(f)), "null_like": int(nullish.sum()),
        "valid_6digit": int(pins.notna().sum()),
        "valid_after_space_strip_only": int(sum(1 for z in raw if isinstance(z, str) and " " in z
                                               and norm_pin(z))),
        "invalid_format_non_null": int((pins.isna() & ~nullish).sum()),
        "valid_in_directory": int(pins.dropna().isin(known).sum()),
        "valid_not_in_directory": int((~pins.dropna().isin(known)).sum()),
        "valid_in_directory_with_centroid": int(pins.dropna().isin(set(cent.dropna(subset=["lat"]).index)).sum()),
        "valid_pin_has_circle_state_mismatch": int(pins.dropna().isin(set(strong.pincode)).sum()),
        "distinct_facility_pins": int(pins.nunique()),
        "not_in_directory_examples": pins[pins.notna() & ~pins.isin(known)].astype(int).head(15).tolist(),
    }
    # facility coords vs PIN centroid
    fc = f.assign(pin=pins).dropna(subset=["pin", "latitude"]).merge(
        cent.dropna(subset=["lat"]), left_on="pin", right_index=True)
    fc["d"] = hav_km(fc.latitude, fc.longitude, fc.lat, fc.lon)
    res["facility_coord_vs_pin_centroid_km"] = {
        "compared": int(len(fc)), "quantiles": fc.d.quantile([.5, .75, .9, .95, .99]).round(1).to_dict(),
        "gt_25km": int((fc.d > 25).sum()), "gt_50km": int((fc.d > 50).sum()),
        "gt_200km": int((fc.d > 200).sum())}
    fc[["unique_id", "d"]].rename(columns={"d": "coord_pin_km"}).to_parquet(
        f"{OUT}/facility_coord_pin_km.parquet", index=False)
    with open(f"{OUT}/q3_results.json", "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
