"""Build a cleaned PIN centroid table from india_post_pincode_directory.

Cleaning steps (each counted in pin_centroids_log.json):
1. parse lat/lon as plain decimals ('NA' and degree strings fail -> dropped)
2. (0,0) or one axis 0 -> dropped
3. swapped pairs (lat in 68..98 and lon in 6..38) -> swapped back, kept
4. outside the India bounding box after step 3 -> dropped
4b. placeholder latitude 15.59xx outside the states where it is plausible -> dropped
5. per-PIN median; offices > OUTLIER_KM from it -> dropped; median recomputed
6. state label outside the postal zone of the first PIN digit -> relabelled from
   the majority of its 3-digit prefix
7. centroid whose 15 nearest PIN centroids are mostly other states -> 'misplaced';
   so is one outside its state's 5-95 percentile box + 2 deg, or > 150 km from its district median;
   best point falls back to district median, then 3-digit-prefix median

Output: pin_centroids.parquet, one row per PIN present in the directory.
Run: .venv/bin/python audit/geo/pin_centroids.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from geo_common import DATA, ROOT, ZONE

OUT = ROOT / "audit/geo"
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 6.0, 37.6, 68.0, 97.6
OUTLIER_KM = 50.0  # ponytail: fixed radius; a big rural PIN rarely spans >50 km
KNN = 15
BOX_MARGIN = 2.0
DISTRICT_KM = 150.0
MISPLACED_SHARE = 0.2  # <3 of 15 nearest PIN centroids share the state


def hav_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def mode_or_none(s):
    s = s[s.notna() & (s != "NA")]
    return s.mode().iloc[0] if len(s) else None


def main():
    p = pd.read_parquet(DATA / "raw/india_post_pincode_directory.parquet")
    log = {"rows_total": len(p), "distinct_pins": int(p.pincode.nunique())}
    p["lat"] = pd.to_numeric(p.latitude, errors="coerce")
    p["lon"] = pd.to_numeric(p.longitude, errors="coerce")
    unparsed = p.lat.isna() | p.lon.isna()
    log["dropped_unparsed"] = int(unparsed.sum())
    log["dropped_unparsed_literal_NA"] = int(((p.latitude == "NA") | (p.longitude == "NA")).sum())
    zero = ~unparsed & ((p.lat == 0) | (p.lon == 0))
    log["dropped_zero"] = int(zero.sum())
    swapped = ~unparsed & ~zero & p.lat.between(68, 98) & p.lon.between(6, 38)
    log["swapped_fixed"] = int(swapped.sum())
    p.loc[swapped, ["lat", "lon"]] = p.loc[swapped, ["lon", "lat"]].values
    inbox = p.lat.between(LAT_MIN, LAT_MAX) & p.lon.between(LON_MIN, LON_MAX)
    outside = ~unparsed & ~zero & ~inbox
    log["dropped_outside_india_bbox"] = int(outside.sum())
    log["outside_examples"] = p.loc[outside, ["pincode", "officename", "latitude", "longitude"]].head(8).astype(str).values.tolist()
    # placeholder latitude 15.5934 / 15.59 (1,065 offices, 669 of them in Gujarat, 223 in Kerala);
    # it is a real latitude only in Goa, Karnataka, Andhra Pradesh and Maharashtra
    sentinel = ~unparsed & ~zero & inbox & p.lat.between(15.5895, 15.5935) & ~p.statename.isin(
        ["GOA", "KARNATAKA", "ANDHRA PRADESH", "MAHARASHTRA"])
    log["dropped_sentinel_lat_15_59"] = int(sentinel.sum())
    ok = p[~unparsed & ~zero & inbox & ~sentinel].copy()

    # a coordinate shared by offices of >= 3 different PINs is a coarse geocode (district or
    # state default point, e.g. 21.5,81.5 for 300 Chhattisgarh offices). A PIN's centroid uses
    # only its non-coarse offices when it has any (686587 Vayala: 2 coarse BOs outvoted the SO).
    ok["coarse"] = ok.groupby(["lat", "lon"]).pincode.transform("nunique") >= 3
    log["offices_on_shared_coarse_point"] = int(ok.coarse.sum())
    has_fine = ok.groupby("pincode").coarse.transform("min") == False  # noqa: E712
    ok["pref"] = ~ok.coarse | ~has_fine
    med = ok[ok.pref].groupby("pincode")[["lat", "lon"]].median().rename(columns={"lat": "mlat", "lon": "mlon"})
    ok = ok.join(med, on="pincode")
    ok["d_med"] = hav_km(ok.lat, ok.lon, ok.mlat, ok.mlon)
    far = ok.d_med > OUTLIER_KM
    log["dropped_far_from_pin_median"] = int(far.sum())
    log["far_examples"] = ok.loc[far, ["pincode", "officename", "district", "latitude", "longitude", "d_med"]].head(8).round(1).astype(str).values.tolist()
    ok = ok[~far]
    log["offices_kept"] = len(ok)
    log["offices_kept_but_not_used_coarse"] = int((~ok.pref).sum())

    g = ok[ok.pref].groupby("pincode")
    cen = g[["lat", "lon"]].median()
    cen["coarse_share"] = g.coarse.mean().round(2)
    cen["n_used"] = g.size()
    ok = ok.join(cen[["lat", "lon"]].rename(columns={"lat": "clat", "lon": "clon"}), on="pincode")
    ok["d_c"] = hav_km(ok.lat, ok.lon, ok.clat, ok.clon)
    cen["spread_km_p90"] = ok.groupby("pincode").d_c.quantile(0.9).round(2)

    # attributes come from ALL offices of the PIN, not just geocoded ones
    ga = p.groupby("pincode")
    attrs = pd.DataFrame({
        "n_offices": ga.size(),
        "state": ga.statename.agg(mode_or_none),
        "n_states": ga.statename.agg(lambda s: s[s != "NA"].nunique()),
        "district": ga.district.agg(mode_or_none),
        "districts": ga.district.agg(lambda s: sorted(set(s) - {"NA"})),
        "circle": ga.circlename.agg(mode_or_none),
        "offices": ga.officename.agg(lambda s: sorted(set(s))),
    })
    out = attrs.join(cen, how="left").reset_index()
    log["pins_with_centroid"] = int(out.lat.notna().sum())
    log["pins_without_centroid"] = int(out.lat.isna().sum())
    log["pins_multi_state"] = int((out.n_states > 1).sum())
    log["pins_state_unknown"] = int(out.state.isna().sum())

    # state label sanity: the first PIN digit fixes the postal zone; a label outside it
    # (e.g. 799001 Agartala labelled TELANGANA/Nirmal) is replaced by the majority state of
    # the same 3-digit prefix among PINs whose label passes
    out["p3"] = out.pincode // 1000
    out["zone_ok"] = [s in ZONE.get(pc // 100000, set()) for s, pc in zip(out.state, out.pincode)]
    good3 = out[out.zone_ok].groupby("p3").state.agg(lambda s: s.mode().iloc[0])
    bad = ~out.zone_ok & out.state.notna()
    log["pins_state_label_outside_zone"] = int(bad.sum())
    log["pins_state_label_outside_zone_examples"] = out.loc[bad, ["pincode", "state", "district"]].head(8).astype(str).values.tolist()
    out["state_raw"] = out.state
    out.loc[~out.zone_ok, "state"] = out.loc[~out.zone_ok, "p3"].map(good3)
    log["pins_state_relabelled"] = int((bad & out.state.notna()).sum())

    # spatial sanity: a PIN whose centroid sits among PINs of other states is misplaced
    # (e.g. 13 Pratapgarh UP PINs geocoded into Raipur, Chhattisgarh). k nearest centroids.
    has = out.lat.notna().values
    la, lo = out.lat.values[has], out.lon.values[has]
    st_arr = out.state.astype(object).to_numpy()[has]
    share = np.empty(has.sum())
    kc = np.cos(np.radians(22.0))
    for i in range(0, len(la), 500):
        d = (la[i:i + 500, None] - la) ** 2 + ((lo[i:i + 500, None] - lo) * kc) ** 2
        nn = np.argpartition(d, KNN + 1, axis=1)[:, 1:KNN + 1]
        share[i:i + 500] = (st_arr[nn] == st_arr[i:i + 500, None]).mean(axis=1)
    out["knn_same_state"] = np.nan
    out.loc[has, "knn_same_state"] = share
    # second rule for whole misplaced clusters (35 Pratapgarh UP PINs sit together in Raipur,
    # so kNN sees each other): outside the state's 5th-95th percentile box + BOX_MARGIN deg
    q = out[has].groupby("state")[["lat", "lon"]].quantile([0.05, 0.95]).unstack()
    lo_lat, hi_lat = out.state.map(q[("lat", 0.05)]) - BOX_MARGIN, out.state.map(q[("lat", 0.95)]) + BOX_MARGIN
    lo_lon, hi_lon = out.state.map(q[("lon", 0.05)]) - BOX_MARGIN, out.state.map(q[("lon", 0.95)]) + BOX_MARGIN
    out["outside_state_box"] = has & ~(out.lat.between(lo_lat, hi_lat) & out.lon.between(lo_lon, hi_lon))
    log["pins_outside_state_box"] = int(out.outside_state_box.sum())
    log["pins_outside_state_box_by_state"] = {"/".join(k): int(v) for k, v in out.loc[out.outside_state_box].groupby(["state", "district"]).size().sort_values(ascending=False).head(12).items()}
    out["misplaced"] = (out.knn_same_state < MISPLACED_SHARE) | out.outside_state_box
    # third rule, within-state misplacement (134118 Panchkula geocoded near Hisar): > DISTRICT_KM from
    # the median of the district's other not-yet-misplaced PIN centroids
    ref = out[has & ~out.misplaced].groupby(["state", "district"])[["lat", "lon"]].median().set_axis(["rlat", "rlon"], axis=1)
    rj = out.join(ref, on=["state", "district"])
    out["far_from_district"] = (hav_km(rj.lat, rj.lon, rj.rlat, rj.rlon) > DISTRICT_KM).values
    log["pins_far_from_district"] = int((out.far_from_district & ~out.misplaced).sum())
    log["pins_far_from_district_by_district"] = {"/".join(k): int(v) for k, v in out[out.far_from_district & ~out.misplaced].groupby(["state", "district"]).size().sort_values(ascending=False).head(10).items()}
    out["misplaced"] = out.misplaced | out.far_from_district
    log["pins_misplaced_knn_only"] = int((out.knn_same_state < MISPLACED_SHARE).sum())
    log["pins_misplaced_total"] = int(out.misplaced.sum())
    log["pins_misplaced_examples"] = out.loc[out.misplaced, ["pincode", "state", "district", "lat", "lon", "knn_same_state"]].head(10).astype(str).values.tolist()

    # fallback point for misplaced PINs: median of trusted PINs in the same district, then prefix
    trusted = out[out.lat.notna() & ~out.misplaced]
    dm = trusted.groupby(["state", "district"])[["lat", "lon"]].median().set_axis(["dlat", "dlon"], axis=1)
    pm = trusted.groupby("p3")[["lat", "lon"]].median().set_axis(["plat", "plon"], axis=1)
    out = out.join(dm, on=["state", "district"]).join(pm, on="p3")
    own = out.lat.notna() & ~out.misplaced
    src = np.select([own, out.dlat.notna(), out.plat.notna()], ["pin_median", "district_median", "prefix3_median"], None)
    out["src"] = src
    out["best_lat"] = np.select([own, out.dlat.notna()], [out.lat, out.dlat], out.plat)
    out["best_lon"] = np.select([own, out.dlat.notna()], [out.lon, out.dlon], out.plon)
    out["d_district_km"] = hav_km(out.lat, out.lon, out.dlat, out.dlon).round(1)
    log["pins_coarse_majority"] = int((out.coarse_share > 0.5).sum())
    log["pins_best_point_source"] = {str(k): int(v) for k, v in out.src.value_counts(dropna=False).items()}
    log["spread_p90_km_quantiles"] = out.spread_km_p90.quantile([0.5, 0.9, 0.99]).round(1).tolist()
    out = out.drop(columns=["dlat", "dlon", "plat", "plon"])
    out.to_parquet(OUT / "pin_centroids.parquet", index=False)
    (OUT / "pin_centroids_log.json").write_text(json.dumps(log, indent=1, default=str))
    print(json.dumps(log, indent=1, default=str))
    # self-check: the drop counts must add up
    assert log["rows_total"] == log["dropped_unparsed"] + log["dropped_zero"] + log["dropped_outside_india_bbox"] + log["dropped_sentinel_lat_15_59"] + log["dropped_far_from_pin_median"] + log["offices_kept"]


if __name__ == "__main__":
    main()
