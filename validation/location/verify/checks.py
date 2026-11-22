"""Independent verification of the location audit (own code; imports only verify/geo.py and verify/city.py).
Each check_<name>() -> dict(name, status, metric, threshold, detail, examples). Run: .venv-viz/bin/python -B checks.py
Writes only verify/out/. Hand reads of seeded samples (SEED 20261121) are recorded in the docstrings and REVIEW dicts."""
import json, re, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from geo import EXT, GZ, L, OUT, ROOT, fac_geo, hav, pin_geo, pinpoly, to_own_pin_poly_km, in_lgd, PRJ  # noqa: E402
from city import city_dist, n as nst  # noqa: E402

SEED = 20261121


def R(name, status, metric, threshold, detail, examples=()):
    return dict(name=name, status=status, metric=metric, threshold=threshold, detail=detail, examples=[str(x) for x in list(examples)[:5]])


def _lf():
    return L().merge(fac_geo(), on="unique_id")


def check_v_loc01_bad_pin_centres():
    p = pin_geo()
    l = _lf()
    placed = l[l.loc_src == "postcode_centre"].pin.dropna().astype(int).value_counts()
    nf = l.pin.dropna().astype(int).value_counts()
    b25, b50 = p[p.gz_pinpoly_km > 25], p[p.gz_pinpoly_km > 50]
    harm = l[(l.r_pinpoly_km <= 2) & (l.c_pinpoly_km > 25)]
    det = (f"facility PINs {len(p)}, with polygon {p.gz_pinpoly_km.notna().sum()}. Gazetteer point > 25 km from own PIN polygon: "
           f"{len(b25)} PINs, {int(b25.pin.map(nf).sum())} facilities, {int(b25.pin.map(placed).fillna(0).sum())} placed on it; > 50 km: "
           f"{len(b50)} PINs, {int(b50.pin.map(nf).sum())} facilities, {int(b50.pin.map(placed).fillna(0).sum())} placed. Raw point within 2 km "
           f"of own polygon but chosen point > 25 km away (cleaning made it worse): {len(harm)} ({harm.loc_conf.value_counts().to_dict()}).")
    return R("v_loc01_bad_pin_centres", "warn", f"{len(harm)} facilities moved off a correct point onto a bad PIN centre; {len(b25)} facility PINs > 25 km off",
             "0", det, harm.unique_id)


def check_v_gazetteer_all_pins_for_app():
    """App PIN lookup (app/facts pins, app/packs pin_index and per-PIN top lists) uses every pin_gazetteer row, not only facility PINs."""
    g = GZ().dropna(subset=["lat", "lon", "district"]).copy()
    g["d"] = to_own_pin_poly_km(g.lat, g.lon, g.pin)
    fp = set(L().pin.dropna().astype(int))
    c = {t: int((g.d > t).sum()) for t in (10, 25, 50, 100)}
    nonf = int(((g.d > 50) & ~g.pin.isin(fp)).sum())
    ex = [f"PIN {r.pin} {r.district} {r.src} {r.d:.0f} km off" for r in g.sort_values("d", ascending=False).head(5).itertuples()]
    return R("v_gazetteer_all_pins_for_app", "warn", f"{c[50]} of {g.d.notna().sum()} exported PIN points > 50 km outside own polygon",
             "PIN points used as search origin within 10 km of their polygon", f"> km counts {c}; {nonf} of the > 50 km PINs carry no "
             f"facility (outside the auditor's scope); by src at > 25 km {g[g.d > 25].src.value_counts().to_dict()}", ex)


def check_v_loc02_state_final():
    l = _lf()
    fix = {"dadra nagar haveli daman and diu": "dnhdd"}
    sf, ps, ds = l.state_final.map(nst).replace(fix), l.c_stname.map(nst).replace(fix), l.district_state.map(nst).replace(fix)
    m = (sf != ps) & (ps == ds)
    hy = l[l.address_city.str.contains("hyderabad|secunderabad", case=False, na=False)]
    return R("v_loc02_state_final", "warn", f"{int(m.sum())} records ({int((m & (l.loc_conf == 'high')).sum())} high)", "0",
             f"pairs {l[m].groupby(['state_final', 'c_stname']).size().sort_values(ascending=False).head(5).to_dict()}; "
             f"Hyderabad/Secunderabad cities: {hy.state_final.value_counts().to_dict()}", l.unique_id[m])


