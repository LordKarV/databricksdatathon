# Service-specific authoritative lists: candidates

Date of search: 2026-11-21. Every count below comes from a page or PDF I opened, or from code I ran
(pdftotext row counts, one duckdb query on our facilities file). Anything marked "unverified" I
could not open from this machine.

## Access finding that affects everything below

Many Indian government hosts refuse TCP connections from this machine (non-Indian egress IP), both
for curl and WebFetch: data.gov.in, hospitals.pmjay.gov.in, notto.mohfw.gov.in, main.mohfw.gov.in,
hmis.mohfw.gov.in, cdsco.gov.in, eparlib.nic.in / eparlib.sansad.in, nhmodisha.gov.in,
jeevandayee.gov.in; pib.gov.in and mohfw.gov.in return 403. Reachable: qps.nhsrcindia.org,
nhsrcindia.org, eraktkosh.mohfw.gov.in, ncgindia.org, nhm.gov.in, dghs.mohfw.gov.in,
aikosh.indiaai.gov.in, naco.mohfw.gov.in. The Wayback Machine (curl, not WebFetch) has copies of
some blocked PDFs. Plan: fetch blocked sources from an Indian network or via Wayback, then upload to
a UC volume (Databricks Free Edition cannot reach these sites either).

## Context from our own data (code run)

Of 10,088 facility rows, operatorTypeId is "private" for 8,842 and "public" for 469; only 444
names match public-facility patterns (district hospital, CHC, civil hospital, GMC, etc.). Most
government programme lists below (LaQshya, MusQan, SNCU, PMNDP, Kayakalp, trauma, burn) name public
facilities, so they will match a few hundred of our rows at most. Lists that include private
facilities (blood centres, NCG, NOTTO, PM-JAY) matter more for join coverage. Text mentions in our
data (regex over name/specialties/procedure/equipment/capability/description): dialysis 1,050;
NICU/SNCU 724; caesarean 441; blood bank 567; trauma 1,808; cath lab/angioplasty 625; MRI 946;
CT scan 1,358; transplant 1,277; cancer/oncology 2,838.

## Candidates (priority 1 = must have)

### 1. eraktkosh_blood_centres (priority 1)
- Name: e-RaktKosh nearest blood bank / blood storage unit finder
- Publisher: MoHFW, built by C-DAC
- URL: https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/nearbyBBRed.cnt ; JSON used by the page:
  https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/nearbyBB.cnt?hmode=GETNEARBYBLOODBANK&stateCode=<LGD>&districtCode=-1&lang=0
- Access: public, no login. I made one call (Goa, stateCode=30): 6 rows, HTTP 200, 2,857 bytes.
  Also a lat/long mode (`&latitude=`) that returns distance. robots.txt returns 404 (none).
- Format: JSON `{"data": [[sno, name, address, phone, email, category, -, links-html, type]]}`;
  type is "Blood Bank" or "BSU"; category "Govt." etc.; links embed `hospitalCode`, `distId`, `stateId`.
- Size: about 36 state calls; national total not run. Licensed blood centres were 3,908 as of
  30 June 2022 per the data.gov.in title (not opened).
- Licence/terms: terms page text: "Though all efforts have been made to ensure the accuracy and
  currency of the content on this website, the same should not be construed as a statement of law
  or used for any legal purposes." No reuse licence found. Unverified.
- Last update: live system; stock pages update in real time.
- Coverage: all India, public and private blood centres and storage units.
- Key fields: name, address (with district), category, type, hospitalCode, district/state codes.
- Roles: evidence, labels, routing
- How it helps: definitive "blood available here" evidence for emergency C-section, trauma and
  burns. A FRU without a blood bank/BSU is weak for CEmONC. Positive labels for a "blood bank"
  capability classifier, including private hospitals.
- Join keys: name + district (address text); no coordinates in the state-mode response, PIN only
  inside free-text address. hospitalCode is a stable ID.
