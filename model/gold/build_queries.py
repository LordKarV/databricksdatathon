"""End-to-end benchmark queries: 40 (service, location) requests for the four personas.

Local only. Run: /Users/karthikvattem/projects/datathon/.venv/bin/python build_queries.py
Writes queries.json next to this script.

Every query location is geocoded from the India Post directory, never typed in by hand:
  pin       robust PIN centroid (audit/geo/pin_centroids.parquet best_lat/best_lon)
  district  median of the robust centroids of all PINs whose dominant district is that district
  village   a branch office ("BO", a village post office) drawn with a fixed seed from the district; its own
            coordinates when within 30 km of its PIN centroid (raw office coordinates are noisy), else the centroid
  city      robust centroid of the city's GPO / head-office PIN
  coords    robust centroid of the PIN of a town on the named highway, rounded to 4 decimals; the query text is
            the bare "lat, lon". Accident-hotspot status of these segments is NOT verified against the MoRTH
            black-spot list; they are planner scenarios on major corridors.
Check per query (task requirement): at least 3 dataset facilities with valid coordinates within 150 km.
Also reported, for benchmark design only: facilities within 150 km whose record mentions the service
(claims audit, any grade except non_offer_only) and those graded strong or medium, plus the nearest mention.
These counts describe the raw records, not verified availability. coverage = none / sparse / ok (see coverage()).
"""
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd

AUDIT = Path("/Users/karthikvattem/projects/datathon/audit")
RAW = Path("/Users/karthikvattem/projects/datathon/data/raw")
OUT = Path(__file__).resolve().parent
SEED = 20261122
RADIUS_KM, MIN_FAC = 150.0, 3
VILLAGE_MAX_KM = 30.0
SVC = {"dialysis": "dialysis", "emergency_csection": "csection", "nicu": "nicu", "cardiac_surgery": "cardiac_surgery",
       "mri": "mri", "burn_care": "burns", "trauma_emergency": "trauma"}
HW, NGO, PLAN, CITY = "rural_health_worker", "ngo_coordinator", "district_planner", "patient_family"

