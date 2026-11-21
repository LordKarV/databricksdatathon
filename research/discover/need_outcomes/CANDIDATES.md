# Candidates: health need, utilization and outcomes

Discovery date: 2026-11-21. Nothing was downloaded beyond pages and small API metadata calls.
Every number below came from a page I read or an API call I ran (IDP CKAN API calls are in the
notes). "Unverified" means I did not see it myself.

## Network finding that shapes everything below

From this machine (and from the WebFetch service) most Indian government portals were unreachable:
data.gov.in returned an Akamai 503 error page, hmis.mohfw.gov.in and hmis.nhp.gov.in timed out or
refused connections, eparlib.nic.in did not resolve, eparlib.sansad.in, dashboard.pmjay.gov.in,
community.data.gov.in and nhm.assam.gov.in refused connections, rchiips.org and pmndp.mohfw.gov.in
failed TLS verification, pib.gov.in returned 403. Mirrors were reachable: the India Data Portal
CKAN (ckan.indiadataportal.com, run by ISB), AIKosh (aikosh.indiaai.gov.in), Dataful
(dataful.in), Zenodo, nhsrcindia.org, censusindia.gov.in NADA, ijmr.org.in, nhm.goa.gov.in and
nhm.gov.in. Plan acquisitions around the mirrors, or have a teammate on an Indian network fetch the
official files.

## Ranked shortlist

| Pri | Slug | What | Grain | Join key |
|---|---|---|---|---|
| 1 | idp-hmis-subdistrict | HMIS monthly service counts incl. C-sections, SNCU admissions, trauma/burn/cardiac emergencies | sub-district x month x sector, 2017-18 and 2019-20 | LGD district and sub-district codes |
| 1 | idp-nfhs-district | NFHS district indicators for 2015-16, 2019-21 and 2023-24, with LGD codes | district | LGD district code |
| 1 | nhsrc-pmndp | PM National Dialysis Programme: state table plus a "districts covered" PDF | state; district list | state and district name |
| 2 | idp-census-pca | Census 2011 Primary Census Abstract | state, district, sub-district, block | LGD-mapped codes |
| 2 | dataful-black-spots | MoRTH road accident black spots with location text | district, police station | state and district name |
| 2 | dataful-hmis-deliveries-csec | District deliveries and C-sections 2020-21 to 2024-25 (RTI) | district x year | LGD district code |
| 3 | zenodo-nfhs-explorer | Harmonised NFHS-3 to NFHS-6 state fact-sheet values | state | state name |
| 3 | ijmr-ckd-states-2023 | GBD 2023 CKD prevalence/incidence/mortality by state | state | state name |
| 3 | goa-facility-deliveries | Facility-wise monthly deliveries and C-sections, 32 Goa facilities | facility | facility name plus district |
| 3 | dataful-hmis-district-monthly | Per-district HMIS monthly series 2008-09 to 2021-22 | district x month x facility category | LGD district code |
| 3 | srs-imr-mmr | SRS Bulletin 2022 (IMR) and SRS MMR bulletin 2021-23 | state | state name |
| 3 | aikosh-rhs-district-2017 | RHS 2017 district-wise SC/PHC/CHC/SDH/DH counts | district | district name |
| 4 | nhm-mis-state-progress | NHM state-wise progress (FRUs, ambulances, etc.) as of 30.09.2024 | state group / state | state name |
| 4 | idp-ncrb-accidents | NCRB traffic accidents and accidental deaths (incl. fire) | state x year 2018-2024 | state code |
| 4 | idp-mission-antyodaya | Mission Antyodaya 2019-20 village survey (PHC/CHC availability at district level) | village to state | LGD codes |
| 4 | shrug | SHRUG village/town panel with Census geometries | village/town to district | shrid, pc11 ids |

## Candidate details

### idp-hmis-subdistrict (priority 1)
- Name: Health Management Information System (HMIS), resource "Major Health Indicators Sub-district Level"
- Publisher: India Data Portal (ISB) mirror of MoHFW HMIS standard reports
- URL: https://ckan.indiadataportal.com/dataset/health-management-information-system-hmis
  (API: https://ckan.indiadataportal.com/api/3/action/package_show?id=health-management-information-system-hmis ;
  resource id eb0d4fba-d333-4025-a574-b0da7fd33b09)
- Access: CKAN datastore API (datastore_search with filters works; I fetched one record). Full CSV is
  411,528,507 bytes, over our 300 MB cap, so pull subsets by state/district via the API.
  A GROUP BY over the whole table through datastore_search_sql timed out, so filter first.