- Risks: phone/email include personal mobiles: do not store them. Undocumented endpoint: keep
  to 1 req/s and a one-off pull. No explicit licence.

### 2. laqshya_master (priority 1)
- Name: LaQshya certification status master data (labour room and maternity OT)
- Publisher: NHSRC Quality and Patient Safety division, MoHFW
- URL: https://qps.nhsrcindia.org/laqshya/quality-Certification-Status ->
  https://qps.nhsrcindia.org/sites/default/files/2026-04/LaQshya_Master_data-08-04-2026.pdf
- Access: direct download via WebFetch (curl got 403, likely user-agent filtering).
- Format: PDF printed from an XLSX ("LaQshya_Master_data_final-8April.xlsx"), 70 pages, 998,821 bytes.
- Size: pdftotext shows serial numbers up to 2,173; 1,227 "Labour Room" and 901 "Maternity OT"
  rows parsed. NHSRC home page states 1,253 LR and 920 MOT certified.
- Licence/terms: none on page; site footer "Copyright 2021 ... NHSRC". Unverified reuse terms.
- Last update: file 08-04-2026; page says "Updated till- : 30-09-2026".
- Coverage: all states, district-level, public DH/SDH/CHC/MC.
- Key fields: State, District, Type of Facility, Name of Facility, Department (LR/MOT),
  Certified/Conditional, Date of Result, Validity Date.
- Roles: evidence, labels
- How it helps: a certified Maternity OT is strong, dated evidence of C-section capability
  (high-risk delivery use case). Validity date lets us show "certification expired" as uncertainty.
- Join keys: facility name + district + state (fuzzy; names like "SDH Area Hospital Gudur").
- Risks: PDF table parsing (columns wrap); expired certifications still listed; public only.

### 3. musqan_master (priority 2)
- Name: MusQan certification status (child-friendly services incl. SNCU/NBSU, paediatric ward)
- Publisher: NHSRC
- URL: https://qps.nhsrcindia.org/musqan-certification-status-0 ->
  https://qps.nhsrcindia.org/sites/default/files/2026-04/Musqan-8April.pdf
- Access: direct download (WebFetch). Format: PDF from XLSX, 8 pages, about 280 KB.
- Size: about 231 rows (pdftotext count). "Updated As on: 08-04-2026".
- Licence/terms: none stated.
- Coverage: all India but sparse (Telangana, UP, Chhattisgarh, AP heavy).
- Key fields: State, District, Category (DH/CHC/MC), Facility Name, Certified/Conditional,
  Date of Certification, Validity till.
- Roles: evidence, labels
- How it helps: certified newborn/paediatric care quality; secondary NICU evidence.
- Join keys: name + district + state.
- Risks: small; certifies child services generally, not specifically SNCU.

### 4. nqas_certified (priority 2)
- Name: NQAS national level certification list
- Publisher: NHSRC
- URL: https://qps.nhsrcindia.org/quality-certification/national-level-certificate ;
  map report https://qps.nhsrcindia.org/nqas-map-report (timed out for me)
- Access: scrape (paginated HTML, 220 pages, 22,015 rows per the page). No file download seen.
- Fields: Sr No, Facility Name, Certified/Conditionality, Validity Till Date; state as section
  heading. No district or departments.
- Last update: "Updated till- : 30-09-2026".
- Roles: evidence (quality signal), other
- How it helps: a quality prior for public facilities, mostly SCs/PHCs. Weak for service routing.
- Join keys: name + state only (no district): poor.
- Risks: mostly sub-centres; ambiguous names ("Pennaperuru"). Low join value.

### 5. kayakalp_winners (priority 3)
- Name: List of Kayakalp winner facilities FY 2021-22
- Publisher: NHSRC / MoHFW
- URL: https://qps.nhsrcindia.org/kayakalp-swachh-swasth-sarvatra/quality-LOKWF ->
  https://qps.nhsrcindia.org/sites/default/files/2024-09/KAYAKALP%20WINNER%20FACILITIES%2021-22.pdf
