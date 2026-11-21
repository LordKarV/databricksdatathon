# Facility registries, empanelment and accreditation: candidate datasets

Discovery pass, 2026-11-21. Nothing larger than a page was downloaded. Sample API calls (one page each)
and page HTML were kept only in the session scratchpad.

## Read this first: most Indian government portals are unreachable from our network

From this machine (and from the WebFetch service) these hosts refused or timed out on 2026-11-21:
data.gov.in, api.data.gov.in, hospitals.pmjay.gov.in, pmjay.gov.in, dashboard.pmjay.gov.in,
cghs.mohfw.gov.in, cghs.nic.in, nhrr.mohfw.gov.in, www.esic.gov.in, hmis.mohfw.gov.in,
indianrailways.gov.in, www.jeevandayee.gov.in, www.echsbpa.utiitsl.com, cdsco.gov.in,
cmhis.nagaland.gov.in. facility.abdm.gov.in, abdm.gov.in and nha.gov.in returned HTTP 403.
This looks like geo-blocking of non-Indian IPs (not verified). Databricks Free Edition egress is limited
to trusted domains, so it will not help either. Whoever fetches these needs a network path from India
(a teammate in India, or an India-region VM), then uploads to a UC volume.

Reachable: nabh.co, nmc.org.in, aikosh.indiaai.gov.in (mirror of many data.gov.in datasets),
www.mohfw.gov.in, www.echs.gov.in, nin.mohfw.gov.in, nhm.gov.in, cbhidghs.mohfw.gov.in,
www.bis.gov.in, cdnbbsr.s3waas.gov.in (state/district NIC sites), journals.plos.org.

How often our records already mention these registries (regex over name, description, specialties,
capability, procedure in data/raw/facilities.parquet, 10,088 rows): NABH 1,318; PMJAY/PM-JAY/Ayushman
679; Medical College/NMC 462; CGHS 181; ECHS 143; ESIC/"ESI " 141; Railway 122. These are claims we can
check against the registries below. No registry IDs exist in our data; joins must use name + PIN
(10,030 rows have a PIN) + coordinates (9,970 rows).

## Ranked summary

| Pri | Slug | What | Access from here |
|-----|------|------|------------------|
| 1 | nabh_accredited | NABH accredited/certified/empanelled organisations, with lat/lng and specialty filter | JSON endpoint works |
| 1 | nmc_colleges | NMC college and course list (839 MBBS colleges, PG/super-specialty courses per college) | JSON endpoint works |
| 1 | pmjay_hem_portal | PM-JAY empanelled hospitals with empanelled specialties | Blocked (India IP needed) |
| 2 | pmjay_plos_2020 | 2020 scrape of PM-JAY empanelled hospitals (PLoS ONE S1 File, CC-BY) | Reachable, contents unverified |
| 2 | nhp_hospital_directory_geo | National Hospital Directory with geo code (NHP/NIHFW) | AIKosh mirror, 9.86 MB |
| 2 | all_india_health_centres_2016 | Public SC/PHC/CHC/DH directory with coordinates, Oct 2016 | AIKosh mirror, 20 MB |
| 2 | abdm_hfr | ABDM Health Facility Registry (HFR) | 403 here; bulk needs ABDM credentials |
| 3 | cghs_empanelled | CGHS empanelled hospitals (city, name, address; specialty validity in PDFs) | AIKosh mirror; BIS PDF copies |
| 3 | blood_bank_directory | Blood bank directory with geo code | AIKosh mirror |
| 3 | nhp_hospital_directory_2015 | Hospital Directory as on July 2015 (with disciplines) | AIKosh mirror, 449 KB |
| 4 | haryana_pmjay_district_lists | Haryana AB-PMJAY empanelled lists per district (PDF) | Reachable |
| 4 | echs_empanelled | ECHS empanelled hospital search (UTIITSL) | Blocked |
| 4 | nin2hfi | NIN-to-HFI public facility IDs (HFR predecessor) | Portal reachable, no bulk file seen |
| 5 | esic_hospitals | ESIC hospital counts by state | Only counts found |
| 5 | railway_hospitals | Railway hospitals, zonal PDFs | Zonal PDFs only |

## Candidates in detail

