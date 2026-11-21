# PIN code boundary polygons (data.gov.in, via ramSeraph mirror)

One polygon per Indian PIN code, published by the Department of Posts on data.gov.in and
mirrored as GeoParquet by ramSeraph. We use it to check whether a facility's coordinates
fall inside the PIN it claims, and to resolve a user's PIN input to an area.

Status: usable. Fetched, inspected and join-tested on 2026-11-21.

## Source

- Release page: https://github.com/ramSeraph/indian_admin_boundaries/releases/tag/postal
  (release published 2024-01-03; that date belongs to the PostalGIS file in the same release)
- File used: https://github.com/ramSeraph/indian_admin_boundaries/releases/download/postal/Datagov_Pincode_Boundaries.parquet
  (26,616,171 bytes, asset updated 2026-03-09 per the GitHub API; sha256 in `data/external/pincode_boundaries/sha256.txt`)
- Original: https://www.data.gov.in/catalog/all-india-pincode-boundary-geo-json. Live site returned
  HTTP 503 on 2026-11-21. Wayback snapshot of 2026-03-11
  (http://web.archive.org/web/20260311061650/https://www.data.gov.in/catalog/all-india-pincode-boundary-geo-json)
  reads: "Released Under: National Data Sharing and Accessibility Policy (NDSAP). Contributor:
  Ministry of Communications Department of Posts. Published On: 09/05/2025 Updated On: 09/05/2025".
  So the vintage is May 2025, not 2024-01-03 as the task brief assumed. The mirror's geojsonl.7z
  asset is dated 2025-05-10, which is consistent.
- Skipped: `PincodeBoundaries.parquet` (PostalGIS scrape, 335,023,721 bytes, over the 300 MB cap).
  Its release notes say it has many polygons with no PIN value and is missing eight states, so
  the data.gov.in file is the better choice anyway. `GSDL_Pincodes.parquet` (Delhi sub-localities,
  2.4 MB) was not fetched.

## Licence

- Release notes for this file: "License: [GODL](https://www.data.gov.in/Godl)".
- GODL text read from the Gazette notification
  (http://web.archive.org/web/20260410130930/https://www.data.gov.in/sites/default/files/Gazette_Notification_OGDL.pdf),
  section 3: "all users are provided a worldwide, royalty-free, non-exclusive license to use, adapt,
  publish (either in original, or in adapted and/or derivative forms), translate, display, add value,
  and create derivative works (including products and services), for all lawful commercial and
  non-commercial purposes". Section 4 conditions: attribution ("The user must acknowledge the provider,
  source, and license of data by explicitly publishing the attribution statement ... including ... the
  URL"), non-endorsement, no warranty.
- The mirror's own terms (https://raw.githubusercontent.com/ramSeraph/indianopenmaps/main/DATA_LICENSE.md)
  are CC0 1.0 with a request to credit Datameet and the government source.
- Redistribution inside a private team repo: allowed. Use in a public demo: allowed with the
  attribution line below and no claim of endorsement by the Department of Posts.
- Attribution to show in the app: "Department of Posts, Ministry of Communications, 2025, All India
  Pincode Boundary Geo JSON, Open Government Data Platform India, 09/05,
  https://www.data.gov.in/catalog/all-india-pincode-boundary-geo-json. Published under Government
  Open Data License - India: https://www.data.gov.in/Godl. Mirror: ramSeraph/indian_admin_boundaries."
- Caveat from the mirror README: Survey of India maps are the standard for political boundaries.
  PIN polygons are postal service areas, so show them as such, not as administrative borders.

## Fetch

```
external/pincode_boundaries/fetch.sh          # downloads the parquet + release JSON, writes sha256
.venv/bin/python -I external/pincode_boundaries/test_pip.py   # self-check of the geometry code
.venv/bin/python -I external/pincode_boundaries/join_test.py \
  data/external/pincode_boundaries/Datagov_Pincode_Boundaries.parquet \
  data/raw/facilities.parquet data/raw/india_post_pincode_directory.parquet \
  data/external/pincode_boundaries
```

No shapely or geopandas in the venv, so `join_test.py` parses WKB and does point-in-polygon in numpy
(about 3 s for everything). Outputs in `data/external/pincode_boundaries/`: `stats.json`,
`facility_pin_polygon_check.parquet` (one row per facility in the join denominator),
`handcheck_sample.csv`, `boundary_attrs.csv`.

## Inspection

- 19,312 rows, columns `Pincode, Office_Name, Division, Region, Circle, geometry (WKB), bbox`.
  GeoParquet 1.1.0, EPSG:4326 lon/lat, bbox 68.18..97.41 E, 6.71..37.09 N.
- Null rate 0.0 in every column. All PINs are 6 digits; every PIN appears once (one polygon per PIN).
- 988 MultiPolygons, 3,340,177 vertices, no unclosed rings. Median area 84 km2, 99th percentile
  1,223 km2, max 86,394 km2 (Diskit, Leh). 18 polygons under 0.01 km2 (slivers).
- `Circle` values carry a trailing space ("Kerala "); strip before use. `Circle` is the postal
  circle, not the state (Goa is under "Maharashtra", the north-east under "North Eastern").
- Coverage against the India Post directory (19,586 distinct PINs): 19,302 have a polygon (98.6%);
  10 polygon PINs are not in the directory. Weakest states: Mizoram 90.9%, Delhi 92.2%, J and K 92.5%.
  All states are present, unlike the PostalGIS file.
- Polygons tile the country without overlap at facility points: 0 facilities fall in 2+ polygons.

## Join test against facilities.parquet

The join key is the stated PIN plus the facility point. Denominators: 10,034 rows with a name,
9,964 with coordinates inside India's bbox, 9,920 with a 6-digit stated PIN.

| Check | Count | Rate |
|---|---|---|
| Point falls inside some PIN polygon | 9,960 / 9,964 | 99.96% |
| Stated PIN has a polygon (and coords valid) | 9,598 / 9,920 | 96.8% |
| Point inside the stated PIN's polygon | 5,925 / 9,598 | 61.7% |
| Within 1 km of the stated polygon | 6,933 / 9,598 | 72.2% |
| Within 2 km | 7,264 / 9,598 | 75.7% |
| More than 100 km from the stated polygon | 1,047 / 9,598 | 10.9% |
| Facility city fuzzy-matches (token_set_ratio >= 80) the containing polygon's office or division name | | 70.3% of contained points |

Distance to stated polygon (km): 0: 5,925; 0-1: 1,008; 1-2: 331; 2-5: 396; 5-10: 238; 10-25: 279;
25-50: 143; 50-100: 231; 100-250: 552; 250-500: 399; over 500: 96.

Compared with the audit's centroid distance (`audit/geo/facility_geo.parquet`, `d_pin_km`):
of the 1,114 facilities in this denominator that the audit puts over 100 km from the PIN centroid,
1,045 are also over 100 km from the polygon, and 33 are actually inside their stated polygon. Those
33 are false alarms caused by bad India Post directory coordinates (for example PIN 422009, Cidco
Colony Nashik: 12 facilities in Nashik inside the polygon but 165 km from the directory centroid;
also 742101 Berhampore, 751010 Bhubaneswar, 560017 Bengaluru). Only 6 facilities are within 10 km
of the centroid but over 10 km outside the polygon.

## Hand check (20 facilities, seed 7: 12 inside stated polygon, 8 outside)

| # | Facility | City | Stated PIN | Containing polygon | Dist km | Verdict |
|---|---|---|---|---|---|---|
| 1 | Bhumi Hospital | Vadodara | 390001 | 390001 Vadodara HO | 0 | correct |
| 2 | Sukoon Physiotherapy Clinic | Jamshedpur | 831003 | 831003 Golmuri SO | 0 | correct (Golmuri is in Jamshedpur) |
| 3 | Garg Ophthalmic Centre | Lucknow | 226020 | 226020 Niralanagar SO | 0 | correct |
| 4 | Nerlikar Multispeciality Hospital | Nashik | 422013 | 422013 Sawarkar Nagar SO | 0 | correct |
| 5 | Panacea Hospital | New Mumbai | 410206 | 410206 Panvel HO | 0 | correct |
| 6 | OrthoPlus Hospital | Ahmedabad | 380052 | 380052 Memnagar SO | 0 | correct |
| 7 | Apollo Sugar Clinic Beltola | Guwahati | 781006 | 781006 Assam Sachivalaya SO | 0 | correct |
| 8 | 32 Pearls Dental Clinic | Calangute | 403516 | 403516 Calangute SO | 0 | correct |
| 9 | Bright Dental Poly Clinic | Sultanpur | 228001 | 228001 Sultanpur Avadh HO | 0 | correct |
| 10 | Sparsh Hospital and IVF Centre | Sirsa | 125055 | 125055 Sirsa HO | 0 | correct |
| 11 | Maa Durga Hospital | Durgapur | 713212 | 713212 Bidhannagar SO | 0 | correct |
| 12 | Sankars Hospital | Kollam | 691001 | 691001 Kollam HO | 0 | correct |
| 13 | Government Medical College, Theni | Theni | 625531 | 625512 Aundipatti SO | 0.20 | near boundary, ambiguous |
| 14 | Essence Cosmetic Surgery | Noida | 201304 | 201316 Sec 122 Noida SO | 0.62 | near boundary, ambiguous |
| 15 | Jivanjyot Hospital | Halvad | 363330 | 363001 Surendranagar HO | 41.7 | real conflict: point is in Surendranagar, Halvad is in Morbi district |
| 16 | Indu Hospital | Ongole | 523002 | 523001 Ongole HO | 0.29 | near boundary, ambiguous |
| 17 | Cosmic Dermatology | Shillong | 793001 | 793003 Laitumkhrah SO | 0.43 | near boundary, ambiguous |
| 18 | Sudha Hospital | Erode | 607802 | 638011 Erode Collectorate SO | 182 | real conflict: 607802 is Cuddalore district, point and city are Erode |
| 19 | Sriya Hospital | Secunderabad | 500094 | 500081 Cyberabad SO | 15.7 | real conflict: point is in Madhapur, not Sainikpuri |
| 20 | Prem Hospital | Valliyur | 627117 | 641659 Karumathampatti SO | 300 | real conflict: coords in Tiruppur district, PIN and city in Tirunelveli |

Precision of "inside stated polygon": 12/12 confirmed. Of the 8 outside: 4 over 10 km are real
location conflicts (4/4), 4 under 1 km are boundary jitter that cannot be called errors. Use a
tolerance (flag at over 2 km, call it a conflict at over 10 km), not strict containment. Verdicts are
from the names and polygon attributes shown, not from a visit to each facility's website.

This is a geography dataset, so there is no service list to compare against facility claims.

## Product role

- Evidence: per-facility "location check" with three levels: inside stated PIN polygon,
  within 2 km, or N km away (cite stated PIN, containing PIN and distance). Feeds the
  uncertainty badge and down-weights facilities whose stated address and point disagree.
- Geography: resolve a PIN typed by the user to its polygon (and its centroid for distance).
  Better than the directory centroid, which is wrong by 100+ km for some PINs (422009 above).
- Reverse lookup: point (or a highway hotspot) to containing PIN, Division, Circle.

## Ingest plan for Databricks Free Edition

1. Upload the parquet (26.6 MB) to a UC volume, e.g. `/Volumes/workspace/external/raw/pincode_boundaries/`
   (we are read-only now; the volume does not exist yet).
2. `CREATE TABLE workspace.geo.pincode_boundaries AS SELECT trim(Pincode) pincode, Office_Name office_name,
   Division division, Region region, trim(Circle) circle, ST_GeomFromWKB(geometry) geom, bbox
   FROM read_files('/Volumes/.../Datagov_Pincode_Boundaries.parquet')`. The SQL warehouse supports
   ST functions: `SELECT st_contains(st_geomfromtext('POLYGON((0 0,4 0,4 4,0 4,0 0))'), st_point(1.0,1.0))`
   returned true on warehouse 6a2f5637720a2c17 on 2026-11-21 (`h3_longlatash3` also works).
   `ST_GeomFromWKB` on this file was not run.
3. Precompute `workspace.geo.facility_pin_check` (unique_id, stated_pin, containing_pin, inside,
   dist_km) once with ST_Contains / ST_Distance, or upload `facility_pin_polygon_check.parquet`
   from this script. The app reads the small table; no polygon maths at request time.
4. Optional: a simplified-geometry copy (or the 20.9 MB PMTiles asset) if the app draws PIN shapes on a map.
5. Refresh: manual, when data.gov.in republishes (last update 09/05/2025). Re-run fetch.sh and compare sha256.
6. App screens: search input (PIN to polygon and centroid), facility card (location-check badge with
   citation), and the district-planner map (reverse lookup of hotspot to PIN).

Effort: about 3 hours (upload and table 0.5 h, facility check table 1 h, app badge and PIN resolve 1.5 h).