- Format: CSV / JSON via API. 547,336 rows (API total). 296 fields.
- Licence: CKAN record says "Open Data Commons Attribution License" (license_id odc-by).
- Last update: metadata modified 2026-11-18; resource says data_last_updated 17-02-2022, years_covered "2017-18, 2019-20".
- Coverage: 36 states/UTs, 739 districts, 4,493 sub-districts (resource metadata); monthly; sector column (first record was "Private").
- Key fields: date, state_code, district_code, subdistrict_code, sector, csec_total, inst_deliv_csec,
  csec_night, sncu_inborn_m, sncu_inborn_f, death_sncu, emer_trauma_acc_poison, emer_burn,
  emer_cardiac, major_surg_nonobgyn, xray_tests, usg_tests, inpatient_* counts.
- How it helps: real delivered volume of C-sections, newborn intensive care, trauma, burn and
  cardiac emergencies by sub-district and public/private sector. Lets us say "this district's
  private sector reported N C-sections in 2019-20" as context for claims, flag facilities claiming
  NICU in sub-districts with zero SNCU admissions, and build need/utilization layers for planners.
  No dialysis items.
- Join: LGD district and sub-district codes. Our facilities have PIN only; go PIN -> India Post
  district name -> LGD district code (name crosswalk needed), or point-in-polygon on sub-district shapes.
- Risks: aggregate, not facility-level; two fiscal years only and 5-7 years old; private-sector
  reporting to HMIS is incomplete; HMIS quality issues are well documented; field names differ
  from labels.

### idp-nfhs-district (priority 1)
- Name: National Family Health Survey (NFHS), resource "District Level NFHS"
- Publisher: India Data Portal (ISB), sourced from IIPS/MoHFW NFHS fact sheets
- URL: https://ckan.indiadataportal.com/dataset/national-family-health-survey-nfhs (resource id b8ac1c23-d13f-4a91-aa4c-a056605f9115)
- Access: API or direct CSV, 1,175,885 bytes.
- Format: CSV, 129 columns.
- Licence: not stated on this dataset record (license field empty). Other IDP datasets are ODC-BY. Treat as "attribution, confirm with IDP".
- Last update: data_last_updated 2026-08-21.
- Coverage: rows by year from my SQL query: 2015-16 = 575, 2019-21 = 707, 2023-24 = 713.
- Key fields: year, state_code, district_code, district_name, births_c_section,
  private_births_c_section, public_births_c_section, institutional_births,
  institutional_births_public, blood sugar and blood pressure indicators.
  Example (2023-24, Bihar, Araria, district_code 188): births_c_section 12.0,
  private_births_c_section 68.1, institutional_births 77.9.
- How it helps: (1) adds LGD district codes to the NFHS-5 data we already hold, which has names only;
  (2) a 2023-24 round (NFHS-6) for C-section rate, institutional delivery and diabetes/hypertension
  as need proxies for delivery, NICU and dialysis.
- Join: LGD district code; name match to our existing nfhs_5 parquet.
- Risks: official NFHS-6 release that I could confirm (29 May 2026) is India and State/UT fact
  sheets; I could not confirm an official NFHS-6 district release (rchiips.org failed TLS from
  here), so the provenance of the 2023-24 district rows is unverified. Cross-check state values
  against zenodo-nfhs-explorer before use.

### nhsrc-pmndp (priority 1 for dialysis)
- Name: Pradhan Mantri National Dialysis Program (PMNDP) data table and district coverage list
- Publisher: NHSRC, MoHFW
- URL: https://www.nhsrcindia.org/pmndp-map-table and https://nhsrcindia.org/pradhan-mantri-national-dialysis-program
  (the second page links a PDF titled "DISTRICTS COVERED UNDER PMNDP-OCTOBER 2026"; I did not open the PDF)
- Access: scrape the HTML table (36 rows); download the PDF.
- Format: HTML table; PDF.
- Licence: page footer "Copyright (c) 2021. Websites managed by NHSRC, Ministry of Health & Family Welfare, Government Of India." Terms page not read.
- Last update: "Page last updated on:" is blank; PDF title says October 2026.
- Coverage: table columns States/UTs, Total No of Districts, districts where dialysis is functional,
  functional dialysis centres, PPP/IN-HOUSE. Example row: "Bihar | 38 | 38 | 94 | PPP".
