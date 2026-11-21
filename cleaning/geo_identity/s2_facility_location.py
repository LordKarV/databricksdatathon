"""Step 2: one resolved location per facility, with source, precision radius, confidence, flags,
a plain-language note that cites the conflicting fields, and a district + NFHS-5 key.

Trust order (GEO-02, PROV-06): stated state bounds everything; postcode and city set the town;
listing coordinates give the fine position only when they agree with the postcode.
Decision for a record with both coordinates and a postcode point, d = distance between them:
  d <= max(10, PIN radius)  coordinates, high (city-level point -> medium, radius 10 km)
  d <= 25                   coordinates, medium
  d <= 50                   coordinates, low ('approximate')
  d >  50                   conflict, first rule that applies:
     a  a mappls link whose place slug names this facility puts it within 25 km of the postcode -> link point, medium
     a2 the address city resolves (directory only) to one point in the stated state: whichever of postcode /
        coordinates lies near it wins; if neither does, the city centre is used, disputed
     b  stated state agrees with exactly one of postcode / coordinates -> that one, low
     c  city matches only the coordinates -> coordinates, low ('postcode looks wrong')
     d  city matches only the postcode -> postcode point, low
     e  otherwise -> postcode point, 'disputed' (the coordinates kept as alt point)
Agreeing postcode and coordinates are marked 'disputed' when the address city resolves to a place
more than max(40 km, its own tolerance) away and matches neither (Kaithal hospital with a Karnal postcode and Karnal coordinates).
Records missing one side fall back to the other, with lower confidence.
Writes facility_location.parquet and s2_stats.json.
"""
import base64
import json
import re

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from common import AUDIT_GEO, OUT, facilities, hav_km, nearest, norm, parse_pin
from places import build_layers, city_point
from district_assign import nfhs_table  # audit/geo: NFHS names normalised the same way as the map

ZD = re.compile(r"mappls\.com/place-([^@\s\"]+)@zdata=([A-Za-z0-9+/]+=*)")
STATE_EXTRA = {  # 'unresolved' stated-state values that are unambiguous places (GEO-05 asked to extend)
    "navi mumbai": "MAHARASHTRA", "navi-mumbai": "MAHARASHTRA", "pimpri chinchwad": "MAHARASHTRA",
    "mira road": "MAHARASHTRA", "kushinagar": "UTTAR PRADESH", "mohali": "PUNJAB", "ahmedabad": "GUJARAT",
    "dakshin kannad": "KARNATAKA", "north 24 parganas": "WEST BENGAL", "south 24 parganas": "WEST BENGAL",
    "mangalore": "KARNATAKA", "mysore": "KARNATAKA", "trivandrum": "KERALA", "kanpur": "UTTAR PRADESH",
    "gomti nagar": "UTTAR PRADESH", "gomtinagar": "UTTAR PRADESH", "east singhbhum": "JHARKHAND",
    "jammu j k": "JAMMU AND KASHMIR", "hoogly": "WEST BENGAL", "bhatinda": "PUNJAB", "kutch": "GUJARAT",
    "mehsana": "GUJARAT", "paschim medinipur": "WEST BENGAL", "west medinipur": "WEST BENGAL",
    "uttar dinajpur": "WEST BENGAL", "west champaran": "BIHAR", "kanyakumari district": "TAMIL NADU",
    "gandhidham": "GUJARAT", "bijapur karnataka": "KARNATAKA", "north cachar hills": "ASSAM",
}
NFHS_NONE = {("MIZORAM", "SAIHA"): "NFHS-5 has no Saiha row (its Mizoram 'Chandel' row copies Manipur's Chandel)",
             ("WEST BENGAL", "PURBA BARDHAMAN"): "NFHS-5 has no Purba Bardhaman row"}


def decode_zdata(m: str):
    try:
        t = base64.b64decode(m + "=" * (-len(m) % 4)).decode("ascii", "ignore")
    except ValueError:
        return None
    x = re.match(r"(-?\d+\.\d+)\+(-?\d+\.\d+)", t)
    return (float(x.group(1)), float(x.group(2))) if x else None


