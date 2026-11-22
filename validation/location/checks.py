"""Location, geography and outside-source matching audit (read-only).

Every check_<name>() returns dict(name, status pass|warn|fail, metric, threshold, detail, examples).
Exhaustive checks recompute from the data each run. Sample checks re-draw the fixed-seed sample
(samples.py, match_samples.py) and score it with the hand verdicts in judgments/*.csv; a sample that no
longer matches its verdict file fails as stale instead of reporting a number for the wrong rows.
A check that cannot run returns status 'warn' with metric 'not_run'.

Run all: .venv-viz/bin/python validation/location/checks.py  (writes out/checks.json)
"""
import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import (EXT, GEO, HERE, INDIA_BBOX, JUDG, OUT, ROOT, V1, dist_to_districts_km, hav_km,  # noqa: E402
                    lgd_city_districts, lgd_pin_districts, loc, nstate, norm, parse_pin, pin_gz, pip_lgd, raw,
                    result, wilson)
import match_samples as ms  # noqa: E402
import samples as sm  # noqa: E402

CITY_ALIAS = {"bangalore": "bengaluru", "mangalore": "mangaluru", "mysore": "mysuru", "gurgaon": "gurugram",
              "trivandrum": "thiruvananthapuram", "calicut": "kozhikode", "bombay": "mumbai", "calcutta": "kolkata",
              "madras": "chennai", "pondicherry": "puducherry", "cochin": "kochi", "vizag": "visakhapatnam",
              "baroda": "vadodara", "poona": "pune", "allahabad": "prayagraj", "belgaum": "belagavi",
              "hubli": "hubballi", "gulbarga": "kalaburagi", "tumkur": "tumakuru", "shimoga": "shivamogga",
              "bellary": "ballari", "bijapur": "vijayapura"}


def _flags(x):
    return list(x) if x is not None else []


# ---------------------------------------------------------------- cached geometry joins
@lru_cache(None)
def _pip_chosen():
    L = loc()
    return pip_lgd(L.loc_lat.values, L.loc_lon.values)


@lru_cache(None)
def _pin_polys():
    import geopandas as gpd
    p = gpd.read_parquet(EXT / "pincode_boundaries/Datagov_Pincode_Boundaries.parquet")[["Pincode", "geometry"]]
    p = p.set_crs("EPSG:4326") if p.crs is None else p.to_crs("EPSG:4326")
    return p.to_crs("EPSG:7755").set_index("Pincode").geometry


def _dist_to_own_pin_polygon(lat, lon, pins):
    import geopandas as gpd
    P = _pin_polys()
    pts = gpd.GeoSeries(gpd.points_from_xy(np.asarray(lon, float), np.asarray(lat, float)), crs="EPSG:4326").to_crs("EPSG:7755")
    out = np.full(len(pts), np.nan)
    for i, (p, pt) in enumerate(zip(pins, pts)):
        k = str(int(p)) if pd.notna(p) else None
        if k in P.index and pt is not None and not pt.is_empty:
            out[i] = P[k].distance(pt) / 1000.0
    return out


@lru_cache(None)
def _own_pin_poly_dist():
    L = loc()
    return (_dist_to_own_pin_polygon(L.raw_lat, L.raw_lon, L.pin), _dist_to_own_pin_polygon(L.loc_lat, L.loc_lon, L.pin))


@lru_cache(None)
def _pin_crosscheck():
    """Every facility PIN: distance (km) of its gazetteer point to its own PIN polygon and to its LGD districts."""
    L = loc()
    fp = sorted(set(L.pin.dropna().astype(int)))
    g = pin_gz().set_index("pin").reindex(fp)
    pc = lgd_pin_districts().groupby("pincode").district_code.agg(lambda s: frozenset(int(x) for x in s))
    d_lgd = dist_to_districts_km(g.lat.values, g.lon.values, [pc.get(p) for p in fp])
    d_poly = _dist_to_own_pin_polygon(g.lat.values, g.lon.values, fp)
    t = pd.DataFrame({"pin": fp, "d_poly": d_poly, "d_lgd": d_lgd, "src": g.src.values, "district": g.district.values})
    t["n_fac"] = t.pin.map(L.pin.dropna().astype(int).value_counts())
    return t


@lru_cache(None)
def _stated_city_dist():
    L = loc()
    T = lgd_city_districts()
    codes = []
    for s, c in zip(L.state_final.map(nstate), L.address_city.map(norm)):
        k = T.get((s, CITY_ALIAS.get(c, c)))
        codes.append(k if k is not None and len(k) <= 2 else None)
    return (dist_to_districts_km(L.loc_lat, L.loc_lon, codes), dist_to_districts_km(L.raw_lat, L.raw_lon, codes),
            np.array([c is not None for c in codes]))


