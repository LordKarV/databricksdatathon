# Gap-filling dataset searches

Run on 2026-11-21 from a non-Indian network. Nothing larger than a page was saved to the project.
Small checks (row counts, headers) were run with curl and the project venv; the helper
/Users/karthikvattem/projects/datathon/external/gaps/ctx.py prints text around keywords in a saved
HTML file. Numbers below come from those runs or from pages I read. Anything else is marked
unverified.

## Summary by priority

| P | slug | what | access from here |
|---|------|------|------------------|
| 1 | jan_sahayak_pmjay_mirror | Nightly mirror of NHA PM-JAY HEM directory, 39,766 hospitals, lat/lon, specialty codes | GitHub Pages JSON, 15.8 MB |
| 1 | wikidata_india_hospitals | Wikidata hospitals (2,772) and medical schools (383) in India, CC0 | SPARQL, works |
| 1 | covid_beds_delhi_tn_telangana | Per-hospital COVID ICU / ventilator / oxygen beds 2020-21 (Delhi, TN, Telangana) | GitHub CSV |
| 2 | gujarat_pmjay_specialty_csv | Gujarat PMJAY-MA 909 private hospitals with PM-JAY IDs and specialties, Feb 2025 | GitHub CSV, 160 KB |
| 2 | telangana_aarogyasri_json | Telangana Aarogyasri 1,236 hospitals with specialty codes | GitHub JSON, 269 KB |
| 2 | nephroplus_clinics | 396 NephroPlus dialysis clinic pages, many inside a named host hospital, with PIN | sitemap + pages |
| 2 | ncdir_hbcr_hospitals | 361 Hospital Based Cancer Registry hospitals (oncology label) | HTML page |
| 2 | psa_oxygen_plants_rti | PM CARES PSA oxygen plants by hospital, 4,135 plants (RTI reply, Mar 2023) | PDF 1.2 MB, OCR |
| 2 | geonames_in | GeoNames India dump plus alternate names, CC BY 4.0 | direct, 15.8 MB + 1.4 MB |
| 2 | wayback_mjpjay_network | Wayback captures of MJPJAY (Maharashtra) network hospitals: 2,432 hospital names + IDs | Wayback |
| 2 | wayback_source_urls | Wayback snapshots of the dataset's own source_urls (10 of 20 sampled archived) | CDX / availability API |
| 3 | apollo_dialysis_centres | 196 Apollo Dialysis centre pages | sitemap + pages |
| 3 | dcdc_centres | 26 DCDC dialysis centre pages, mostly PPP units in district hospitals | sitemap + pages |
| 3 | aarthi_scans_branches | 169 Aarthi Scans branch pages with address, PIN, modality list | sitemap + pages |
| 3 | kerala_kasp_empanelled | Kerala SHA KASP empanelled hospitals by district (HTML tables) | HTML |
| 3 | indicxlit | AI4Bharat IndicXlit transliteration models (MIT), about 125 MB each | GitHub release |
| 3 | osm_name_variants | OSM name:hi / name:* tags (from the existing OSM India extract) | taginfo counts only |
| 3 | nnf_fellowship_centres | NNF trainee fellowship centres list (NICU training units), PDF dated 06-07-2026 | robots.txt disallows PDF path; ask NNF |
| 4 | mahajan_imaging_locations | 15 Mahajan Imaging locations (Delhi NCR) | sitemap + pages |
| 4 | wikidata_india_villages | 154,328 "village in India" items, 32,609 with Hindi labels | SPARQL |
| 4 | delhi_dlsa_burn_hospitals | 13 Delhi hospitals with burn facilities (DLSA PDF, Feb 2026) | PDF 250 KB |

## Candidates

### jan_sahayak_pmjay_mirror (priority 1)
- Name: Jan Sahayak data, nightly copy of the NHA PM-JAY empanelled hospital directory.
  Publisher: independent GitHub project (amithrh), source NHA Hospital Engagement Module.
