# LGD district polygons (ramSeraph mirror)

District boundary polygons keyed by LGD district code, used to put any point (a facility or a user's
location) into a district, flag facility coordinates that fall outside their stated district, and
reach NFHS-5 district indicators.

## Source

- Release page: https://github.com/ramSeraph/indian_admin_boundaries/releases/tag/districts
  (release "Indian Districts", published 2023-12-11T10:14:05Z)
- File fetched: https://github.com/ramSeraph/indian_admin_boundaries/releases/download/districts/LGD_Districts.parquet
  (34,454,472 bytes, GeoParquet 1.1.0, WKB, EPSG:4326 lon/lat, bbox covering column)
  sha256 3482b2d53e42a62b80fa36b156995ddee8a33e6c73c8c2b2764084234967571a
- Upstream per the release notes: LGD/Bharatmaps,
  https://mapservice.gov.in/gismapservice/rest/services/BharatMapService/Admin_Boundary_Village/MapServer/1
- Same release also has SOI_Districts (46.2 MB, Survey of India) and bhuvan_districts (62.5 MB). Not
  fetched; SOI is the one to use if boundaries are ever drawn on a public map (see licence).

## Licence and terms

The release notes point to https://github.com/ramSeraph/indianopenmaps/blob/main/DATA_LICENSE.md
(saved as data/external/lgd_district_polygons/DATA_LICENSE.md). Quote:

> Most of the data here(anything that links here for licensing) is licensed using CC0 1.0 ...
> This means that I am relinquishing what ever rights I might have on this data.
> However, I request that you actively acknowledge and give attribution to Datameet community for
> collating the data and also the original government sources wherever possible.

It also tells readers to see the National Data Sharing and Access Policy 2012, the Geospatial
Guidelines 2021 and the National Geospatial Policy 2022. The LGD tiles are served under an
indianopenmaps.com "not-so-open" path, so the mirror author himself flags upstream terms as unclear.

- Private team repo: fine for the mirror's rights (CC0). Keep the raw file out of git anyway (it is
  34 MB and the data dir is gitignored); fetch.sh reproduces it byte for byte (sha256 above).
- Public demo: using the polygons for lookups and showing district names plus an attribution line
  ("District boundaries: LGD/Bharatmaps via Datameet / ramSeraph, CC0") is low risk. Drawing these
  polygons as a map of India is not recommended: Survey of India boundaries are the legal standard for
  displayed maps, and this layer has two PoK districts (Muzaffarabad, Mirpur) with LGD code 0. If a map
  is needed, use SOI_Districts or a basemap. This is my reading of the pages above, not legal advice.

## Fetch

    ./fetch.sh

Downloads the parquet, the licence and the release JSON into
/Users/karthikvattem/projects/datathon/data/external/lgd_district_polygons/ and writes SHA256SUMS.

## Inspection

- 785 rows (districts), 36 states/UTs, 18 columns: OBJECTID, dtname, stname, stcode11, dtcode11,
  year_stat, dist_lgd, state_lgd, remarks, Dist, InPoly_FID, SimPgnFlag, MaxSimpTol, MinSimpTol,
  SHAPE_Length, SHAPE_Area, geometry (WKB Polygon/MultiPolygon), bbox.
- Null rate 0.0 in every column; remarks is blank in all 785 rows.
- 1,812 rings, 3,341,402 vertices.
- dist_lgd is unique except code 0, used by Muzaffarabad and Mirpur (PoK, no facilities possible).
- year_stat: 622 "2011_c", 41 "2016_c", 31 "update2014", 30 "2022", 19 "2023", 13 blank (all 13 are
  Andhra Pradesh parent districts after the 2022 split), remainder 2012 to 2020.
- Freshness: includes the 2022 AP split (26 AP districts), Rajasthan at 50 districts (2023 creations
  such as Balotra, Kekri, Dudu), Telangana 33, Assam 35. It predates the Rajasthan cabinet decision of
  2024-12-28 that dissolved 9 of those districts (Dudu, Kekri, Shahpura, Neem Ka Thana, Gangapur City,
  Jaipur Rural, Jodhpur Rural, Anupgarh, Sanchore; state back to 41), per
  https://www.newsonair.gov.in/rajasthan-govt-announces-to-dissolve-9-out-of-17-districts-created-by-previous-govt
  and https://scroll.in/latest/1077338/rajasthans-bjp-government-scraps-12-new-districts-and-3-divisions .
  Those 9 polygons need a parent mapping before the app shows them. Other post-2023 changes not checked.