# ---------------------------------------------------------------- facility_location: table contract
def check_location_table_integrity():
    L, R = loc(), raw()
    ok_ids = R.unique_id.str.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-", na=False) & (R.source == "kie")
    r = R[ok_ids].drop_duplicates("unique_id").set_index("unique_id").reindex(L.unique_id)
    probs = {}
    probs["rows_not_9959"] = int(len(L) != 9959)
    probs["dup_ids"] = int(L.unique_id.duplicated().sum())
    probs["ids_not_in_raw"] = int((~L.unique_id.isin(R[ok_ids].unique_id)).sum())
    for c in ["name", "address_city", "address_stateOrRegion"]:
        a, b = L[c].values, r[c].values
        probs[f"{c}_not_verbatim"] = int(sum(not ((x == y) or (pd.isna(x) and pd.isna(y))) for x, y in zip(a, b)))
    probs["raw_lat_changed"] = int((~np.isclose(r.latitude.astype(float).values, L.raw_lat.values, equal_nan=True)).sum())
    probs["raw_lon_changed"] = int((~np.isclose(r.longitude.astype(float).values, L.raw_lon.values, equal_nan=True)).sum())
    probs["pin_not_parsed_from_raw"] = int((~np.isclose(r.address_zipOrPostcode.map(parse_pin).values, L.pin.values, equal_nan=True)).sum())
    lo, hi, lo2, hi2 = INDIA_BBOX
    probs["chosen_point_missing"] = int(L.loc_lat.isna().sum())
    probs["chosen_point_outside_india_box"] = int((~(L.loc_lat.between(lo, hi) & L.loc_lon.between(lo2, hi2))).sum())
    probs["bad_loc_src"] = int((~L.loc_src.isin(["listing_coordinates", "postcode_centre", "address_city_centre", "map_link"])).sum())
    probs["bad_loc_conf"] = int((~L.loc_conf.isin(["high", "medium", "low", "disputed"])).sum())
    probs["radius_not_positive"] = int((~(L.loc_radius > 0)).sum())
    probs["state_final_missing"] = int(L.state_final.isna().sum())
    bad = sum(probs.values())
    return result("location_table_integrity", "pass" if bad == 0 else "fail", f"{bad} violations",
                  "0 violations", json.dumps(probs), [])


def check_chosen_point_provenance():
    """The chosen point must be exactly the source its loc_src names; alt point must hold the raw coords on conflicts."""
    L = loc()
    g = pin_gz().set_index("pin").reindex(L.pin)
    lc = (L.loc_src == "listing_coordinates").values
    pc = (L.loc_src == "postcode_centre").values
    bad_l = lc & ~(np.isclose(L.loc_lat, L.raw_lat) & np.isclose(L.loc_lon, L.raw_lon))
    bad_p = pc & ~(np.isclose(L.loc_lat, g.lat.values) & np.isclose(L.loc_lon, g.lon.values))
    cf = L.loc_flags.map(lambda f: "coords_pin_conflict_gt50km" in _flags(f)).values
    bad_a = cf & ~lc & ~np.isclose(L.alt_lat.values, L.raw_lat.values, equal_nan=False)
    n = int(bad_l.sum() + bad_p.sum() + bad_a.sum())
    ex = list(L.unique_id[bad_l | bad_p | bad_a][:5])
    return result("chosen_point_provenance", "pass" if n == 0 else "fail", f"{n} mismatches", "0",
                  f"listing_coordinates rows equal raw: {lc.sum() - bad_l.sum()}/{lc.sum()}; postcode_centre rows equal "
                  f"pin_gazetteer point: {pc.sum() - bad_p.sum()}/{pc.sum()}; conflict rows keeping raw coords as alt: "
                  f"{(cf & ~lc).sum() - bad_a.sum()}/{(cf & ~lc).sum()}", ex)


def check_raw_to_pin_distance_rederived():
    """Re-derive raw-coordinate to PIN-centre distance and its distribution; compare with stored column and s2 stats."""
    L = loc()
    g = pin_gz().set_index("pin").reindex(L.pin)
    lo, hi, lo2, hi2 = INDIA_BBOX
    inbox = L.raw_lat.between(lo, hi) & L.raw_lon.between(lo2, hi2)
    d = pd.Series(np.where(inbox, hav_km(L.raw_lat, L.raw_lon, g.lat.values, g.lon.values), np.nan))
    diff = float(np.nanmax(np.abs(d.values - L.raw_coords_to_pin_km.values)))
    nan_mis = int((d.isna().values != L.raw_coords_to_pin_km.isna().values).sum())
    s2 = json.loads((GEO / "s2_stats.json").read_text())["raw_coords_gt50km_from_repaired_pin"]
    q = d.quantile([0.5, 0.75, 0.9, 0.95, 0.99]).round(1).tolist()
    n50 = int((d > 50).sum())
    ok = diff < 0.01 and nan_mis == 0 and [n50, int(d.notna().sum())] == s2
    det = (f"n={d.notna().sum()} (6 outside India box, 84 without a PIN point); quantiles p50/p75/p90/p95/p99 km = {q}; "
           f">10 km {int((d > 10).sum())}, >25 km {int((d > 25).sum())}, >50 km {n50} ({n50 / d.notna().sum():.1%}), "
           f">100 km {int((d > 100).sum())}, >500 km {int((d > 500).sum())}. Max abs diff vs stored raw_coords_to_pin_km "
           f"{diff:.4f} km; s2_stats says {s2}.")
    ex = list(L.unique_id[(d > 500).values][:5])
    return result("raw_to_pin_distance_rederived", "pass" if ok else "fail", f"{n50} of {d.notna().sum()} raw points > 50 km from PIN centre",
                  "recomputed distances equal stored within 10 m and counts equal s2_stats", det, ex)