- How it helps: the only public dialysis-specific delivery data I found. For a Bihar dialysis
  query it says every district has a functional PMNDP centre, typically at the district hospital,
  so a public district hospital is a defensible dialysis candidate even when our scraped text is
  silent. The PMNDP portal (pmndp.mohfw.gov.in) reportedly lists centres state- and district-wise
  in its app, but it failed TLS from here and is unverified.
- Join: state name; district name from the PDF; facility match to "District Hospital <name>" in our data.
- Risks: centre-level names and sessions not yet seen; PDF may only list districts.

### idp-census-pca (priority 2)
- Name: Census PCA Demography
- Publisher: India Data Portal (ISB), source Census of India 2011
- URL: https://ckan.indiadataportal.com/dataset/census-pca-demography
- Access: direct CSV. Districts file 18,642,831 bytes; sub-districts 134,471,517; blocks 214,494,348; states 822,011.
- Format: CSV, long format (Area Type, Gender, Age, Social Group, Literacy, Working Status, ..., Population).
- Licence: "Open Data Commons Attribution License".
- Last update: data year 2011.
- Key fields: State Code, District Code, Sub District Code, Block Code, Population breakdowns.
- How it helps: population denominators for rates (C-sections per 1,000 population, dialysis
  centres per million), rural share for routing and need scores.
- Join: LGD-mapped codes (lgd_mapping "yes").
- Risks: 2011 counts are 15 years old; districts split since then. Long format needs pivoting.

### dataful-black-spots (priority 2 for trauma)
- Name: Black Spots: State and District wise locations of Black Spots on Roads managed by NHAI, NHIDCL, MoRTH (PWD NH), BRO, State PWD and Other Offices
- Publisher: Dataful (Factly), source Black Spot MIS, MoRTH
- URL: https://dataful.in/datasets/21559/
- Access: download from Dataful (CSV/XLSX/Parquet listed). Page shows an "HFI" tag, no "Exclusive" tag. Whether a free login is needed: unverified.
- Format: CSV; 8,862 rows, 13 columns.
- Licence: Dataful terms: "Factly neither owns nor is selling the raw data sourced from official
  sources", "The datasets downloaded from the portal can be used by subscribers as per their needs
  without any attribution to Dataful", and "You agree not to reproduce, duplicate, copy, sell,
  resell, or exploit any portion of the Service".
- Last update: 13 November 2025; period 2014 to 2025.
- Key fields: black_spot_id, state, district, location (free text with chainage), police_station, repair status/dates.
- How it helps: the district planner example. Trauma demand hotspots on highways; geocode
  location text to rank trauma-capable facilities by distance from each black spot.
- Join: state and district name; geocoding of location text.
- Risks: no coordinates or NH number columns; geocoding chainage text is error prone.

### dataful-hmis-deliveries-csec (priority 2 if obtainable, else 5)
- Name: Year, State and District-wise Total Number of Deliveries and Caesarean (C-Section) Deliveries Reported
- Publisher: Dataful, from an MoHFW RTI reply (App. no. MOHFW/R/E/26/01283)
- URL: https://dataful.in/datasets/23368/
- Access: page HTML shows "is_premium":true and an "Exclusive" badge, so it is likely paywalled.
- Format: CSV/XLSX/Parquet; 3,803 rows; 9 columns.
- Licence: Dataful terms (quoted above); paywalled data "should not be downloaded and sold on other platforms".
- Last update: 04 November 2026; covers 2020-21 to 2024-25.
- Key fields: fiscal_year, state, district_as_per_lgd, district_lgd_code, deliveries_reported, caesarean_deliveries_reported.
- How it helps: newest district C-section volumes (5 years) for the high-risk delivery use case.
- Join: LGD district code.
- Risks: paywall; RTI data is HMIS-derived with the same quality caveats.

### zenodo-nfhs-explorer (priority 3)
- Name: NFHS India Explorer: a harmonised NFHS-3 to NFHS-6 fact-sheet database and dashboard
- Publisher: Abhijit Pakhare and Ankur Joshi, AIIMS Bhopal (not endorsed by IIPS)
- URL: https://zenodo.org/records/20460015
- Access: direct download, NFHS-6-v1.0.0.zip, 7.7 MB.
- Format: long-format tables plus a static dashboard.
- Licence: data CC-BY-4.0, code MIT.
- Last update: v1.0.0, 30 May 2026.
- Coverage: India and all states/UTs, urban/rural/total, NFHS-3 to NFHS-6. No district level.
- How it helps: validates the IDP 2023-24 district rows against state fact-sheet values; state-level fallback for NFHS-6.
- Join: state name.
- Risks: third-party transcription.

