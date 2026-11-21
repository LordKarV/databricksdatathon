"""Step 1: PIN gazetteer = audit PIN centroids + two repairs + a precision radius per PIN.

Input: audit/geo/pin_centroids.parquet (India Post directory cleaned by audit/geo/pin_centroids.py:
NA/swapped/outside-India/placeholder/far offices dropped, misplaced PINs moved to their district median).
Repairs added here:
  R0 within-district misplacement: > 60 km and > 3x the district's p90 from the district median.
  R1 facility consensus: a PIN with >= 3 facilities at >= 3 distinct points within 5 km of their
     median (and >= half of the PIN's facilities) whose directory point is > 10 km from that
     consensus gets the consensus point (verifier: 78 of 1,033 busy PINs were > 25 km off,
     e.g. 422009 Nashik 165 km). Circularity risk: the consensus is built from facility coordinates,
     which are then checked against it. Requiring 3 distinct points that agree limits that risk.
     A second path: a single-office directory point outvoted by 2 agreeing distinct facility
     points more than 25 km away.
  R2 PINs missing from the directory (206 facility PINs, mostly real per the verifier) get the
     facility consensus when it exists, else the 3-digit-prefix median (coarse).
radius_km is the precision shown to the user when the PIN point stands in for a facility.
Writes pin_gazetteer.parquet and s1_stats.json.
"""
import json

import numpy as np
import pandas as pd

from common import AUDIT_GEO, OUT, facilities, hav_km, parse_pin

AGREE_KM, MIN_AGREE, OVERRIDE_KM = 5.0, 3, 10.0
KNOWN = {110001: (28.632, 77.219), 400001: (18.938, 72.835), 560001: (12.975, 77.605), 600001: (13.090, 80.285),
         700001: (22.572, 88.351), 302001: (26.920, 75.820), 226001: (26.848, 80.946), 800001: (25.611, 85.144),
         500001: (17.385, 78.475), 380001: (23.025, 72.585), 682001: (9.966, 76.243), 695001: (8.500, 76.950),
         411001: (18.520, 73.856), 141001: (30.900, 75.850), 462001: (23.260, 77.410), 751001: (20.270, 85.840),
         781001: (26.180, 91.750), 248001: (30.320, 78.030), 834001: (23.350, 85.330), 492001: (21.250, 81.630)}
# same 20 city-centre points as audit/geo/check_pin_known.py, plus the two verifier counter-examples
KNOWN_EXTRA = {422009: (19.995, 73.760), 560017: (12.960, 77.650)}  # Nashik Indira Nagar, Bengaluru HAL


def facility_consensus(f):
    lat, lon = f.latitude.astype(float), f.longitude.astype(float)
    ok = lat.between(6, 37.6) & lon.between(68, 97.6) & f.pin.notna()
    x = f.loc[ok, ["pin"]].assign(la=lat[ok], lo=lon[ok])
    med = x.groupby("pin")[["la", "lo"]].median().set_axis(["mla", "mlo"], axis=1)
    x = x.join(med, on="pin")
    x["agree"] = hav_km(x.la, x.lo, x.mla, x.mlo) <= AGREE_KM
    x["pt"] = x.la.round(4).astype(str) + "," + x.lo.round(4).astype(str)
    a = x[x.agree]
    g = pd.DataFrame({"n_fac": x.groupby("pin").size(), "n_agree": a.groupby("pin").size(),
                      "n_pts": a.groupby("pin").pt.nunique(), "cla": a.groupby("pin").la.median(),
                      "clo": a.groupby("pin").lo.median()}).fillna({"n_agree": 0, "n_pts": 0})
    a = a.join(g[["cla", "clo"]], on="pin")
    g["c_spread"] = hav_km(a.la, a.lo, a.cla, a.clo).groupby(a.pin).quantile(0.9)
    g["ok"] = (g.n_pts >= MIN_AGREE) & (g.n_agree >= 0.5 * g.n_fac)
    return g


