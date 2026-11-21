# PMNDP state counts and state centre lists

Pradhan Mantri National Dialysis Programme (PMNDP) supply data: state-level counts of functional public
dialysis centres for all 36 states/UTs, plus one state facility list (Goa, 8 centres, 2020). Fetched
2026-11-21.

## Sources

| File | URL | What it holds |
|---|---|---|
| map_table.html | https://www.nhsrcindia.org/pmndp-map-table | NHSRC table, 36 rows: state, total districts, districts with functional dialysis, functional centres, PPP/in-house. No date on the page. |
| js/settings.js | https://pmndp.mohfw.gov.in/themes/rvs/js/settings.js | Map data of the MoHFW PMNDP portal (https://pmndp.mohfw.gov.in/en): same counts plus aspirational districts and functional machines. Home page says "Statewise Status of PMNDP (As on 31st October 2026)". |
| goa_pmndp_centres_2020.csv | https://nhm.goa.gov.in/wp-content/uploads/2020/07/PMNDP-List-of-centres.pdf | Goa NHM list of operational haemodialysis centres, "Status as on : 29/06/2020", 3 pages. Transcribed by hand into parse.py (district, centre, address, PIN); contact columns dropped. |

Other state lists looked for and not obtained: Odisha NHM page https://nhmodisha.gov.in/pmndp_centers_odisha/
(connection refused / timed out from here and from WebFetch); Karnataka 2020 list only on SlideShare and
Scribd (third-party, not fetched); Vikaspedia state-wise page is rendered by JavaScript (no links in the HTML);
a Bihar "dialysis units" PDF on state.bihar.gov.in turned out to be a 2010 PPP proposal and was discarded.
There is no national facility-level list. The PMNDP portal has a State > District > Facility dropdown in its
grievance form (Drupal AJAX); it was not scraped, because it is a form endpoint and the site's WAF already
tagged our plain GET requests with `_event_attackname=Evasion`.

## Licence and terms (quoted)