- URL: https://github.com/amithrh/jan-sahayak-data ; data https://amithrh.github.io/jan-sahayak-data/data/meta.json
  and https://amithrh.github.io/jan-sahayak-data/data/states/<NHA state code>.json
- Access: direct download (GitHub Pages, reachable from here). Format: JSON arrays.
- Size: gh-pages branch blobs total 15,798,105 bytes; largest state file 9.json 1,026,871 bytes.
- meta.json (read 2026-11-21): snapshotDate 2026-11-21, hospitals 39,766, locatedHospitals 38,262,
  nhaReportedTotal 40,449, pincodes 19,334.
- Row fields per README: facilityId, name, address, phone, type (G/P), lat, lon, specialityCodes,
  stateCode, districtCode, empanelledOn. Sample (Sikkim): HOSP11P156231, Amara Health City,
  lat 27.31938, lon 88.60693, speciality code string "100005".
- Licence: none in the repo (GitHub licence null). README: "This is an independent project, not a
  government service. A directory listing does not confirm that a hospital is accepting PM-JAY
  patients today or offers a particular treatment package." Attribution: NHA HEM.
- Roles: labels, evidence, geo. Gives a national PM-JAY list without the geo-block that stops us
  reaching hem.nha.gov.in and hospitals.pmjay.gov.in. Specialty codes are per-hospital labels for
  cardiac surgery, dialysis, oncology, neonatal care. HEM coordinates corroborate or correct ours.
- Join keys: name + PIN (parse from address) + district code; lat/lon distance; PM-JAY facility ID
  (also in the Gujarat CSV below).
- Risks: unofficial mirror with no licence; the specialty code dictionary is not published in the
  repo (codes like "100005" need decoding, unverified); phone field holds hospital numbers that
  should be dropped; NHA lists some hospitals twice (README). Already-found list covers HEM itself,
  but not a reachable copy.

### wikidata_india_hospitals (priority 1)
- Name: Wikidata items for hospitals and medical schools in India. Publisher: Wikimedia / Wikidata.
- URL: https://query.wikidata.org/sparql (SPARQL endpoint; bulk dump
  https://dumps.wikimedia.org/wikidatawiki/entities/latest-all.json.bz2 is 103,919,291,959 bytes, skip).
- Access: API (SPARQL, worked from here). Format: CSV/JSON results.
- Counts from my queries (P31/P279* Q16917 hospital, P17 Q668 India): 2,772 items; 2,503 with
  coordinates (P625); 561 with official website (P856); 105 with bed count (P6801); 1,530 with postal
  code (P281); 134 with a Hindi label. Medical schools (P31/P279* Q494230): 383, 254 with coordinates.
  Most frequent external IDs on Indian hospitals: ROR 409, Scilit 401, GRID 391, ISNI 295, Ringgold 289,
  OpenStreetMap node ID 23.
- Licence: https://www.wikidata.org/wiki/Wikidata:Licensing says "Wikidata requires a CC0 license,
  which is equivalent to public domain".
- Roles: evidence, geo, other (identity crosswalk). Use websites and coordinates to match and to
  flag merged records (two Wikidata items matching one facility row, or one item matching rows in
  different cities). ROR/GRID link teaching hospitals to research output.
- Join keys: normalized official website domain vs our officialWebsite; name + PIN; coordinates.
- Risks: small and skewed to large urban and teaching hospitals; bed counts on only 105 items;
  some items have multiple bed values (Cama Hospital returned 367 and 505).

