# Geography, routing, access and population: dataset candidates

Scope: datasets that improve location resolution (PIN, village, district), travel time and
routing, population and need, and the trauma use case (road crashes, blackspots, highways).
Searched 2026-11-21. Nothing larger than a web page or metadata JSON was downloaded. Sizes come
from HTTP HEAD Content-Length, GitHub release asset sizes, HDX/CKAN metadata, or the listing pages,
unless marked "not verified".

Why this matters for our data: the geo audit (audit/geo/facility_geo_stats.json) found that of
9,682 facilities with a PIN in the India Post directory, 595 + 417 + 95 + 7 = 1,114 sit more than
100 km from their PIN centroid, and the 90th percentile PIN-to-coordinate distance is 128.4 km.
PIN polygons, LGD village-PIN mapping and district polygons turn those into checkable
contradictions instead of silent errors.

Databricks constraint: no outbound internet from compute, so every file must be fetched on a laptop
and uploaded to a UC volume. Prefer files under about 100 MB that already cover only India.

## Priority 1 (must have)

### lgd_archive_parquet: LGD daily archive (ramSeraph opendata)
- URL: https://ramseraph.github.io/opendata/lgd (index: https://ramseraph.github.io/opendata/lgd/data/metadata.json)
- Publisher: community mirror (ramSeraph / Datameet) of Ministry of Panchayati Raj LGD reports.
- Access: direct download of Parquet per entity, sha256 in the index.
- Size and rows (from metadata.json, observed 2026-11-19): villages 677,660 rows, 8.0 MB;
  pincode_villages 672,593 rows, 5.6 MB; pincode_urban 7,307 rows, 66 KB; districts 790 rows;
  subdistricts 7,112; blocks 7,343; urban_local_bodies 5,050; invalidated_census_villages 4,953.
- Licence: page says only "Public data collected from Indian government sources." Upstream LGD
  copyright policy: "Material featured on this site may be reproduced free of charge in any format
  or media without requiring specific permission ... the source must be prominently acknowledged."
- Helps: canonical LGD codes for state, district, sub-district, village; PIN to village and PIN to
  urban body mapping lets us resolve a user's PIN or village name to a district, and lets us check
  a facility's PIN against its stated city and district.
- Join keys: PIN code; district and state names (fuzzy) to LGD codes; LGD district code to NFHS
  district (via names) and to district polygons below.
- Risks: unofficial mirror; schema not read (manifest JSON was rate limited); names need fuzzy
  matching; "A missing record does not by itself establish that an entity was deleted."

### pincode_boundaries: All India PIN code boundary polygons
- URL: https://github.com/ramSeraph/indian_admin_boundaries/releases/tag/postal
  (source cited: https://www.data.gov.in/catalog/all-india-pincode-boundary-geo-json)
- Publisher: Department of Posts via data.gov.in; mirrored by ramSeraph.
- Files: Datagov_Pincode_Boundaries.parquet 26.6 MB (GeoJSONL 7z 17.1 MB, PMTiles 20.9 MB).
  A second set, PincodeBoundaries (PostalGIS), is 335 MB parquet / 214 MB 7z and is missing HP,
  J and K, Sikkim, Meghalaya, Mizoram, Manipur, Nagaland and Arunachal; skip it.
- Licence: release notes say "License: GODL" for the data.gov.in set.
- Helps: point-in-polygon test of each facility's coordinates against its stated PIN; PIN input
  resolved to a polygon (better than a post office centroid) for distance and travel time.
- Join keys: PIN code; facility lat/lon.
- Risks: data.gov.in itself was unreachable from this machine (connection refused), so the
  vintage of the original file is not verified; release posted 2024-01-03.

### lgd_district_polygons: District, sub-district and block polygons with LGD codes
- URL: https://github.com/ramSeraph/indian_admin_boundaries/releases/tag/districts (also
  /subdistricts, /blocks, /states)