def check_pin_gazetteer_vs_polygon_and_lgd():
    """Each facility PIN's centre against two independent sources: the PIN's own polygon (data.gov.in) and
    the LGD districts that the PIN covers. Off by > 25 km from both = the gazetteer point is wrong."""
    t = _pin_crosscheck()
    bad = t[(t.d_poly > 25) & (t.d_lgd > 25)].sort_values("d_poly", ascending=False)
    n_both = int(((t.d_poly.notna()) & (t.d_lgd.notna())).sum())
    L = loc()
    aff = L[L.pin.isin(bad.pin.astype(float))]
    placed = aff[aff.loc_src == "postcode_centre"]
    ex = [f"PIN {r.pin} ({r.district}, src {r.src}): {r.d_poly:.0f} km from its polygon, {r.d_lgd:.0f} km outside its LGD districts, {int(r.n_fac)} facilities"
          for r in bad.head(5).itertuples()]
    det = (f"{len(bad)} of {n_both} facility PINs with both references are > 25 km from both (any one reference: polygon "
           f"{int((t.d_poly > 25).sum())}, LGD {int((t.d_lgd > 25).sum())}). They carry {len(aff)} facilities; "
           f"{len(placed)} are placed on the wrong PIN point (loc_src postcode_centre), e.g. {list(placed.unique_id[:3])}. "
           f"By gazetteer src: {bad.src.value_counts().to_dict()}.")
    return result("pin_gazetteer_vs_polygon_and_lgd", "warn" if len(bad) else "pass", f"{len(bad)} PINs / {len(aff)} facilities",
                  "0 facility PINs > 25 km from both their polygon and their LGD districts", det, ex)


def check_chosen_point_vs_own_pin_polygon():
    L = loc()
    dr, dc = _own_pin_poly_dist()
    s, r = pd.Series(dc), pd.Series(dr)
    n = int(s.notna().sum())
    hi = (L.loc_conf == "high").values
    far_hi = hi & (s > 10).values
    ex = list(L.unique_id[far_hi][:5])
    det = (f"PIN polygon available for {n}. Distance to own PIN polygon, raw -> chosen: inside {int((r == 0).sum())} -> {int((s == 0).sum())}; "
           f"> 10 km {int((r > 10).sum())} -> {int((s > 10).sum())}; > 50 km {int((r > 50).sum())} -> {int((s > 50).sum())}. "
           f"Chosen > 50 km by loc_src: {L.loc_src[(s > 50).values].value_counts().to_dict()}. "
           f"High-confidence points > 10 km outside their own PIN polygon: {int(far_hi.sum())}.")
    return result("chosen_point_vs_own_pin_polygon", "warn" if far_hi.sum() else "pass",
                  f"{int((s > 50).sum())} of {n} chosen points > 50 km from own PIN polygon (raw: {int((r > 50).sum())})",
                  "high-confidence points within 10 km of their PIN polygon", det, ex)


def check_high_conf_far_from_pin_centre():
    """loc_conf high (radius 1 km) is granted when coords are within max(10, PIN radius) of the PIN centre; PIN radius reaches 50."""
    L = loc()
    g = pin_gz().set_index("pin").reindex(L.pin)
    h = (L.loc_conf == "high").values
    d = L.raw_coords_to_pin_km.values
    p3 = pd.Series(g.src.values).fillna("").str.startswith("prefix3").values
    n10, n20 = int((h & (d > 10)).sum()), int((h & (d > 20)).sum())
    ex = list(L.unique_id[h & (d > 30)][:5])
    det = (f"{n10} of {h.sum()} high-confidence records (radius shown 1.0 km) have coordinates > 10 km from the PIN centre; "
           f"{n20} > 20 km, {int((h & (d > 40)).sum())} > 40 km. {int((h & p3).sum())} high records have a PIN point that is only a "
           f"3-digit-prefix median (radius 50 km), so 'agreement' there means within 50 km. Root cause: s2_facility_location.py "
           f"choose(): `if d <= max(10.0, r.p_radius)` returns conf='high', radius=1.0.")
    return result("high_conf_far_from_pin_centre", "warn" if n10 else "pass", f"{n10} high records > 10 km from PIN centre",
                  "high confidence only when coords are within 10 km of a precise PIN point", det, ex)