- NHSRC copyright policy (https://www.nhsrcindia.org/copyright-policy): "Material featured on this site may be
  reproduced free of charge in any format or media without requiring specific permission. This is subject to
  the material being reproduced accurately and not being used in a derogatory manner or in a misleading
  context. Where the material is being published or issued to others, the source must be prominently
  acknowledged."
- PMNDP portal copyright policy (https://pmndp.mohfw.gov.in/node/139): "This contents of this Portal may not be
  reproduced partially or fully, without due permission from MoHFW, Govt. of India. If referred to as a part of
  another publication, the source must be appropriately acknowledged."
- Goa NHM: the copyright policy page (https://nhm.goa.gov.in/copyright-policy/) has no policy text. Its footer
  reads "Copyright (c) Rummy Game - Yono Apk - 2026" and carries gambling spam links, so the site appears
  compromised. Treat the Goa PDF as untrusted; it was only text-extracted with pdftotext and then deleted.

Verdict: the NHSRC table may be redistributed in the private team repo and shown in a public demo with
attribution ("Source: NHSRC, PMNDP data, nhsrcindia.org"). The PMNDP portal numbers must not be reproduced
without MoHFW permission; use them only as an internal cross-check (they agree with NHSRC exactly on centres
and districts). The 8 Goa rows are facts (facility names and addresses) from a government notice with no
stated licence; citing them with the URL in the demo is low risk, but this is a judgment, not a stated grant.

## Fetch and rebuild

```sh
sh fetch.sh            # ~10 polite GETs, 1 s apart, into data/external/pmndp_counts_and_state_lists/
PY=/Users/karthikvattem/projects/datathon/.venv/bin/python
DATA=/Users/karthikvattem/projects/datathon/data/external/pmndp_counts_and_state_lists
$PY -I parse.py $DATA
$PY -I join_test.py data/raw/facilities.parquet data/raw/india_post_pincode_directory.parquet $DATA
```

fetch.sh deletes the Goa PDF and the portal home page after extracting what is needed: the PDF lists staff
names, e-mails and mobile numbers, and the home page embeds the requester IP. Only the PIN codes from the PDF
(state_lists/goa_pins.txt) are kept; parse.py asserts they equal the transcribed PINs.

## Inspection

- pmndp_state_counts.csv: 36 rows, 12 columns, 0 nulls after the state-name alias fixes.
- NHSRC centres sum to 1,994 and districts to 751; PMNDP portal: 1,994 centres, 751 districts, 14,281 machines.
  Every state's centre and district counts agree between the two sources. Operation mode wording differs in
  10 states (for example NHSRC "In-house" vs portal "In-house & PPP" for Maharashtra and Karnataka).
- Functional districts equal total districts in all 36 states. A web-search snippet of a Rajya Sabha answer
  (https://rsdebate.nic.in/bitstream/123456789/757935/1/PQ_267_04022025_U291_p523_p524.pdf, PDF not opened, so
  unverified) says 748 districts as on 31 Dec 2024 "(49 Linked to nearby districts)". If so, "functional"
  includes districts served by a centre in a neighbouring district; do not read it as "every district has a
  centre".
- Centres per district range 0.45 to 9.0 (median 1.58). Jharkhand 24 centres / 24 districts, UP 76 / 75.
- Freshness: NHSRC page has no date; the portal says as on 31 Oct 2026. Goa list is 29 Jun 2020 and has 8
  centres versus 18 for Goa in the current table, so it is stale.
- Obvious errors: NHSRC spells "A&N lsland"; Goa list gives CHC Valpoi the same PIN as PHC Balli (403703),
  while Valpoi is usually 403506; CHC Canacona is given 403709 (not checked further).
- Also found: India Post directory rows sometimes have latitude and longitude swapped (for example PIN 403709
  "Macazana B.O" at 72.46, 14.68); join_test.py drops rows outside India's bounding box before PIN centroids.

## Join test results (join_test_output.txt)

State join: 9,658 / 10,088 VF rows (95.7%) have a state string that maps to one of the 36 PMNDP states (the
rest have a city, junk or null in address_stateOrRegion). 34 / 36 PMNDP states have at least one VF row
(Ladakh and Lakshadweep have none).

Supply sanity check (join_state_supply.csv): VF has 2,383 facilities whose specialties, procedure, equipment,
capability or description mention dialysis/haemodialysis/nephrology, but only 169 of them are public, against
1,994 PMNDP public centres. In no state does the VF public dialysis count reach the PMNDP count (Bihar 7 vs 94,
UP 7 vs 76, Gujarat 7 vs 284). Correlation of PMNDP centres with VF dialysis claims across states is 0.77.
So VF misses most public dialysis capacity; PMNDP is the only source here that says it exists.

Goa list, name + PIN match (rapidfuzz token_set_ratio >= 85 on names with CHC/PHC/SDH expanded, and same
PIN or within 10 km of the PIN centroid), candidates = 35 VF rows in Goa or with PIN 403xxx:
matched 1 / 8.

| PMNDP centre | Best VF candidate | Score | km | Result | Hand check |
|---|---|---|---|---|---|
| Hospicio Hospital, 403601 | Pai Hospital | 80 | 20.0 | no match | correct: no Hospicio in VF |
| CHC Canacona, 403709 | Primary Health Centre Sanguem | 62 | 37.1 | no match | correct |
| PHC Navelim, 403707 | Primary Health Centre Sanguem | 86 | 36.6 | no match (distance) | correct: different PHC |
| PHC Balli, 403703 | Primary Health Centre Sanguem | 88 | 21.3 | no match (distance) | correct: different PHC |
| SDH Ponda, 403401 | Pai Hospital | 80 | 18.7 | no match | correct: no Ponda SDH in VF |
| District Hospital Mapusa, 403507 | Pai Hospital | 80 | 21.1 | no match | correct: only a Mapusa dental clinic in VF |
| CHC Valpoi, 403703 | Primary Health Centre Sanguem | 62 | 21.3 | no match | correct |
| Goa Medical College, 403202 | Goa Medical College (dda3e7e4) | 100 | 0.0 | match | correct; VF claims dialysis: yes |

Precision 1/1, recall 1/8 (the 7 misses were confirmed absent by substring search of all 10,088 names). The PIN
or distance gate is what blocks the two PHC false positives. Twenty hand-checked matches were not possible:
the only list fetched has 8 rows.

Label proxy (district_hospital_candidates.csv): since PMNDP covers every district, a public district-level
hospital is a likely PMNDP site. 75 VF rows have a public operator and a name like district/civil/sadar/general
hospital; 32 claim dialysis, 43 are silent. Hand check of 20 random rows (seed 0, names judged by me, not
against an official list): 15 look like district headquarters hospitals (Civil Hospital Panipat, DH Pulwama,
DH Satara, Civil Hospital Amritsar, Civil Hospital Williamnagar, GGH Wanaparthy, Civil Hospital Nadiad,
Kalimpong DH, DH Rewa, Asansol DH, DH Nashik, DH Samba, Champhai DH, Goalpara Civil Hospital, GGH Alwar);
5 are not or are doubtful (Osmania General Hospital is a tertiary teaching hospital; SDH Karad is sub-district;
Habra and Gabberia State General Hospitals are sub-divisional; "Civil Hospital, Nashik" is likely a duplicate of
DH Nashik). Precision about 15/20. The full list also contains blood banks ("District Hospital Blood Bank"),
which must be filtered before use.

## Product role

- Need/supply context: state public dialysis supply (centres, machines, centres per district) for the
  explanation panel ("Bihar has 94 PMNDP centres across 38 districts; free for BPL patients").
- Evidence: a public district hospital in a state where PMNDP is functional gets a "likely offers free
  haemodialysis under PMNDP (state-level programme evidence, not facility-confirmed)" flag, shown as
  medium/low confidence, never as fact.
- Labels: weak positives only (Goa Medical College; district hospitals). Too few facility-level rows to train.

## Ingest plan (Databricks Free Edition)

Upload pmndp_state_counts.csv (NHSRC columns only, drop portal_* before any public demo) and
goa_pmndp_centres_2020.csv to a Unity Catalog volume, e.g. /Volumes/<catalog>/external/raw/pmndp/, then
CREATE TABLE <catalog>.external.pmndp_state_counts and <catalog>.external.pmndp_facility_list AS SELECT from
read_files. Join on a normalised state key (reuse norm_state from parse.py) to the facility table. Refresh:
manual, re-run fetch.sh off-platform quarterly (outbound internet from Databricks is restricted). App screens:
recommendation detail (programme evidence line and citation) and the planner/state view (supply vs need,
with NFHS). Effort: about 3 hours (upload, two tables, state-key join, flag logic and UI text).