### covid_beds_delhi_tn_telangana (priority 1)
- Name: Archived per-hospital COVID bed availability, Delhi, Tamil Nadu and Telangana.
- Publishers and URLs:
  - Delhi: https://github.com/gurmanbh/delhi-beds-scraper (scrapes https://coronabeds.jantasamvad.org),
    file data/beds-by-hospital-timeseries.csv 13,669,129 bytes, licence CC0-1.0, last push 2023-07-18.
    Columns: name, beds_total/occupied/vacant, type, last_updated_at, icu_beds_without_ventilator_*,
    covid_icu_beds_*, oxygen_left_for_days/hours, noncovid_icu_beds_*, ventilators_*.
  - Tamil Nadu: https://github.com/stopcoronatn/stopcoronatn.github.io data/beds.csv 71,736 bytes,
    licence Unlicense, source stopcorona.tn.gov.in / tncovidbeds.tnega.org. Columns: District,
    Institution, COVID beds, oxygen-supported beds, non-oxygen beds, ICU beds, ventilator (total/
    occupied/vacant), Last updated (2021-05-12 in the rows I saw), Contact Number.
  - Telangana: https://github.com/covid-telangana/covid-telangana.github.io data/beds.csv
    145,261 bytes, no licence file, last push 2021-12-12. Columns: DISTRICT, NAME OF THE HOSPITAL,
    regular / oxygen / ICU (ventilator, CPAP) beds total-occupied-vacant, TYPE (Private/Govt),
    CONTACT NO, LAST UPDATED (2021-08-31).
  - Index of other state sources (scrapers, not data): https://github.com/pxthxk/COVIDBedsIndia
    (MIT; Ahmedabad, AP, Bengaluru, Bihar, Chhattisgarh, Delhi, Goa, Haryana, Jharkhand, MP, Nagpur,
    Nashik, Odisha, Pune, Rajasthan, Surat, TN, Telangana, Thane). Wayback has BBMP
    https://apps.bbmpgov.in/covid19/ captures from 2021-05-20 to 2022-05-23 and TN
    https://tncovidbeds.tnega.org/api/hospitals (2021-06-01, application/json, 4,254 bytes).
- Access: direct download. Coverage: 3 states, 2020-21; Git history of the TN and Telangana repos
  likely holds hourly snapshots (not checked).
- Roles: evidence, labels. The only facility-level ICU, ventilator and oxygen-bed evidence found;
  ICU is a required service with no other label. A hospital that reported ICU beds in 2021 is a
  dated positive label.
- Join keys: hospital name + district (no PIN or coordinates); fuzzy name match within district.
- Risks: 2021 surge capacity, not current; contact numbers must be dropped; Telangana repo has no
  licence; names are short and ambiguous.

### gujarat_pmjay_specialty_csv (priority 2)
- Name: Total empanelled hospitals speciality-wise, Feb 2025 (Gujarat PMJAY-MA). Publisher: GitHub
  user the-patel (source presumably the Gujarat SHA list, not stated).
- URL: https://github.com/the-patel/GCard-Hospital/blob/HEAD/Total_Empaneled_hospitals_Speciality_wise_Feb-2025.csv
- Access: direct download; CSV 160,270 bytes. Licence: GPL-3.0 on the repo (source data terms unknown).
- Rows: 909, 909 distinct Hospital Id, 32 districts; types Private (For Profit) 758, Private (Not
  For Profit) 84, Trust 67. No government hospitals in this file.
- Fields: District, Hospital Name, Hospital Type, Hospital Id (PM-JAY IDs such as HOSP24P10245),
  Specialities (comma list: General Medicine/Dialysis, Cardiology, Cardio thoracic & Vascular
  Surgery, Medical/Surgical/Radiation Oncology, Neo natal care Packages, Polytrauma, ...).
- Roles: labels. Per-hospital specialty labels for 981 Gujarat rows in our data.
- Join keys: name + district; Hospital Id joins to the jan_sahayak mirror for coordinates.
- Risks: provenance not documented; some specialty strings are concatenated without commas
  ("CardiologyJoint Replacement").

### telangana_aarogyasri_json (priority 2)
- Name: Aarogyasri data (Telangana). Publisher: GitHub user yahiyabinhadi7-del, source not stated.
- URL: https://github.com/yahiyabinhadi7-del/AAROGYASRI-DATA (aarogyasri.json, 269,043 bytes,
  created 2026-10-08, no licence).