def check_chosen_vs_stated_city():
    """Stated city resolved through LGD names only (district, sub-district, urban body -> LGD district polygon)."""
    L = loc()
    dc, dr, ok = _stated_city_dist()
    s, r = pd.Series(dc), pd.Series(dr)
    hi = (L.loc_conf == "high").values
    far_hi = hi & (s > 50).values
    ex = [f"{u} {n} (city {c}, PIN {int(p) if pd.notna(p) else '-'}, district {d})"
          for u, n, c, p, d in L.loc[far_hi, ["unique_id", "name", "address_city", "pin", "district"]].head(5).values]
    det = (f"City resolves to <= 2 LGD districts for {ok.sum()} of {len(L)}. Point > 50 km outside the stated city's district: "
           f"raw {int((r > 50).sum())} -> chosen {int((s > 50).sum())}; > 10 km: raw {int((r > 10).sum())} -> chosen {int((s > 10).sum())}. "
           f"Chosen > 50 km by loc_conf: {L.loc_conf[(s > 50).values].value_counts().to_dict()}. {int(far_hi.sum())} are 'high'; "
           f"hand review of those: 19 are real city-vs-(PIN+coords) conflicts the s2 'city_points_elsewhere' rule missed, "
           f"4 are this check's false alarms (Gorantla, Khanpur, Sheikhpura are also localities; Mahe polygon).")
    return result("chosen_vs_stated_city", "warn", f"{int((s > 50).sum())} of {ok.sum()} chosen points > 50 km from stated city district",
                  "no high-confidence point > 50 km from its stated city", det, ex)


def check_state_final_vs_point_and_district():
    L = loc()
    a = _pip_chosen()
    ps, sf, ds = a.stname.map(nstate), L.state_final.map(nstate), L.district_state.map(nstate)
    mism = (ps.values != sf.values) & a.stname.notna().values & (ps.values == ds.values)
    sd = (sf != ds).values
    top = L[mism].groupby(["state_final", "district_state"]).size().sort_values(ascending=False).head(4).to_dict()
    ex = [f"{u} {n} ({c}): state_final {s}, point and district in {d}" for u, n, c, s, d in
          L.loc[mism, ["unique_id", "name", "address_city", "state_final", "district_state"]].head(5).values]
    det = (f"state_final (shown in app/facts and planner) differs from district_state for {int(sd.sum())} records; for "
           f"{int(mism.sum())} the chosen point also lies in district_state per the LGD polygon ({int((mism & (L.loc_conf == 'high').values).sum())} "
           f"high confidence). Top pairs {top}. Root cause: s2_facility_location.py `state_final = state_final_stated.fillna(p_state)` "
           f"always prefers the typed state, including the pre-2014 'Andhra Pradesh' for Hyderabad.")
    return result("state_final_vs_point_and_district", "warn" if mism.sum() else "pass", f"{int(mism.sum())} records",
                  "state_final agrees with the state holding the point and district", det, ex)


def _judged(sample_ids, file, key="unique_id"):
    j = pd.read_csv(JUDG / file)
    if set(j[key]) != set(sample_ids):
        return None
    return j


def check_moved_sample_30():
    s, tot = sm.moved_sample()
    j = _judged(s.unique_id, "moved_30.csv")
    if j is None:
        return result("moved_sample_30", "fail", "stale", "-", "sample ids differ from judgments/moved_30.csv", [])
    k, n = int((j.verdict == "right").sum()), len(j)
    lo, hi = wilson(k, n)
    wrong = j[j.verdict == "wrong"]
    det = (f"Population: {tot} records whose ranking point is > 25 km from the raw coordinates (s7 says 1171). "
           f"Judged from address lines, city, PIN and description: right {k}, wrong {len(wrong)}, unclear {int((j.verdict == 'unclear').sum())}. "
           f"Unclear rows are records whose text names two towns. Wrong: {wrong.note.tolist()}.")
    return result("moved_sample_30", "pass" if lo >= 0.7 else "warn", f"right {k}/{n} = {k / n:.2f} (95% Wilson {lo}-{hi})",
                  "Wilson lower bound >= 0.70", det, list(wrong.unique_id) + list(j[j.verdict == "unclear"].unique_id))


def check_district_coverage():
    L = loc()
    miss = L.district.isna()
    srcset = miss & L.district_src.isin(["postcode", "map_point"])
    det = (f"district assigned for {int((~miss).sum())} of {len(L)}. All {int(miss.sum())} missing rows still carry district_src "
           f"'{L.district_src[miss].unique().tolist()}' and state {L.state_final[miss].value_counts().to_dict()}: the nearest reference "
           f"PIN point has no district (pin_gazetteer src prefix3 / missing). s2 sets district_src before checking that the "
           f"looked-up district is non-null. nfhs_how for them: {L.nfhs_how[miss].fillna('null').value_counts().to_dict()}.")
    return result("district_coverage", "warn" if srcset.sum() else "pass", f"{int((~miss).sum())}/{len(L)} assigned",
                  "every record has a district, or district_src 'none' when it has none", det, list(L.unique_id[miss][:5]))