def mappls_points(f):
    """Name-matched mappls points: the slug's leading words must match the facility name (ratio >= 85),
    because a record can carry mappls links for other facilities (verifier note on GEO-01)."""
    out = {}
    for r in f[["unique_id", "name", "source_urls"]].itertuples():
        for slug, z in ZD.findall(str(r.source_urls)):
            pt = decode_zdata(z)
            words = slug.split("-")[0].replace("+", " ")
            if pt and fuzz.token_set_ratio(norm(words), norm(r.name)) >= 85:
                out.setdefault(r.unique_id, []).append(pt)
    return out


def copied_geocodes(lat, lon, pin_lat, pin_lon, d_pin):
    """ID4 (verifier version): within 100 m of a record whose postcode point is > 30 km from this one,
    while this record is itself > 30 km from its own postcode."""
    flag = np.zeros(len(lat), bool)
    ok = np.isfinite(lat) & np.isfinite(pin_lat)
    idx = np.where(ok)[0]
    la, lo, pla, plo = lat[idx], lon[idx], pin_lat[idx], pin_lon[idx]
    for s in range(0, len(idx), 500):
        d = hav_km(la[s:s + 500, None], lo[s:s + 500, None], la, lo)
        dp = hav_km(pla[s:s + 500, None], plo[s:s + 500, None], pla, plo)
        hit = ((d < 0.1) & (dp > 30)).any(axis=1)
        flag[idx[s:s + 500]] = hit
    return flag & (d_pin > 30)