# (persona, service, location_type, geocode key, urgency, scenario)
# district / village key: (DISTRICT, STATE); pin key: PIN; city key: (City, GPO PIN); coords key: (PIN, corridor)
SPECS = [
    (HW, "emergency_csection", "village", ("SITAMARHI", "BIHAR"), "emergency", "obstructed labour at home, ASHA arranging transport"),
    (HW, "nicu", "district", ("GAYA", "BIHAR"), "urgent", "preterm baby under 1.8 kg at a block PHC needs a referral"),
    (HW, "dialysis", "district", ("DARBHANGA", "BIHAR"), "scheduled", "patient with kidney failure needs twice-weekly dialysis"),
    (HW, "burn_care", "village", ("PURNIA", "BIHAR"), "emergency", "child with kerosene-lamp burns"),
    (HW, "cardiac_surgery", "district", ("MUZAFFARPUR", "BIHAR"), "scheduled", "child with congenital heart disease found in school screening"),
    (HW, "emergency_csection", "village", ("BAHRAICH", "UTTAR PRADESH"), "emergency", "prolonged labour, previous caesarean scar"),
    (HW, "nicu", "district", ("SHRAVASTI", "UTTAR PRADESH"), "urgent", "newborn with breathing difficulty after home birth"),
    (HW, "dialysis", "district", ("GORAKHPUR", "UTTAR PRADESH"), "scheduled", "diabetic patient started on maintenance dialysis"),
    (HW, "mri", "district", ("AZAMGARH", "UTTAR PRADESH"), "elective", "back pain with leg weakness, doctor asked for MRI"),
    (HW, "emergency_csection", "village", ("GUMLA", "JHARKHAND"), "emergency", "antepartum haemorrhage in a tribal hamlet"),
    (HW, "nicu", "district", ("SAHEBGANJ", "JHARKHAND"), "urgent", "low-birth-weight twins born at a CHC"),
    (HW, "trauma_emergency", "district", ("PALAMU", "JHARKHAND"), "emergency", "tractor rollover with head injury"),
    (HW, "emergency_csection", "village", ("KORAPUT", "ODISHA"), "emergency", "eclampsia at 36 weeks"),
    (HW, "nicu", "district", ("KALAHANDI", "ODISHA"), "urgent", "newborn with severe jaundice"),
    (HW, "burn_care", "district", ("MAYURBHANJ", "ODISHA"), "urgent", "adult with scald burns over 20 percent of body"),
    (HW, "dialysis", "pin", 767001, "scheduled", "Balangir town PIN, patient needs a nearer dialysis centre"),
    (NGO, "dialysis", "district", ("NANDURBAR", "MAHARASHTRA"), "scheduled", "mapping free dialysis slots for tribal patients"),
    (NGO, "nicu", "district", ("GADCHIROLI", "MAHARASHTRA"), "urgent", "sick newborn referral pathway for village health workers"),
    (NGO, "emergency_csection", "village", ("AMRAVATI", "MAHARASHTRA"), "emergency", "remote village, obstetric emergency transport plan"),
    (NGO, "cardiac_surgery", "district", ("YAVATMAL", "MAHARASHTRA"), "elective", "rheumatic heart disease valve surgery under a health scheme"),
    (NGO, "mri", "district", ("OSMANABAD", "MAHARASHTRA"), "elective", "subsidised MRI for a camp follow-up"),
    (NGO, "burn_care", "district", ("BEED", "MAHARASHTRA"), "urgent", "women with stove burns, NGO arranging referral"),
    (NGO, "trauma_emergency", "district", ("WASHIM", "MAHARASHTRA"), "emergency", "road crash victims on a state highway"),
    (NGO, "dialysis", "village", ("PALGHAR", "MAHARASHTRA"), "scheduled", "village patient needs a dialysis slot"),
    (PLAN, "trauma_emergency", "coords", (410202, "Mumbai-Pune Expressway near Khalapur"), "emergency", "multi-vehicle crash on the ghat section"),
    (PLAN, "trauma_emergency", "coords", (203135, "Yamuna Expressway near Jewar"), "emergency", "high-speed crash, golden hour planning"),
    (PLAN, "burn_care", "coords", (303108, "NH-48 Delhi-Jaipur near Kotputli"), "emergency", "tanker fire with burn casualties"),
    (PLAN, "trauma_emergency", "coords", (209732, "Agra-Lucknow Expressway near Tirwa, Kannauj"), "emergency", "bus overturn"),
    (PLAN, "trauma_emergency", "coords", (821109, "NH-19 Grand Trunk Road near Mohania, Kaimur"), "emergency", "truck and car collision"),
    (PLAN, "mri", "coords", (504001, "NH-44 near Adilabad"), "urgent", "spinal injury after crash needs MRI the same day"),
    (PLAN, "trauma_emergency", "coords", (443203, "Samruddhi Expressway near Sindkhed Raja, Buldhana"), "emergency", "night-time crash on the expressway"),
    (PLAN, "burn_care", "coords", (756001, "NH-16 near Balasore"), "emergency", "vehicle fire after collision"),
    (CITY, "cardiac_surgery", "city", ("Jaipur", 302001), "scheduled", "bypass surgery advised for a parent"),
    (CITY, "mri", "pin", 226003, "elective", "knee MRI near home in Lucknow"),
    (CITY, "dialysis", "city", ("Patna", 800001), "scheduled", "dialysis three times a week"),
    (CITY, "nicu", "city", ("Guwahati", 781001), "urgent", "baby born at 32 weeks needs NICU transfer"),
    (CITY, "burn_care", "pin", 781001, "emergency", "kitchen fire burns"),
    (CITY, "cardiac_surgery", "city", ("Bhubaneswar", 751001), "urgent", "valve disease with heart failure"),
    (CITY, "emergency_csection", "pin", 834001, "emergency", "foetal distress, private clinic cannot operate"),
    (CITY, "cardiac_surgery", "city", ("Bhopal", 462001), "elective", "planned valve replacement"),
]


def coverage(n_mention, n_strong_medium):
    """none: no record within 150 km mentions the service, so a correct answer says so and widens the radius.
    sparse: fewer than 3 strong-or-medium records, so a correct answer must flag weak evidence."""
    return "none" if n_mention == 0 else "sparse" if n_strong_medium < 3 else "ok"


