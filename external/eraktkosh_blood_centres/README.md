# e-RaktKosh blood centres

National directory of licensed blood banks (BB) and blood storage units (BSU) from e-RaktKosh, the MoHFW blood centre management system built by C-DAC. Pulled on 2026-11-21 from the JSON endpoints behind the public "Blood Center Directory" pages. We use it as outside evidence that a facility has blood on site, which matters for emergency C-section, trauma and burns.

## Source

- Publisher: Ministry of Health and Family Welfare (National Health Mission Blood Cell), built and run by C-DAC Noida.
- Portal: https://eraktkosh.mohfw.gov.in/eraktkoshPortal/ (React app). The legacy pages live under https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/.
- Endpoints used (all undocumented public GETs that the portal's own pages call):
  - State list: `https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/nearbyBB.cnt?hmode=GETNEARBYBLOODBANK&stateCode={code}&districtCode=-1&lang=0`. Each row is `[sno, name, address, phone, email, category, "-", links html, type]`. The links html carries `hospitalCode`, `distId` and `stateId`.
  - District names: `https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/nearbyBB.cnt?hmode=GETDISTRICTLIST&selectedStateCode={code}`.
  - Coordinates: `https://eraktkosh.mohfw.gov.in/eraktkoshPortal/eraktkosh/bloodbank/nearest?latitude={lat}&longitude={lon}&radius=100000`. The endpoint name was found in the portal bundle `main.4212cda9.js`. It returns latitude, longitude, hospitalType, type, distId and stateCode for each centre. This is the only place coordinates appear.
- State codes: Census 2011 codes 10 to 37 work directly (Goa = 30). Codes 1 to 9 return nothing; the portal stores them as 90 + code (Uttar Pradesh = 99, J&K = 91, Delhi = 97). DNH and Daman & Diu sit under 25 and Ladakh under 37. Codes 26, 38 and 90 return 0 rows.
- robots.txt: https://eraktkosh.mohfw.gov.in/robots.txt returns 404, so the site publishes no crawl rules. All calls ran one at a time with at least 1.1 s between them.

## Licence and terms

I found no reuse licence for the directory. The Terms & Conditions page (https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/termsAndConditions.cnt, read 2026-11-21) says:

> "The blood stock availability, camp schedule, nearby blood bank services are provided based on information received from blood banks. The documents and information displayed in this website are for reference purposes only and do not purport to a legal document. Though all efforts have been made to ensure the accuracy and currency of the content on this website, the same should not be construed as a statement of law or used for any legal purposes. In case of any ambiguity or doubts, users are advised to verify / check with the Department(s) and / or other source(s), and to obtain appropriate professional advice before use of information."

> "Under no circumstances will this Ministry/Department be liable for any expense, loss or damage ... arising from use, or loss of use, of data, arising out of or in connection with the use of this website."

The terms neither grant nor forbid reuse. What that means for us:
- Private team repo: commit the scripts. Keep the data out of git (it is already under the gitignored `data/external/`). Teammates can re-run `fetch.py`. Redistributing the bulk pull is not explicitly allowed.
- Public demo: showing one centre's name, type and category with a "source: e-RaktKosh" link back looks reasonable for public government information, but this is unverified. Do not publish the bulk table. Show the disclaimer ("for reference only, verify with the blood centre").
- A licensed alternative exists: NIHFW's "Blood Bank Directory (updated till last month)" is listed under GODL on AIKosh (https://aikosh.indiaai.gov.in/home/datasets/details/blood_bank_directory_updated_till_last_month.html). It is not fetched or checked here, and its vintage may be 2017.

Personal data: phones and emails are dropped in code before anything is written to disk. Many of them are staff mobiles.

## Fetch steps

```
P=/Users/karthikvattem/projects/datathon/.venv/bin/python
D=/Users/karthikvattem/projects/datathon/data/external/eraktkosh_blood_centres
PIN=/Users/karthikvattem/projects/datathon/data/raw/india_post_pincode_directory.parquet
$P -I fetch.py $D $PIN all              # states 1..38 and 90..99, then the coordinate grid
$P -I fetch.py $D $PIN states 91,99     # re-pull and merge only some states
$P -I fetch.py $D $PIN coords           # resume the grid (checkpoint in nearest_progress.json)
$P -I join.py $D /Users/karthikvattem/projects/datathon/data/raw/facilities.parquet \
   /Users/karthikvattem/projects/datathon/cleaning/geo_identity/facility_location.parquet
```

The coordinate pass queries `/nearest` at the 492 one-degree grid cells that contain an India Post office. The state pass makes about 100 calls; the coordinate pass makes 492 at 2 to 5 s each, about 35 minutes. On 2026-11-21 some calls timed out and succeeded on retry. No call failed after retries.

Outputs, in `data/external/eraktkosh_blood_centres/` (6.6 MB in total, gitignored):
- `state_mode_rows.parquet` has 6,342 rows. `districts.parquet` has the distId to name map. `nearest_coords.parquet` has 5,262 centres with coordinates.
- `erk_centres.parquet` has 6,904 centres: the 6,342 state-list rows plus 562 centres that only `/nearest` returned (`source = nearest_only`).
- `erk_vf_matches.parquet` and `join_stats.json` hold the join results.
- `raw/terms.html` and `raw/portal_main.js` are kept as evidence for the terms quote and the endpoint names.

## Inspection

All numbers come from `join_stats.json`, produced by `join.py`.
- 6,904 centres across 36 state codes: 5,135 Blood Bank and 1,769 BSU. By category: Govt. 3,426, Private 1,796, Charitable/Vol 1,536, Red Cross 146.
- The task brief cites about 3,908 licensed centres nationally in 2022 (not verified here). The 5,135 BB count here is higher; it includes the 562 nearest-only rows, and some of those may be inactive or duplicates (unverified).
- Null rates: name, address, category and type 0%. hospitalCode 0.67% (46 state-list rows have no camp or stock links). distId 0.75%. Latitude 23.8% (1,642 centres never appeared in any `/nearest` answer).
- Coordinates: none fall outside the India bounding box, but 1,147 rows share a coordinate with another row. 32 sit exactly on India's geographic centroid (22.3511, 78.6677), which is a failed geocode. Many BSUs share a district-centroid point. Treat any coordinate shared by 3 or more centres as district-level only.
- Text quality: 113 names map to more than one hospitalCode. 305 BSU names are just "<place> (Bsu)" with no host hospital. Some names have typos ("Hosptial", "Collage": 6 rows). Category strings carry trailing spaces ("Red Cross "), which `join.py` strips.
- The `/nearest` radius is not enforced: a 100 km query returned a centre 147 km away.
- Freshness: live data as of 2026-11-21. Rows carry no update date. Blood stock is a separate live page per hospitalCode, not pulled here.

## Join test against the Virtue Foundation facilities

Matcher (`join.py`):
- VF side: cleaned locations from `cleaning/geo_identity/facility_location.parquet` (9,970 rows), joined on unique_id to the raw claim text.
- Location gate: both sides have coordinates and lie within 5 km plus the VF location radius (capped at 15 km). If the e-RaktKosh centre has no coordinates, the gate is the same district name plus the same state (the state is found by majority vote).
- Name gate: blood words (blood, bank, centre, BSU, storage, unit) are removed first. The two names must share a distinctive token, meaning one that is not generic ("hospital", "medical", "college"...), not a place name (district, city, old city names like Madras) and not a single letter. Neither side may carry extra distinctive tokens the other lacks; "Madras Egmore" vs "Madras ENT" is rejected. Shared tokens must make up at least half of the larger distinctive set, and rapidfuzz token_set_ratio must be at least 85.
- `selfcheck()` in `join.py` asserts the known false positives found while tuning: PSP vs Meenakshi Medical College, and "North Western Railway, Jaipur" vs a VF record named "Jaipur".

Results:
- 388 of 6,904 e-RaktKosh centres (5.6%) match a VF record: 342 through the distance gate and 46 through the district gate. Of these, 369 are blood banks and 19 are BSUs.
- The low rate is expected. Most centres are standalone or government blood banks and BSUs that VF does not list. Of the unmatched centres with coordinates, 2,239 have some VF record within 1 km. In a 30-row sample of those, the nearest VF record was a different facility in 28 rows. The 2 misses were "Health World Hospitals Bloodbank" vs "Healthworld Hospitals" (a joined word) and "Malda MCH" vs "Malda Medical College and Hospital" (an abbreviation).
- These matches give 365 distinct VF facilities with an outside blood-centre record:
  - 159 already claim a blood bank or transfusion service in VF text. That is outside corroboration.
  - 206 do not claim one. These are new positive labels and evidence the VF text misses.
- VF has 688 records whose text claims a blood bank, blood centre, blood storage or transfusion. Only 159 (23%) are confirmed by a name match. For 83 of the 688, no e-RaktKosh centre lies within 5 km; those claims are weak or unsupported.

Hand check: 20 random matches (random_state=7), listed with verdicts in `handcheck_sample.csv`. 16 are correct, 2 likely and 2 uncertain, so precision is 80% strict and 90% counting the likely ones. An earlier tuning run's sample had 2 clear errors in 20 (Noble Kaithal vs Noble Rohtak, and Bapuji Hospital vs Bapuji Dental College). Two of the correct matches show the VF city is wrong while e-RaktKosh has the right place: Nidaan Hospital (VF says Gurgaon, both sit at Sonipat) and North Western Railway Hospital (VF says Udaipur, the PIN is Ajmer).

| hospitalCode | e-RaktKosh name | VF name | km / gate | verdict |
|---|---|---|---|---|
| 280756 | Doaba Hospital Blood Centre | Doaba Hospital | 0.01 | correct |
| 284973 | Vgm Blood Centre | VGM Gastro Centre | 0.29 | likely |
| 96114 | DR JAI DEV MEMORIAL ROTARY AMBALA HOSPITAL | Dr. Jai Dev Memorial Rotary Ambala Hospital | 0.32 | correct |
| 18005 | Breach Candy Hospital Trust Blood Centre | Breach Candy Hospital, Mumbai, India | 0.03 | correct |
| 285341 | Trinity Hospital Melthum BSU | Trinity Hospital | district | correct |
| 283959 | Ganga Sewa Sadan Blood Centre | Ganga Sewa Sadan Hospital | 6.06 | correct |
| 12104 | Tomo Riba Institute of Health and Medical Science Hospital Naharlagun | Tomo Riba Institute of Health and Medical Sciences, Naharlagun | 0.08 | correct |
| 864 | Narhari Hospital | Narhari Hospital | district | correct |
| 91112 | Shri Maharaja Gulab Singh Hospital Blood Bank | Shri Maharaja Gulab Singh Hospital, GMC Jammu | 0.45 | correct |
| 11051 | Blood Centre, Alchemist Hospital (Panchkula) | Alchemist Hospital (VF city Gurgaon) | 0.01 | uncertain |
| 16085 | Mary Queens Mission Hospital | Mary Queens Mission Hospital | 0.00 | correct |
| 18136 | Gleneagles Hospital, Mumbai | Gleneagles Hospital | 0.13 | correct |
| 280569 | Sharda Narayan Hospital Blood Centre (Mau) | Sharda Narayan Sips Hospital (VF city Lucknow) | 1.57 | uncertain |
| 284877 | Shivay Blood Centre | Shivay Hospital | 0.26 | likely |
| 282776 | Blood Centre Fims | Fims Hospital | 5.09 | correct |
| 29143 | Usha Mullapudi Cardiac Centre Blood Centre | Usha Mullapudi Cardiac Centre | 0.00 | correct |
| 282774 | Nidaan Blood Centre | Nidaan Hospital | 3.87 | correct |
| 13004 | Shri Maharaja Hari Singh Hospital | Sri Maharaja Hari Singh Hospital | district | correct |
| 494 | Sanjiban Hospital | Sanjiban Hospital | 0.01 | correct |
| 18039 | Lilavati Hospital And Research Centre Blood Centre | Lilavati Hospital and Research Centre | 0.03 | correct |

## Product role

- Evidence: on a recommendation card, "Blood centre on site: listed in e-RaktKosh (Govt., Blood Bank, code 18039)" with a link to that centre's live stock page (`/BLDAHIMS/bloodbank/stockAvailability.cnt?...hospitalCode=`). This applies to C-section, trauma and burns. The VF claim sentence is cited next to it when one exists.
- Routing: "nearest licensed blood centre" distance for every candidate facility and for the user's location, including the 6,500 centres that are not VF facilities. A hospital with no blood centre within X km is a real risk for an obstetric haemorrhage and should be flagged, not hidden.
- Labels: 365 positive blood-capability labels, 206 of them absent from VF text, for a claim-verification or capability model. The 83 VF blood claims with no centre within 5 km become weak negatives, to review before use.
- Uncertainty: show "matched by name and distance (x km)" or "matched by district only". Mark coordinates shared by 3 or more centres as district-level. Never show a stock count we did not fetch live.

## Ingest plan for Databricks Free Edition

1. Run `fetch.py` and `join.py` locally, since Databricks compute cannot reach eraktkosh.mohfw.gov.in. Upload `erk_centres.parquet` and `erk_vf_matches.parquet` to a Unity Catalog volume, for example `/Volumes/workspace/external/eraktkosh/2026-11-21/`. Writing is a team step; nothing was written to the workspace in this task.
2. Create tables `workspace.external.eraktkosh_blood_centres` (6,904 rows, no phone or email) and `workspace.external.eraktkosh_vf_matches` (388 rows) with `CREATE TABLE ... AS SELECT * FROM read_files('/Volumes/...', format => 'parquet')`. Add `pulled_on`.
3. Refresh: re-run the pull manually before the demo, or monthly. There is no scheduled job, because outbound internet is restricted.
4. App screens: the facility detail card (blood evidence badge plus link), the results ranking (feature `has_blood_centre`, `km_to_nearest_blood_centre`), and the planner map layer (blood centres coloured by Govt/Private/Charitable).

Effort: about 4 hours. That covers upload and tables (1 h), wiring the badge and distance feature into the app (2 h), and adding the joined-word and abbreviation cases to the matcher plus a second hand check (1 h).

## Scripts

- `fetch.py`: polite, resumable pull. It drops phones and emails.
- `join.py`: inspection stats, matcher with `selfcheck()`, 20-row hand-check sample.
- `handcheck_sample.csv`: the 20 checked matches with verdicts.
