# Health facilities of India (OSM, HOT export)

Independent OpenStreetMap record of 139,664 health features in India, used to check that a
Virtue Foundation (VF) facility exists where the VF record says it is.

## Source

- HDX page: https://data.humdata.org/dataset/hotosm_ind_health_facilities
- HDX metadata API (read for licence and dates): https://data.humdata.org/api/3/action/package_show?id=hotosm_ind_health_facilities
- File used: https://production-raw-data-api.s3.amazonaws.com/ISO3/IND/_layers/osm/health_facilities.parquet
  (GeoParquet, 14,531,655 bytes, sha256 543ea012d01a79123a65a62421d77ff1624f8ea29edd5c40086293bf9d2ea4ae)
- Also fetched: the GeoJSON zip (to read its README.txt and config.yaml), the STAC metadata JSON and the
  HTML data quality report from the same S3 prefix.
- Publisher: Humanitarian OpenStreetMap Team (HOT), built with oex 0.4.16 (https://github.com/osgeonepal/oex).
- OSM snapshot date 2026-10-09; HDX resource last modified 2026-10-11. HDX `data_update_frequency` is -2
  (I read this as "as needed"; not verified against HDX docs).

## Licence and terms

HDX `license_title`: "Open Database License (ODC-ODbL)", https://opendatacommons.org/licenses/odbl/1-0/.
HDX caveat: "OpenStreetMap data is crowd sourced and cannot be considered to be exhaustive".

From https://www.openstreetmap.org/copyright: the data is "licensed under the Open Data Commons Open
Database License (ODbL)"; you must "Provide credit to OpenStreetMap by displaying our attribution notice"
and "Make clear that the data is available under the Open Database License"; "If you alter or build upon
our data, you may distribute the result only under the same license."

From https://opendatacommons.org/licenses/odbl/summary/: free to "copy, distribute and use the database",
"produce works from the database" and "modify, transform and build upon the database"; "You must
attribute any public use of the database, or works produced from the database"; "If you publicly use any
adapted version of this database ... you must also offer that adapted database under the ODbL."

What this means for us (my reading, not legal advice):
- Private team repo: allowed. The raw file stays in data/external (gitignored); scripts are fine to commit.
- Public demo: allowed with the notice "(c) OpenStreetMap contributors, ODbL" on any screen that shows
  OSM-derived data, linking to openstreetmap.org/copyright.
- Share-alike: the VF-to-OSM match table is an adapted database. If the demo is public we must be ready to
  publish that table (osm_id, match tier, distance) under ODbL. Keep it as a separate table from the VF data
  so the VF dataset itself is not pulled under ODbL (ODbL treats a collection of independent databases
  differently from one merged database).

## Fetch steps

```
bash external/hotosm_ind_health_facilities/fetch.sh               # GeoParquet + metadata, about 15 MB
bash external/hotosm_ind_health_facilities/fetch_overpass_sample.sh # Bihar, all tags, one Overpass request
```

The GeoJSON zip (9.5 MB) was fetched once by hand with curl to read its README.txt and config.yaml; it is
not needed for the pipeline.

## What is in the file

139,664 rows: 130,808 nodes, 8,748 ways, 108 relations. Extent lon 68.58 to 97.02, lat 8.08 to 34.85.
Only 12 OSM tags are exported (config.yaml `osm.select`): name, name:en, amenity, building, healthcare,
healthcare:speciality, operator:type, capacity:persons, addr:full, addr:city, source, plus admin codes
(adm1 to adm3 from geoBoundaries) and a transliterated `name_latin`.

Null rates (empty string counted as null):

| field | non-null | null rate |
|---|---|---|
| name | 136,336 | 0.024 |
| name_latin | 136,647 | 0.022 |
| amenity | 96,669 | 0.308 |
| healthcare | 85,011 | 0.391 |
| addr_full | 100,161 | 0.283 |
| addr_city | 8,789 | 0.937 |
| operator_type | 9,554 | 0.932 |
| healthcare_speciality | 5,877 | 0.958 |
| building | 4,058 | 0.971 |
| adm1/adm2/adm3 | 138,372 | 0.009 |
| capacity_persons | 0 | 1.000 |
| source | 0 | 1.000 |
| adm4 | 0 | 1.000 |

Values: amenity hospital 53,674, clinic 21,952, pharmacy 7,691, dentist 6,082, doctors 3,712,
health_post 3,475. healthcare=centre 39,180 (37,545 of them with no amenity tag). Most common names are
generic: "Government Hospital" 669, "Apollo Pharmacy" 516, "Primary Health Centre" 481.
Top states: Maharashtra 15,166, Tamil Nadu 12,634, Kerala 11,543; Bihar 6,640; Lakshadweep 1.

Obvious problems:
- No `emergency`, `addr:postcode`, `description`, `beds`, `phone` or `website` columns. `source` is 100% null
  even though the tag is common in OSM (96% of the Bihar sample has it), so the export drops it.
- Only 202 rows have a 6-digit PIN anywhere in addr_full, so PIN join is not possible from this file.
- Geometry column `geom` needs the DuckDB spatial extension (not installed); I used the bbox centre as the point.

Overpass sample (Bihar, hospitals/clinics/centres, all tags, 6,328 elements): addr:postcode on 6,020 (95%),
addr:district 6,111, description 5,129 (SubCentre 4,456, Primary Health Centre 558, Referral Hospital 27,
District Hospital 22), source "Local Knowledge" 5,039 and "OpenGovernmentData" 1,054, emergency on only 29
(24 yes, 5 no), healthcare:speciality 46. So the 39k healthcare=centre rows look like a bulk import of
government sub-centres and PHCs, which this export strips of their facility level.

## Join test against VF facilities.parquet

Script: `match.py` (self-check `test_match.py`). Inputs: the OSM parquet, data/raw/facilities.parquet, and
two audit outputs read-only (audit/geo/facility_geo.parquet for cleaned VF coordinates and PIN centroids,
audit/claims/out/grades.parquet for VF service claim grades). Output: data/external/hotosm_ind_health_facilities/
vf_osm_matches.parquet and match_stats.json.

Method:
- Names normalised (ASCII, lower case, punctuation stripped). A "core" name drops kind-of-place words
  (hospital, clinic, centre, pvt, ltd...) and service words (dental, eye, maternity, diagnostic...).
- Candidates: OSM points within 10 km of the VF coordinate (if valid) or of the VF PIN centroid.
  OSM pharmacies are skipped unless the VF row is a pharmacy (same-brand pharmacies sit beside hospitals).
- Score = min(token_set_ratio of full names, token_set_ratio of cores); 0.85 x full score if either core is empty.
- Tier strong: score >= 90 within 2 km, or >= 95 within 5 km. Weak: score >= 85 within 5 km or >= 95
  within 10 km, and core token_sort_ratio >= 60. Names whose core has no distinctive word (only admin words
  like government/civil/district, or the town name) need score >= 95 within 0.5 km for strong.
- `location_conflict`: the matched OSM point is more than 25 km from the VF PIN centroid.

Thresholds were tuned over two rounds of reading samples (false matches: "Dental Clinic", "Hospital",
"SIVA" pharmacy, "RB Diagnostic"); the precision below is from a third, fresh sample drawn after the last change.

Results (denominator 10,077 distinct VF unique_ids; 11 ids repeat in the raw file and are kept once):

| | count |
|---|---|
| VF rows with a usable anchor (valid coord or PIN centroid) | 9,958 |
| strong matches | 3,263 |
| weak matches | 269 |
| match rate, all VF | 35.1% (3,532 / 10,077) |
| match rate, VF with anchor | 35.5% (3,532 / 9,958) |
| strong and no location conflict | 2,803 |
| strong with location conflict | 460 |
| matched via VF coordinate / via PIN centroid | 2,839 / 693 |
| OSM ids matched by more than one VF row | 80 |

By VF type: hospital 2,988 of 5,626 matched (53%), clinic 471 of 3,782 (12%), dentist 65 of 490 (13%).

Distance from the VF coordinate to the matched OSM point (strong): 747 of 3,260 within 10 m, 2,128 within
100 m, 2,500 within 1 km; median 30 m over all matches. That closeness is suspicious: many VF coordinates
look geocoded from a map search by name, so coordinate agreement is not independent evidence, and a VF
coordinate can sit exactly on a same-name facility in another town (all three wrong matches below).
The PIN-centroid conflict flag is what catches those.

### Hand-check, 20 random accepted matches (seed 99)

Full table with ids: `handcheck_sample.csv`.

1. Green Leaf Hospital, Surat = OSM node/7592765755 Green Leaf Hospital, Surat. correct
2. Kamal Hospital, Chikodi (KA) = way/741800462 Kamal Eye Hospital, Gulbarga. wrong, flagged conflict (259 km)
3. MidTown Hospital and Research Institute, North Lakhimpur = node/6913293197 Mid Town Hospital... correct
4. M.V. Hospital for Diabetes, Royapuram = node/6933130958 Diabetes Research Centre and M.V. Hospital for Diabetes. correct
5. Aakar Plastic Surgery Hospital, Vadodara = node/7866013239. correct
6. Sethi Hospital, Gurgaon = node/6993922158. correct
7. Comfort Multi Speciality Hospital, Bangalore = node/4690537789. correct
8. Dr Padmaja Fertility Centre, Hyderabad = node/6527839627. correct
9. Tirupati Hospital, Deulgaon Raja = node/7648906330 Tirupati Hospital, Beed. wrong, flagged conflict (128 km)
10. Ritu Health Clinic, Dhanbad = node/7676478628. correct
11. Government Medical College and Hospital, Purnea = way/193899151 "Government medical college & hospital",
    Pashchim Champaran. uncertain: VF says Purnea but its PIN 845438 and coordinate are in West Champaran
12. Pranjali Maternity Surgical and General Hospital, Thane = node/4605880700 (name:en Pranjali Hospital). correct
13. Verma Hospital, "Indore" PIN 474009 = node/7016368970 Verma Hospital and Fertility Centre, Gwalior. likely correct (VF city wrong)
14. Prolife Hospitals, Ludhiana = node/7852268146. correct
15. Sowmya Hospital, Hyderabad = way/356464777 Sowmya Children's Hospital, 4.8 km. uncertain
16. Amma Hospital, Chennai PIN 636001 (Salem) = node/1472969165 Amma Hospital, Chennai. wrong or unresolved, flagged conflict (274 km)
17. Sant Hirdaram Yoga and Nature Cure Hospital, Bhopal = node/7288631339. correct
18. Arpan Hospital, "Bardoli" PIN 388001 = node/6982092245 Arpan Hospital Heart Care Centre, Anand. likely correct (VF city wrong)
19. City Heart Hospital and Research Centre, Guwahati = node/12971549372. correct
20. Gaurav Hospital, Sikar = node/7682191201. correct

Precision: 15 of 20 correct or likely correct (75%), 2 uncertain, 3 wrong. All 3 wrong ones carry
`location_conflict`; among the 17 unflagged, 15 correct or likely and 2 uncertain, 0 wrong.
A side sample of 10 weak matches had about 3 correct, so the weak tier is a lead for review, not evidence.

### Service tags versus VF claims

OSM healthcare:speciality is present on 287 of the 3,532 matched OSM features. For each service, matched
pairs whose OSM speciality hints at it, split by whether the VF text claims the service (audit grade
strong/medium/weak/enum_only):

| service | OSM tag pattern | OSM tagged | VF claims | VF no claim |
|---|---|---|---|---|
| dialysis | nephro, dialy, renal | 16 | 6 | 10 |
| C-section | gyn, obstet, matern | 66 | 15 | 51 |
| NICU | neonat, paed, pedia | 72 | 16 | 56 |
| cardiac surgery | cardi | 41 | 20 | 21 |
| MRI | radiol | 19 | 8 | 11 |
| trauma | trauma, emergency, orthop | 57 | 41 | 16 |
| burns | burn, plastic | 14 | 0 | 14 |

These are weak signals: "gynaecology" does not mean C-section capability and "cardiology" does not mean
cardiac surgery. They are useful as a second, independently cited source on a facility card, not as labels.

## Product role

- Existence and location check on each recommended facility: "Found in OpenStreetMap as <name>
  (osm.org/node/...), 30 m from the listed location" or "Same name found 128 km away in Beed: location
  unresolved". The match tier and conflict flag feed the uncertainty score.
- Backup coordinates when the VF coordinate is invalid and the match came via the PIN centroid.
- Coverage layer: OSM facilities near the user's location that VF lacks, shown as "other facilities
  nearby (unverified)", especially government PHCs/CHCs for rural users.

## Ingest plan (Databricks Free Edition)

1. Upload health_facilities.parquet (14.5 MB) and vf_osm_matches.parquet to a Unity Catalog volume, e.g.
   `/Volumes/workspace/external/raw/hotosm/` (the `workspace` catalog is writable per audit/capabilities).
2. Tables: `workspace.external.osm_health_facilities` (osm_id, names, tags, lat, lon from bbox centre,
   adm1-3) and `workspace.external.vf_osm_match` (unique_id, osm_id, tier, score, km, anchor,
   location_conflict). Run match.py locally or as a serverless notebook job; it takes about 12 s on a laptop.
3. Refresh: re-run fetch.sh and match.py monthly or when HDX publishes a new snapshot.
4. App screens: the facility recommendation card (evidence row, uncertainty badge) and the map view
   (nearby unmatched OSM facilities layer, with the ODbL attribution in the map corner).
5. Optional: one national Overpass pull for hospitals with all tags to recover addr:postcode, emergency and
   the government facility level (description); not run beyond the Bihar sample.

Effort: about 4 hours (upload and tables 1 h, app card and map wiring 2 h, attribution and review 1 h).