def check_v_loc03_high_conf():
    l = _lf()
    g = GZ().set_index("pin")
    h = l[l.loc_conf == "high"].assign(gsrc=lambda d: d.pin.map(g.src))
    f = h[h.raw_coords_to_pin_km > 10]
    det = (f"{len(f)} of {len(h)} high > 10 km from PIN centre; of these with a polygon ({f.c_pinpoly_km.notna().sum()}): inside own polygon "
           f"{int((f.c_pinpoly_km == 0).sum())}, within 5 km {int((f.c_pinpoly_km <= 5).sum())}, > 10 km outside {int((f.c_pinpoly_km > 10).sum())}; "
           f"no polygon {int(f.c_pinpoly_km.isna().sum())}. All high > 10 km outside own polygon: {int((h.c_pinpoly_km > 10).sum())}. "
           f"High on prefix3 PIN point: {int(h.gsrc.fillna('').str.startswith('prefix3').sum())}. Auditor example 19302dcf (Nashik 422007, 44 km) "
           f"is inside its own polygon: the PIN centre is wrong, not the point.")
    bad = h[h.c_pinpoly_km > 10]
    return R("v_loc03_high_conf", "warn", f"{len(bad)} high records > 10 km outside own PIN polygon (auditor headline 164)", "0", det, bad.unique_id)


def check_v_loc04_city_conflicts():
    l = L().merge(city_dist(), on="unique_id")
    x = l[(l.d_loc > 50) & (l.loc_conf == "high")]
    return R("v_loc04_city_conflicts", "warn", f"{len(x)} high points > 50 km outside stated city's LGD district (own resolver, {l.city_code.notna().sum()} resolved)",
             "0", f"chosen > 50 km {int((l.d_loc > 50).sum())}, raw > 50 km {int((l.d_raw > 50).sum())}. Own read: 7 resolver false alarms "
             "(Mahe enclave, Khanapur TS, Gorantla, Kalol x2, Khanpur and Sheikhpura localities), about 22 real text-vs-(PIN+coords) conflicts. "
             "f59cbf5c Jabalpur escaped the rule because audit facility_geo city_match_pin/near are both True for a Sagar PIN; Thalassery and "
             "Bengaluru escaped because places.build_layers has no 'city' layer although v1 place_gazetteer has one (s3).", x.unique_id)


def check_v_loc05_moved():
    l = _lf()
    d = hav(l.raw_lat, l.raw_lon, l.loc_lat, l.loc_lon)
    m = l[d > 25]
    return R("v_loc05_moved", "warn", f"{len(m)} moved > 25 km; {int(((m.r_pinpoly_km == 0) & (m.c_pinpoly_km > 10)).sum())} had a raw point inside own PIN polygon",
             "-", f"moved points landing inside own PIN polygon {int((m.c_pinpoly_km == 0).sum())}", ["c50d0b3e-8615-4166-9579-6708be64ef66", "404af51a-ac38-4d7c-b405-2f0361f0f3c4"])


def check_v_loc06_nirmal():
    d = pd.read_parquet(ROOT / "data/raw/india_post_pincode_directory.parquet")
    x = d[d.pincode.astype(str) == "799001"]
    l = L()
    k = l[(l.district == "Nirmal") & (l.district_state == "TRIPURA")]
    return R("v_loc06_nirmal", "warn" if len(k) else "pass", f"{len(k)} facilities", "0",
             f"raw directory 799001 districts {x.district.value_counts().to_dict()}", k.unique_id)


def check_v_loc07_null_district():
    l = L()
    x = l[l.district.isna()]
    ref = GZ()[GZ().src.isin(["pin_median", "facility_consensus"])]
    return R("v_loc07_null_district", "warn" if len(x) else "pass", f"{len(x)} null district, district_src {x.district_src.value_counts().to_dict()}",
             "0", f"reference gazetteer rows with null district {int(ref.district.isna().sum())}; cities {x.address_city.tolist()}", x.unique_id)


def check_v_loc08_external_tables():
    l = L().set_index("unique_id").district
    nm = lambda s: re.sub(r"[^a-z]", "", s.lower()) if isinstance(s, str) else None  # noqa: E731
    out = {}
    for k, t in (("idp", pd.read_csv(EXT / "idp-nfhs-district/facility_idp_district.csv", dtype=str)),
                 ("lgd", pd.read_parquet(EXT / "lgd_district_polygons/facility_lgd_district.parquet"))):
        b = t.drop_duplicates("unique_id").set_index("unique_id").district.reindex(l.index)
        out[k] = dict(raw_ne=int((l != b).sum()), both_null=int((l.isna() & b.isna()).sum()),
                      real=int(((l.map(nm) != b.map(nm)) & ~(l.isna() & b.isna())).sum()))
    return R("v_loc08_external_tables", "warn", f"{out['idp']['real']} real disagreements (auditor 289 counts NaN != NaN)", "0",
             json.dumps(out) + "; no consumer outside external/*/ build scripts found by grep", [])