def _nd(s):
    import re
    s = norm(s)
    return re.sub(r"\s+", " ", re.sub(r"\b(district|dist)\b", "", s)).strip()


def _same_district(x, y):
    from rapidfuzz import fuzz
    x, y = _nd(x), _nd(y)
    return bool(x and y) and (fuzz.ratio(x, y) >= 80 or fuzz.token_set_ratio(x, y) >= 90 or x.replace(" ", "") == y.replace(" ", ""))


def check_district_vs_lgd_exhaustive():
    L = loc()
    a = _pip_chosen()
    pcn = lgd_pin_districts().groupby("pincode").district_name.agg(lambda s: sorted(set(s)))
    pin_lgd = [pcn.get(int(p)) if pd.notna(p) else None for p in L.pin]
    ag_poly = np.array([_same_district(d, p) for d, p in zip(L.district, a.dtname)])
    ag_pin = np.array([bool(c) and any(_same_district(d, x) for x in c) for d, c in zip(L.district, pin_lgd)])
    has = L.district.notna().values
    neither = has & ~ag_poly & ~ag_pin
    nirmal = (L.district == "Nirmal").values & (L.district_state == "TRIPURA").values
    top = pd.Series(list(zip(L.district[neither], a.dtname[neither]))).value_counts().head(6).to_dict()
    det = (f"Of {has.sum()} assigned districts: agree with the LGD polygon holding the chosen point {int(ag_poly[has].sum())}, with the LGD "
           f"districts of the PIN {int(ag_pin[has].sum())} (PIN in LGD for {sum(c is not None for c in pin_lgd)}), with either "
           f"{int((ag_poly | ag_pin)[has].sum())}. Neither: {int(neither.sum())}, mostly post-2011 splits and renames that India Post "
           f"names still use (Chittoor->Tirupati, East Godavari->Kakinada) and Delhi/Hyderabad/Kolkata boundary edges. Real error: "
           f"PIN 799001 (Agartala) carries district 'Nirmal' (a Telangana district) from the India Post directory, so "
           f"{int(nirmal.sum())} Agartala facilities show district Nirmal, TRIPURA. Top neither pairs {top}.")
    return result("district_vs_lgd_exhaustive", "warn", f"{int((ag_poly | ag_pin)[has].sum())}/{has.sum()} agree with LGD",
                  "assigned district matches LGD polygon or PIN district set", det, list(L.unique_id[nirmal][:5]))


def check_district_sample_30():
    s = sm.district_sample()
    j = _judged(s.unique_id, "district_30.csv")
    if j is None:
        return result("district_sample_30", "fail", "stale", "-", "sample ids differ from judgments/district_30.csv", [])
    k, n = int((j.verdict == "correct").sum()), len(j)
    lo, hi = wilson(k, n)
    w = j[j.verdict != "correct"]
    return result("district_sample_30", "pass" if lo >= 0.8 else "warn", f"correct {k}/{n} = {k / n:.2f} (95% Wilson {lo}-{hi})",
                  "Wilson lower bound >= 0.80",
                  f"Random 30 of the 9,946 assigned districts, judged against LGD archive PIN-village / urban-body districts, LGD "
                  f"polygons and the address text. Wrong: {w.note.tolist()}", list(w.unique_id))


def check_nfhs_join():
    L = loc()
    N = pd.read_parquet(ROOT / "data/raw/nfhs_5_district_health_indicators.parquet")
    nn = set(zip(N.state_ut.str.strip(), N.district_name.str.strip()))
    j = L.nfhs_district_name.notna()
    bad_key = int(sum((s.strip(), d.strip()) not in nn for s, d in zip(L.nfhs_state_ut[j], L.nfhs_district_name[j])))
    wb = set(N[N.state_ut.str.contains("Bengal")].district_name.str.strip())
    claim_ok = ("Purba Barddhaman" not in wb) and ("Chandel" in set(N[N.state_ut.str.strip() == "Mizoram"].district_name.str.strip()))
    det = (f"NFHS key present for {int(j.sum())} of {len(L)}; every key exists in the raw NFHS-5 table: {bad_key == 0}. "
           f"How: {L.nfhs_how.fillna('null').value_counts().to_dict()}. The two documented gaps hold in the raw table: no Purba "
           f"Barddhaman row, Mizoram has a 'Chandel' row: {claim_ok}. 'Maharastra' is the raw NFHS spelling, not a join error.")
    return result("nfhs_join", "pass" if bad_key == 0 and claim_ok else "fail", f"{int(j.sum())}/{len(L)} joined", "every key exists in NFHS-5", det, [])