def choose(r) -> dict:
    """Pick the location for one record. Returns source, lat, lon, radius, confidence, alt point, flags, note."""
    c_ok, p_ok = r.c_ok, pd.notna(r.p_lat)
    city = r.address_city if isinstance(r.address_city, str) else "?"
    pin_txt = f"postcode {int(r.pin)}" if pd.notna(r.pin) else "no postcode"
    flags, alt = [], (None, None)
    cp = (r.city_lat, r.city_lon) if pd.notna(r.city_lat) else None
    tol = max(30.0, 1.5 * r.city_spread) if cp else None
    if c_ok and p_ok:
        d = r.d_pin
        if cp and d <= 50:
            dc = float(hav_km(r.lat, r.lon, *cp))
            # threshold loosened from max(50, 2*tol) after the Kaithal ground-truth miss (see REPORT)
            if dc > max(40.0, tol) and not r.city_match_pin and not r.city_match_near:
                return dict(src="listing_coordinates", lat=r.lat, lon=r.lon, radius=max(10.0, d), conf="disputed", flags=["city_points_elsewhere"], alt=cp,
                            note=f"Listing coordinates and {pin_txt} agree ({r.p_district}), but the address city '{city}' is a place {dc:.0f} km away. Confirm which town before travelling.")
        if d <= max(10.0, r.p_radius):
            if r.city_level_point:
                return dict(src="listing_coordinates", lat=r.lat, lon=r.lon, radius=10.0, conf="medium",
                            flags=["city_level_point"], note=f"Listing coordinates agree with {pin_txt} but look like a city-centre point shared by other listings.")
            return dict(src="listing_coordinates", lat=r.lat, lon=r.lon, radius=1.0, conf="high", flags=[],
                        note=f"Listing coordinates agree with {pin_txt} ({d:.1f} km from its centre).")
        if d <= 25:
            return dict(src="listing_coordinates", lat=r.lat, lon=r.lon, radius=round(max(2.0, d / 2), 1), conf="medium",
                        flags=["coords_pin_10_25km"], note=f"Listing coordinates are {d:.0f} km from the centre of {pin_txt}; position approximate.")
        if d <= 50:
            return dict(src="listing_coordinates", lat=r.lat, lon=r.lon, radius=round(d / 2, 1), conf="low",
                        flags=["coords_pin_25_50km"], note=f"Listing coordinates are {d:.0f} km from the centre of {pin_txt}; position approximate.")
        flags.append("coords_pin_conflict_gt50km")
        alt = (r.lat, r.lon)
        base = f"Listing coordinates are {d:.0f} km from {pin_txt} ({r.p_district}, {r.p_state}); address city is '{city}'."
        if r.mappls_lat is not None:
            return dict(src="map_link", lat=r.mappls_lat, lon=r.mappls_lon, radius=2.0, conf="medium", flags=flags + ["map_link_used"], alt=alt,
                        note=base + f" A map link for this facility's name places it {r.mappls_d_pin:.0f} km from the postcode, so that point is used.")
        if cp:
            near_p = float(hav_km(r.p_lat, r.p_lon, *cp)) <= tol
            near_c = float(hav_km(r.lat, r.lon, *cp)) <= tol
            if near_c and not near_p:
                return dict(src="listing_coordinates", lat=r.lat, lon=r.lon, radius=10.0, conf="low", flags=flags + ["city_confirms_coords"], alt=(r.p_lat, r.p_lon),
                            note=base + f" '{city}' lies near the coordinates, not the postcode, so the coordinates are used.")
            if near_p and not near_c:
                return dict(src="postcode_centre", lat=r.p_lat, lon=r.p_lon, radius=max(r.p_radius, 10.0), conf="low", flags=flags + ["city_confirms_pin"], alt=alt,
                            note=base + f" '{city}' lies near the postcode, so the postcode centre is used (accurate to about {max(r.p_radius, 10.0):.0f} km).")
            if not near_p and not near_c:
                rad = round(max(10.0, r.city_spread), 1)
                # 'disputed', not 'low': in a 15-record hand check the city was right in about half
                return dict(src="address_city_centre", lat=cp[0], lon=cp[1], radius=rad, conf="disputed", flags=flags + ["both_points_elsewhere"], alt=alt,
                            note=base + f" Neither point is near '{city}'; the centre of '{city}' is used, but this record probably mixes several places. Confirm by phone.")
        s, sp, sc = r.state_final_stated, r.p_state, r.near_state
        if s and sp == s and sc != s:
            return dict(src="postcode_centre", lat=r.p_lat, lon=r.p_lon, radius=max(r.p_radius, 10.0), conf="low", flags=flags + ["coords_other_state"], alt=alt,
                        note=base + f" The coordinates fall in {sc}, the stated state is {s}, so the postcode centre is used.")
        if s and sc == s and sp != s:
            return dict(src="listing_coordinates", lat=r.lat, lon=r.lon, radius=10.0, conf="low", flags=flags + ["pin_other_state"], alt=(r.p_lat, r.p_lon),
                        note=base + f" The postcode belongs to {sp}, the stated state is {s}, so the coordinates are used.")
        if r.city_match_near and not r.city_match_pin:
            return dict(src="listing_coordinates", lat=r.lat, lon=r.lon, radius=10.0, conf="low", flags=flags + ["pin_looks_wrong"], alt=(r.p_lat, r.p_lon),
                        note=base + " The city matches the coordinates, not the postcode, so the coordinates are used.")
        if r.city_match_pin and not r.city_match_near:
            return dict(src="postcode_centre", lat=r.p_lat, lon=r.p_lon, radius=max(r.p_radius, 10.0), conf="low", flags=flags + ["coords_look_wrong"], alt=alt,
                        note=base + f" The city matches the postcode, so the postcode centre is used (accurate to about {max(r.p_radius, 10.0):.0f} km).")
        return dict(src="postcode_centre", lat=r.p_lat, lon=r.p_lon, radius=max(r.p_radius, 25.0), conf="disputed", flags=flags + ["location_disputed"], alt=alt,
                    note=base + " Nothing settles which is right; the postcode centre is used and the location should be confirmed by phone.")
    if c_ok:
        miss = "postcode not in the India Post directory" if pd.notna(r.pin) else "no valid postcode"
        good = r.city_match_near or (r.state_final_stated and r.state_final_stated == r.near_state)
        return dict(src="listing_coordinates", lat=r.lat, lon=r.lon, radius=5.0 if good else 10.0, conf="medium" if good else "low",
                    flags=["no_pin_point"], note=f"Listing coordinates only ({miss}); " + ("city or state agrees with them." if good else "nothing else confirms them."))
    if p_ok:
        conf = "medium" if r.city_match_pin else "low"
        why = "coordinates outside India" if r.c_outside else "no coordinates"
        return dict(src="postcode_centre", lat=r.p_lat, lon=r.p_lon, radius=max(r.p_radius, 5.0), conf=conf, flags=["no_coordinates"],
                    note=f"Centre of {pin_txt} used ({why}); accurate to about {max(r.p_radius, 5.0):.0f} km.")
    return dict(src="none", lat=None, lon=None, radius=None, conf="none", flags=["no_location"], note="No usable coordinates or postcode.")


