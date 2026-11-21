"""Q5: how well can a typed city / district / PIN be resolved to a point with these tables?

Gazetteer layers (all normalised with geo_common.norm):
  district  directory district names (and NFHS names) -> median of the district's PIN points
  office    India Post office base names ('Navrangpura S.O' -> 'navrangpura') -> PIN point
  city      facility address_city values -> median PIN point of those facilities (PIN is the more
            trustworthy facility location signal, see FINDINGS)
Ambiguity = a name that maps to more than one state; spread = p90 distance of its points from their median.
Writes resolve_stats.json and resolve_test_cases.csv.
"""
import json
import sys

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo")
from geo_common import CITY_ALIAS, GEO, PIN_DIR, hav_km, norm, office_base

TESTS = ["Jaipur", "Lucknow", "Patna", "Gurgaon", "Gurugram", "Bombay", "Mumbai", "Bangalore", "Bengaluru",
         "Madras", "Calcutta", "Kolkata", "Trivandrum", "Cochin", "Kochi", "Vizag", "Mysore", "Allahabad",
         "Prayagraj", "Baroda", "Poona", "Noida", "Navi Mumbai", "Secunderabad", "Mohali", "Darbhanga",
         "Muzaffarpur", "Aurangabad", "Bilaspur", "Hamirpur", "Pratapgarh", "Raigarh", "Rampur", "Balrampur",
         "Jaipur Rajasthan", "Hydrabad", "Lucknw", "Bhubaneshwar", "Pondicherry", "Thane"]


def spread_km(pts):
    if len(pts) < 2:
        return 0.0
    la, lo = np.median(pts[:, 0]), np.median(pts[:, 1])
    return float(np.quantile(hav_km(la, lo, pts[:, 0], pts[:, 1]), 0.9))  # p90: robust to a few bad PINs


def build():
    cen = pd.read_parquet(GEO / "pin_centroids.parquet").dropna(subset=["best_lat"])
    p = pd.read_parquet(PIN_DIR)[["pincode", "officename", "district", "statename"]]
    p = p.merge(cen[["pincode", "best_lat", "best_lon", "state"]], on="pincode")
    p["office"] = p.officename.map(office_base)
    p["dn"] = p.district.map(norm)
    g = pd.read_parquet(GEO / "facility_geo.parquet").dropna(subset=["pin_lat"])
    g["cn"] = g.address_city.map(norm)
    layers = {
        "district": p.drop_duplicates("pincode").groupby("dn").apply(
            lambda x: (x[["best_lat", "best_lon"]].values, set(x.state.dropna())), include_groups=False),
        "office": p.groupby("office").apply(
            lambda x: (x[["best_lat", "best_lon"]].values, set(x.state.dropna())), include_groups=False),
        "city": g.groupby("cn").apply(lambda x: (x[["pin_lat", "pin_lon"]].values, set(x.pin_state.dropna())), include_groups=False),
    }
    return layers, cen


def resolve(q, layers, alias=True):
    n = norm(q)
    if alias:
        n = CITY_ALIAS.get(n, n)
    for layer in [x for x in ["district", "city", "office"] if x in layers]:
        if n in layers[layer].index:
            pts, states = layers[layer][n]
            return layer, len(pts), spread_km(pts), sorted(states)
    return None, 0, None, []


def main():
    layers, cen = build()
    st = {}
    for name, s in layers.items():
        sp = s.map(lambda t: spread_km(t[0]))
        ns = s.map(lambda t: len(t[1]))
        st[f"{name}_names"] = len(s)
        st[f"{name}_names_multi_state"] = int((ns > 1).sum())
        st[f"{name}_names_spread_over_50km"] = int((sp > 50).sum())
    # how many facility address_city values resolve, and how
    g = pd.read_parquet(GEO / "facility_geo.parquet")
    res = g.address_city.map(lambda c: resolve(c, {k: v for k, v in layers.items() if k != "city"})[0])
    st["facility_city_resolves_without_city_layer"] = res.fillna("unresolved").value_counts().to_dict()
    st["pins_in_directory"] = int(cen.pincode.nunique())
    st["facility_pins_not_in_directory"] = int((g.pin.notna() & ~g.pin_in_dir).sum())

    big = sorted(set(layers["district"].index) | set(layers["city"].index))
    rows = []
    for q in TESTS:
        a = resolve(q, layers, alias=False)
        b = resolve(q, layers, alias=True)
        fz = process.extractOne(CITY_ALIAS.get(norm(q), norm(q)), big, scorer=fuzz.WRatio, score_cutoff=85)
        rows.append((q, a[0], b[0], b[1], None if b[2] is None else round(b[2]), "|".join(b[3]),
                     None if fz is None else f"{fz[0]} ({fz[1]:.0f})"))
    t = pd.DataFrame(rows, columns=["typed", "layer_no_alias", "layer_with_alias", "n_points", "spread_km_p90",
                                    "states", "fuzzy_district_or_city"])
    t["ambiguous"] = t.states.str.count(r"\|") > 0
    t.to_csv(GEO / "resolve_test_cases.csv", index=False)
    st["tests_resolved_no_alias"] = int(t.layer_no_alias.notna().sum())
    st["tests_resolved_with_alias"] = int(t.layer_with_alias.notna().sum())
    st["tests_ambiguous"] = int(t.ambiguous.sum())
    st["tests_total"] = len(t)
    (GEO / "resolve_stats.json").write_text(json.dumps(st, indent=1, default=str))
    print(json.dumps(st, indent=1, default=str))
    print(t.to_string())


if __name__ == "__main__":
    main()