### ijmr-ckd-states-2023 (priority 3)
- Name: Chronic kidney disease in India: incidence, prevalence, mortality, DALYs and state-level disparities 1990-2023 (Table I)
- Publisher: Indian Journal of Medical Research 163(6):810-818, 2026 (Meshram, Chauhan, Puri), using GBD 2023
- URL: https://ijmr.org.in/chronic-kidney-disease-in-india-incidence-prevalence-mortality-dalys-and-state-level-disparities-19902023/
- Access: open-access article; transcribe Table I.
- Format: HTML table.
- Licence: "Creative Commons Attribution-Non Commercial-Share Alike 4.0 License".
- Coverage: 31 states/UTs, 2023, age-standardised rates per 100,000. Example: Kerala prevalence 11124.73.
- How it helps: dialysis need prior by state, combined with NFHS district diabetes and hypertension.
- Join: state name.
- Risks: modelled estimates, not measured prevalence; state level only. Raw GBD Results Tool
  data needs registration and its user agreement forbids redistributing the data sets (seen in
  search snippets only, not opened).

### goa-facility-deliveries (priority 3)
- Name: Facility wise deliveries
- Publisher: NHM Goa
- URL: https://nhm.goa.gov.in/facility-wise-deliveries/
- Access: scrape HTML table.
- Format: HTML; 32 facilities (North Goa 18, South Goa 14).
- Licence: not stated on the page.
- Last update: page modified 5 November 2026; reporting month not named.
- Key fields: district, facility name and type, total deliveries (incl. C-section), C-sections, OPD, IPD, major and minor surgery.
- How it helps: facility-level ground truth that a named public facility does C-sections (labels for the claim checker), e.g. "DH Mapusa".
- Join: facility name plus district (fuzzy).
- Risks: one small state, one month, public facilities only. Similar Assam NHM PDFs exist (2018-19 to 2020-21) but refused connections from here.

### dataful-hmis-district-monthly (priority 3)
- Name: Month-wise Data for all Health Indicators under HMIS for <district> (one dataset per district), e.g. Rohtak
- Publisher: Dataful, source HMIS
- URL: https://dataful.in/datasets/16434 (example; 132,120 rows, 13 columns)
- Access: per-district downloads from Dataful; free/premium status per dataset not confirmed.
- Licence: Dataful terms (quoted above).
- Last update: 28 July 2026; covers 2008-09 to 2021-22.
- Key fields: fiscal_year, month, district_lgd_code, indicator_head, indicator, facility_category (public/private/rural/urban), value.
- How it helps: longer and more recent series than idp-hmis-subdistrict for priority districts (e.g. Bihar, Maharashtra demo districts).
- Join: LGD district code.
- Risks: one dataset per district, so national coverage means hundreds of downloads.

### srs-imr-mmr (priority 3)
- Name: SRS Bulletin 2022 Vol 57-I; SRS Special Bulletin on Maternal Mortality in India 2021-23
- Publisher: Office of the Registrar General & Census Commissioner, India
- URL: https://censusindia.gov.in/nada/index.php/catalog/45567 and https://censusindia.gov.in/nada/index.php/catalog/46177
- Access: PDF download (SRS_Bulletin_2022_Vol_57_No_1.pdf; SRS_MMR_Bulletin_2021_2023.pdf).
- Licence: "(c) ORGI Digital Library, All Rights Reserved."
- Last update: published 2025-06-12 and 2025-09-03.
- How it helps: state IMR/MMR as context lines in explanations ("Bihar's MMR is ...").
- Join: state name.
- Risks: state only, PDF tables; MMR state rows not verified (catalog page lists spatial coverage as India).

### aikosh-rhs-district-2017 (priority 3)
- Name: District-wise availability of health centres in India as on 31st March, 2017
- Publisher: MoHFW via AIKosh (Rural Health Statistics 2017)
- URL: https://aikosh.indiaai.gov.in/home/datasets/details/district_wise_availability_of_health_centres_march_2017.html
- Access: download button, 26.65 KB; login requirement not stated.
- Licence: "GODL license" (Government Open Data License - India), text not shown.
- How it helps: expected count of public CHCs, SDHs and DHs per district to check whether our
  facility list is missing public facilities in a district.