- Coastal polygons are simplified: 3 Mumbai facility points (Juhu, Hinduja Mahim) fall just outside;
  join_test.py snaps points within 0.03 degrees (about 3 km) of a polygon vertex.

## Join test

    /Users/karthikvattem/projects/datathon/.venv/bin/python -I join_test.py \
      /Users/karthikvattem/projects/datathon/data/external/lgd_district_polygons/LGD_Districts.parquet \
      /Users/karthikvattem/projects/datathon/data/external/lgd_district_polygons

No shapely in the venv, so WKB is parsed by hand and point-in-polygon is even-odd ray casting in
numpy with a bbox prefilter (a hole self-check runs first). Whole run takes about 5 s. Outputs in the
data dir: facility_lgd_district.parquet, pin_lgd_district.parquet, nfhs_lgd_crosswalk.csv, stats.json.

### Facilities (data/raw/facilities.parquet)

- 10,088 rows, 9,970 with coordinates. 9,962 of 9,970 (99.9%) land in a district polygon (9,959 inside,
  3 snapped). 0 points fall in two polygons. The 8 left outside all have impossible coordinates
  (for example latitude -81.7, or 46.07, 106.17 for a Hazaribagh hospital).
- Agreement of polygon district with the PIN-directory district from audit/geo/facility_district.parquet
  (name fuzzy match, token_sort_ratio >= 85 or containment): 8,289 of 9,954 compared (83.3%).
  By how the audit assigned the district: "pin" (coords within 50 km of the PIN) 94.0% of 8,271;
  "coords" 97.1% of 278; "coords_city" 97.3% of 149; "pin_conflict" (coords > 50 km from the PIN)
  7.8% of 1,256. So the polygons confirm clean rows and the disagreements are concentrated in rows
  whose coordinates are already suspect.
- Among the "pin" rows the residual 6% are mostly metro boundary pairs: Ranga Reddy / Medchal vs
  Hyderabad (48 + 25), Kanchipuram vs Chennai (21), Tirupati vs Chittoor (16, a 2022 split the PIN
  directory does not have), Thane vs Mumbai Suburban (15), Delhi sub-districts.

### Hand check of 20 random facility assignments (random_state=7)

Verdict = is the polygon district the facility's real district, judged from name, city and PIN.

| # | facility | city, PIN | PIN district | polygon district | verdict |
|---|---|---|---|---|---|
| 1 | Jalaram Hospital | Ahmedabad 380015 | Ahmadabad | Vadodara | wrong (coords off) |
| 2 | Popular Nursing Home | Patna 800004 | Patna | Patna | right |
| 3 | Shanti Ved Hospital | Agra 282004 | Agra | Deoria | wrong (coords off) |
| 4 | Brij Dental Clinic | Ahmedabad 380013 | Ahmadabad | Ahmadabad | right |
| 5 | Arogyam Health Clinic | Pune 411014 | Pune | Pune | right |
| 6 | Manipal Hospital, Vijayawada | Vijayawada 520003 | NTR | Guntur | plausible, unverified (point is on the Guntur bank of the Krishna) |
| 7 | Prashanth Dental Clinic | Bangalore 560040 | Bengaluru Urban | Mandya | wrong (coords off) |
| 8 | Central Hospital and Maternity Home | Jalandhar 144001 | Jalandhar | Jalandhar | right |
| 9 | Rejuvena Cosmo Care | Jaipur 302021 | Jaipur | Jaipur | right |
| 10 | Lifeaid Medical Centre | Gurgaon 122022 | Gurugram | Gurugram | right |
| 11 | Westfort Hi-Tech Hospital | Thrissur 680022 | Thrissur | Thrissur | right |
| 12 | Chaudhary Dental Clinic | Chhatarpur 471001 | Chhatarpur | Vidisha | wrong (coords off) |
| 13 | Anmol Children Hospital | Vadodara 390012 | Vadodara | Vadodara | right |
| 14 | Center for Medical Genetics | Chennai 600010 | Chennai | Chennai | right |
| 15 | Oral White Dental Clinic | Kochi 682032 | Ernakulam | Ernakulam | right |
| 16 | Kumaran Medical Center | Coimbatore 641107 | Coimbatore | Coimbatore | right |
| 17 | Accident and Fracture Hospital | Vadodara 390016 | Vadodara | Vadodara | right |
| 18 | Anu Shree Dental Care | Indore 452018 | Indore | Indore | right |
| 19 | Deepam Hospital | Guduvancheri 607001 | Cuddalore | Chengalpattu | right (Guduvancheri is in Chengalpattu; the PIN is wrong) |
| 20 | Netaji Eye Hospital, Purulia | Ramchandrapur 723142 | Purulia | Purulia | right |