def check_external_district_tables_consistency():
    L = loc()
    i = pd.read_csv(EXT / "idp-nfhs-district/facility_idp_district.csv", dtype=str).drop_duplicates("unique_id")
    f = pd.read_parquet(EXT / "lgd_district_polygons/facility_lgd_district.parquet").drop_duplicates("unique_id")
    a = L.merge(i, on="unique_id", how="left", suffixes=("", "_idp"))
    b = L.merge(f[["unique_id", "district"]], on="unique_id", how="left", suffixes=("", "_lgdext"))
    d1, d2 = int((a.district != a.district_idp).sum()), int((b.district != b.district_lgdext).sum())
    ex = list(a.unique_id[a.district != a.district_idp][:5])
    return result("external_district_tables_consistency", "warn" if d1 or d2 else "pass",
                  f"{d1} (IDP NFHS map) and {d2} (LGD polygon join) of {len(L)} disagree with derived/v1 district",
                  "external join tables keyed on the canonical v1 district",
                  "data/external/idp-nfhs-district/facility_idp_district.csv and lgd_district_polygons/facility_lgd_district.parquet were "
                  "built from the older audit district assignment (raw coordinates), so their district and code_best differ from "
                  "derived/v1 facility_location.district for about 2.8% of records (e.g. VADODARA vs SURAT). Anything that joins "
                  "HMIS or NFHS codes through these tables uses a different district than the app shows.", ex)


# ---------------------------------------------------------------- matches to outside sources
STATED = {  # precision stated in each README for the accepted tier, as (correct, n, text)
    "osm": (17, 20, "kb/opendata/OPENDATA.md: high 17/20 validation (0.64-0.95); medium 7/10 pooled"),
    "wikidata": (17, 20, "kb/opendata/OPENDATA.md: pooled with OSM, high 17/20 validation"),
    "hot": (15, 20, "external/hotosm README: 15/20 correct or likely (75%)"),
    "nabh": (39, 40, "external/nabh_accredited README: 39/40 (97.5%)"),
    "eraktkosh": (18, 20, "external/eraktkosh README: 16 correct + 2 likely + 2 uncertain of 20 (80% strict, 90% with likely)"),
    "laqshya": (20, 20, "external/laqshya_master README: 17 correct, 3 plausible, 0 wrong of 20"),
    "nmc": (19, 20, "external/nmc_colleges README: 19/20 clean, 1 right name on a mislocated VF record"),
    "trauma": (19, 20, "external/mohfw_trauma_196 README: 19/20 (all 20 accepted)"),
}
POP = {}


def _samples(source):
    if source in ("osm", "wikidata"):
        a, r, na, nr = ms.opendata(source)
        return a[["unique_id", "cand_name"]], r[["unique_id", "cand_name"]], na, nr, "matches_opendata.csv"
    if source == "hot":
        a, r, na, nr = ms.hot()
        return a[["unique_id", "osm_name"]], r[["unique_id", "osm_name"]], na, nr, "matches_lists.csv"
    if source == "trauma":
        a, r, na, nr = ms.trauma()
        return a[["vf_id", "tcf_name"]], r[["vf_id", "tcf_name"]], na, nr, "matches_lists.csv"
    if source == "nabh":
        a, _, na, _ = ms.nabh()
        r, nr = ms.nabh_rejected()
        return a[["unique_id", "name_nb"]], r[["unique_id", "name"]], na, nr, "matches_lists.csv"
    path, salt, col = {"eraktkosh": ("eraktkosh_blood_centres/erk_vf_matches.parquet", 60, "erk_name"),
                       "laqshya": ("laqshya_master/laqshya_vf_matches.parquet", 70, "lq_name"),
                       "nmc": ("nmc_colleges/nmc_vf_matches.parquet", 80, "college_name")}[source]
    a, _, na, _ = ms.simple(path, salt)
    r, nr = {"eraktkosh": ms.erk_rejected, "laqshya": ms.laqshya_rejected, "nmc": ms.nmc_rejected}[source]()
    rcol = {"eraktkosh": "name", "laqshya": "full", "nmc": "college_name"}[source]
    return a[["unique_id", col]], r[["unique_id", rcol]], na, nr, "matches_lists.csv"


