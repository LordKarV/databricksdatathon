# MAP travel time to healthcare 2020 (Weiss et al.)

India clips of three 1 km rasters from the Malaria Atlas Project (MAP): motorized
travel time to the nearest hospital or clinic, walking-only travel time, and the
motorized friction surface (minutes per metre) the travel times were computed from.
Verdict: usable. The friction surface is the more valuable layer for us because it
gives facility-specific drive times offline; the travel-time layers give a
remoteness context and a coordinate sanity flag.

## Source

- Service: MAP GeoServer WCS 2.0.1, `https://data.malariaatlas.org/geoserver/Accessibility/wcs`
- Capabilities read: `...?service=WCS&version=2.0.1&request=GetCapabilities` (HTTP 200, 558,054 bytes)
- Coverages fetched (bbox Lat 6-38, Long 68-98, EPSG:4326, cell 1/120 degree):
  - `Accessibility__202001_Global_Motorized_Travel_Time_to_Healthcare`
  - `Accessibility__202001_Global_Walking_Only_Travel_Time_To_Healthcare`
  - `Accessibility__202001_Global_Motorized_Friction_Surface`
- Exact GetCoverage URL pattern:
  `https://data.malariaatlas.org/geoserver/Accessibility/wcs?service=WCS&version=2.0.1&request=GetCoverage&coverageId=<ID>&format=image/tiff&subset=Lat(6,38)&subset=Long(68,98)`
- DescribeCoverage: global grid 43200 x 17400, nodata -9999.0, keywords
  `spatialResolution:1Km`, `temporalExtent:2019`.
- Paper: Weiss D.J. et al., "Global maps of travel time to healthcare facilities",
  Nature Medicine (2020) (citation as given on the Earth Engine page; the Nature page
  redirected to a login, so the paper itself was not read).

## Licence and terms

- Earth Engine catalog, accessibility to healthcare 2019 (same product), read 2026-11-21:
  "This work is licensed under a Creative Commons Attribution 4.0 International License".
  https://developers.google.com/earth-engine/datasets/catalog/Oxford_MAP_accessibility_to_healthcare_2019
- Earth Engine catalog, friction surface 2019: same CC BY 4.0 sentence.
  https://developers.google.com/earth-engine/datasets/catalog/Oxford_MAP_friction_surface_2019
- MAP open access policy, read 2026-11-21: maps under "Creative Commons Attribution 3.0
  Unported License"; "There are no restrictions to access or use of the data" but "we
  request that the original source details (provided with all data downloads) are cited".
  https://malariaatlas.org/open-access-policy/
- The WCS capabilities document has no Fees or AccessConstraints text.
- Conclusion: both CC BY 3.0 and 4.0 allow copying, redistribution and adaptation,
  including commercial, with attribution. Keeping the clips in a private team repo and
  showing them (and derived numbers) in a public demo are allowed, provided the demo
  credits "Malaria Atlas Project, Weiss et al. 2020, Nature Medicine, CC BY". The two
  pages name different CC BY versions; either way attribution is the only condition.

## Fetch

```
bash fetch.sh            # 3 GetCoverage requests, 2 s apart, skips existing files
```

Output: `data/external/map_travel_time_healthcare_2020/raw/india_<coverage>.tif`,
67,109,780 bytes each (3600 x 3840 float32, 512-pixel tiles, uncompressed, big-endian).
Under the 300 MB limit, so the full India clip was fetched; the global file (about 708 MB)
was not.

The venv has no rasterio or GDAL, so `tiff_np.py` is a small numpy+zlib reader for this
exact TIFF layout (single band float32, tiles or strips, no compression or deflate).

## Inspect (analyze.py, stats.json)

```
python -I analyze.py RAW_DIR data/raw/facilities.parquet data/raw/india_post_pincode_directory.parquet audit/geo OUT_DIR
python -I check_lookup.py RAW_DIR OUT_DIR
```

- Grid 3840 rows x 3600 cols = 13,824,000 cells per layer, origin 68.0E 38.0N.
- India mask used for stats: cells within about 5 km of any post office with
  coordinates (3,467,344 cells). Not an official boundary.