- Join: state and district name.
- Risks: 2017 is stale; the current Health Dynamics of India 2022-23 district tables are on
  hmis.mohfw.gov.in, which was unreachable.

### nhm-mis-state-progress (priority 4)
- Name: State-wise progress under NHM, status as on 30.09.2024
- Publisher: NHM Facility Centre, MoHFW
- URL: https://nhm.gov.in/New-Update-2023-24/NHM-MIS/Sept_2024/National_Overview.pdf (plus per-state-group PDFs under https://nhm.gov.in/MIS-NHM/)
- Access: PDF, 230.4 KB (I read pages 1-3 and grepped the text).
- Licence: not stated.
- Key fields: counts by state group of FRUs (1,551 at CHC and other level, India), ALS ambulances (3,058), RKS, plus SRS indicators.
- How it helps: state-level counts of FRUs (C-section capable public units) to sanity-check our counts.
- Risks: state/group level only, PDF.

### idp-ncrb-accidents (priority 4)
- Name: Traffic Accidents in India; Accidental Deaths in India (NCRB ADSI)
- Publisher: India Data Portal, source NCRB
- URL: https://ckan.indiadataportal.com/dataset/traffic-accidents-in-india and https://ckan.indiadataportal.com/dataset/accidental-deaths-in-india
- Access: direct CSV (largest resource 3,526,110 bytes).
- Licence: "Open Data Commons Attribution License".
- Coverage: state x year 2018-2024; includes "The Place of Occurrence Wise Fire Accidental Deaths".
- How it helps: state-level trauma and burn need context.
- Risks: state level only.

### idp-mission-antyodaya (priority 4)
- Name: Mission Antyodaya (2019-20 survey)
- Publisher: India Data Portal, source MoRD
- URL: https://ckan.indiadataportal.com/dataset/mission-antyodaya
- Licence: "Open Data Commons Attribution License".
- Coverage: village (186,292,442-byte file), panchayat, block, district, state. District resource has "CHC Available", "PHC Available", "No Health Centre Available".
- How it helps: rural access gaps at block/district level for need scoring.
- Risks: village-level files are large (village infrastructure 186 MB) and the health columns I saw are only at district level.

### shrug (priority 4)
- Name: SHRUG (Socioeconomic High-resolution Rural-Urban Geographic Platform for India)
- Publisher: Development Data Lab
- URL: https://www.devdatalab.org/shrug (download page https://www.devdatalab.org/shrug_download/ rendered no module list for me)
- Licence: "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License"; data "provided on an 'as is' basis".
- How it helps: village/town population and Census 2011 polygons for catchment population around facilities.
- Risks: module contents not verified; non-commercial licence.

## Searched but not found or not verifiable

- data.gov.in HMIS district item-wise monthly catalog and PM-JAY state-wise admissions resources:
  appear in search results but data.gov.in returned 503 from here; not seen.
- HMIS facility-wise reports on hmis.mohfw.gov.in / hmis.nhp.gov.in: portal unreachable (timeout / refused).
- Rural Health Statistics 2021-22 and Health Dynamics of India 2022-23 district tables (Section II):
  the cited mohfw.gov.in PDF URL returns 404; the HMIS publications path is unreachable; the PARI
  library page renders client-side and showed no file link. No 2023-24 edition found.
- PMNDP centre-level list and sessions (pmndp.mohfw.gov.in): TLS verification failed; not seen.
- PM-JAY claims or utilisation by specialty and district: only Parliament answers and PIB releases
  in search results (all hosts refused); NHA public dashboard refused connection. No downloadable
  district-by-specialty data found.
- ICMR-INDIAB state-wise diabetes/hypertension tables (Lancet Diabetes Endocrinol 2023): found only
  in news coverage; supplementary appendix not opened.
- LASI Wave 1 state CKD/diabetes data: IIPS page lists only instruments; g2aging access page did
  not name LASI. Microdata needs registration; not verified.
- NFHS-6 official district fact sheets: release of India/State fact sheets on 29 May 2026 confirmed
  by search results; a district release could not be confirmed (rchiips.org TLS failure).
- Dialysis session counts by district or facility from HMIS: no HMIS dialysis item exists in the IDP field list.
- Census 2011 district PCA from censusindia.gov.in directly: not needed, IDP mirror covers it.
- Assam NHM facility-wise institutional delivery PDFs (2018-19 to 2020-21): connection refused.