def _match_check(source):
    a, r, na, nr, file = _samples(source)
    j = pd.read_csv(JUDG / file)
    j = j[j.source == source]
    ja, jr = j[j.kind == "accepted"], j[j.kind == "rejected"]
    key = lambda df: sorted(zip(df.iloc[:, 0].astype(str), df.iloc[:, 1].astype(str)))  # noqa: E731
    if key(a) != sorted(zip(ja.unique_id.astype(str), ja.cand_name.astype(str))) or \
            key(r) != sorted(zip(jr.unique_id.astype(str), jr.cand_name.astype(str))):
        return result(f"match_{source}", "fail", "stale", "-", f"sample differs from judgments/{file}", [])
    k = int(ja.verdict.isin(["yes", "likely"]).sum())
    n = len(ja)
    lo, hi = wilson(k, n)
    miss = int((jr.verdict == "same").sum())
    unc = int((jr.verdict == "uncertain").sum())
    sk, sn, stext = STATED[source]
    slo, shi = wilson(sk, sn)
    overlap = not (hi < slo or lo > shi)
    exact = " (the sample is the whole accepted set, so this is exact)" if n == na else ""
    wrong = ja[~ja.verdict.isin(["yes", "likely"])]
    mlo, mhi = wilson(miss, len(jr)) if len(jr) else (float("nan"), float("nan"))
    det = (f"Accepted population {na}; sample {n}: yes {int((ja.verdict == 'yes').sum())}, likely {int((ja.verdict == 'likely').sum())}, "
           f"uncertain {int((ja.verdict == 'uncertain').sum())}, no {int((ja.verdict == 'no').sum())}{exact}. README: {stext} "
           f"(Wilson {slo}-{shi}); intervals overlap: {overlap}. Rejected: {len(jr)} drawn from {nr} refused best candidates with "
           f"name score >= 70 (>= 85 for regenerated list candidates); judged same facility (missed match) {miss}, uncertain {unc} "
           f"(miss rate {miss}/{len(jr)}, Wilson {mlo}-{mhi}). Wrong or uncertain accepted: {wrong.note.tolist()}. "
           f"Missed: {jr[jr.verdict == 'same'].note.tolist()}")
    status = "pass" if lo >= 0.75 and miss <= 2 else "warn"
    return result(f"match_{source}", status, f"precision {k}/{n} = {k / n:.2f} (95% Wilson {lo}-{hi}); missed {miss}/{len(jr)} rejected",
                  "precision Wilson lower bound >= 0.75 and <= 2 of 10 rejected pairs are misses", det,
                  list(wrong.unique_id) + list(jr[jr.verdict == "same"].unique_id))


def check_match_osm_opendata():
    return _match_check("osm")


def check_match_wikidata_opendata():
    return _match_check("wikidata")


def check_match_hot_osm():
    return _match_check("hot")


def check_match_nabh():
    return _match_check("nabh")


def check_match_eraktkosh():
    return _match_check("eraktkosh")


def check_match_laqshya():
    return _match_check("laqshya")


def check_match_nmc():
    return _match_check("nmc")


def check_match_mohfw_trauma():
    r = _match_check("trauma")
    r["detail"] += (" Recall note: TCF 'New Medical College Hospital, Kota' was refused against Jhalawar Medical College, while VF holds "
                    "'Government Medical College, Kota' (95c8fde2-09e3-47b0-b2c9-96b492149fa4), its parent college.")
    return r


def check_match_pmndp_goa():
    g = pd.read_csv(EXT / "pmndp_counts_and_state_lists/goa_matches.csv")
    L = loc()
    goa = L[L.state_final == "GOA"]
    acc = g[g.matched]
    ok_acc = bool((acc.vf_name == "Goa Medical College").all() and len(acc) == 1)
    towns = ["Hospicio", "Canacona", "Navelim", "Balli", "Valpoi", "Asilo"]
    absent = all(not goa.name.str.contains(t, case=False, na=False).any() for t in towns)
    return result("match_pmndp_goa", "pass" if ok_acc and absent else "warn", f"accepted {len(acc)}/1 correct; rejected 7/7 correct",
                  "all 8 Goa rows judged", "Goa list only (8 rows, the other states are counts). Accepted Goa Medical College = VF dda3e7e4 "
                  f"(same PIN 403202). For the 7 refused rows no VF record in Goa ({len(goa)} records) names Hospicio, Canacona, Navelim, "
                  "Balli, Valpoi or Asilo, so the refusals are right. README 1/1 precision confirmed; its 'recall 1/8' is coverage of VF, "
                  "not matcher recall.", [])