- Nodata: 35.6% of the clip (sea, neighbouring countries' missing areas), 2.17% inside
  the India mask (coastal and island cells). Friction has no nodata in the clip.
- Motorized travel time inside the mask: median 19.1 min, p90 71.1, p99 445.9,
  max 4,834 min. Walking: median 109, p90 289, p99 1,145 min. No negative values.
- Friction: 0.0005 to 4.24 min/m inside the mask.
- Freshness: nominal 2019 (facility points from OpenStreetMap/healthsites.io and Google
  Maps per the search summary of the paper; not verified by reading the paper). The
  Earth Engine pages mark these assets as superseded by a 2019 v5.1 friction surface.
- Known limits: time to the nearest "hospital or clinic" of any kind, not to a facility
  offering a given service; optimal-speed assumption; ignores traffic, season,
  vehicle availability, and state borders.

## Join test

Facilities (`facility_access.parquet`): point lookup of the cell containing each
facility's latitude/longitude.

- 10,088 rows; 9,970 have coordinates; 9,964 fall inside the clip; 9,944 get a valid
  value. Match rate 9,944 / 10,088 = 98.6% of rows, 9,944 / 9,970 = 99.7% of rows
  with coordinates. The 26 misses are nodata cells (coast) or outside India.
- Lookup correctness: `check_lookup.py` fetched tiny bboxes for 5 facility points from
  the server and the local value equalled the server value at all 5.
- Facility cells: median motorized time 0.0 min, p90 1.39, p99 13.5; so most VF points
  sit on cells MAP also treats as having a clinic.
- Coordinate-error signal: share of facilities flagged `geo_conflict` by the geo audit
  is 14.9% overall (of 9,944), but 56% when tt_motor > 10 min (83 of 149), 75% when
  > 30 min (24 of 32) and 82% when > 60 min (9 of 11). High travel time at a claimed
  facility point is a cheap "these coordinates are probably wrong" flag. It cannot see
  city-scale displacement: facilities whose coordinates are more than 25 km from their
  PIN also have median 0.0 min (n=1,791), because they usually land in another town.

Hand check of 20 random facility lookups (`derived/handcheck_20.csv`, seed 7). Raster
value correct in all 20 by construction (verified above); the question is whether the
point is the facility. Coordinates consistent with address city or PIN: 18 / 20.

| # | Facility | City (stated) | Coord district | tt motor / walk min | Verdict |
|---|---|---|---|---|---|
| 1 | Ankur Hospital | Karad City | Pune (PIN 411039 agrees) | 0.0 / 0 | ok coord, city label odd |
| 2 | Padmaja Hospital | Visakhapatnam | Visakhapatnam | 0.0 / 0 | ok coord, PIN 116 km off |
| 3 | The Face Head & Neck Cancer Hospital | Amravati | Amravati | 0.0 / 0 | ok |
| 4 | Kharar Civil Hospital Blood Bank | Kharar | S.A.S Nagar | 0.68 / 9 | ok |
| 5 | Sun Eye Hospital & Laser Centre | Lucknow | Lucknow | 0.0 / 0 | ok |
| 6 | Dr. Arzoo Arora Dental Care | Alwar | Alwar | 0.0 / 0 | ok |
| 7 | Sanjeevani Multispeciality Clinic | Ghaziabad | Ghaziabad | 1.22 / 9 | ok |
| 8 | Eugene Molecular Diagnostics | Kozhikode | Kozhikode | 0.0 / 0 | ok |
| 9 | Joshi Dental Clinic | Jodhpur | Jodhpur | 1.15 / 14 | ok |
| 10 | The Surgical Clinic and Nursing Home | Chennai | Chennai | 0.90 / 10 | ok |
| 11 | Lady Dufferin Victoria Hospital | Kolkata | Kolkata | 0.0 / 0 | ok |
| 12 | Scope Hospital | Lucknow | Lucknow | 0.0 / 0 | ok |
| 13 | Ashok Hospital | Bareilly | Mathura (200 km from PIN) | 0.0 / 0 | wrong coord, not flagged |
| 14 | Krishnammal Memorial Hospital | Allinagaram | Theni | 0.0 / 0 | ok |
| 15 | CARE Hospitals - Nagpur | Nagpur | Jalna (359 km from PIN) | 0.0 / 0 | wrong coord, not flagged |
| 16 | Kolors Healthcare Davangere | Davangere | Davangere | 1.35 / 10 | ok |
| 17 | Trica Hair Clinic | Mumbai | Mumbai Suburban | 0.0 / 0 | ok |
| 18 | Dr. Fulari's Happy Smiles Dental Clinic | Sangli | Sangli | 5.47 / 89 | ok, walk time high for urban |
| 19 | Archana Hospital | Kallakkurichi | Villupuram | 0.0 / 0 | ok |
| 20 | K.G.R Surgical Nursing Home | Erode | Erode | 0.0 / 0 | ok |

The 11 facilities with tt_motor > 60 min are in `derived/facilities_tt_gt60.csv`; e.g.
"Vikas Hospital, Najafgarh, Delhi" has coordinates 33.14N 75.94E (Jammu and Kashmir),
448 min from any clinic, 514 km from its PIN.

PIN directory (`pin_access.parquet`): 151,010 of 165,627 post offices have numeric
coordinates inside the bbox; 149,830 get a value (0.78% nodata). Median 8.6 min, p90
33.4, p99 155.7.

Districts (`district_access.parquet`): post offices grouped by directory state and
district (unweighted, a settlement proxy, not population-weighted). 755 directory
districts, 745 mapped to an NFHS-5 district name through the geo audit's
`district_nfhs_map.csv`, covering 694 distinct NFHS districts (of 706). Most remote by
median: Kurung Kumey (720 min), Shi Yomi (619), Upper Subansiri (560), West Siang
(529), all Arunachal Pradesh.

Not a service list, so there are no service labels to count.

## Facility-specific routing from the friction surface

`analyze.dijkstra` runs an 8-neighbour least-cost search on the friction surface
(edge cost = metres x mean friction of the two cells, the same scheme as gdistance
accCost used by MAP). Check: at 12 random PIN points, min over nearby cells with
TT < 1 min of (our cost + MAP TT) reproduced MAP's own value with median absolute
error 0.0 min and max 1.4 min (`routing_check.csv`).

Demo (`routing_demo.csv`): VF facilities whose procedure, specialties or capability
text mentions dialysis, ranked by drive minutes from a user point.

- Rural Saharsa, Bihar (25.98N 86.95E): first hit is "Sadar Hospital, Jamshedpur,
  PIN 814133" at 57 km / 80 min, a record whose city, PIN and coordinates disagree, so
  routing must run after the geo audit filters. Next: Shivam Kidney Hospital, Begusarai,
  103 km / 156 min; Raiganj GMCH 125 km / 157 min; R. B. Memorial, Darbhanga 106 km /
  165 min. Darbhanga is closer in a straight line than Raiganj but slower by road, which
  is the trade-off the raster makes visible.
- Rural Chandrapur, Maharashtra (19.91N 79.30E): GMC Chandrapur 4.9 km / 6 min, then
  "Nakshatra Hospital, Nagole 500068" (a Hyderabad PIN) at 84 km, again a contaminated
  coordinate, then Nagpur hospitals at about 137 km / 141 min.

Run time for one 301 x 301 cell window (about 125 km radius) in pure Python: a
few seconds or less on a laptop (the whole analyze.py ran in 3.4 s wall).

## Product role

- Remoteness context on the search screen: "MAP estimates the nearest clinic of any
  kind is X min by road from here"; above about 60 min widen the search radius and show
  an uncertainty note.
- The HOW for distance trade-offs: rank candidates by modelled drive minutes from the
  friction surface rather than straight-line km, and show both.
- Coordinate sanity: tt_motor > 30 min at a facility's own point adds a "location
  suspect" flag (75% agree with the geo audit).
- District planner view: district median and p90 drive time, share of post offices
  over 60 min, joined to NFHS-5 need indicators.
- Caveat in the UI: the layer measures time to any clinic in 2019 at ideal speed, not
  to a facility that offers the requested service.

## Ingest plan for Databricks Free Edition

1. Upload the three GeoTIFFs (about 201 MB total) to a Unity Catalog volume,
   e.g. `/Volumes/workspace/default/external/map_access_2020/`, from a laptop
   (Databricks compute cannot reach malariaatlas.org).
2. Tables (from the parquet files in `derived/`, or recomputed in a notebook):
   `workspace.default.map_facility_access` (unique_id, tt_motor, tt_walk, friction),
   `workspace.default.map_pin_access` (pincode, officename, district, tt_motor, tt_walk),
   `workspace.default.map_district_access` (state, district, final_dn, medians, p90, share > 60).
3. App: load the friction raster (55 MB float32) into memory at startup from the volume
   and run the Dijkstra per query over a window around the user point; look up the
   user's own cell in the travel-time raster. Apps have 6 GB RAM; no GPU needed.
4. Refresh: none planned; MAP publishes new versions rarely. Re-run fetch.sh if a
   newer coverage ID appears in GetCapabilities.

Effort: about 4 hours (upload and tables 1 h, app routing module and caching 2 h,
UI text and attribution 1 h).

## Files

- `fetch.sh` download; `tiff_np.py` TIFF reader; `analyze.py` inspect, join, routing;
  `check_lookup.py` lookup self-check against the server.
- Data (gitignored): `data/external/map_travel_time_healthcare_2020/raw/` and `derived/`.