- Rows: 1,236 hospitals, 33 districts; a 0/1 flag split 911/325 (likely private/government,
  unverified); 11 rows with coordinates. Fields: id, name, district, flag, specialty group names,
  contact person + phone, address, lat, lon, Aarogyasri specialty codes (S5, S7, S9, M2 ...), hours.
- Roles: labels. Telangana Aarogyasri specialty labels (cardiac S7, nephrology/dialysis, oncology).
- Join keys: name + district; address text.
- Risks: unknown provenance and date; contains named contact persons with phone numbers, which we
  must drop on ingest; no licence.

### nephroplus_clinics (priority 2)
- Name: NephroPlus clinic locator pages. Publisher: NephroPlus.
- URL: https://nephroplus.com/sitemap-ind.xml (1,085 URLs, 396 under /our-clinics/<state>/);
  example https://nephroplus.com/our-clinics/assam/dialysis-clinic-in-athgaon
- robots.txt (https://nephroplus.com/robots.txt): disallows /api, /admin, /search, /not-found,
  /investors; clinic pages allowed. Terms page not found in the sitemap (only /privacy-policy); not read.
- State counts: Karnataka 99, Andhra Pradesh 41, Maharashtra 38, Bihar 26, Gujarat 23, West Bengal 20,
  Tamil Nadu 19, Telangana 17, Jharkhand 16, Uttar Pradesh 15.
- Fields: clinic name, host hospital and street address, city, state, PIN (Athgaon page: "Marwari
  Hospital, B-3, Sati Joymati Road, Athgaon, Guwahati, Assam- 781008").
- Roles: labels, evidence. Positive dialysis labels; when the clinic sits inside a named hospital it
  labels that hospital directly. Fills the "no facility-level dialysis list" gap.
- Join keys: host hospital name + PIN.
- Risks: scrape at 1 req/s (about 7 minutes); marketing pages may lag closures; terms unread.

### ncdir_hbcr_hospitals (priority 2)
- Name: Hospital Based Cancer Registries, list of hospitals. Publisher: ICMR-NCDIR, Bengaluru.
- URL: https://ncdirindia.org/cancersamiksha/reg_HBCRHistory.aspx (HTML, "Last Updated On: 20th
  February 2023"). ncdirindia.org/robots.txt returns a 404 page.
- Rows: numbered list 1 to 361 ("A A Rahim Memorial Government District Hospital, Kollam" to "Zulekha
  Yenepoya Institute Of Oncology, Dakshina Kannada"). Fields: name, city only. The HBCR 2021 report
  (https://ncdirindia.org/All_Reports/HBCR_2021/resources/HBCR_2021.pdf) says 96 of 269 registered
  HBCRs were used (per search snippet, not opened).
- Licence: page says data use should be referenced; no open licence seen.
- Roles: labels. A hospital that runs a cancer registry treats cancer patients: oncology label.
- Join keys: name + city.
- Risks: registry participation, not treatment capability by modality (radiotherapy unknown).

### psa_oxygen_plants_rti (priority 2)
- Name: PSA oxygen plants commissioned, hospital-wise (MoHFW RTI reply dated 16 March 2023).
  Publisher: MoHFW, hosted by IndiaSpend H-library.
- URL: https://www.indiaspend.com/h-library/mohfw-pmcares-cpiolttr-psaplantshospitalslist-mar23.pdf
  (1,165,189 bytes, 32 pages, scanned with OCR text layer).
- Fields: S.No, Hospital Name, PSA plant units, unit capacity (LPM), State/Agency, installation
  status. Last page grand total 4,135 plants (4,132 in the second column).
- Licence: government RTI disclosure; no licence stated.
- Roles: evidence. A hospital with an installed PSA oxygen plant has piped oxygen, a proxy for
  oxygen beds and ICU readiness in public hospitals.
- Join keys: hospital name + state (no district or PIN).
- Risks: OCR errors; the first page names the RTI applicant (personal data, do not reproduce); the
  reply says 190 pages were enclosed but this file has 32.

### geonames_in (priority 2)
- Name: GeoNames India gazetteer dump and alternate names. Publisher: GeoNames.
- URLs: https://download.geonames.org/export/dump/IN.zip (15,755,098 bytes),
  https://download.geonames.org/export/dump/alternatenames/IN.zip (1,371,341 bytes),
  https://download.geonames.org/export/zip/IN.zip (postal codes, 1,742,997 bytes); all last modified
  2026-11-21.
- Licence (readme.txt): "This work is licensed under a Creative Commons Attribution 4.0 License".
- Fields: geonameid, name, asciiname, alternatenames, lat, lon, feature class/code, admin codes;
  alternate names file adds isolanguage (hi, mr, bn, ...).
- Roles: geo. Village and town name variants, including Devanagari, for fuzzy input resolution.
- Join keys: names to LGD/Census villages via coordinates; lat/lon.
- Risks: coverage of Indian villages and share with Hindi names not measured (download not done).

### wayback_mjpjay_network (priority 2)
- Name: Internet Archive captures of the MJPJAY (Maharashtra) network hospital pages.
- URL: CDX https://web.archive.org/cdx/search/cdx?url=jeevandayee.gov.in/* ; key capture
  https://web.archive.org/web/20260419182318/https://www.jeevandayee.gov.in/MJPJAY/FrontServlet?Network+Hospitals=&actionVal=AarogyasriView&mainMenu=Hospitals&page=Network+Hospitals&requestType=PublicViewsRH&subMenu=Network+Hospitals
- What I saw in that capture (551 KB HTML, deleted after parsing): "Results 1-10 of 2432"; a
  hospital dropdown with 2,433 options (hospital ID plus name), 39 specialty codes (Burns S13,
  Cardiac And Cardiothoracic Surgery S7, Nephrology M8, Critical Care M3, Polytrauma S14,
  Neonatal M6, Medical/Radiation/Surgical Oncology ...), 40 districts, 386 talukas. Table columns:
  Hospital ID, display code, District, Taluka, Hospital Name, Address, Pincode, MCO contact, Email.
  Only the first page of 10 rows is archived; pagination is a POST.
- Other captures: HospitalWise Specialties (2021-09-21, 44,858 bytes), SpecialityWise Hospitals
  (2021-12-05, 2023-07-11), View Bed Occupancy (2021-04-22, 105,290 bytes), ListofHospitals
  (2022-07-12). Jeevandayee hospital-related PDFs were not found in CDX; only GRs and manuals.
- Licence: Wayback terms (https://archive.org/about/terms.php, not reread); government content.
- Roles: labels, evidence. Names and IDs for all 2,432 MJPJAY hospitals, dated; specialty pages
  give per-hospital specialties for the hospitals captured.
- Join keys: name (with town in the name) + district; Pincode only for 10 rows.
- Risks: no full table without the live POST; the page shows MCO phone and email (personal-ish,
  drop). The NOTTO approved hospitals page has a 2023-05-27 capture (794,019 bytes) that I could
  not parse (mostly ASP.NET state); NHRR, hem.nha.gov.in and hospitals.pmjay.gov.in have no useful
  captures (PMJAY only 2019 assets and a captcha endpoint). cmchistn.com captures are empty shells,
  but the live site is reachable from here (React app behind Cloudflare, no robots.txt).

### wayback_source_urls (priority 2)
- Name: Wayback snapshots of the dataset's own source_urls. Publisher: Internet Archive.
- URL: https://archive.org/wayback/available?url=<url> and the CDX API.
- My counts: source_urls holds 170,021 URLs, 109,502 distinct, on 13,793 hosts (practo.com 33,178,
  facebook.com 18,422, justdial.com 16,161, medindia.net 5,178, onefivenine.com 4,236). For 20 random
  distinct URLs, 10 had a snapshot (timestamps 2020-07 to 2026-07); justdial, facebook, linkedin,
  instagram and policybazaar samples had none.
- Roles: evidence, other (provenance). Dated copy of the text a claim came from; lets us show
  "source as of <date>" and detect claims whose page has since changed.
- Join keys: the URL itself.
- Risks: about half of URLs unarchived in this small sample; Wayback was intermittently offline
  during this run ("Temporarily Offline", 504); rate-limit politely.

### apollo_dialysis_centres (priority 3)
- URL: https://www.apollodialysis.com/our_center-sitemap.xml (196 centre URLs); robots.txt allows
  centre pages (disallows /our-centres/page/ and query pagination). Terms page /terms-and-conditions/
  returned 404.
- Fields: centre name, town, district, state, phone, map link (Punganuru page shows "Apollo Dialysis
  Clinics, Punganuru, Chittoor District, Andhra Pradesh"). Many pages lack a street address or PIN.
- Roles: labels (dialysis). Join: name/town + district. Risk: weak location fields.

### dcdc_centres (priority 3)
- URL: https://dcdc.co.in/page-sitemap.xml (26 "dialysis-center-in-..." pages); robots.txt only
  disallows /wp-admin/. Example https://dcdc.co.in/dialysis-center-in-mahoba/ : "District Hospital,
  near roadways bus stand, Makaniya Purva, Mahoba, Uttar Pradesh 210427".
- Roles: labels (dialysis in public district hospitals, PPP). Join: host hospital + PIN.
- Risk: small; the main /dcdc-centres/ list renders by script and was not parsed.

### aarthi_scans_branches (priority 3)
- URL: https://aarthiscan.com/branch-sitemap.xml (169 branch URLs, e.g.
  https://aarthiscan.com/branches/chennai/west-mambalam/); robots.txt disallows only /wp-admin/.
- Fields: address with PIN, phone, hours, "Available Scans and Tests" list per branch.
- Roles: labels (MRI/CT availability), evidence. Join: address + PIN. Risk: stand-alone imaging
  centres rarely match our hospital rows; modality list per branch not verified to include MRI.

### kerala_kasp_empanelled (priority 3)
- URL: https://sha.kerala.gov.in/?page_id=1084 (district table) linking to per-district public and
  private pages, e.g. https://sha.kerala.gov.in/?page_id=470&lang=en (Thiruvananthapuram private,
  24 rows). Reachable from here.
- Fields: Hospital name, Contact Number, Address with PIN, Email. No specialty column seen.
- Roles: labels (empanelment only), evidence. Join: name + PIN. Risk: no specialties; emails and
  phones to drop.

### indicxlit (priority 3)
- URL: https://github.com/AI4Bharat/IndicXlit ; models
  https://github.com/AI4Bharat/IndicXlit/releases/download/v1.0/indicxlit-en-indic-v1.0.zip
  (126,832,968 bytes) and indicxlit-indic-en-v1.0.zip (124,533,637 bytes); PyPI
  ai4bharat-transliteration 1.1.3 (MIT). README: "The IndicXlit code (and models) are released under
  the MIT License." About 11M parameters, 21 languages, trained on Aksharantar (26M word pairs).
- Roles: nlp_model, geo. Turn Devanagari or other-script input into romanized candidates (and the
  reverse) before fuzzy matching against LGD/Census names.
- Risks: depends on fairseq (old, hard to install on current Python, not tested); last push
  2023-10-13. Lighter fallback: indic-transliteration 2.3.82 (MIT, rule-based script conversion).

### osm_name_variants (priority 3)
- Source: the OSM India extract already listed; taginfo (https://taginfo.openstreetmap.org/api/4/key/stats)
  global counts: name:hi 84,150 objects (52,051 nodes), name:kn 103,988, name:ml 51,889, name:ta 41,287,
  name:te 32,398, name:bn 27,978, name:mr 27,150, name:pa 34,519, name:gu 6,269, name:or 3,771.
  India-only counts not obtained (Overpass returned 502 from both public instances).
- Roles: geo. Licence ODbL.

### nnf_fellowship_centres (priority 3)
- Portal page seen: https://www.nnfi.org/nff-database.php ("NNF Trainee Fellowship Program centers
  list") linking https://nnfi.org/assests/upload/database-pdf/NNF-trainee-fellowship-program-centers-list-06072026.pdf
- Not downloaded: https://www.nnfi.org/robots.txt has "Disallow: /assests/upload/". Ask NNF or fetch
  manually after checking terms. The accreditation programme itself (Level II-B, III-A, III-B forms
  on https://www.nnfi.org/download-form.php) publishes no list of accredited units.
- Roles: labels (NICU). Risk: training centres, not an accreditation roster; contents unverified.

### mahajan_imaging_locations (priority 4)
- https://www.mahajanimaging.com/sitemap.xml: 267 URLs, 15 under /location/ (Delhi NCR).
  robots.txt allows all. Pages show a site-wide modality menu (3T MRI, 1.5T MRI, CT), not per centre.

### wikidata_india_villages (priority 4)
- SPARQL: 154,328 items with P31 Q56436498 (village in India); 32,609 have a Hindi label. Property
  P6425 is "LGD local body code". CC0. Adds Hindi spellings for a fifth of villages; GeoNames and LGD
  remain the main sources.

### delhi_dlsa_burn_hospitals (priority 4)
- https://cdnbbsr.s3waas.gov.in/s395b7a6d9a47c56ff9118bb45379fc884/uploads/2026/02/20260225331095626.pdf
  "Database of all Government or Private Hospitals having Specialized Facilities for treatment of
  Burn Victims", 1 page, 13 Delhi hospitals by DLSA district, name and address with PIN; created
  2026-02-25. Labels for burn care in Delhi only.

## Searched but not found
- NNF list of accredited Level II/III NICUs: no public roster on nnfi.org; press releases name single
  hospitals (Kasturba Manipal III-B 2024, New Era Nagpur III-A 2024).
- CSI National Interventional Council cath-lab registry hospital list: annual reports give totals
  only (705 centres in 2017, PMC6620470, CC BY-NC-ND); no centre names.
- STEMI India / state STEMI hub lists: no official list; Karnataka hubs only in news articles.
- National Academy of Burns India burn unit directory: nabi.org.in and similar hosts did not resolve.
- MoRTH Cashless Treatment scheme 2025, now PM-RAHAT (renamed Feb 2026 per NHA): no designated
  hospital list found; AB PM-JAY hospitals are deemed empanelled, so the PM-JAY mirror is the proxy.
- NHAI ambulance and trauma centre location lists: a Lok Sabha reply says the list is on the NHAI
  website; not found.
- 108/102 ambulance base locations: Punjab PHSC page (phsc.punjab.gov.in/en/emergency) unreachable;
  Uttarakhand NHM PDF 404; Odisha NHM PDF no response.
- Live state scheme portals unreachable from here: drysraarogyasri.ap.gov.in, ysraarogyasri.ap.gov.in,
  aarogyasri.telangana.gov.in, arogya.karnataka.gov.in, sast.karnataka.gov.in, chiranjeevi and maa
  .rajasthan.gov.in, magujarat.com, sachisup.in, bssa.bihar.gov.in, shsbihar.gov.in,
  gramawardsachivalayam.ap.gov.in, notto.mohfw.gov.in, phsc.punjab.gov.in, davita.in (403),
  vijayadiagnostic.com (403).
- GitHub or Kaggle mirrors of AP YSR Aarogyasri, Karnataka SAST/AB-ArK, Rajasthan MAA/Chiranjeevi,
  Bihar or UP SHA lists: none found (an MP PM-JAY CSV exists in
  rayeenzaki744-spec/ayushman-bharat-healthcare-analytics, not inspected).
- Wayback copies of HFR/NHRR search results, hem.nha.gov.in, hospitals.pmjay.gov.in lists and
  data.gov.in facility-level COVID bed CSVs: none (the TN data.gov.in COVID bed resource is 1.1 KB
  district-level).
- India-only OSM counts of place nodes with name:hi: Overpass unavailable (502).