def check_match_counts_vs_readme():
    """Recompute the headline counts each README states."""
    got, want = {}, {}
    m = pd.read_parquet(ROOT / "kb/opendata/vf_opendata_match.parquet")
    for (s, t), n in m.groupby(["source", "tier"]).size().items():
        got[f"opendata_{s}_{t}"] = int(n)
    want.update(opendata_osm_high=2596, opendata_osm_medium=195, opendata_osm_conflict=634,
                opendata_wikidata_high=182, opendata_wikidata_medium=24, opendata_wikidata_conflict=31)
    got["opendata_any_match"] = int(m[m.tier.isin(["high", "medium"])].unique_id.nunique())
    want["opendata_any_match"] = 2844
    f = pd.read_parquet(ROOT / "kb/opendata/vf_opendata_facts.parquet")
    got["opendata_facts_rows"], want["opendata_facts_rows"] = len(f), 6001
    hm = set(m[m.tier.isin(["high", "medium"])].unique_id)
    got["opendata_facts_uid_not_matched"], want["opendata_facts_uid_not_matched"] = int((~f.unique_id.isin(hm)).sum()), 0
    h = pd.read_parquet(EXT / "hotosm_ind_health_facilities/vf_osm_matches.parquet")
    got["hot_strong"], got["hot_weak"] = int((h.tier == "strong").sum()), int((h.tier == "weak").sum())
    want.update(hot_strong=3263, hot_weak=269)
    n = pd.read_parquet(EXT / "nabh_accredited/nabh_vf_match.parquet")
    got["nabh_vf_matched"], got["nabh_rows_matched"] = int(n.unique_id.nunique()), int(n.nabh_id.nunique())
    want.update(nabh_vf_matched=2061, nabh_rows_matched=2042)
    e = pd.read_parquet(EXT / "eraktkosh_blood_centres/erk_vf_matches.parquet")
    got["erk_matched"], got["erk_distance_gate"] = len(e), int((e.gate == "distance").sum())
    want.update(erk_matched=388, erk_distance_gate=342)
    q = pd.read_parquet(EXT / "laqshya_master/laqshya_vf_matches.parquet")
    got.update(laqshya_pairs=len(q), laqshya_vf_rows=int(q.unique_id.nunique()), laqshya_lists=int(q.lq_id.nunique()))
    want.update(laqshya_pairs=66, laqshya_vf_rows=58, laqshya_lists=63)
    c = pd.read_parquet(EXT / "nmc_colleges/nmc_vf_matches.parquet")
    got.update(nmc_pairs=len(c), nmc_colleges=int(c.college_id.nunique()))
    want.update(nmc_pairs=81, nmc_colleges=79)
    t = pd.read_csv(EXT / "mohfw_trauma_196/tcf_vf_matches.csv")
    got["trauma_accepted"], want["trauma_accepted"] = len(t), 20
    L = loc()
    ids = set(L.unique_id)
    for nm, df, col in [("hot", h, "unique_id"), ("nabh", n, "unique_id"), ("erk", e, "unique_id"), ("laqshya", q, "unique_id"),
                        ("nmc", c, "unique_id"), ("trauma", t, "vf_id")]:
        got[f"{nm}_uids_outside_9959"] = int((~df[col].isin(ids)).sum())
    bad = {k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}
    outside = {k: v for k, v in got.items() if k.endswith("outside_9959") and v}
    det = f"mismatches {bad}; match rows whose VF id is not in the 9,959 cleaned records (11 byte-duplicate raw rows): {outside}"
    return result("match_counts_vs_readme", "pass" if not bad else "fail", f"{len(want) - len(bad)}/{len(want)} counts reproduce",
                  "every stated count reproduces", det, list(bad)[:5])


def check_v2_location_contract():
    """Contract for #11 output, designed only: when derived/v2 has a facility table with unique_id and a point,
    the ids must equal v1's and the point, district and state must equal v1 facility_location (or be documented)."""
    v2 = ROOT / "derived" / "v2"
    files = sorted(v2.glob("*.parquet")) if v2.is_dir() else []
    if not files:
        return result("v2_location_contract", "warn", "not_run", "-", "derived/v2 has no parquet files yet; contract not run", [])
    import pyarrow.parquet as pq
    L = loc().set_index("unique_id")
    msgs = []
    for p in files:
        cols = pq.read_schema(p).names
        latc = next((c for c in ("loc_lat", "p1_lat", "lat") if c in cols), None)
        if "unique_id" not in cols:
            continue
        d = pd.read_parquet(p, columns=["unique_id"] + [c for c in (latc, latc and latc.replace("lat", "lon"), "district") if c and c in cols])
        extra = int((~d.unique_id.isin(L.index)).sum())
        msg = f"{p.name}: {extra} ids not in v1"
        if latc:
            u = d.drop_duplicates("unique_id").set_index("unique_id")
            lonc = latc.replace("lat", "lon")
            dd = hav_km(u[latc], u[lonc], L.loc_lat.reindex(u.index), L.loc_lon.reindex(u.index))
            msg += f", {int((dd > 0.01).sum())} points differ from v1 loc"
        if "district" in d:
            u = d.drop_duplicates("unique_id").set_index("unique_id")
            msg += f", {int((u.district != L.district.reindex(u.index)).sum())} districts differ"
        msgs.append(msg)
    bad = any((" 0 ids" not in m) or ("points differ" in m and " 0 points" not in m) for m in msgs)
    return result("v2_location_contract", "warn" if bad else "pass", f"{len(msgs)} v2 tables with unique_id checked",
                  "ids, points and districts equal v1", "; ".join(msgs) or "no v2 table with unique_id", [])


ALL = [v for k, v in sorted(globals().items()) if k.startswith("check_") and callable(v)]


def main():
    res = []
    for f in ALL:
        try:
            r = f()
        except Exception as e:  # noqa: BLE001 - one failing check must not hide the others
            r = result(f.__name__[6:], "fail", "error", "-", f"{type(e).__name__}: {e}", [])
        res.append(r)
        print(f"{r['status']:5} {r['name']}: {r['metric']}")
    (OUT / "checks.json").write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    main()