### nabh_accredited (priority 1)
- Name: NABH "Find an Accredited Healthcare Organisation". Publisher: National Accreditation Board for
  Hospitals and Healthcare Providers (QCI).
- URL: https://nabh.co/find-a-healthcare-organisation/ ; data endpoint used by the page's own JS
  (https://nabh.co/wp-content/themes/nabh/js/my-map.js): POST https://nabh.co/wp-admin/admin-ajax.php
  with form fields action=get_hospitals, q, selectState, specialities[], page. Helpers:
  GET ...admin-ajax.php?action=get_states, ?action=get_cities_by_state&state=X.
- Format: JSON {html, pagination, mapData}. mapData = [{name, lat, lng, address}]; the html table has
  HCO Name, Address (ends with PIN), Contact, website link, Acc. No., Accreditations/Certifications status.
- Size: unfiltered query returned total_results 21,609 in 865 pages of 25 (ran 2026-11-21). With
  specialities[]=DIA: 1,743 results (the state filter in my test did not take effect; needs work).
- Status values seen: "Accredited on 6th Edition", "Renewed on 5th Edition", "Empaneled", "Certified",
  "Forced Withdrawal of ...". Acc. No. prefixes: H-, HOS/, PEH-, PESHCO-, numeric.
- Specialty filter codes (39): ANA, AYU, BLO, CAR, DEN, DER, DIA (Dialysis), EMD (Emergency Medicine),
  END, ENT, EYE, GAS, HEP, HOM, ICU (Critical Care), IMG (Imaging), INF, LAB, MED, NEU, NPH, OBG, ONC, ORT,
  PED, PSY, PUL, REP, RHE, SID, SUR, TRN, UNA, URO, YOG, PHARMACY, AMBULANCE, CAE, PAN.
- Terms (https://nabh.co/terms-and-conditions/): "All content available on this website ... is the
  intellectual property of NABH and/or QCI unless otherwise indicated. You may not reproduce, distribute,
  or publish any part of this content for commercial purposes without prior written consent from NABH."
  robots.txt allows /wp-admin/admin-ajax.php. Non-commercial datathon use looks permitted; keep to
  about 1 request per second (865 pages = about 15 minutes).
- Freshness: live; accreditation numbers dated up to 2026.
- Roles: evidence, labels, geo.
- How it helps: hard corroboration that a facility exists, at a PIN and coordinate, and holds a current
  quality accreditation; the specialty filter gives per-specialty evidence (dialysis, OBG, ICU, emergency,
  cardiology, imaging) to back or contradict our extracted claims. 1,318 of our rows mention NABH, so it
  also measures how often our text overclaims. Accreditation status can be a ranking feature and a
  weak training label.
- Join keys: normalised name + PIN (from address tail) + haversine distance on lat/lng; Acc. No. as a
  stable key once matched.
- Risks: mixes hospitals, SHCOs, clinics, labs, entry-level and "Empaneled" (CGHS/ECHS empanelment
  programme) records; some Nepal entries in the state list; addresses messy (one row showed Kolkata
  address under Jhunjhunu); geocoordinates likely Google-geocoded, not surveyed; whether the specialty
  filter reflects accredited scope or self-declared services is not documented.

### nmc_colleges (priority 1)
- Name: NMC College and Course Search / List of College Teaching MBBS. Publisher: National Medical Commission.
- URL: https://nmc.org.in/page/information-desk-for-students-to-study-in-india-list-of-college-teaching-mbbs
  (page) ; JSON used by that page: GET https://nmc.org.in/college-courses/list?page=N&per_page=M ;
  detail: GET https://nmc.org.in/college-courses/detail/{college_id} (send Accept: application/json,
  X-Requested-With: XMLHttpRequest).
- Format: JSON. List fields: id, college_id, college_code, college_name, course_name, state_name,
  university_name, management_type, inception_year, lop_date, approved_seat, approval_date, updated_at,
  previous_approved_seat, recognition_status, remark, status, seat_matrix. Detail fields: address, city,
  pincode, email, website, mobile/landline (institutional), no_of_seat, and courses[] with every
  MD/MS/DM/MCh course and approved seats.
- Size: list total 839 records, total_seats 140,664 (run 2026-11-21). Detail is one call per college.
- Terms: none found on the page; robots.txt is "User-agent: * / Disallow:" (allows all). Licence not stated.
- Freshness: approval_date and updated_at of 2026-11-04 on the first record.
- Roles: evidence, labels, geo.
- How it helps: a teaching hospital with approved DM Nephrology, MCh CTVS, DM Neonatology, MD OBG or
  MS Orthopaedics seats has that department by regulation, which is strong evidence for dialysis,
  cardiac surgery, NICU, high-risk obstetrics and trauma. Medical colleges are usually the tertiary
  referral option for rural users. Beds are not in the JSON (not found).
- Join keys: college name + pincode; state_name; then lat/lng via the India Post PIN directory.
- Risks: college name differs from attached hospital name (e.g. "X Medical College" vs "Y District
  Hospital"); no coordinates; no beds; PG course list is a proxy for departments, not service hours.

### pmjay_hem_portal (priority 1 value, blocked)
- Name: AB PM-JAY HEM empanelled hospitals search. Publisher: National Health Authority.
- URL: https://hospitals.pmjay.gov.in/Search/empnlWorkFlow.htm?actionFlag=ViewRegisteredHosptlsNew
- Access: paginated HTML form, POST with actionFlag=ViewRegisteredHosptlsNew, search=Y, pageNo,
  searchState, searchDistrict, searchHospType, searchSpeciality (from the 2019 R scraper at
  https://gist.github.com/apoorv74/2e047db089b1771e283b5b641238cc22). Connection refused and timed out
  from here: I did not see the page myself. Unverified.
- Fields (per PLoS ONE 2021 methods, https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0251814):
  hospital name, type (public/private for profit/not for profit), address, email, contact,
  specialties empanelled and specialties upgraded.
- Size: 20,257 hospitals in March 2020 (PLoS); a Business Standard article cites 29,870 empanelled as
  of 31 Oct 2024 (Lok Sabha figure), not verified.
- Terms: not seen.
- Roles: evidence, labels, routing.
- How it helps: the only national list with per-hospital empanelled specialties tied to PM-JAY packages
  (dialysis, cardiology/CTVS, neonatal, obstetrics, burns, polytrauma). It also answers "is this free for
  an Ayushman card holder", which matters to the Bihar health worker.
- Join keys: name + district + state; PM-JAY hospital ID (HOSP...) once matched. No coordinates known.
- Risks: blocked from our network; scraping a portal has no licence statement; Tamil Nadu counts
  departments as facilities (PLoS); list changes monthly.

### pmjay_plos_2020 (priority 2)
- Name: S1 File of "Public sector hospital empanelment under PM-JAY" (PLoS ONE 16(5): e0251814).
- URL: https://doi.org/10.1371/journal.pone.0251814.s007 (served as pone.0251814.s007.xlsx; s001-s006
  are DOCX summary tables).
- Format: XLSX, size not checked. Contents not opened: the paper says the extracted dataset is in the S1
  File; whether it holds per-hospital specialty rows is unverified.
- Licence: "This is an open access article distributed under the terms of the Creative Commons
  Attribution License ..." (CC BY).
- Freshness: Feb-Mar 2020 snapshot (20,257 hospitals; specialty data for 15,177).
- Roles: evidence, labels.
- How it helps: a citable, legally reusable fallback if the live portal stays blocked; good enough to
  corroborate long-standing empanelment and specialties.
- Join keys: name + address/district.
- Risks: 6 years old; may contain only public facilities (the paper focuses on public-sector
  empanelment); exact columns unknown until opened.

### nhp_hospital_directory_geo (priority 2)
- Name: National Hospital Directory with Geo Code and additional parameters (updated till last month).
  Publisher: MoHFW / NIHFW (National Health Portal).
- URL: https://data.gov.in/resource/national-hospital-directory-geo-code-and-additional-parameters-updated-till-last-month
  (blocked here); mirror with a download button:
  https://aikosh.indiaai.gov.in/home/datasets/details/national_hospital_directory_with_geo_code_and_additional_parameters_updated_till_last_month.html
- Format: CSV per OSM wiki; AIKosh shows "Download 9.86 MB". Whether AIKosh download needs a login: not tested.
- Fields (from https://wiki.openstreetmap.org/wiki/India_Health_Facilities_Import): Name, Address,
  Street, Locality, Pincode, State_Name, District_Name, Taluka_Name, Block_Name, Hospital_Category,
  Website, Emergency_Services, Facilities, Specialties, plus coordinates, Hospital_Reg_No,
  Established_year (and phone/email fields we would drop).
- Licence: GODL-India (AIKosh "GODL license"; OSM wiki: "Public Domain with attribution").
- Freshness: published 10 Aug 2017 per OSM wiki; AIKosh metadata date 10/08/17. Treat as 2017.
- Roles: evidence, geo, labels.
- How it helps: a second, independent geocoded record of hospitals with self-reported specialties and
  emergency services; useful to resolve our contradictory locations and to vote on service claims.
- Join keys: name + Pincode + District_Name; coordinates.
- Risks: old; self-reported; OSM import notes "gross location errors" in places and placeholder values
  (N/A, 0).

### all_india_health_centres_2016 (priority 2)
- Name: All India Health Centres Directory as on 7th October 2016. Publisher: MoHFW.
- URL: https://data.gov.in/catalog/all-india-health-centres-directory (blocked);
  mirror https://aikosh.indiaai.gov.in/home/datasets/details/all_india_health_centres_directory_till_october_2016.html
- Format: structured file, "Download 20 MB" on AIKosh. Fields per description: state, district,
  sub-district, facility name, address, geolocation; facility types SC, PHC, CHC, District and State
  Hospitals.
- Licence: GODL-India. Freshness: Oct 2016.
- Roles: geo, routing, population.
- How it helps: our dataset is web-text and skews private and urban; this gives the public referral chain
  (PHC -> CHC -> District Hospital) with coordinates for rural Bihar-type queries and a place to send a
  patient when no verified private option exists.
- Join keys: facility name + district + coordinates.
- Risks: 10 years old; public only; no specialties.

### abdm_hfr (priority 2)
- Name: ABDM Health Facility Registry. Publisher: National Health Authority.
- URL: https://facility.abdm.gov.in/searchV2 (public search; HTTP 403 from here, not seen).
  NHRR now appears under https://facility.abdm.gov.in/nhrr (search result only, not opened).
- Access: public web search by name, location, specialities, facility type (per search snippets);
  APIs are for registered integrators (sandbox https://sandbox.abdm.gov.in, credentials needed). No bulk
  download or data.gov.in release found.
- Key fields: 12/14-character HFR ID (e.g. IN0123456789 format in ABDM docs), name, ownership, type,
  address, specialities, verification status.
- Scale: "over 3.54 lakh" facilities registered (2024 MoHFW figure via search; unverified).
- Licence: not seen.
- Roles: evidence, geo.
- How it helps: the canonical facility ID; "verified" status is direct evidence of existence.
- Join keys: HFR ID; name + PIN.
- Risks: no bulk access; blocked; scraping the search would need care with terms.

### cghs_empanelled (priority 3)
- Name: List of Hospitals empaneled under CGHS all over India. Publisher: CGHS, MoHFW.
- URL: https://data.gov.in/resource/list-hospitals-empaneled-under-cghs-all-over-india (blocked);
  mirror https://aikosh.indiaai.gov.in/home/datasets/details/list_of_hospitals_empaneled_under_cghs_all_over_india.html
  ("Redirected" to OGD, updated 02 Jul 2026, GODL). Fields: city name, hospital name, address.
  Granularity half-yearly (search snippet). Specialty-level validity appears only in the CGHS PDFs:
  consolidated copy at https://www.bis.gov.in/wp-content/uploads/2026/08/circular-217-cghs-cashless-consolidated-list-05-Aug-2026_compressed-1.pdf
  (HEAD: 6,127,045 bytes, Last-Modified 6 Aug 2026; not opened).
- Roles: evidence.
- How it helps: central-government empanelment requires NABH or inspection; confirms existence in 80+
  cities; 181 of our rows mention CGHS.
- Join keys: city + name + address.
- Risks: city-only, no PIN or coordinates in the OGD table; PDF parsing needed for specialties.

### blood_bank_directory (priority 3)
- Name: Blood Bank Directory (updated till last month). Publisher: MoHFW/NHP.
- URL: https://aikosh.indiaai.gov.in/home/datasets/details/blood_bank_directory_updated_till_last_month.html
  (seen in search; page not opened). OSM import page counted 2,259 blood banks.
- Fields: state, city, address, geo location, PIN, website. Licence GODL.
- Roles: evidence, routing.
- How it helps: C-section, trauma and burns need blood; a licensed blood bank in or near the facility is
  corroborating evidence and a routing factor.
- Join keys: name + PIN + coordinates. Risks: probably 2017 vintage.

### nhp_hospital_directory_2015 (priority 3)
- URL: https://aikosh.indiaai.gov.in/home/datasets/details/hospital_directory_as_on_july_2015.html
  (449.16 KB, GODL, NIHFW). Fields: name, address, category, systems of medicine, PIN, specializations.
- Use: older version of nhp_hospital_directory_geo; only if the geo version is unobtainable.

### haryana_pmjay_district_lists (priority 4)
- URL: https://ayushmanbharat.haryana.gov.in/pm-jay/ (22 district PDFs, "as on 03/08/2026"; page last
  updated 04.08.2026); plus de-empanelled, inactive, suspended, withdrawn lists at
  https://ayushmanbharat.haryana.gov.in/?p=8322
- Columns (Ambala PDF, page 1 read): S.no., Hospital ID (e.g. HOSP6G03078), Hospital Name, Hospital Type,
  Hospital Email ID, Nodal Officer Name, Hospital Contact Number. No specialties.
- Use: shows the PM-JAY hospital ID format and gives de-empanelled/suspended lists (negative evidence).
- Risks: one state; Nodal Officer Name and mobile numbers are personal data: drop those columns at ingest.

### echs_empanelled (priority 4)
- https://www.echs.gov.in/ links "Search Empanelled Hospitals ... over 3,000 cashless civil hospitals,
  diagnostic centers & specialty cl[inics]" to https://www.echsbpa.utiitsl.com/ECHS/ (timed out here).
  143 of our rows mention ECHS. Same role as CGHS; lower coverage of civilians' needs.

### nin2hfi (priority 4)
- https://nin.mohfw.gov.in/about_nin2hfi.php: 10-digit NIN for public facilities with MDDS state,
  district, taluka, village codes. Superseded by HFR; no bulk download seen.

### esic_hospitals (priority 5) and railway_hospitals (priority 5)
- ESIC: only state-wise counts (data.gov.in resource "State/UT-wise Number of Hospitals of ESIC as on
  April 2016", parliamentary answers: 151 ESI hospitals in 2023). esic.gov.in unreachable.
- Railways: CAG 2024 cites 129 hospitals and 586 health units; lists exist only as zonal PDFs, e.g.
  https://ecr.indianrailways.gov.in/cris//uploads/files/1754649574318-Organisational%20Details%20(Medical%20Department),%20East%20Central%20Railway,%20Hajipur.pdf
  Railway and ESI hospitals serve restricted beneficiaries, so they matter little for routing.

## Searched for and not found (or not verifiable)
- A bulk download, data.gov.in release or open API for ABDM HFR / NHRR. Only the public search page and
  integrator APIs.
- A PM-JAY national export (CSV/XLSX) or open API; the "Public Dashboard > Download" PDF route described
  by blogs could not be checked (pmjay.gov.in blocked).
- Bed counts per medical college in NMC data (not in the JSON; UG MSMER documents are standards, not data).
- A current CGHS or ECHS table with per-hospital approved specialties in machine-readable form.
- A per-hospital ESIC list with beds; a national Railway hospital list.
- Maharashtra MJPJAY empanelled list (https://www.jeevandayee.gov.in/RGJAYDocuments/Empanelled_Hospitals_Under_MJPJAY.pdf
  seen only in search results; site blocked). Tamil Nadu CMCHIS list: https://www.cmchistn.com/ loads a
  1.7 KB JS shell, no list link found.
- Bihar state health department hospital list (statehealth.bihar.gov.in blocked).
- GitHub or Kaggle copies of PM-JAY, HFR or NABH lists (only a 2019 R scraper gist).
- The full GODL-India licence text (data.gov.in blocked); summary per Wikipedia Template:GODL-India-text:
  worldwide, royalty-free, non-exclusive right to use, adapt and publish, with attribution; excludes
  personal data.
