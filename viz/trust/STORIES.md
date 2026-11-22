# How wrong is the data?

Seven data stories about the Virtue Foundation facility records (10,088 raw rows, 9,959 usable records). Each
story has one primary chart (PNG at 2x and SVG), an alt-text sidecar (.txt) and the tidy CSV behind it, all in
`viz/trust/out/`, and one script in `viz/trust/`. Every number below was printed by those scripts on 2026-11-21,
except where a line says "read from" a file another pipeline wrote. Rates carry 95% Wilson intervals; where the
count is a census of the whole file the interval is under one point and is said so on the chart.

Reproduce everything (about 5 s):

```
/Users/karthikvattem/projects/datathon/.venv-viz/bin/python /Users/karthikvattem/projects/datathon/viz/trust/notebook.py
```

`notebook.py` is in Databricks notebook source format. Its first cell sets `REPO_ROOT` and `SOURCE` ("local"
parquet, or "uc" to read `<catalog>.<schema>.<table>`; tables not yet in Unity Catalog fall back to the local
parquet with a printed note). Its last cell asserts the headline numbers (1,232; 723 vs 821; 1,367; 348; 7,514).

Map rule: the only map (story 2) draws points and arrows on a plain background. No national, state or district
outline is drawn.

---

## 1. One record, two hospitals

Headline: 1,232 of 9,959 records (12.4%, 95% CI 11.7 to 13.0) contain a sentence that places a service or fact at
another named facility, and the share climbs from 1.5% (5 of 324) in records built from 1-2 web pages to 33.1%
(638 of 1,930) in records built from 30-50.

Charts:
- `out/s1_anatomy.png` (primary): every claim sentence of two records as a tile. The record "Aravind Eye Hospital",
  listed in Hyderabad, has postcode 110002 (Central Delhi), coordinates near Villupuram in Tamil Nadu (1,871 km from
  the postcode) and 151 sentences: 1 names Aravind, 5 name another facility or its town, 145 name nobody. Its 29
  service sentences (a 20-bed dialysis unit, CT and MRI, "Sushtruta Trauma Centre" (sic)) all name no facility,
  and so does the line "Is a government hospital under the Government of NCT of Delhi." "Wockhardt Hospital Nagpur" has a Mumbai postcode (400078),
  coordinates 2 km from it in Bhandup, and text about Wockhardt Mira Road, Fortis Mulund and Nair Hospital; its "3T
  MRI" (a 2-word sentence that names nobody) earns a strong MRI grade.
- `out/s1_who.png`: the 12.4% by state (20 states with 100+ records), facility type and number of source URLs.

Why it matters: a health worker who reads "dialysis unit of 20 beds" on an eye hospital's card will send a patient
on dialysis to the wrong building. For coordinators, the share does not depend much on region: states run from
4.5% (Uttarakhand) to 16.3% (Andhra Pradesh), and only those two plus Jharkhand have intervals that exclude the
national rate. What predicts it is how the record was built: hospitals 17.1% (962 of 5,611), clinics 6.8% (255 of
3,770), dentists 2.5% (12 of 488). For the model: the number of source URLs is a strong, cheap contamination
feature, and it should lower trust, never raise it as "more evidence".

Method: flag = at least one claim sentence with `context = direct` in `derived/v1/claims.parquet` (a named other
facility is where the thing happens). State from `derived/v1/facility_location.parquet` (`state_final`), type from
`audit/scale/scale_flags.parquet`, URL count from `audit/provenance/q1_records.parquet`. Script: `s1_merged.py`.

Caveats: the flag's sentence precision was about 20 of 30 on the audit's hand check, and it misses copied text
that names nobody (story 6), so 12.4% is neither an upper nor a lower bound; the audit's precision-adjusted
estimate is about 1,405 records (14%, REPORT.md finding 1). source_urls is capped at 50. Hospitals have more URLs
than clinics, and more URLs also means more sentences and more chances to name someone, so type and breadth are
not independent effects. The two anatomy records were chosen by hand because REPORT.md names them; they are
illustrations, not a sample.

## 2. The hospital that moved

Headline: 1,367 of 9,869 records (13.9%, CI 13.2 to 14.5) put their map pin more than 50 km from their own
postcode; when the record's own text says the facility is "located in" another district or state, the pin is far
off 52.9% of the time (723 of 1,367, CI 50.2 to 55.5) against 10.1% (821 of 8,165, CI 9.4 to 10.7). The
coordinates follow the contaminating facility.

Charts:
- `out/s2_map.png` (primary): 1,367 arrows from each record's postcode centre to its listed pin, coloured by
  whether its text says it is located elsewhere (726 on the cleaned distances). 128 pins land in a different state
  from the postcode (state of the nearest India Post office). Labelled: Gem Hospital, Bathinda (2,349 km), the
  Aravind record (1,871 km), Prasanthi Hospital, Bhimavaram (postcode 222321 in Uttar Pradesh, 1,416 km), SMS
  Hospital, Jaipur (895 km).