def main():
    cen = pd.read_parquet(AUDIT_GEO / "pin_centroids.parquet")
    f = facilities()
    f["pin"] = f.address_zipOrPostcode.map(parse_pin)
    con = facility_consensus(f)
    st = {"directory_pins": len(cen), "pins_with_point_before": int(cen.best_lat.notna().sum())}

    g = cen[["pincode", "state", "district", "districts", "n_used", "spread_km_p90", "src", "best_lat", "best_lon"]].copy()
    g = g.rename(columns={"pincode": "pin", "best_lat": "lat", "best_lon": "lon"}).join(con, on="pin")
    # R0 (new): within-district misplacement the audit's 150 km rule misses in small districts, e.g.
    # 403513 Pernem, North Goa, whose offices hold swapped and shifted values and sit 141 km out at sea.
    # Rule: > 60 km and > 3x the district's p90 PIN distance from the district median -> district median.
    pm = g.src == "pin_median"
    dmed = g[pm].groupby(["state", "district"])[["lat", "lon"]].median().set_axis(["dla", "dlo"], axis=1)
    j0 = g.join(dmed, on=["state", "district"])
    dd = pd.Series(hav_km(j0.lat, j0.lon, j0.dla, j0.dlo), index=g.index)
    p90 = dd[pm].groupby([g.state, g.district]).transform(lambda s: s.quantile(0.9))
    r0 = pm & (dd > 60) & (dd > 3 * p90.reindex(g.index))
    st["pins_misplaced_within_district_r0"] = int(r0.sum())
    g["dir_lat"], g["dir_lon"] = g.lat, g.lon
    g.loc[r0, ["lat", "lon"]] = j0.loc[r0, ["dla", "dlo"]].values
    g.loc[r0, "src"] = "district_median"
    g["d_consensus_km"] = hav_km(g.lat, g.lon, g.cla, g.clo)
    # second path for single-office directory points (3,951 PINs rest on one office): 2 agreeing
    # distinct facility points more than 25 km away outvote one office (560017 Bengaluru, 106 km)
    single = (g.n_pts >= 2) & (g.n_used == 1) & (g.n_agree >= 0.5 * g.n_fac) & (g.d_consensus_km > 25)
    over = (g.ok.fillna(False).astype(bool) & (g.d_consensus_km > OVERRIDE_KM)) | single.fillna(False).astype(bool)
    # guard against circularity: the consensus must sit inside the PIN's own district (within 30 km of
    # the district's median directory point, or no further from it than the directory point + 10 km).
    # Rejects e.g. 518501 Nandyal, whose 3 facilities name Visakhapatnam, Proddatur and Nandyal.
    dm = cen[cen.src == "pin_median"].groupby(["state", "district"])[["best_lat", "best_lon"]].median()
    j = g.join(dm, on=["state", "district"])
    d_cons, d_dir = hav_km(j.cla, j.clo, j.best_lat, j.best_lon), hav_km(j.lat, j.lon, j.best_lat, j.best_lon)
    in_district = (d_cons <= 30) | (d_cons <= d_dir + 10) | j.best_lat.isna()
    st["override_candidates_rejected_outside_district"] = int((over & ~in_district).sum())
    over = over & in_district
    st["pins_overridden_single_office_path"] = int((over & ~g.ok.fillna(False).astype(bool)).sum())
    st["pins_overridden_by_facility_consensus"] = int(over.sum())
    st["override_d_km_quantiles_50_90_max"] = g.loc[over, "d_consensus_km"].quantile([0.5, 0.9, 1]).round(1).tolist()
    g.loc[over, ["lat", "lon"]] = g.loc[over, ["cla", "clo"]].values
    g.loc[over, "src"] = "facility_consensus"

    # R2: facility PINs absent from the directory
    miss = sorted(set(f.pin.dropna().astype(int)) - set(g.pin))
    p3 = g.dropna(subset=["lat"]).assign(p3=lambda d: d.pin // 1000)
    p3m = p3.groupby("p3").agg(lat=("lat", "median"), lon=("lon", "median"),
                               state=("state", lambda s: s.mode().iat[0] if s.notna().any() else None))
    rows = []
    for pin in miss:
        c = con.loc[pin] if pin in con.index else None
        pm = p3m.loc[pin // 1000] if pin // 1000 in p3m.index else None
        if c is not None and c.ok:
            rows.append((pin, c.cla, c.clo, "facility_consensus_not_in_directory", pm.state if pm is not None else None))
        elif pm is not None:
            rows.append((pin, pm.lat, pm.lon, "prefix3_median_not_in_directory", pm.state))
    add = pd.DataFrame(rows, columns=["pin", "lat", "lon", "src", "state"])
    st["facility_pins_missing_from_directory"] = len(miss)
    st["missing_pins_added"] = add.src.value_counts().to_dict()
    g = pd.concat([g, add], ignore_index=True)

    # precision radius (km) for using the PIN point as a facility location
    base = g.spread_km_p90.fillna(5.0).clip(lower=2.0)
    g["radius_km"] = np.select(
        [g.src == "pin_median", g.src.str.startswith("facility_consensus", na=False), g.src == "district_median"],
        [np.where(g.n_used == 1, np.maximum(base, 10.0), base), g.c_spread.fillna(2.0).clip(lower=2.0), 25.0],
        50.0).round(1)
    g["radius_km"] = g.radius_km.clip(upper=50.0)
    st["pins_with_point_after"] = int(g.lat.notna().sum())
    st["src_after"] = g.src.value_counts(dropna=False).to_dict()
    st["radius_km_quantiles_50_90"] = g.radius_km.quantile([0.5, 0.9]).tolist()

    # validation against known points (before = directory point, after = repaired point)
    k = g.set_index("pin")
    val = []
    for pin, (la, lo) in {**KNOWN, **KNOWN_EXTRA}.items():
        r = k.loc[pin]
        val.append((pin, round(float(hav_km(la, lo, r.dir_lat, r.dir_lon)), 1), round(float(hav_km(la, lo, r.lat, r.lon)), 1), r.src))
    v = pd.DataFrame(val, columns=["pin", "err_before_km", "err_after_km", "src"])
    st["known_points"] = v.values.tolist()
    st["known20_within_10km_before_after"] = [int((v.err_before_km[:20] <= 10).sum()), int((v.err_after_km[:20] <= 10).sum())]
    out = g[["pin", "state", "district", "districts", "lat", "lon", "src", "radius_km", "n_used", "n_fac",
             "dir_lat", "dir_lon", "d_consensus_km"]]
    out.to_parquet(OUT / "pin_gazetteer.parquet", index=False)
    (OUT / "s1_stats.json").write_text(json.dumps(st, indent=1, default=str))
    print(json.dumps(st, indent=1, default=str))
    assert out.pin.is_unique
    assert v.err_after_km.iloc[20:].max() < 15, "repair must fix the two verifier counter-examples"


if __name__ == "__main__":
    main()