- Access: direct download (WebFetch). PDF, 18 pages, about 770 KB, about 1,178 numbered rows.
  Archive link on page for older years.
- Fields: S.No, Incentive (Winner/Runner up/Eco-friendly), Type (DH, SDH/CHC, PHC), Name,
  District, State.
- Last update: FY 2021-22 list, uploaded 2024-09. Newer lists not published here (a June 2025
  D.O. letter asks states for FY 2024-25 lists).
- Roles: evidence (cleanliness/infection-control quality), other
- How it helps: tie-breaker quality signal; not service evidence.
- Join keys: name + district + state.
- Risks: 4+ years old; quality not capability.

### 6. mohfw_trauma_196 (priority 1)
- Name: List of 196 Trauma Care Facilities and funds allocated (NPPMTBI, Annexure-I)
- Publisher: MoHFW
- URL: https://main.mohfw.gov.in/sites/default/files/List%20of%20Trauma%20Care.pdf (blocked here);
  Wayback copy http://web.archive.org/web/20231215043518/https://main.mohfw.gov.in/sites/default/files/List%20of%20Trauma%20Care.pdf
- Access: blocked direct; via Wayback I fetched it (421,544 bytes, 5 pages, created 2023-02-08)
  into /Users/karthikvattem/projects/datathon/data/external/mohfw_trauma_list/source.pdf.
- Fields: S.No, State, Name of TCF, Amount allocated (Rs cr). No level column; the level can
  probably be inferred from the amount (9.63 vs 4.775 cr), but I have not checked this.
- Size: 192 numbered rows parsed (196 stated).
- Licence/terms: MoHFW site terms not readable from here. Unverified.
- Coverage: all states, highway-oriented public hospitals (DH, MC, taluk).
- Roles: evidence, labels, routing
- How it helps: the district-planner trauma use case: government-designated trauma facilities
  along highways. Level definitions (L-I MC >500 beds, L-II 300-500, L-III DH 100-200) are in the
  programme brief and the Dec 2025 Lok Sabha answer.
- Join keys: name + state (city/district in the name text).
- Risks: "supported" does not mean functional; funds allocated, many may be incomplete. Newer
  Lok Sabha Q2240 (12 Dec 2025, eparlib.sansad.in/bitstream/123456789/3017720/1/AU2240_qvZ1Ej.pdf)
  reportedly includes level per TCF but was unreachable (not archived).

### 7. nppmbi_burn_units (priority 2)
- Name: Medical colleges supported under NPPMBI (47, 12th FYP), Annexure-1 of the burn
  programme brief
- Publisher: MoHFW
- URL: https://mohfw.gov.in/sites/default/files/Prog%20brief%20Burn%20component.pdf (403 here);
  Wayback copy http://web.archive.org/web/20250124103152/https://mohfw.gov.in/sites/default/files/Prog%20brief%20Burn%20component.pdf
- Access: via Wayback, fetched (482,220 bytes, 4 pages, created 2019-09-25) into
  /Users/karthikvattem/projects/datathon/data/external/nppmbi_burn_units/source.pdf.