15 right, 1 plausible but unverified, 4 wrong. All 4 wrong ones are audit "pin_conflict" rows, where
the coordinate itself is wrong; the polygon lookup was correct for the coordinate given. A further 12
randomly drawn disagreements were all coordinate errors (for example an Andheri West nursing home
plotted in Nashik, a Surat hospital plotted in Kachchh).

### India Post offices (data/raw/india_post_pincode_directory.parquet)

151,012 of 165,627 offices have coordinates inside the India bbox; 149,313 land in a polygon;
123,828 (82.9%) agree with the directory's district name. Disagreements are mostly new districts the
directory still files under the parent (Balotra / Barmer 228, Didwana Kuchaman / Nagaur 224, Anakapalli /
Visakhapatnam 128) and post offices with wrong coordinates (Koppal / Palakkad 113, Adilabad / Bijnor 104).
Every LGD district except one (784 of 785 codes) contains at least one post office.

### NFHS-5 crosswalk (nfhs_lgd_crosswalk.csv)

Within-state name match LGD dtname to NFHS district_name: 632 score >= 90, 24 at 80 to 89, 129 below 80.
Rule used: name when >= 90, or 80 to 89 and the post-office majority agrees (this rejects
Korea -> Korba); otherwise the NFHS district that most post offices inside the polygon map to through
audit/geo/district_nfhs_map.csv. Result: 655 by name, 129 by post-office majority, 1 unmapped
(Leparada), 696 of 706 NFHS districts reached. Spot check of 15 post-office-majority rows: 13 right,
2 wrong (Poonch -> Anantnag should be Punch; Kamjong -> Imphal East should be Ukhrul). po_majority_share
is kept so the app can show low-confidence mappings as approximate.

## Product role

- Resolve a user point (coordinates, or a PIN centroid) to an LGD district and state, then to the NFHS
  district for the local-need panel.
- Second, independent location signal per facility: "coordinates fall in X district, address says Y".
  Disagreement is an uncertainty flag on the result card, not a silent fix.
- District is the planner unit for the district-planner screen (coverage by district).

## Ingest plan (Databricks Free Edition)

1. Upload LGD_Districts.parquet (34 MB) to a UC volume, e.g. /Volumes/<catalog>/geo/raw/lgd/.
2. CREATE TABLE <catalog>.geo.lgd_districts AS SELECT dist_lgd, dtname, stname, state_lgd, year_stat,
   bbox, geometry AS geom_wkb FROM parquet.`/Volumes/.../LGD_Districts.parquet`, plus a
   <catalog>.geo.lgd_nfhs_crosswalk table from nfhs_lgd_crosswalk.csv and a
   <catalog>.geo.facility_district table from facility_lgd_district.parquet (precomputed locally, no
   spatial compute needed in the workspace).
3. App point lookup on the warehouse: ST_Contains(ST_GeomFromWKB(geom_wkb), ST_Point(lon, lat)) with a
   bbox prefilter. Verified read-only that the SQL warehouse runs ST_Contains and h3_longlatash3
   (SELECT returned true and an H3 cell). Query speed on the real 3.3M-vertex table not measured.
4. Refresh: static; re-run fetch.sh if the release is updated. Before the demo, map the 9 dissolved
   Rajasthan districts to their parents.
5. Screens: search (location to district), result card (location consistency flag), planner view.

Effort: about 3 hours (upload and tables 1 h, app lookup 1 h, Rajasthan fix and checks 1 h).
