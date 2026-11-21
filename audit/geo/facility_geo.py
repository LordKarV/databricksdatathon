"""Location consistency of facilities: PIN vs coordinates vs state vs city.

Writes facility_geo.parquet (one row per well-formed facility, all signals and flags)
and facility_geo_stats.json (every count quoted in FINDINGS.md).
Needs pin_centroids.parquet (run pin_centroids.py first).
Run: .venv/bin/python audit/geo/facility_geo.py
"""
import json
import sys

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo")
from geo_common import (CITY_ALIAS, GEO, PIN_DIR, STATE_ALIAS, ZONE, hav_km, load_facilities, nearest,
                        norm, office_base, parse_pin)

LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = 6.0, 37.6, 68.0, 97.6
DIST_BINS = [-0.01, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 5000]


def build_gazetteer():
    p = pd.read_parquet(PIN_DIR)
    p = p[p.statename != "NA"]
    p["dn"] = p.district.map(norm)
    p["on"] = p.officename.map(office_base)
    district_states = p.groupby("dn").statename.agg(lambda s: set(s))
    office_places = p.groupby("on").apply(lambda g: set(zip(g.statename, g.district)), include_groups=False)
    return p, district_states, office_places


def normalise_state(raw, canon, district_states):
    """Return (state, how). how in exact|alias|district_name|multi|unresolved."""
    n = norm(raw)
    if not n:
        return None, "empty"
    if ";" in str(raw):
        parts = {normalise_state(x, canon, district_states)[0] for x in str(raw).split(";")}
        return (parts.pop(), "exact") if len(parts) == 1 else ("MULTI", "multi")
    if n.upper() in canon:
        return n.upper(), "exact"
    if n in STATE_ALIAS:
        return STATE_ALIAS[n], "alias"
    if "," in str(raw):  # 'Kadapa, Andhra Pradesh'
        return normalise_state(str(raw).split(",")[-1], canon, district_states)
    n2 = norm(n.replace(" district", ""))
    if n2 in district_states and len(district_states[n2]) == 1:
        return next(iter(district_states[n2])), "district_name"
    return None, "unresolved"


def city_matches(city_n, names):
    """True if a normalised city matches any normalised district/office name."""
    if not city_n:
        return False
    for nm in names:
        if not nm:
            continue
        if city_n == nm or (len(city_n) >= 4 and (city_n in nm.split() or nm.startswith(city_n + " "))):
            return True
        if len(city_n) >= 5 and fuzz.ratio(city_n, nm) >= 88:
            return True
    return False