- `out/s2_distance.png`: distance bands (78.9% within 10 km; 996 records, 10.1%, at 100-500 km; 105 beyond 500
  km) and the 52.9% vs 10.1% comparison.

Why it matters: a distance on the slip is only as good as the pin. A worker told "5 km" can face 300 km. For
planners, district counts built from raw coordinates misplace about one facility in seven. For the model: "text
says located elsewhere" plus "pin far from postcode" together are the location feature; either alone is weaker.

Method: left panel and map from `derived/v1/facility_location.parquet` (`raw_coords_to_pin_km`, cleaned postcode
centres from `derived/v1/pin_gazetteer.parquet`). The comparison recomputes `audit/merge/verify/v_missed.py`:
raw coordinates against raw India Post postcode medians (`data/raw/india_post_pincode_directory.parquet`), with
"located elsewhere" = a quarantined sentence naming another state or district that says located / situated /
based in / address (`audit/merge/out/sentences_flagged.parquet`, `sentence_decisions.parquet`). It reproduces
723 / 1,367 and 821 / 8,165 exactly. Script: `s2_moved.py`.

Caveats: the two 1,367s are a coincidence (one counts far records, the other records that say "located
elsewhere"). The far count depends on postcode centres: about 69 to 72 of the audit's far records were centroid
errors (REPORT.md GEO-01). The 128 cross-state count uses the nearest post office and includes border cases
around Delhi; REPORT.md's figure, from a different method, is 67 of 1,407. A far pin is sometimes right and the
postcode wrong (hand check: coordinates right 14 of 40 in REPORT.md GEO-02).

## 3. Strong-looking evidence is mostly wording

Headline: under the first grader, 1,252 of 1,804 "strong" grades (69.4%, CI 67.2 to 71.5) passed their clinical
prerequisite check only because the claim sentence itself contained the prerequisite word (dialysis 345 of 355,
trauma 340 of 353, MRI 433 of 530). After the fix, 1,551 of 4,151 strong grades (37.4%, CI 35.9 to 38.8) still rest
only on a specialty tag or on claims of three words or fewer, such as "Dialysis" (40 grades) or "MRI scanner" (37).

Chart: `out/s3_wording.png`, two dot plots by service, before and after.

Why it matters: "strong" sounds like a staffed unit. For dialysis, 402 of 695 strong grades (58%) are a tag or a
phrase. A coordinator should read strong as "the listing says so clearly", not "confirmed". For the model: tag-only
and short-only are features that should cap a grade, and the per-service gap (trauma 4% vs dialysis 58%) says the
cap must be service-specific.

Method: left panel read from `audit/claims/verify/out/v_grades.json` (`prereq_circularity`, written by
`audit/claims/verify/v_grades.py`; not recomputed here). Right panel from `derived/v1/grades.parquet` (grader v2):
grade = strong, tag-only = `corr_tags_only`, short = every cited evidence sentence has 3 words or fewer. Script:
`s3_wording.py`.

Caveats: the two panels use different graders and different denominators (1,804 vs 4,151 strong), so the drop from
69% to 37% is not a like-for-like improvement. Short is not the same as false: "Hemodialysis" may be true. Whether
thin evidence is less often confirmed was not tested: the gold dev split has 18 strong pairs with a verdict (4 of 6
thin confirmed, 5 of 12 not thin), too few to say anything. The sealed test split was not touched.

## 4. One phone number, 432 records

Headline: one mobile number is attached to 432 facility records in 37 different state spellings and 167 cities,
and is the "official" phone of 87 of them; 385 of those records cite proptiger.com, a property-listing site. In all
1,014 of 9,959 records (10.2%) carry a number shared across 3 or more cities, and 348 of 9,459 official phones
(3.7%) are such numbers.

Chart: `out/s4_phones.png`, the 12 most-shared numbers (partly masked), split into official phone vs listed only,
with the source domain most over-represented among the holders (proptiger.com for the top three, then skedoc.com,
vinsfertility.com, bajajfinservhealth.in, hexahealth.com).

Why it matters: the call is the product's safety net ("call before you leave"). A health worker who calls the
official number of 87 hospitals reaches the same line, which is not the hospital. For the model and the app: a
number held in 3+ cities is a directory line; cleaning already hides these (292 records, story 6), and "no direct
number" should be shown, not filled in.

Method: numbers from `phone_numbers` and `officialPhone` in `data/raw/facilities.parquet`, normalised to 10 digits
(drop +91 or a leading 0; toll-free kept), counted over the 9,959 records. Cities and states as written. Domain lift
from `derived/v1/source_urls.parquet`. Script: `s4_phones.py`.

Caveats: REPORT.md says 431 records for the top number (different row set); this script counts 432. "State names"
counts spellings, so 37 overstates distinct states. That proptiger.com is the origin is an inference from
co-occurrence (385 of 432 holders cite it), not a traced scrape.

## 5. The coverage table vs what is usable

Headline: a COUNT(column) coverage table shows all 19 fields at least 98.8% filled, because missing values are
stored as the text 'null', '[]' or '[""]'. Usable values are far fewer: official website 78% (7,902), year
established 47% (4,754), number of doctors 35% (3,532), bed capacity 22% (2,220), accepts volunteers 0.2% (21).

Chart: `out/s5_coverage.png`, one row per field with three dots: reported, has a value, usable.

Why it matters: planners who read a data dictionary would assume they can rank by bed count; only 1 record in 5
has a usable one. For the model: size fields cannot be required features; missingness itself carries signal (a
record with no official phone was more often anomalous, REPORT.md ID12).

Method: reported = not SQL NULL over 10,088 rows of `data/raw/facilities.parquet` (encodings listed in
`data/raw/PROFILE.json`); has a value = in the 9,959 records and not a null encoding; usable = passes the rule in
`out/s5_coverage.csv` (`rule` column), using `derived/v1/record_trust.parquet`, `derived/v1/facility_location.parquet`,
`audit/geo/facility_geo.parquet`, `audit/scale/scale_flags.parquet` and `audit/provenance/q2_records.parquet`.
Script: `s5_coverage.py`.

Caveats: no organiser coverage table was found in the project, so "reported" is our reconstruction of what a naive
table shows. The usable rules are ours; a looser rule moves some fields by a few points (for example, numberDoctors
counts named doctors and 1,195 rows say 1). Usable does not mean true: a usable postcode can still disagree with
the pin (story 2).

## 6. What cleaning could and could not fix

Headline: cleaning fixes geometry, contacts and duplicates, but 2,610 of 9,959 records (26.2%) keep a problem no
rule can fix, and 1,589 of them are among the 7,812 records the cleaning pipeline rates "no concerns".

Chart: `out/s6_cleaning.png`, records affected per issue, grouped fixed / flagged / cannot fix.
- Fixed: 118 malformed rows and 11 duplicate rows dropped; 152 records linked in 75 duplicate groups; 1,171 ranked
  on a corrected point; 292 directory phones hidden; 376 bad emails dropped; 27,528 duplicate sentences in 5,349
  records counted once; 9,506 sentences in 2,489 records quarantined.
- Flagged: 1,142 low-confidence and 538 disputed locations; 1,037 size flags; 881 records with a strong grade
  backed only by a tag; 574 with an outpatient type claiming an inpatient service.
- Cannot fix: 7,514 service sentences that name no facility in 1,390 records that also name another facility;
  1,232 merged records (story 1); 1,495 records whose lists were cut at 50 items.

Why it matters: this is the case for the product design. Fix what has a stated reason, flag the rest in words, and
make "call first" the default, because a quarter of records hold something no rule can see. For the model: the
"cannot" set is where the evidence score must widen its interval rather than move its point.

Method: counts recomputed from `derived/v1` (facility_location, record_trust, facility_groups, claims, grades) and
`data/raw/PROFILE.json`; the 7,514 / 1,390 match `cleaning/claims/out/measure.json`. Script: `s6_cleaning.py`.

Caveats: bars overlap; a record can sit in several. "No concerns" is the cleaning pipeline's record-level trust
label, which looks at location and contact data, not at copied text, so the 1,589 overlap is expected by design,
not a bug. Copied text that names nobody is only counted when the same record also names another facility; the
true count is likely higher.

## 7. Follow the citation

Headline: of 6,364 claim sentences tested against a page their own record cites, 346 (5.4%) appear on the page and
1,539 (24.2%) have most of their words there; even on the facility's own about page only 9.6% do (277 of 2,891),
and on government pages 1.2% (12 of 1,035).

Chart: `out/s7_citations.png`, strict and loose match rates by page type, with pages readable and pages that hold
any claim (own about page: 117 of 150 readable, 81 hold at least one claim).

Why it matters: source_urls look like citations but behave like search results. The app should cite the sentence,
not the URL, and a coordinator should not treat "has a government URL" as verification. For the model: page
support is a usable feature only for own-site pages; elsewhere it is close to zero for everyone.

Method: `derived/v1/source_page_checks.parquet` (Goal 3 page check from `pipelines/source_scoring`, 385 URLs in five
strata). Read, not re-fetched. Script: `s7_citations.py`.

Caveats: the extractor paraphrased page text, so strict matching understates support; the token rule is the more
generous reading. Strata were sampled at fixed sizes, so the pooled 5.4% is not a population rate. Sentences
cluster within 258 pages, so the plotted intervals are too narrow.

---

## Not run

- An organiser coverage table to compare against (none found on disk); story 5 reconstructs it.
- Whether thin "strong" evidence is confirmed less often (gold dev has 18 strong pairs with a verdict; the test
  split is sealed).
- A re-fetch of cited pages (story 7 reads the existing page-check table).
- Gold labels on the merged-record flag beyond the audit's 30-sentence hand check.