def hav(lat, lon, lats, lons):
    r = np.radians
    a = np.sin(r(lats - lat) / 2) ** 2 + np.cos(r(lat)) * np.cos(r(lats)) * np.sin(r(lons - lon) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def main():
    cent = pd.read_parquet(AUDIT / "geo/pin_centroids.parquet").set_index("pincode")
    pdir = pd.read_parquet(RAW / "india_post_pincode_directory.parquet")
    pdir["lat"], pdir["lon"] = pd.to_numeric(pdir.latitude, errors="coerce"), pd.to_numeric(pdir.longitude, errors="coerce")
    geo = pd.read_parquet(AUDIT / "geo/facility_geo.parquet")
    fac = geo[geo.latitude.notna() & ~geo.coord_outside][["unique_id", "latitude", "longitude"]]
    grades = pd.read_parquet(AUDIT / "claims/out/grades.parquet")
    rng = random.Random(SEED)

    def pin_pt(p):
        c = cent.loc[p]
        return float(c.best_lat), float(c.best_lon)

    def district_pt(d, s):
        sub = cent[(cent.district.str.upper() == d) & (cent.state.str.upper() == s)]
        assert len(sub), (d, s)
        return float(sub.best_lat.median()), float(sub.best_lon.median()), len(sub)

    def village_pt(d, s):
        bo = pdir[(pdir.district.str.upper() == d) & (pdir.statename.str.upper() == s) & (pdir.officetype == "BO")]
        row = bo.sort_values(["officename", "pincode"]).iloc[rng.randrange(len(bo))]
        clat, clon = pin_pt(int(row.pincode))
        ok = pd.notna(row.lat) and hav(clat, clon, np.array([row.lat]), np.array([row.lon]))[0] <= VILLAGE_MAX_KM
        name = row.officename.replace(" B.O", "").replace(" BO", "").strip().title()
        return (float(row.lat), float(row.lon)) if ok else (clat, clon), name, int(row.pincode), "office" if ok else "pin_centroid"

    queries = []
    for i, (persona, svc, ltype, key, urgency, scenario) in enumerate(SPECS, 1):
        geo_note = ""
        if ltype == "district":
            lat, lon, n = district_pt(*key)
            text = f"{key[0].title()} district, {key[1].title()}"
            geo_note = f"median of {n} PIN centroids"
        elif ltype == "village":
            (lat, lon), vname, vpin, how = village_pt(*key)
            text = f"{vname} village, {key[0].title()} district, {key[1].title()}"
            geo_note = f"India Post branch office {vname} (PIN {vpin}), coordinates from {how}"
        elif ltype == "pin":
            lat, lon = pin_pt(key)
            text = str(key)
            geo_note = "robust PIN centroid"
        elif ltype == "city":
            lat, lon = pin_pt(key[1])
            text = key[0]
            geo_note = f"centroid of GPO PIN {key[1]}"
        else:
            lat, lon = (round(x, 4) for x in pin_pt(key[0]))
            text = f"{lat:.4f}, {lon:.4f}"
            geo_note = f"{key[1]}; centroid of PIN {key[0]}"
        d = hav(lat, lon, fac.latitude.values, fac.longitude.values)
        near = fac.unique_id.values[d <= RADIUS_KM]
        g = grades[(grades.service == SVC[svc]) & (grades.grade != "non_offer_only")]
        gm = g[g.unique_id.isin(near)]
        dist_by_id = dict(zip(fac.unique_id.values, d))
        nearest = min((dist_by_id[u] for u in g.unique_id if u in dist_by_id), default=None)
        assert len(near) >= MIN_FAC, (i, text, len(near))
        queries.append(dict(
            query_id=f"q{i:02d}", service=svc, location_text=text, location_type=ltype, persona=persona, urgency=urgency,
            notes=f"{scenario}. Geocode: {geo_note}.",
            lat=round(lat, 4), lon=round(lon, 4),
            n_facilities_150km=int(len(near)), n_service_mention_150km=int(gm.unique_id.nunique()),
            n_service_strong_or_medium_150km=int(gm[gm.grade.isin(["strong", "medium"])].unique_id.nunique()),
            nearest_service_mention_km=None if nearest is None else round(float(nearest), 1),
            coverage=coverage(int(gm.unique_id.nunique()), int(gm[gm.grade.isin(["strong", "medium"])].unique_id.nunique()))))

    for k in ("service", "location_type", "persona", "urgency"):
        print(k, pd.Series([q[k] for q in queries]).value_counts().to_dict())
    print("coverage", pd.Series([q["coverage"] for q in queries]).value_counts().to_dict())
    assert coverage(0, 0) == "none" and coverage(4, 2) == "sparse" and coverage(5, 3) == "ok"
    assert len(queries) == 40 and {q["service"] for q in queries} == set(SVC)
    assert {q["location_type"] for q in queries} == {"city", "district", "pin", "coords", "village"}
    assert {q["urgency"] for q in queries} == {"emergency", "urgent", "scheduled", "elective"}
    (OUT / "queries.json").write_text(json.dumps(queries, indent=1, ensure_ascii=True))
    for q in queries:
        print(q["query_id"], q["service"], q["location_type"], q["location_text"], q["n_facilities_150km"],
              q["n_service_mention_150km"], q["n_service_strong_or_medium_150km"], q["nearest_service_mention_km"])


if __name__ == "__main__":
    main()