def main():
    f = load_facilities()
    cen = pd.read_parquet(GEO / "pin_centroids.parquet")
    p, district_states, _ = build_gazetteer()
    canon = set(cen.state.dropna())
    st = {"facilities": len(f)}

    # ---- PIN parsing
    f["pin"] = f.address_zipOrPostcode.map(parse_pin)
    st["pin_valid_format"] = int(f.pin.notna().sum())
    cen_i = cen.set_index("pincode")
    f["pin_in_dir"] = f.pin.isin(cen_i.index)
    st["pin_in_directory"] = int(f.pin_in_dir.sum())
    st["pin_valid_but_not_in_directory"] = int((f.pin.notna() & ~f.pin_in_dir).sum())
    j = cen_i.reindex(f.pin)
    f["pin_state"] = j.state.values
    f["pin_district"] = j.district.values
    f["pin_lat"], f["pin_lon"], f["pin_src"] = j.best_lat.values, j.best_lon.values, j.src.values
    f["pin_coarse"] = (j.coarse_share > 0.5).values

    # ---- coordinate anomalies
    lat, lon = f.latitude.astype(float), f.longitude.astype(float)
    f["coord_zero"] = (lat == 0) & (lon == 0)
    f["coord_swapped"] = lat.between(68, 98) & lon.between(6, 38)
    f["coord_outside"] = ~(lat.between(LAT_MIN, LAT_MAX) & lon.between(LON_MIN, LON_MAX))
    for k in ["coord_zero", "coord_swapped", "coord_outside"]:
        st[k] = int(f[k].sum())
    # coordinates JSON must agree with latitude/longitude
    cj = f.coordinates.map(lambda s: json.loads(s)["coordinates"] if s and s.startswith("{") else [np.nan, np.nan])
    f["coord_json_mismatch"] = (np.abs(cj.str[1] - lat) > 1e-4) | (np.abs(cj.str[0] - lon) > 1e-4)
    st["coord_json_mismatch"] = int(f.coord_json_mismatch.sum())

    # ---- duplicated coordinates
    key = lat.round(5).astype(str) + "," + lon.round(5).astype(str)
    f["coord_key"] = key
    grp = f.groupby("coord_key")
    f["coord_dup_n"] = grp.unique_id.transform("size")
    f["coord_dup_names"] = grp.name.transform(lambda s: s.map(norm).nunique())
    f["coord_dup_pins"] = grp.pin.transform("nunique")
    st["coord_points_shared_by_2plus"] = int((grp.size() >= 2).sum())
    st["facilities_on_shared_point_2plus"] = int((f.coord_dup_n >= 2).sum())
    st["facilities_on_shared_point_3plus_distinct_names"] = int((f.coord_dup_names >= 3).sum())
    st["facilities_on_shared_point_5plus_distinct_names"] = int((f.coord_dup_names >= 5).sum())
    top = f[f.coord_dup_n >= 5].groupby("coord_key").agg(n=("unique_id", "size"), names=("coord_dup_names", "first"),
                                                         pins=("pin", "nunique"), cities=("address_city", lambda s: sorted(set(s))[:5]),
                                                         ex=("unique_id", "first")).sort_values("n", ascending=False)
    st["top_shared_points"] = top.head(15).reset_index().astype(str).values.tolist()

    # ---- facility coords vs its PIN centroid
    good = ~f.coord_outside & f.pin_lat.notna()
    f["d_pin_km"] = np.where(good, hav_km(lat, lon, f.pin_lat, f.pin_lon), np.nan)
    st["pin_distance_denominator"] = int(good.sum())
    st["pin_distance_bins"] = pd.cut(f.d_pin_km, DIST_BINS).value_counts().sort_index().astype(int).rename(str).to_dict()
    st["pin_distance_quantiles"] = f.d_pin_km.quantile([0.5, 0.75, 0.9, 0.95, 0.99]).round(1).to_dict()

    # ---- nearest PIN centroid to the coordinates (coords-derived state/district)
    cc = cen.dropna(subset=["best_lat"]).reset_index(drop=True)
    inb = ~f.coord_outside
    idx, dist = nearest(lat[inb].values, lon[inb].values, cc.best_lat.values, cc.best_lon.values)
    for col, src in [("near_pin", "pincode"), ("near_state", "state"), ("near_district", "district")]:
        f[col] = None
        f.loc[inb, col] = cc[src].values[idx]
    f["near_km"] = np.nan
    f.loc[inb, "near_km"] = dist
    st["near_km_quantiles"] = f.near_km.quantile([0.5, 0.9, 0.99, 1.0]).round(1).to_dict()

    # ---- stated state
    ns = f.address_stateOrRegion.map(lambda r: normalise_state(r, canon, district_states))
    f["state_n"], f["state_how"] = ns.str[0], ns.str[1]
    st["state_how"] = f.state_how.value_counts().to_dict()

    # ---- PIN first digit vs stated state zone
    zstate = f.pin.map(lambda x: ZONE.get(int(str(x)[0]), set()) if pd.notna(x) else None)
    has = f.pin.notna() & f.state_n.isin(canon)
    f["zone_mismatch"] = has & np.array([z is not None and s not in z for s, z in zip(f.state_n, zstate)])
    st["zone_check_denominator"] = int(has.sum())
    st["zone_mismatch"] = int(f.zone_mismatch.sum())

    # ---- stated state vs PIN state vs coordinate state
    both = f.state_n.isin(canon) & f.pin_state.notna()
    f["state_vs_pin_mismatch"] = both & (f.state_n != f.pin_state)
    st["state_vs_pin_denominator"], st["state_vs_pin_mismatch"] = int(both.sum()), int(f.state_vs_pin_mismatch.sum())
    both = f.pin_state.notna() & f.near_state.notna()
    f["pin_vs_coord_state_mismatch"] = both & (f.pin_state != f.near_state)
    st["pin_vs_coord_state_denominator"], st["pin_vs_coord_state_mismatch"] = int(both.sum()), int(f.pin_vs_coord_state_mismatch.sum())
    both = f.state_n.isin(canon) & f.near_state.notna()
    f["state_vs_coord_mismatch"] = both & (f.state_n != f.near_state)
    st["state_vs_coord_denominator"], st["state_vs_coord_mismatch"] = int(both.sum()), int(f.state_vs_coord_mismatch.sum())

    # ---- city vs PIN district/offices, city vs coordinate district/offices
    pin_names = p.assign(on=p.officename.map(office_base), dn=p.district.map(norm)).groupby("pincode").apply(
        lambda g: set(g.on) | set(g.dn), include_groups=False)
    f["city_n"] = f.address_city.map(norm).map(lambda c: CITY_ALIAS.get(c, c))

    # India Post division/region names carry the metro name ('Hyderabad City Division' for a
    # Ranga Reddy PIN, 'Chennai City Region' for a Chengalpattu PIN); Delhi PINs use zone districts
    strip = r"\b(division|region|city|hq|north|south|east|west|central|moffusil|mofussil|rural|urban|new)\b"
    dv = p.assign(dv=(p.divisionname + " " + p.regionname.str.replace("DivReportingCircle", "")).map(norm)
                  .str.replace(strip, " ", regex=True).str.split())
    div_tokens = dv.groupby("pincode").dv.agg(lambda s: {t for x in s for t in x if len(t) >= 4})
    delhi_pins = set(p.loc[p.statename == "DELHI", "pincode"])

    def names_for(pin):
        if pd.isna(pin):
            return set()
        extra = {"delhi", "new delhi"} if pin in delhi_pins else set()
        return pin_names.get(pin, set()) | div_tokens.get(pin, set()) | extra

    f["city_match_pin"] = [city_matches(c, names_for(q)) for c, q in zip(f.city_n, f.pin)]
    f["city_match_near"] = [city_matches(c, names_for(q)) for c, q in zip(f.city_n, f.near_pin)]
    d = f.pin_in_dir
    st["city_check_denominator"] = int(d.sum())
    st["city_match_pin"] = int((d & f.city_match_pin).sum())
    st["city_match_near_only"] = int((d & ~f.city_match_pin & f.city_match_near).sum())
    st["city_match_neither"] = int((d & ~f.city_match_pin & ~f.city_match_near).sum())

    # ---- combined verdict per facility
    def verdict(r):
        sigs = {k: v for k, v in [("stated", r.state_n), ("pin", r.pin_state), ("coord", r.near_state)]
                if isinstance(v, str) and v in canon}
        vals = list(sigs.values())
        if len(vals) < 2:
            return "insufficient"
        if len(set(vals)) == 1:
            return "all_agree" if len(vals) == 3 else "two_agree_one_missing"
        odd = [k for k, v in sigs.items() if vals.count(v) == 1]
        return "odd_one_out:" + odd[0] if len(vals) == 3 and len(set(vals)) == 2 else "all_differ_or_split"

    f["state_verdict"] = f.apply(verdict, axis=1)
    st["state_verdict"] = f.state_verdict.value_counts().to_dict()

    # distance banding of the coordinate-vs-PIN disagreement, and joint flag
    f["geo_conflict"] = (f.d_pin_km > 50) | f.state_vs_pin_mismatch | f.pin_vs_coord_state_mismatch | f.coord_outside
    st["geo_conflict_any"] = int(f.geo_conflict.sum())
    keep = ["unique_id", "name", "address_line1", "address_line2", "address_line3", "address_city",
            "address_stateOrRegion", "address_zipOrPostcode", "latitude", "longitude", "pin", "pin_in_dir",
            "pin_state", "pin_district", "pin_lat", "pin_lon", "pin_src", "pin_coarse", "coord_zero", "coord_swapped",
            "coord_outside", "coord_json_mismatch", "coord_key", "coord_dup_n", "coord_dup_names", "coord_dup_pins",
            "d_pin_km", "near_pin", "near_state", "near_district", "near_km", "state_n", "state_how", "zone_mismatch",
            "state_vs_pin_mismatch", "pin_vs_coord_state_mismatch", "state_vs_coord_mismatch", "city_n",
            "city_match_pin", "city_match_near", "state_verdict", "geo_conflict"]
    f[keep].to_parquet(GEO / "facility_geo.parquet", index=False)
    (GEO / "facility_geo_stats.json").write_text(json.dumps(st, indent=1, default=str))
    print(json.dumps({k: v for k, v in st.items() if k != "top_shared_points"}, indent=1, default=str))
    print(*st["top_shared_points"], sep="\n")


if __name__ == "__main__":
    main()