- Fields: S.No, State, District, Name of the Medical College.
- Size: 47 rows. DGHS page (https://dghs.mohfw.gov.in/national-burn.php, updated 21/11/2024)
  confirms "47 Government Medical College Hospitals".
- Roles: evidence, labels
- How it helps: the only national list of designated tertiary burn units (burn care use case).
- Join keys: college name + district + state.
- Risks: 2019 document; "sanctioned" not "functional"; district-hospital burn units under NHM are
  not listed here.

### 8. ncg_members (priority 2)
- Name: National Cancer Grid member institutions
- Publisher: National Cancer Grid (Tata Memorial Centre)
- URL: https://www.ncgindia.org/hospitals-and-institutions/members
- Access: scrape; members load dynamically (filters by country, state, category: Cancer Centres /
  Units, Research Institutions, NGOs, Professional Societies). No download.
- Size: 310 members (Lok Sabha answer, Dec 2023, via search snippet); page count not verified.
- Licence/terms: "(c) 2026 The National Cancer Grid (NCG). All rights reserved." Ask before reuse.
- Roles: evidence, labels
- How it helps: cancer care routing; private and public centres.
- Join keys: name + city + state.
- Risks: membership is not a capability audit; dynamic page needs browser rendering.

### 9. pmndp_state_counts (priority 3) and state PMNDP lists (priority 2 where they exist)
- Name: PMNDP data table (state counts) and state PMNDP centre lists
- Publisher: NHSRC / MoHFW; state NHMs
- URLs: https://www.nhsrcindia.org/pmndp-map-table ; example state list
  https://nhm.goa.gov.in/wp-content/uploads/2020/07/PMNDP-List-of-centres.pdf
- National table: 36 rows; columns States/UTs, Total districts, Functional districts, Functional
  dialysis centres, PPP/In-house. Sum of centres = 1,994 (my sum of the 36 rows). No facility names.
  "Page last updated on:" blank.
- Goa list: 3-page PDF, "Status as on : 29/06/2020"; fields district, centre name, address with
  PIN, email, phone.
- Patient portal https://pmndp.mohfw.gov.in has a centre search inside the app for registered
  (ABHA) patients only: do not use.
- Roles: need (state supply counts), evidence and labels (state lists)
- How it helps: state counts give a sanity check of our dialysis coverage per state; state lists
  are strong labels for public dialysis (e.g. a DH in Bihar).
- Join keys: state (table); name + district + PIN (state lists).
- Risks: no national facility list exists publicly that I found; state lists are scattered and
  dated; PDFs carry staff phone numbers: drop them.

### 10. naco_art_centres (priority 4)
- Name: ART centre facilities list
- Publisher: NACO, MoHFW
- URL: https://naco.mohfw.gov.in/wp-content/uploads/2024/06/ART-CENTRE-FACILITIES.pdf
  (sister file ICTC-CENTRE-FACILITIES.pdf)
- Access: direct download. PDF, 56 pages, about 990 KB, created 2024-06-27.
- Fields: State, District, Facility Name. Row count not verified (text-line count was ambiguous).
- Roles: evidence, other
- How it helps: out of our named services, but it is a clean national State/District/Facility
  list, useful as a public-facility gazetteer for name/district matching.
- Risks: facility name field mixes codes ("AP_Ananthapur_..._ART-AP-APR-01").

### 11. aikosh_blood_bank_directory (priority 2)
- Name: Blood Bank Directory (updated till last month), mirrored from data.gov.in
- Publisher: NIHFW, hosted on AIKosh (IndiaAI)
- URL: https://aikosh.indiaai.gov.in/home/datasets/details/blood_bank_directory_updated_till_last_month.html
  (original https://data.gov.in/resources/blood-bank-directory-updated-till-last-month, blocked here)
- Access: Download button on AIKosh; whether login is needed is unverified. File size shown as "0".
- Licence: "GODL license" (Government Open Data License India). OSM import wiki quotes data.gov.in
  terms as "Public Domain with attribution".
- Last update: AIKosh "updated 11 Aug 2026", but date field "10/08/17"; OSM wiki says published
  10 Aug 2017. Treat as a 2017 snapshot.
- Fields: address, geo location, contact details, PIN, email, website (per description).
  OSM imported 2,259 blood banks from it. A forum user reports about 82 missing lat/long and some
  points plotted in Africa.
- Roles: evidence, geo
- How it helps: coordinates and PIN for blood banks; cross-check against e-RaktKosh.
- Join keys: name + PIN + coordinates.
- Risks: stale (2017); bad coordinates; unverified download.

### 12. pmjay_hem_hospitals (priority 1 if obtainable; access unverified)
- Name: AB PM-JAY empanelled hospitals (Hospital Empanelment Module), with specialties
- Publisher: National Health Authority
- URL: https://hospitals.pmjay.gov.in/ (connection refused from here; Wayback has only 2019 assets
  and a captcha endpoint `empanelApplicationForm.htm?actionVal=captchaCode`).
- Access: unavailable from this machine; per third-party guides the search filters by state,
  district, hospital type and specialty. Captcha likely: do not bypass. Some state SHAs publish
  district PDFs with empanelled specialties (e.g. Haryana, Agra district page
  https://agra.nic.in/document/list-of-empanelled-gov-pvt-hospitals-under-ayushman-bharat-pmjay-district-agra/),
  not opened.
- Size: 26,209 empanelled hospitals as of Nov 2022 (CAG report snippet).
- Roles: evidence, labels
- How it helps: specialty empanelment (cardiology, CTVS, nephrology, neonatology, burns, oncology)
  is a regulator-checked claim for private hospitals, which are 88% of our rows. This is the only
  candidate that could label most of our facilities.
- Risks: unverified access, captcha, possible terms against scraping. Needs an Indian network and a
  human to check the terms.

## Searched but not found or not usable

- National facility-level PMNDP dialysis centre list: only state counts (NHSRC) and scattered state
  PDFs. The PMNDP portal centre search is for registered patients only.
- National SNCU / NBSU / NICU facility list: none found. Parliamentary answers give counts (374,
  later 399 SNCUs); FBNC guidelines 2025 give coverage claims. State lists found by search
  (Uttarakhand nhm.uk.gov.in/files/SNCU.pdf, Tamil Nadu nhm.tn.gov.in SNCU_20.pdf) now return 404.
  The Bihar 2026 PDF is a scanned Hindi image (OCR needed). Maharashtra list not found.
- First Referral Unit / CEmONC / BEmONC facility lists: only state-level counts (NHM MIS,
  https://nhm.gov.in/MIS-NHM/2025-26/Sept-25/G4.pdf, not opened) and Lok Sabha annexures
  (blocked). LaQshya MOT is the best proxy.
- HMIS facility-wise C-section counts: hmis.mohfw.gov.in is blocked here; data.gov.in has only
  district-level HMIS. Some state NHMs publish facility-wise HMIS extracts (Assam). Unverified.
- NOTTO registered transplant hospitals: the approved-hospital page on notto.mohfw.gov.in is blocked
  and not archived. The NOTTO directory PDF of 26.08.2025 is a staff contact list, not hospitals;
  I deleted my copy because it holds personal contact data. Goa SOTTO page returns 403.
  TRANSTAN and ZTCC lists not found.
- Cardiac cath lab / STEMI hub lists: no public list. STEMI India and TN-STEMI papers give counts
  only (4 hubs and 35 spokes in the pilot). The MoHFW STEMI guideline is on a blocked host.
- Cardiac surgery centre lists: none outside PM-JAY / state insurance empanelment.
- MRI / CT availability lists: FDSI gives state-level mode counts only (NHSRC RFP July 2025: CT under
  PPP in 18 states, in-house in 14, hybrid in 2). No facility list. AERB eLORA has no public
  facility search that I could find (elora.aerb.gov.in unreachable). MRI is not regulated by AERB.
- Tertiary Care Cancer Centres / State Cancer Institutes (19 SCI + 20 TCCC per PIB Dec 2023):
  the annexure lists are in PIB / Lok Sabha pages that return 403 or refuse connections from here.
- CDSCO licensed blood centre names: CDSCO is blocked; national file is state counts only. Delhi
  (https://drugs.delhi.gov.in/hi/node/8231, list as on 12.11.2026) and Punjab SACS publish
  per-centre lists with licence numbers (not opened).
- Kayakalp lists newer than FY 2021-22: not published on the QPS page.
- Maharashtra MJPJAY empanelled hospitals PDF (jeevandayee.gov.in): host unreachable.
  Tamil Nadu CMCHIS high-end hospital list (cmchistn.com/highendHospital.php): content dynamic,
  not readable.