def main():
    f = facilities()
    gz = pd.read_parquet(OUT / "pin_gazetteer.parquet").set_index("pin")
    ag = pd.read_parquet(AUDIT_GEO / "facility_geo.parquet").drop_duplicates("unique_id").set_index("unique_id")
    ms = pd.read_parquet(AUDIT_GEO / "merge_signal.parquet").drop_duplicates("unique_id").set_index("unique_id")
    st = {"facilities": len(f)}

    f["pin"] = f.address_zipOrPostcode.map(parse_pin)
    f["lat"], f["lon"] = f.latitude.astype(float), f.longitude.astype(float)
    f["c_outside"] = ~(f.lat.between(6, 37.6) & f.lon.between(68, 97.6))
    f["c_ok"] = ~f.c_outside
    for c in ["state_n", "state_how", "city_match_pin", "city_match_near", "coord_dup_names"]:
        f[c] = f.unique_id.map(ag[c])
    f["other_pin_district_in_text"] = f.unique_id.map(ms.other_pin_district).fillna(False).astype(bool)
    extra = f.address_stateOrRegion.map(lambda s: STATE_EXTRA.get(norm(s)))
    f["state_final_stated"] = f.state_n.where(f.state_n.isin(set(gz.state.dropna())), extra)
    f["state_final_stated"] = f.state_final_stated.where(f.state_final_stated.notna(), None)
    st["stated_state_resolved_before_after"] = [int(f.state_n.isin(set(gz.state.dropna())).sum()), int(f.state_final_stated.notna().sum())]

    j = gz.reindex(f.pin)
    f["p_lat"], f["p_lon"], f["p_radius"] = j.lat.values, j.lon.values, j.radius_km.values
    f["p_state"], f["p_district"], f["p_src"] = j.state.values, j.district.values, j.src.values
    f["d_pin"] = np.where(f.c_ok, hav_km(f.lat, f.lon, f.p_lat, f.p_lon), np.nan)
    f["city_level_point"] = (f.coord_dup_names >= 3) | ((f.lat.round(2) == f.lat) & (f.lon.round(2) == f.lon))

    # nearest trusted gazetteer point to the coordinates -> coordinate state/district
    ref = gz[gz.src.isin(["pin_median", "facility_consensus"])].dropna(subset=["lat"]).reset_index()
    idx, dist = nearest(f.lat.where(f.c_ok, 0).values, f.lon.where(f.c_ok, 0).values, ref.lat.values, ref.lon.values)
    f["near_state"] = np.where(f.c_ok, ref.state.values[idx], None)
    f["near_district"] = np.where(f.c_ok, ref.district.values[idx], None)

    layers = build_layers()
    look_state = f.state_final_stated.fillna(f.p_state)

    def place_of(r, st_):
        hit = city_point(r.address_city, st_, layers)
        if hit is None and r.state_how == "district_name":  # state field holds a district ('Kollam')
            hit = city_point(r.address_stateOrRegion, st_, layers)
        return hit

    cps = [place_of(r, s_) for r, s_ in zip(f.itertuples(), look_state)]
    f["city_lat"] = [c[0] if c else None for c in cps]
    f["city_lon"] = [c[1] if c else None for c in cps]
    f["city_spread"] = [c[3] if c else 0.0 for c in cps]
    st["records_with_city_point"] = [int(f.city_lat.notna().sum()), len(f)]
    st["city_point_kind"] = pd.Series([c[2] for c in cps if c]).value_counts().to_dict()

    mp = mappls_points(f)
    st["records_with_name_matched_mappls_point"] = len(mp)

    def best_mappls(r):
        pts = mp.get(r.unique_id, [])
        if not pts or pd.isna(r.p_lat):
            return None, None, None
        d = [float(hav_km(a, b, r.p_lat, r.p_lon)) for a, b in pts]
        k = int(np.argmin(d))
        return (pts[k][0], pts[k][1], d[k]) if d[k] <= 25 else (None, None, None)

    m3 = f.apply(best_mappls, axis=1, result_type="expand")
    f["mappls_lat"], f["mappls_lon"], f["mappls_d_pin"] = m3[0], m3[1], m3[2]
    f["mappls_lat"] = f.mappls_lat.astype(object).where(f.mappls_lat.notna(), None)

    res = pd.DataFrame([choose(r) for r in f.itertuples()])
    f = pd.concat([f, res.add_prefix("loc_")], axis=1)
    f["alt_lat"] = f.loc_alt.map(lambda t: t[0] if isinstance(t, tuple) else None)
    f["alt_lon"] = f.loc_alt.map(lambda t: t[1] if isinstance(t, tuple) else None)

    # record-level location flags that do not change the point but lower confidence
    f["copied_geocode"] = copied_geocodes(f.lat.values, f.lon.values, f.p_lat.values, f.p_lon.values, f.d_pin.fillna(0).values)
    extra_flags = {"other_pin_district_in_text": "address or description carries a postcode from another postal district",
                   "copied_geocode": "coordinates are shared with a listing in another town"}
    for col, why in extra_flags.items():
        hit = f[col]
        f.loc[hit, "loc_flags"] = f.loc[hit, "loc_flags"].map(lambda x, c=col: x + [c])
        f.loc[hit, "loc_note"] = f.loc[hit, "loc_note"] + f" Also: {why}."
        f.loc[hit & (f.loc_conf == "high"), "loc_conf"] = "medium"
    sv = f.state_final_stated.notna() & f.p_state.notna() & (f.state_final_stated != f.p_state)
    f.loc[sv, "loc_flags"] = f.loc[sv, "loc_flags"].map(lambda x: x + ["stated_state_vs_pin_state"])

    # state used for filters: stated state, else postcode state, else coordinate state (GEO-05)
    f["state_final"] = f.state_final_stated.fillna(f.p_state).fillna(f.near_state)

    # district: postcode district when the chosen point is within 50 km of the postcode point,
    # else the district of the nearest trusted postcode point to the chosen point
    has = f.loc_lat.notna()
    li, _ = nearest(f.loc_lat.fillna(0).astype(float).values, f.loc_lon.fillna(0).astype(float).values, ref.lat.values, ref.lon.values)
    d_best_pin = hav_km(f.loc_lat.astype(float), f.loc_lon.astype(float), f.p_lat, f.p_lon)
    use_pin = has & f.p_district.notna() & (d_best_pin <= 50)
    f["district_src"] = np.select([use_pin, has], ["postcode", "map_point"], "none")
    f["district"] = np.select([use_pin, has], [f.p_district, ref.district.values[li]], None)
    f["district_state"] = np.select([use_pin, has], [f.p_state, ref.state.values[li]], None)
    f["district_boundary_note"] = use_pin & f.c_ok & f.near_district.notna() & (f.near_district != f.p_district) & (f.d_pin <= 50)
    f["district_note"] = np.select(
        [f.district_src == "map_point", f.district_boundary_note],
        ["District taken from the map position because the postcode does not fit it.",
         "District from postcode; the listing coordinates fall in neighbouring " + f.near_district.fillna("").astype(str) + "."], "")

    # NFHS-5 key via the audit's reviewed directory-district map
    dm = pd.read_csv(AUDIT_GEO / "district_nfhs_map.csv").set_index(["state", "district"])
    nt = nfhs_table().drop_duplicates(["state", "dn"]).set_index(["state", "dn"])
    keys = list(zip(f.district_state, f.district))
    f["nfhs_how"] = [dm.how.get(k) if k in dm.index else None for k in keys]
    dn = [dm.final_dn.get(k) if k in dm.index else None for k in keys]
    nrow = [nt.loc[(s, d)] if isinstance(d, str) and (s, d) in nt.index else None for (s, _), d in zip(keys, dn)]
    f["nfhs_state_ut"] = [x.state_ut if x is not None else None for x in nrow]
    f["nfhs_district_name"] = [x.district_name if x is not None else None for x in nrow]
    blocked = pd.Series([k in NFHS_NONE for k in keys])
    st["nfhs_blocked_missing_or_copied_row"] = int(blocked.sum())
    f.loc[blocked.values, ["nfhs_state_ut", "nfhs_district_name"]] = None
    f.loc[blocked.values, "nfhs_how"] = "no_nfhs_row"
    f["nfhs_note"] = np.select([f.nfhs_how.isin(["parent_table", "spatial_parent"]), blocked.values],
                               ["NFHS-5 figures are for the parent district (pre-split boundaries).",
                                [NFHS_NONE.get(k, "") for k in keys]], "")

    # ---- stats: before (raw coordinates vs repaired PIN point) and after (chosen point)
    st["loc_src"] = f.loc_src.value_counts().to_dict()
    st["loc_conf"] = f.loc_conf.value_counts().to_dict()
    st["flag_counts"] = pd.Series([x for fl in f.loc_flags for x in fl]).value_counts().to_dict()
    st["raw_coords_gt50km_from_repaired_pin"] = [int((f.d_pin > 50).sum()), int(f.d_pin.notna().sum())]
    old = ag.reindex(f.unique_id).d_pin_km
    st["raw_coords_gt50km_from_audit_pin"] = [int((old > 50).sum()), int(old.notna().sum())]
    st["raw_coords_10_50km_audit_vs_repaired"] = [int(old.between(10, 50).sum()), int(f.d_pin.between(10, 50).sum())]
    st["district_src"] = f.district_src.value_counts().to_dict()
    st["district_boundary_note"] = int(f.district_boundary_note.sum())
    st["nfhs_joined"] = [int(f.nfhs_district_name.notna().sum()), len(f)]
    st["nfhs_how"] = f.nfhs_how.fillna("no_district").value_counts().to_dict()
    st["state_final_missing"] = int(f.state_final.isna().sum())

    keep = ["unique_id", "name", "address_city", "address_stateOrRegion", "pin", "lat", "lon", "d_pin", "p_src",
            "loc_src", "loc_lat", "loc_lon", "loc_radius", "loc_conf", "loc_flags", "loc_note", "alt_lat", "alt_lon",
            "state_final", "district", "district_state", "district_src", "district_note",
            "nfhs_state_ut", "nfhs_district_name", "nfhs_how", "nfhs_note"]
    out = f[keep].rename(columns={"lat": "raw_lat", "lon": "raw_lon", "d_pin": "raw_coords_to_pin_km"})
    for c in ["loc_lat", "loc_lon", "alt_lat", "alt_lon", "loc_radius"]:
        out[c] = pd.to_numeric(out[c])
    out.to_parquet(OUT / "facility_location.parquet", index=False)
    (OUT / "s2_stats.json").write_text(json.dumps(st, indent=1, default=str))
    print(json.dumps(st, indent=1, default=str))
    assert out.unique_id.is_unique and len(out) == 9959
    assert (out.loc_lat.notna() == (out.loc_conf != "none")).all()


if __name__ == "__main__":
    main()