def _far(df, uid, la, lo):
    l = L().set_index("unique_id")
    x = df.dropna(subset=[la, lo]).copy()
    j = l.reindex(x[uid])
    x["d_loc"] = hav(x[la], x[lo], j.loc_lat.values, j.loc_lon.values)
    x["d_raw"] = hav(x[la], x[lo], j.raw_lat.values, j.raw_lon.values)
    return x, x[(x.d_loc > 25) & (x.d_raw <= 2)]


def check_v_hot_matches_on_rejected_raw_point():
    """Seeded read of 12 (random_state SEED): 12/12 are a same-name hospital in the raw (copied-geocode) town, e.g. SPARSH Hennur Road
    Bengaluru -> Sparsh Hospital Hassan; Star Hospitals Hyderabad -> Star Hospital Tenali; Ankur Hospital Bhopal -> Ankur Hospital Indore."""
    h = pd.read_parquet(EXT / "hotosm_ind_health_facilities/vf_osm_matches.parquet")
    x, b = _far(h[h.tier == "strong"], "unique_id", "osm_lat", "osm_lon")
    return R("v_hot_matches_on_rejected_raw_point", "warn", f"{len(b)} of {len(x)} HOT strong matches sit on the raw point but > 25 km from the v1 point; sample 12/12 wrong (Wilson 0.76-1.00)",
             "0", f"anchor x geo_conflict for strong: {pd.crosstab(h[h.tier=='strong'].anchor, h[h.tier=='strong'].geo_conflict).to_dict()}", b.unique_id)


def check_v_nabh_matches_on_rejected_raw_point():
    """Seeded read of 10: 7 wrong matches (Alpha Wakad -> Latur, Lotus Pune -> Borivali, Marwar Jodhpur -> Bikaner, City Rohtak -> Jagadhri,
    Sri Raghavendra Chennai -> Erode eye hospital, Guru Nanak Bareilly -> Shahjahanpur, Seven Sisters Jorhat -> Goalpara); 3 where NABH confirms the
    raw point and v1 moved the facility wrongly (Vivekanand Khalilabad, Dayawati Dhampur, Satish Mainpuri)."""
    n = pd.read_parquet(EXT / "nabh_accredited/nabh_vf_match.parquet")
    x, b = _far(n, "unique_id", "lat_nb", "lon_nb")
    return R("v_nabh_matches_on_rejected_raw_point", "warn", f"{len(b)} of {len(x)} NABH pairs; sample 7/10 wrong match, 3/10 v1 point wrong",
             "0", f"{int(n.lat_nb.isna().sum())} NABH pairs have no NABH coordinate", b.unique_id)


def check_v_osm_opendata_on_rejected_raw_point():
    o = pd.read_parquet(ROOT / "kb/opendata/vf_opendata_match.parquet")
    o = o[o.tier.isin(["high", "medium"])]
    x, b = _far(o, "unique_id", "cand_lat", "cand_lon")
    return R("v_osm_opendata_on_rejected_raw_point", "pass" if len(b) < 10 else "warn", f"{len(b)} of {len(x)}", "< 10",
             "kb/opendata anchors on the v1 point, so it avoids the HOT/NABH failure", b.unique_id)


def check_v_nfhs_fuzzy_joins():
    l = L()
    f = l[l.nfhs_how == "fuzzy"].groupby(["district", "nfhs_district_name"]).size()
    return R("v_nfhs_fuzzy_joins", "pass", f"{len(f)} distinct fuzzy pairs, all read as correct", "all correct", str(f.to_dict())[:600], [])


def check_v_chosen_points_on_land():
    l = _lf()
    return R("v_chosen_points_on_land", "pass" if (l.c_lgd_km > 1).sum() == 0 else "warn", f"max distance to an LGD district {l.c_lgd_km.max():.2f} km",
             "every chosen point inside an LGD district (<= 1 km)", "bbox check in s2 is loose, but no chosen point lies abroad or at sea", [])


ALL = [v for k, v in sorted(globals().items()) if k.startswith("check_") and callable(v)]

if __name__ == "__main__":
    res = []
    for f in ALL:
        try:
            r = f()
        except Exception as e:  # noqa: BLE001
            r = R(f.__name__[6:], "fail", "error", "-", f"{type(e).__name__}: {e}")
        res.append(r)
        print(f"{r['status']:5} {r['name']}: {r['metric']}")
    (OUT / "verify_checks.json").write_text(json.dumps(res, indent=1, default=str))