- Publisher: LGD / Bharatmaps (mapservice.gov.in), Survey of India and Bhuvan layers, mirrored.
- Files: LGD_Districts.parquet 34.5 MB; SOI_Districts.parquet 46.2 MB; bhuvan_districts 62.5 MB;
  LGD_Subdistricts.parquet 95.4 MB; SOI_Subdistricts 83.4 MB; LGD_Blocks 100.0 MB.
- Licence (repo DATA_LICENSE.md): "Most of the data here ... is licensed using CC0 1.0 ...
  I request that you actively acknowledge and give attribution to Datameet community ... and also
  the original government sources wherever possible." Several tile URLs sit under "not-so-open",
  meaning the upstream terms are unclear. The repo README quotes the Geospatial Guidelines: "SoI
  published maps or SoI digital boundary data are the standard to be used".
- Helps: assign every facility and every user location to an LGD district (current, about 790
  districts) by coordinates; detect facilities whose coordinates fall outside their stated district;
  district is the unit for NFHS need indicators and for planners.
- Join keys: lat/lon (spatial join), LGD district code, district name.
- Risks: release dated 2023-12-11, so districts created since then are missing; mixed upstream
  licences; for maps shown to users, SOI boundaries are the legal standard.

### hotosm_ind_health_facilities: OSM health facilities of India (HOT export)
- URL: https://data.humdata.org/dataset/hotosm_ind_health_facilities
  (GeoParquet: https://production-raw-data-api.s3.amazonaws.com/ISO3/IND/_layers/osm/health_facilities.parquet)
- Publisher: Humanitarian OpenStreetMap Team, data by OpenStreetMap contributors.
- Size: GeoParquet 14.5 MB; GeoJSON zip 9.5 MB; GPKG zip 13.4 MB. Updated 2026-10-11.
- Licence: "Open Database License (ODC-ODbL)".
- Coverage note from the STAC metadata: "hospitals, clinics, pharmacies, doctors, and dentists
  tagged via `amenity` or `healthcare` ... Urban areas are usually well represented, remote areas
  may be sparse."
- Helps: independent corroboration that a facility exists at roughly the claimed place (name plus
  distance match); a second coordinate for facilities with bad or missing coordinates; OSM tags such
  as emergency=yes or healthcare:speciality give weak service evidence with its own citation.
- Join keys: fuzzy name plus distance (for example under 2 km), addr:postcode, OSM id.
- Risks: ODbL share-alike on any derived database we publish; volunteer coverage is uneven; tags
  are sparse and also unverified.

### map_travel_time_healthcare_2020: Weiss et al. 2020 travel time to nearest healthcare
- URL (WCS, supports bbox subsetting): https://data.malariaatlas.org/geoserver/Accessibility/wcs?service=WCS&version=2.0.1&request=GetCapabilities
  Coverage ids: Accessibility__202001_Global_Motorized_Travel_Time_to_Healthcare and
  Accessibility__202001_Global_Walking_Only_Travel_Time_To_Healthcare.
  Earth Engine mirror: https://developers.google.com/earth-engine/datasets/catalog/projects_malariaatlasproject_assets_accessibility_accessibility_to_healthcare_2019
- Publisher: Malaria Atlas Project (Oxford / Telethon Kids). Paper: Weiss DJ et al., Nature
  Medicine 26:1835-1838 (2020), doi 10.1038/s41591-020-1059-1.
- Format: GeoTIFF via WCS, EPSG:4326, 1/120 degree (about 1 km); global grid 43,200 x 17,400.
- Size: an India bbox (68-98 E, 6-38 N) is 3,600 x 3,840 = 13.8 M pixels, 55.3 MB as float32
  uncompressed (computed); the upstream global raster is about 708 MB per the Emilsson repo README.
- Licence: Earth Engine catalog: "This work is licensed under a Creative Commons Attribution 4.0
  International License." The MAP portal's own licence page was not read.
- Helps: context layer for "how remote is this user location" and for uncertainty: if baseline
  travel time is high we say so and widen the search radius; district-level summaries for planners.
- Join keys: lat/lon raster lookup.
- Risks: travel time is to ANY clinic in OSM/Google 2019, not to a facility offering the requested
  service; optimal-speed assumption understates real time.

### map_friction_surface_2020: motorized and walking friction surfaces
- URL: same WCS; ids Accessibility__202001_Global_Motorized_Friction_Surface and
  Accessibility__202001_Global_Walking_Only_Friction_Surface.
- Format and size: same grid as above, minutes per metre; India clip about 55 MB float32.
- Licence: CC BY 4.0 (Earth Engine catalog quote above). Catalog caveat: version changes "may
  reflect OpenStreetMap data quality rather than real infrastructure change".
- Helps: the routing core that fits Free Edition. A least-cost path (Dijkstra on the raster, done
  once per query on a cropped window, or precomputed per facility) gives an estimated travel time
  from the user's point to each candidate facility for the requested service. No routing server or
  internet is needed.
- Join keys: lat/lon.
- Risks: 1 km cells blur city traffic; nominal year 2019-2020; needs a small cost-distance routine
  (scikit-image MCP_Geometric or similar) in the app or a job.

### worldpop_r2025a: WorldPop Global2 R2025A population and age-sex grids, India
- URL: https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/IND/v1/
  and https://data.worldpop.org/GIS/AgeSex_structures/Global_2015_2030/R2025A/2025/IND/v1/1km_ua/constrained/
- Publisher: WorldPop, University of Southampton.
- Files (HEAD): ind_pop_2025_CN_1km_R2025A_UA_v1.tif 16.3 MB (2025-08-18);
  ind_pop_2025_CN_100m_R2025A_v1.tif 778 MB (over limit, skip). Age-sex 1 km files are about
  16.2 MB each; women 15-49 = 7 files (f_15 to f_45), about 113 MB in total.
  Older 2020 files: 1 km UN-adjusted 18.3 MB; 100 m 1.65 GB; constrained 100 m 489 MB.
- Licence: "WorldPop datasets are licensed under the Creative Commons Attribution 4.0
  International License" (hub.worldpop.org listing page).
- Helps: population within X minutes of each facility; population per facility for district
  planners; women of reproductive age for the high-risk delivery use case; children for NICU.
- Join keys: raster lookup by lat/lon, zonal sums by district polygon.
- Risks: modelled estimates, not counts; constrained version places zero population outside
  detected settlements.

## Priority 2 (strongly useful)

### lgd_portal_official: Local Government Directory download
- URL: https://lgdirectory.gov.in/downloadDirectory.do
- Publisher: Ministry of Panchayati Raj, NIC.
- Access: manual only. The form uses a CAPTCHA, so a person must download it; we must not
  automate it. Formats offered: Pdf, Xls, ODT. Entities include "Pincode to Village Mapping",
  "Pincode to Urban Mapping", all villages, districts, sub-districts, blocks.
- Licence: copyright policy quoted under lgd_archive_parquet; terms page: "should not be
  constructed as a statement of law or used for any legal purposes".
- Helps: authoritative source to spot-check the community archive.
- Risks: CAPTCHA, one entity per request; a 2019 notice says Tripura sub-districts were replaced
  by 23 revenue sub-divisions.

### census2011_villages_towns: Census 2011 village points, town and village directory
- URL: https://github.com/ramSeraph/indian_admin_boundaries/releases/tag/census-2011
- Files: Census_Villages.parquet 49.7 MB ("Census villages as points", source given as
  mapservice.gov.in Panchayat layer); PC11_TV_DIR.csv.7z 3.1 MB ("Town and Village Directory from
  Census 2011"); Districts_2011.parquet 37.6 MB; SHRUG district parquet 19.4 MB.
- Licence: CC0 with attribution request (same DATA_LICENSE.md); SHRUG parts are CC BY-NC-SA 4.0.
- Helps: geocode a village name typed by a health worker to a point; Census 2011 codes link to
  SHRUG and older district datasets.
- Join keys: Census 2011 village/town code, village name plus district, lat/lon.
- Risks: 2011 vintage; "Quality Check: None was performed"; extraction needs 7-Zip (7z archive),
  must be extracted safely.

### geoboundaries_ind: geoBoundaries India ADM1-ADM3
- URL: https://www.geoboundaries.org/api/current/gbOpen/IND/ADM2/ (API JSON read)
- ADM1: 36 units, year 2011, source DataMeet / ECI, licence "Creative Commons Attribution 2.5
  India (CC BY 2.5 IN)", all.zip 36.0 MB, simplified GeoJSON 5.1 MB.
- ADM2: 736 districts, year 2021, source "Pathways Data Pvt. Ltd., lgdirectory.gov.in", licence
  "Open Data Commons Open Database License 1.0", all.zip 36.6 MB, simplified 8.0 MB.
- ADM3: 6,836 sub-districts, year 2018, ODbL, all.zip 96.0 MB, simplified 40.0 MB. Built Dec 2023.
- Helps: clean, documented fallback for district assignment with a clear licence.
- Join keys: lat/lon, shapeName to district name.
- Risks: 2021 district set is older than LGD; ODbL share-alike.

### geofabrik_osm_india: OpenStreetMap India extract
- URL: https://download.geofabrik.de/asia/india.html
- Size: india-latest.osm.pbf 1.6 GB (daily). Zone PBFs: North-Eastern 105 MB, Eastern 236 MB,
  Northern 215 MB, Western 212 MB, Central 336 MB, Southern 534 MB. Zone gpkg zips are larger
  (Central 912 MB, Eastern 607 MB, Northern 508 MB by HEAD). india-latest-free.shp.zip is 1.87 GB
  and dated 2021-01-02 (stale).
- Licence: "License: ODbL 1.0", "OpenStreetMap Contributors".
- Helps: road network for national highways (highway=trunk/motorway, ref=NH ...) for the trauma
  use case; health amenities; place names for geocoding.
- Join keys: lat/lon, names.
- Risks: only the four zones under 300 MB fit our download rule; filter locally (osmium) and upload
  only small derived layers. Prefer the HOT health facility export above for facilities.

### osm_national_highways: OSM national highway relations
- URL: https://wiki.openstreetmap.org/wiki/India/National_Highways_(new_numbering)
- Publisher: OSM India community.
- What it is: per-NH relation table with a completeness Status column and OSM vs MoRTH length,
  based on MoRTH lists from 2018-2019 and a March 2023 PDF.
- Helps: NH geometry for snapping a highway accident location ("NH-44 near km 210") to a point and
  for routing trauma cases.
- Access: extract relations from the Geofabrik zone PBFs; no bulk file was found on the wiki page
  (only the first 100,000 of 240,552 characters were read).
- Risks: incomplete for some highways; ODbL.

### pmgsy_geosadak: PMGSY rural roads, habitations and facilities
- URL: https://github.com/datameet/pmgsy-geosadak (mirror); source https://geosadak-pmgsy.nic.in/opendata/
  (portal unreachable from this machine).
- Publisher: Ministry of Rural Development (PMGSY).
- Files: data/Facilities 29 state zips, 34.0 MB total; data/Road_DRRP about 1.09 GB total by
  state; Habitation and Bound_Block folders; MasterData.xls 0.8 MB. Mirror last pushed 2022-07-18.
- Licence: README: "Published under India's Government Open Data License ... Free to copy, reuse
  and redistribute for commercial use - Attribution required".
- Helps: rural road network and geotagged rural facilities (about 7 lakh POIs per the Datameet
  announcement) for rural Bihar style queries; habitation points with population estimates.
- Join keys: lat/lon, block id, habitation name.
- Risks: OSM wiki: roads "not topologically connected", POI locations from phone photos, block IDs
  mismatch, some states have block ID 0. Whether the facility layer has health categories was not
  verified.

### morth_road_accidents_in_india: MoRTH Road Accidents in India 2024
- URL: https://morth.gov.in/backend/documents/uploaded/1781177676_V1gUW8tJWT.pdf (linked from
  https://morth.gov.in/#/documents/reports as "Road Accident in India-2024").
- Size: 21.4 MB PDF, Last-Modified 2026-06-11.
- Content: state-wise and million-plus-city tables (search results for the 2023 edition describe
  section 5 inter-state comparison and section 6 million-plus cities). No district tables seen.
- Licence: not stated on the page (government publication).
- Helps: trauma need by state and city (deaths, NH share), to weight district planner views and to
  explain why trauma capacity matters on a route.
- Join keys: state name, city name.
- Risks: PDF tables need extraction; state level only.

### morth_top10_blackspots: State-wise top ten road accident blackspots 2016-2018
- URL: https://dataful.in/datasets/19622 (data.gov.in original:
  https://data.gov.in/resource/states-wise-list-top-ten-black-spots-2016-2018, unreachable here).
- Fields (Dataful page): year, state, name_of_traffic_unit_district,
  name_of_jurisdictional_police_station, road_type, accident_location,
  high_accident_prone_starting_point, high_accident_prone_ending_point, category, value, unit.
  1,638 rows. No coordinates.
- Licence: Dataful page states none; it has Sign in and Pricing links. The data.gov.in original is
  presumably GODL (not verified).
- Helps: named blackspot stretches to geocode (with OSM NH geometry) as demo origins for the
  district planner trauma scenario.
- Join keys: state, district, location text, NH number.
- Risks: only the top ten per state; text locations; 2016-2018 vintage; access terms unclear.

## Priority 3 (useful, with caveats)

### ghsl_ghs_pop_r2023a: GHS-POP R2023A epoch 2025
- URL: https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2025_GLOBE_R2023A_4326_30ss/V1-0/
- Size: global 1 km zip 484 MB (over limit); a tiles/ folder exists, so fetch only the India tiles
  (tile ids not yet determined; use the tile index shapefile on the GHSL download page).
- Licence (copyright.txt): "licensed under the Creative Commons Attribution 4.0 International
  (CC BY 4.0) licence ... Reuse is allowed provided appropriate credit is given".
- Helps: second population estimate to show uncertainty next to WorldPop.
- Risks: only redundant with WorldPop for our needs.

### meta_hrsl_india: Meta High Resolution Population Density Maps, India 2025
- URL: https://data.humdata.org/dataset/india-high-resolution-population-density-maps
- Files: general, women 15-49, children under five, youth, elderly; each zip about 780-784 MB;
  male and female about 498 MB. Updated 2026 with Overture building footprints.
- Licence: "Creative Commons Attribution International (CC BY)".
- Helps: women of reproductive age at about 30 m for the delivery use case.
- Risks: every file is over our 300 MB rule; only usable through a documented subset (for example
  one 10 x 10 degree tile or a cloud-hosted COG range read, not verified).

### shrug: SHRUG 2.2 (Development Data Lab)
- URL: https://www.devdatalab.org/shrug_download/ ; docs https://docs.devdatalab.org/
- Modules seen in docs: Open Polygons and Spatial Statistics, town and village identifiers
  (shrids), Population Census 2011 PCA, Village and Town Directory, PMGSY roads, Mission Antyodaya
  Village Facilities 2020.
- Licence: "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License".
- Helps: clean Census 2011 village polygons and crosswalks; Antyodaya village facility indicators.
- Risks: non-commercial and share-alike; module sizes not seen (tables did not render).

### ncrb_adsi_road_deaths: NCRB ADSI 2023 road accident deaths by place
- URL: https://aikosh.indiaai.gov.in/home/datasets/details/road_accident_deaths_by_place_2023.html
- Publisher: NCRB (Ministry of Home Affairs). Size 19.42 KB, licence GODL, State/UT/City level.
- Other tables (OpenCity mirror, behind a Cloudflare check, not opened):
  https://data.opencity.in/dataset/accidental-deaths-and-suicides-in-india-2023
- Helps: city and state trauma burden, second source next to MoRTH.
- Risks: no district level; NCRB site gave a TLS certificate error.

### datameet_maps: Datameet India maps
- URL: https://github.com/datameet/maps
- Licence: "Unless explicitly stated, all datasets in this repository is shared under CC BY 4.0".
- Content: country (india-composite.geojson), states, districts, assembly and parliamentary
  constituencies. No sub-district or village layer.
- Risks: district file scraped from ECI, old; superseded by LGD polygons above.

### aikosh_lgd_villages_pin: LGD villages with PIN codes (AIKOSH mirror of data.gov.in)
- URL: https://aikosh.indiaai.gov.in/home/datasets/details/local_government_directory_lgd_villages_with_pin_codes.html
- Licence: "Open Government License, India". Updated 18 Jul 2025 (page). Size shown as 0.
- Use only if the ramSeraph archive turns out to be incomplete.

## Priority 4 and 5 (skip unless a gap appears)

- global_hospital_travel_time (4): https://github.com/emailsson/global-hospital-travel-time,
  MIT, pushed 2026-09-10. 15/30/60 minute OSM drive-time isochrones from 217,841 OSM hospitals with
  emergency and tertiary tiers; India slice must be cut from global outputs (coverage.ndjson.gz
  97 MB, sensitivity file 747 MB). Preprint arXiv:2609.12696, single author, not peer reviewed.
- hotosm_ind_roads (4): https://data.humdata.org/dataset/hotosm_ind_roads, ODbL, GeoParquet
  2.39 GB. Over limit; use Geofabrik zones instead.
- healthsites_io (4): https://healthsites.io/ ; API at /api/v3/facilities/?country=India needs an
  api-key from an OSM account, 100 records per page. OSM-derived, so mostly redundant with HOT.
- soi_online_maps (4): https://onlinemaps.surveyofindia.gov.in/Digital_Product_Show.aspx. Page
  failed TLS verification here; search results say registration is required and village boundary
  products are free. Use the SOI mirror in ramSeraph releases for display boundaries.
- gadm (5): https://gadm.org/license.html: "freely available for academic use and other
  non-commercial use ... Redistribution or commercial use is not allowed without prior permission."
  Skip; geoBoundaries and LGD polygons cover the need with clearer terms.

## Not found or not reachable

- A machine-readable list of all NH blackspots (5,803 for 2016-2018 per a 2021 Lok Sabha answer;
  13,795 in a 2024 answer) with coordinates or chainage. Only top-ten-per-state lists with text
  locations exist; full lists appear only as PDF annexures to parliamentary answers.
- An official NHAI or MoRTH national highway geometry download. Only OSM and a 2019 GitHub repo
  (datta07/INDIAN-SHAPEFILES, sources not stated).
- District-level road crash deaths for all of India (MoRTH and NCRB publish state and
  million-plus-city tables; iRAD is not public).
- data.gov.in pages: connection refused from this machine, so none of its resources were opened.
- A direct MAP GeoTIFF download link for the 2020 layers (WCS works; MAP's own licence page unread).
- Official Census of India village coordinates on censusindia.gov.in.
- A healthsites.io India dataset on HDX.

## Process notes

- The Playwright browser tool wrote two log files into /Users/karthikvattem/projects/datathon/.playwright-mcp/
  (console-2026-11-21T17-43-07-848Z.log, page-2026-11-21T17-43-16-270Z.yml) when opening
  morth.gov.in. That directory already existed from another session; the files were left in place.
- Metadata scratch files are in the session scratchpad, not in the project.
