# WorldPop Global2 R2025A, India 2025, 1 km

Modelled people-per-pixel grids for India (total, women 15-49, children under 5) used to
estimate the population a facility serves and local need.

## Source

- Publisher: WorldPop, School of Geography and Environmental Science, University of Southampton.
- Release R2025A v1 (alpha), files dated 2025-08-17/18 on the server. Release statement dated
  September 2025: https://data.worldpop.org/repo/prj/Global_2015_2030/R2025A/doc/Global2_Release_Statement_R2025A_v1.pdf
- Total population, 1 km, constrained, UN-adjusted (DOI 10.5258/SOTON/WP00840, hub listing
  https://hub.worldpop.org/geodata/listing?id=136):
  https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/IND/v1/1km_ua/constrained/ind_pop_2025_CN_1km_R2025A_UA_v1.tif
- Age-sex bands, 1 km, constrained (DOI 10.5258/SOTON/WP00842 per the Earth Engine catalogue):
  https://data.worldpop.org/GIS/AgeSex_structures/Global_2015_2030/R2025A/2025/IND/v1/1km_ua/constrained/
  File pattern `ind_{m|f|t}_{age}_2025_CN_1km_R2025A_UA_v1.tif`, age 00 = 0-12 months,
  01 = 1-4 years, 05 = 5-9 ... 90 = 90+.

## Licence

Hub listing page, read 2026-11-21: "WorldPop datasets are licensed under the Creative Commons
Attribution 4.0 International License". CC BY 4.0 allows copying, redistribution and adaptation
for any purpose, including commercial, with attribution. So keeping the files in a private team
repo and showing derived numbers in a public demo are both allowed, as long as the app and repo
credit WorldPop and cite the DOI. The Earth Engine catalogue notes that WorldPop products
derived from OSM or Microsoft buildings/roads are ODbL instead; these population grids are not
in that group.

Attribution string to use in the app: "Population: WorldPop Global2 R2025A (2025), University
of Southampton, CC BY 4.0, doi:10.5258/SOTON/WP00840 and WP00842."

## Fetch

`./fetch.sh [out_dir]` downloads 10 GeoTIFFs (158 MB total) into
`data/external/worldpop_r2025a/`, 1 request per second, `curl -z` so re-runs skip unchanged
files, and writes `SHA256SUMS`. Fetched: total population, women 15-19 ... 45-49 (7 files),
total 0-12 months and 1-4 years. Skipped because they exceed the 300 MB cap: the 100 m total
(742 MB on the index page) and the 1 km age-sex zip (874 MB).

## Inspect

`join_test.py` (needs rasterio, numpy, pandas, pyarrow, scipy; we used a scratch uv venv, not
the project venv) writes `derived/inspect.json`, `facility_population.parquet`,
`district_population.csv`, `hand_check.csv`.

- Grid 3504 x 3451 cells, EPSG:4326, 30 arc-second (0.00833 deg), bounds lon 68.19-97.39,
  lat 6.75-35.51, float32, LZW, nodata -99999.
- Total band: 3,201,579 valid cells, 8,890,725 nodata (sea, outside India), 80 valid zeros,
  no negatives, sum 1,457,435,338, max 31,448 people per cell.
- Women 15-49 sum 383,935,034 (26.3% of total); children under 5 sum 113,251,737 (7.8%).
  No cell has women 15-49 above the total.
- Age bands have 31,928 more nodata cells than the total band; those cells hold 0.00004
  people in the total band, so nothing is lost.
- Freshness: 2025 estimate built from c.2010 and c.2020 census rounds projected to UN WPP 2024
  national totals (release statement). India's last census was 2011, so sub-national shares
  are extrapolated. Alpha product, "may change over the coming year".

## Join test

Join is a raster lookup at each facility's latitude/longitude plus sums over cells whose
centres fall within 5, 10 and 25 km.

- facilities.parquet: 10,088 rows, 9,970 with coordinates, 9,964 inside the grid, 9,952 on a
  cell with population > 0. Match rate 9,952 / 10,088 = 98.7% (99.8% of those with coordinates).
- The 6 outside the grid and 12 on zero/nodata cells are wrong VF coordinates (for example
  B.M. Birla Heart Research Centre, Kolkata at 20.63, 87.38 is in the Bay of Bengal; Gem
  Hospital, Bathinda at 9.10, 73.83 is in the Arabian Sea). 10 of the 12 are more than 25 km
  from their own PIN (audit/geo). A zero-population cell is a cheap flag for a bad geocode.
- People within 10 km of a facility: median 1,438,920; 5th percentile 211,455; 95th 5,099,671.
  Facilities more than 25 km from their PIN have a median of 731,354 against 1,562,134 for the
  rest, so the catchment is only as good as the VF coordinates. 7,210 of 9,702 facilities with
  a directory PIN sit within 10 km of it; 1,797 are more than 25 km away.

Hand check of 20 random in-grid facilities (seed 7, `derived/hand_check.csv`): 18 land in a
populated cell of the stated city (urban cells 7,066-24,724 people/km2, Kerala small-town cells
931-1,310, which fits). Two land in the wrong place, both due to VF coordinates, not WorldPop:
Harmony Hospital, Rajkot at 23.055, 72.665 is in Ahmedabad, 209 km from its PIN; Ankur Hospital,
"Karad City" at 18.624, 73.857 is in Pune with a Pune PIN, while Karad is a separate town (Satara district from memory, not checked here, so treat this one as
unverified). Precision of the location-to-catchment step: 18/20.

| # | Facility | City | Lat, lon | Cell pop | Pop 10 km | Women 15-49 10 km | Under-5 10 km | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | Harmony Hospital | Rajkot | 23.0546, 72.6646 | 8,840 | 1,736,378 | 465,054 | 128,493 | wrong city (Ahmedabad) |
| 2 | Dr. Pradip Doshi's Hospital | Ahmedabad | 23.0189, 72.5544 | 9,674 | 2,578,156 | 690,507 | 190,785 | ok |
| 3 | Usha Mullapudi Cardiac Centre | Hyderabad | 17.5207, 78.4294 | 10,825 | 2,414,196 | 679,354 | 146,022 | ok |
| 4 | Shakya Nursing And Maternity Home | Agra | 27.1806, 77.9878 | 24,724 | 3,599,735 | 899,127 | 311,987 | ok |
| 5 | Blossom Valley Child Development Centre | Pampady | 9.5581, 76.6384 | 931 | 392,322 | 108,882 | 22,585 | ok |
| 6 | Kamala Nehru Hospital | Pune | 18.5241, 73.8632 | 14,624 | 2,816,099 | 752,611 | 190,009 | ok |
| 7 | Zion Hospital | Bangalore | 13.0149, 77.6355 | 10,671 | 2,645,518 | 736,187 | 176,532 | ok |
| 8 | Dr Jariwala Laboratory | Mumbai | 19.2358, 72.8565 | 14,281 | 1,375,627 | 367,480 | 92,776 | ok (coast cuts catchment) |
| 9 | Pal Hospital | Jalandhar | 31.3081, 75.5669 | 7,680 | 1,088,555 | 292,980 | 67,501 | ok |
| 10 | Rajdeep Fertility Research Centre | Kota | 25.1892, 75.8611 | 7,066 | 951,861 | 243,838 | 85,192 | ok |
| 11 | Mulamoottil Group Eye Hospital | Kozhencherry | 9.2742, 76.7104 | 1,310 | 537,369 | 149,138 | 30,935 | ok |
| 12 | Life Care Hospital | Ranchi | 23.3955, 85.3823 | 10,564 | 1,595,013 | 403,186 | 148,495 | ok |
| 13 | Genesis IVF | Erode | 11.3380, 77.7129 | 9,316 | 896,547 | 254,173 | 52,088 | ok |
| 14 | Breathefree Lung clinic | Hyderabad | 17.4929, 78.3979 | 12,894 | 2,740,103 | 771,021 | 165,725 | ok (15.7 km from PIN, still in city) |
| 15 | Dr Madhavi's ReLive Homeopathy | Vrindavan | 27.5610, 77.6672 | 10,841 | 1,366,319 | 341,274 | 118,418 | ok |
| 16 | Solar Hospital | Ahmedabad | 23.0551, 72.5556 | 10,664 | 2,521,771 | 675,406 | 186,612 | ok |
| 17 | Dr. Moses Matthias Hospital | Nagercoil | 8.1805, 77.4189 | 7,554 | 524,989 | 148,836 | 30,501 | ok |
| 18 | Positron Super Speciality Cancer Hospital | Rohtak | 28.9133, 76.6241 | 1,888 | 570,571 | 149,665 | 43,757 | ok |
| 19 | Syed Dental Clinic | Attur | 11.5966, 78.5963 | 7,546 | 230,079 | 65,228 | 13,367 | ok |
| 20 | Ankur Hospital | Karad City | 18.6244, 73.8569 | 10,927 | 1,906,997 | 509,641 | 128,668 | probably wrong city (Pune), unverified |

Service-claim counts do not apply: this is a population grid, not a service list.

### District zonal sums (not reliable yet)

Without district polygons we assigned each populated cell to its nearest India Post office
(after dropping 23,897 offices with missing or out-of-box coordinates or more than 100 km from
their district median). 753 districts, 700 with an NFHS key via audit/geo/district_nfhs_map.csv;
53 unmatched hold 44.4 M people (new districts such as Amethi, Alipurduar, the 2022 Andhra
Pradesh splits). The totals are visibly wrong where office coverage is uneven: Mumbai gets
903,114 people over 132 cells while Jaunpur gets 12,079,152 over 10,580 cells. Do not ship
these; use district boundary polygons for zonal sums (source not yet chosen or verified).

## Product role

- Facility card: "about 1.4 M people live within 10 km (WorldPop 2025 modelled estimate)"
  and, for delivery/NICU queries, women 15-49 and under-5 counts in the same radius.
- Ranking: a tie-breaker or need weight (people per qualified facility in a radius), never a
  substitute for evidence the facility offers the service.
- Data quality: a facility on a zero-population or sea cell gets a "location doubtful" flag.
- Planner screen: district demand, once real district polygons are in.

## Ingest plan (Databricks Free Edition)

1. Do the raster work offline (this script, about 5 s locally) because serverless egress to
   data.worldpop.org is not on the trusted list and rasterio on serverless is untested.
2. Upload `derived/facility_population.parquet` (about 2 MB) to a UC volume such as
   `/Volumes/workspace/external/worldpop/` and create
   `workspace.external.worldpop_facility_catchment` keyed by `unique_id`.
3. For arbitrary user locations (a PIN or village, not a facility), export the populated cells
   as a table `workspace.external.worldpop_cells_1km` (3.2 M rows: lat, lon, pop, wra, u5,
   size not measured, export not run) and sum within a lat/lon bounding box plus haversine in SQL.
4. Refresh: only when WorldPop publishes a new release (R2025B or later) or VF coordinates are
   cleaned; rerun `fetch.sh` and `join_test.py`, re-upload.
5. Attribution line in the app footer and the facility card.

Effort: about 3 hours (cells export plus SQL radius query 1.5 h, volume upload and tables 0.5 h,
app wiring 1 h). District polygons add about 2 hours once a source is chosen.
