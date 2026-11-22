# What facilities say vs what we can confirm

Six data stories about the gap between what a facility record claims and what anything outside the record can
confirm. Every number below was produced by the scripts in this folder on 2026-11-21 and is saved in `data/`.
Rates carry 95% Wilson intervals unless stated. Charts are in `charts/` as PNG (2x), SVG and an alt-text `.txt`.

Reproduce everything (about 7 s on a laptop):

```
cd /Users/karthikvattem/projects/datathon
.venv-viz/bin/python viz/claims/notebook.py      # Databricks notebook source; also runs as a script
```

Each story is also its own script (`s1_longtail.py` ... `s6_hours.py`); `claims_io.py` holds the input paths,
the Unity Catalog switch and the shared "dataset claim" rule. No test-split gold label is read anywhere here.

"Record" means one of the 9,959 usable Virtue Foundation (VF) facility records. "Dataset claim" for a (record,
service) pair follows `kb/web_evidence/compare_dataset.py`: a claim sentence that names the service with no
non-offer cue, not attributed to another facility and not a staff or directory line, or a raw specialties value
that `kb/taxonomy/specialty_map.csv` maps to the service.

---

## 1. Specialty strings are a long tail, and the most common ones are type defaults

Headline: 1,976 of 2,932 specialty values (67%) occur in exactly one record; the most common value,
internalMedicine, is on 5,607 of 5,610 hospitals (99.9%, 99.8% to 100%) and familyMedicine on 3,769 of 3,770
clinics.

Charts: `charts/s1_longtail.png` (primary), `charts/s1_default_tags.png`.
Data: `data/s1_rank_frequency.csv`, `data/s1_label_shares.csv`, `data/s1_default_tags.csv`.

What the data shows:
- 2,932 non-empty distinct values (the map's 2,933 include one empty string) over 118,213 (record, value) mentions.
  2,269 values occur in 2 or fewer records. The log-log rank-frequency slope is -1.37.
- The top 10 values carry 34% of all mentions. The taxonomy labels 1,964 values (67%) out of scope, 465 (16%) too
  general and 42 not a service; only 461 values (16%) map to a service, and they carry 13% of mentions. 28 of the
  36 taxonomy services receive at least one specialty value.
- The head is not information. internalMedicine is on 99.9% of hospitals, familyMedicine on 99.97% of clinics,
  dentistry on 484 of 488 dentists (99.2%). familyMedicine is also on 384 of 488 dentists (79%, 75% to 82%) and
  dentistry on 2,111 of 5,610 hospitals (38%).

Why it matters:
- For the model: a value present on nearly every record of a type cannot separate facilities. Specialties are
  weak evidence, and story 5 measures how weak: claims resting only on a specialty value are confirmed by the
  facility's own website 29% of the time (Wilson 25% to 33%, independent sites), against 47% for claim
  sentences.
- For health workers: "internal medicine" on a hospital card says nothing; the app should not show it as a
  service.

Method: `s1_longtail.py`. Labels and facility counts are read from `kb/taxonomy/specialty_map.csv` (labelled by
rule 2,355, LLM 532, manual 24, fuzzy 21 over the 2,932 non-empty values; see `kb/taxonomy/TAXONOMY.md`). The default-tag table re-reads the raw
specialties JSON arrays from `data/raw/facilities.parquet` and the facility type from
`model/proto/evidence/pair_features.parquet`.

Caveats: the labels are the taxonomy's, with its own hand-check error; a value mapped to a service is a claim, not
an offer. The raw specialties array sits at the 50-item cap in 2,880 of 9,959 records (counting repeats; median 21 distinct
values in those arrays), so some values were cut and tail counts are low by an unknown amount.

---

## 2. Small records claim big services

Headline: 609 of 1,867 records that state 1 or 2 doctors (33%, 31% to 35%) claim at least one of 8 tertiary
services; 383 claim an ICU (21%, 19% to 22%).

Chart: `charts/s2_inflation.png`. Data: `data/s2_facility_claims.csv` (one row per record), `data/s2_by_size.csv`,
`data/s2_small_tertiary.csv`.

What the data shows:
- Services claimed (of 36) rise with stated doctors, but slowly: hospitals stating 1 doctor claim a median of 4
  (bootstrap 95% interval 3 to 4), hospitals with 50+ doctors 9 (9 to 10). Clinics claim a median of 0 to 2 at
  every size. Spearman rho between doctors and services claimed is 0.47 (0.44 to 0.50, n = 3,433); with beds,
  0.45 (0.42 to 0.48, n = 2,493).
- Among records stating 1 or 2 doctors: ICU 383 (298 with a claim sentence), neurosurgery 337 (only 139 with a
  sentence; the rest rest on a specialties value), trauma care 175, cardiac surgery 112, dialysis 109,
  cath lab 102, kidney transplant 56, radiotherapy 50.
- 5,947 of 9,380 hospitals and clinics state no doctor count at all (shaded column).
- The share claiming any of the 8 rises with stated size: 1-2 doctors 33% (n = 1,867), 3-9 53% (49% to 56%,
  n = 836), 10-49 79% (76% to 82%, n = 603), 50+ 85% (80% to 88%, n = 309). Small records claim less, not more; the
  point is that a third of them still claim a tertiary service, which is a flag to check, not proof of a false claim.

Why it matters:
- For referral: a one-doctor record that claims an ICU or neurosurgery is the case the app must not rank first on
  text alone. Size-vs-claim mismatch is a cheap, explainable flag ("claims neurosurgery; record states 1 doctor").
- For the model: stated size is a context feature (the Witness Ledger already carries beds, doctors and breadth
  bins, and a scale_contradiction flag); this chart is the evidence for keeping it.

Method: `s2_inflation.py`. Doctors, beds and type come from `pair_features.parquet` (cleaned there). Services
claimed per record use the shared dataset-claim rule. Medians carry 1,000-sample bootstrap intervals; the thin bar
is the interquartile range.

Caveats: a stated doctor count may be the number of doctors named on a web page, not the staff. Clinics with 50+
doctors (n = 19) are a small sample. Claim sentences per record are not shown because the arrays are capped at 50.

---

## 3. The confirmation funnel: a mention is not a confirmation

Headline: of 7,969 facility-service mentions of the 7 core services, 1,798 (23%) pass the record's own checks
(2+ fields and a prerequisite) and 837 (10.5%, 9.8% to 11.2%) also have a website or official-list confirmation.
The narrowest step is inside the record: of the 1,798 that pass it, 837 (47%, 44% to 49%) have an outside check.
(Verification changed this headline: the earlier "outside confirmation is rare" put the drop in the wrong place,
and the chart now draws the website bar as a share of mentions, with the part that had a site to check shown
pale, so every bar shares one axis.)

Chart: `charts/s3_funnel.png`. Data: `data/s3_funnel.csv`, `data/s3_pairs.csv` (per pair flags).

Stages (per record and service, from `model/proto/evidence/pair_features.parquet`):
1. Mentioned: text level T >= 1 (any own mention, including a specialties value).
2. In 2+ fields: T >= 4 (own units in two or more of procedure, capability, equipment, description, after echo
   collapse).
3. ...and a prerequisite: stage 2 and P >= 1 (a prerequisite cue such as ICU, OT, blood bank or nephrology in a
   sentence not about the service).
4. Own website confirms: a strict website quote (strong, on 2+ pages or a list item; 16 of 16 correct in
   `kb/web_evidence/qa/QA.md`), among mentioned records that have an attributable site.
5. On an official list: NABH scope DIA (dialysis) or EMD (emergency), LaQshya Maternity OT (C-section), MoHFW
   trauma 196, NMC postgraduate course of tier "strong" (DM Nephrology, MCh CTVS, DM Neonatology, MS OBG, MCh
   Plastic Surgery, trauma courses). No list covers MRI.

| Service | Mentioned | 2+ fields | + prerequisite | Website confirms | On a list |
|---|---|---|---|---|---|
| Dialysis | 1,039 | 498 (48%) | 457 (44%) | 352 of 663 (53%) | 106 (10%) |
| Trauma and emergency | 3,571 | 891 (25%) | 852 (24%) | 1,243 of 2,020 (62%) | 283 (8%) |
| Emergency C-section | 442 | 64 (14%) | 64 (14%) | 52 of 266 (20%) | 10 (2%) |
| NICU | 741 | 178 (24%) | 176 (24%) | 208 of 462 (45%) | 0 |
| Cardiac surgery | 970 | 186 (19%) | 165 (17%) | 227 of 594 (38%) | 10 (1%) |
| MRI | 945 | 465 (49%) | 49 (5%) | 158 of 549 (29%) | no list |
| Burn care | 261 | 38 (15%) | 35 (13%) | 36 of 133 (27%) | 6 (2%) |

The reverse direction is in the CSV (`outside_not_mentioned`): 323 records have outside evidence of dialysis but
never mention it, 386 for trauma and emergency, 148 for C-section.

Why it matters:
- For coordinators: "mentions C-section" covers 442 records, but only 52 have a facility website that says so
  and 10 a LaQshya Maternity OT certificate or an OBG postgraduate course. Call ahead.
- For the model and the demo: this is the evidence ladder the Witness Ledger scores, drawn as counts. Each stage
  is one explainable term on the result card.

Caveats: MRI's prerequisite rate (5%) is low because few MRI prerequisites are defined, not because MRI claims are
weaker. List coverage is structural: NABH scopes were fetched for 7 codes only, LaQshya and MoHFW cover public
facilities, NMC covers teaching hospitals. Website rates use only records with an attributable own site (stage 4
denominators). Website and dataset are not fully independent (story 5).

---

## 4. Official lists vs the dataset: who is missing from whom

Headline: 540 of 1,242 records that say NABH (43%, 41% to 46%) are not found on NABH's current list, while 1,359
list-matched records never mention NABH; 19,573 of 21,615 NABH entries have no record in the dataset at all.

Charts: `charts/s4_lists.png` (primary), `charts/s4_pmndp.png`. Data: `data/s4_lists.csv`, `data/s4_pmndp.csv`.

| List | Dataset claims it, no list match | Both | On the list, record silent | List entries with no record |
|---|---|---|---|---|
| NABH (claim: NABH in the record text) | 540 | 702 | 1,359 | 19,573 of 21,615 |
| e-RaktKosh (claim: blood bank service) | 512 | 162 | 203 | 6,516 of 6,904 |
| LaQshya Maternity OT (C-section, public records) | 15 | 3 | 44 | 854 of 902 |
| MoHFW trauma care facilities (trauma or emergency, public) | 253 | 17 | 3 | 176 of 196 |

- Of the 702 NABH "both" records, 244 hold only entry-level "Certified" status, not full accreditation.
- PMNDP (NHSRC state counts): 1,994 functional public dialysis centres; the dataset has 75 public records that
  mention dialysis, out of 467 public records in all (1,039 records of any operator mention dialysis). Bihar 4 vs
  94 centres, Uttar Pradesh 4 vs 76, Gujarat 4 vs 284.

Why it matters:
- For health workers: a record's "NABH accredited" is wrong or stale often enough (up to 43%) that the app should
  show the NABH certificate link, or "not found on NABH's current list", next to the claim.
- For planners: the dataset is not a census of public facilities. A district hospital with no dialysis text is
  not evidence that the district has no public dialysis; PMNDP says most districts do.
- For the model: list matches are the only evidence not written by the same extraction as the record text, which
  is why they are family X in the Witness Ledger. Most lists confirm far more facilities than the record admits
  (the "record silent" segments), so lists add recall as well as precision.

Method: `s4_lists.py`. Matches are the precomputed matcher outputs in `data/external/<slug>/` (hand-checked
precision: NABH 39/40, e-RaktKosh 16/20 strict plus 2 likely, LaQshya 17/20 plus 3 plausible, MoHFW 19/20). NABH
claims are `kb/vf_details` accreditation facts (usable rows), service claims use the shared rule, public
operator comes from `pair_features.parquet`. PMNDP is a state count compared with record counts, not a match.

Caveats: matcher recall was not measured, so "no list match" is an upper bound on false claims (the NABH research
probe found 19 of 20 unmatched claimers had no same-place entry). LaQshya and MoHFW are subset designations: a
public facility can do C-sections or trauma care without being on them, so their "dataset only" segment is
expected and is not a false-claim rate. The LaQshya claim group is small (18 records). Earlier research quoted
169 public dialysis facilities using its own text match and public flag; this page uses the taxonomy claim rule
and the model's public flag, which gives 75. The lists are used for per-facility facts with citation only and are
not redistributed (licences in `research/DATASETS.md`).

---

## 5. What facility websites say that the dataset does not, and the reverse

Headline: a facility's own website confirms 60% of dataset service claims (10,621 of 17,735, 59% to 61%) and
names 9,557 services the dataset never mentions; a website the record does not cite confirms 47% of sentence
claims but 29% of claims resting on a specialties value alone. The gap is not a service-mix effect: within each of
the 13 services with 20+ claims of each kind, sentence claims are confirmed more often (median gap 30 points).

Charts: `charts/s5_web_by_service.png` (primary), `charts/s5_why_unconfirmed.png`.
Data: `data/s5_by_service.csv`, `data/s5_claim_kind.csv`, `data/s5_claims.csv`.

What the data shows (4,866 records with an attributable own site or branch page):
- Confirm rate by service ranges from psychiatric care 14% (8% with strict quotes) and chemotherapy 33% to ICU 77%
  and cataract surgery 78%. With strict quotes only, the overall rate is 40% (7,171 of 17,735).
- Web-only: 9,557 of 20,218 positive website pairs (47%, 47% to 48%) have no dataset mention; with strict quotes,
  3,568 of 10,761 (33%). Highest for burn care (81%), TB care (79%) and ventilator support (72%).
- Silent: where the site has a services page, it never mentions 34% of dataset claims (4,961 of 14,495); psychiatric
  care 85%.
- Claim kind and independence (`s5_why_unconfirmed.png`): claim sentences on a site the record does not cite are
  confirmed 47% (792 of 1,698, 44% to 49%); on a cited site 70% (8,835 of 12,653). Specialty-only claims: 29%
  (144 of 503) and 30% (850 of 2,881), with or without citation.

Why it matters:
- For the model: two features any card can show ("this claim is only a specialty tag", "the website is the
  record's own source") shift the confirmation rate by about 20 to 40 points. The cited-site rate overstates
  agreement, since the record text was probably extracted from that site; 47% is the closer estimate of
  independent agreement.
- For coordinators: websites carry services the record misses, but web-only quotes are noisy (QA: strict quotes
  16/16 correct, weak single-page quotes 7 of 18). Use strict web-only quotes as weak positive evidence only.

Method: `s5_web.py` re-derives `kb/web_evidence/out/compare_by_service.csv` from the web tables and asserts that
claim, confirm, web-only and silent counts match it for every service, then adds the strict level and the split.

Caveats: the crawl stored at most 6 pages per site and did not read PDFs or JavaScript pages, so silence is weak
evidence of absence. Weighted QA precision of "any positive quote" is 0.69 (0.46 to 0.84).

---

## 6. Hours live on websites, and 3,885 records have none

Headline: the dataset gives clock-time hours for 511 records (5.1%, 4.7% to 5.6%), facility websites for 2,421
(24.3%), OpenStreetMap for 51; 3,885 of 9,959 records have no hours or 24x7 statement from any source.

Chart: `charts/s6_hours.png`. Data: `data/s6_hours_by_source.csv`, `data/s6_emergency_agreement.csv`,
`data/s6_facility_hours.csv` (per record flags).

| Records with... (of 9,959) | Dataset text | Own website | OpenStreetMap | Any |
|---|---|---|---|---|
| Any hours or 24x7 statement | 4,330 | 3,669 | 139 | 6,074 (61%) |
| A 24x7 statement | 4,047 | 2,275 | 88 | 4,672 (47%) |
| 24x7 emergency | 2,281 | 1,433 | 162 (emergency=yes tag) | 2,829 (28%) |
| A clock-time schedule | 511 | 2,421 | 51 | 2,808 (28%) |

- Among the 4,866 records with an own site, 1,918 have a 24x7 emergency statement from the dataset or the site:
  950 from both (50%), 485 from the dataset only, 483 from the website only.
- Among records with a site, the website gives a clock-time schedule for 2,421 of 4,866 (50%, 48% to 51%).

Why it matters:
- For health workers: "is it open now?" is answerable from a stated schedule for about 28% of records, almost all
  of it from websites. For the rest the app must say "hours unknown, call first".
- For the night-time referral: 24x7 claims are common (47%), but "24x7" is often generic wording; only the 24x7
  emergency scope held up in QA (website 9 of 10; other 24x7 scopes 1 of 5).
- For the model: 24x7 emergency agreement between two sources (950 records) is a stronger access-hours signal than
  either alone.

Method: `s6_hours.py`. Facility-level fact tables with n_usable > 0: `kb/vf_details/out/facility_details.parquet`,
`kb/web_evidence/out/web_facility_details.parquet` (attributable pages), and OSM facts in
`kb/opendata/vf_opendata_facts.parquet` (is_24x7, opening_hours, emergency). Helpline, home-care and visiting
hours are excluded.

Caveats: "A 24x7 statement" counts unit-level scopes too (24x7 pharmacy, ambulance, lab); 215 dataset records
have only such a unit-level 24x7 statement. OSM has no 24x7 emergency field; its row is the emergency=yes tag. OSM tags were not hand-checked. QA
found 716 of 3,038 website OPD facts whose facility-level value differs from the cited quote, so schedules need the
quote shown next to them. Absence of hours is not evidence of closure.

---

## Features for the model, from these stories

| Feature | Story | Evidence for it |
|---|---|---|
| claim is specialty-only (no sentence) | 1, 5 | website confirms 29% vs 47% for sentences on independent sites |
| specialty value is a type default (internalMedicine on hospitals, familyMedicine on clinics) | 1 | present on 99.9% of a type; carries no signal; drop it |
| stated size vs tertiary claim (doctors 1-2 and ICU, neurosurgery, cardiac surgery) | 2 | 609 of 1,867 small records claim one |
| text level T (2+ fields) and prerequisite P | 3 | funnel stages; 2+ fields keeps 14% to 49% of mentions by service |
| strict website quote (strong, 2+ pages or list item) | 3, 5 | QA 16/16; confirms 40% of claims |
| website is among the record's sources | 5 | confirmation 70% vs 47%: not independent, discount it |
| official list match (family X) with list precision as prior | 3, 4 | the only evidence not from the same extraction; 43% of NABH claims unmatched |
| 24x7 emergency agreed by dataset and website | 6 | 950 records; website 24x7 emergency 9/10 in QA |
| hours known (schedule from any source) | 6 | 2,808 records; drives "call first" wording |

## Verification (2026-11-21)

Every headline number above was recomputed with independent code in `verify/` (`v1_longtail.py` ...
`v6_hours.py`, shared helpers in `verify/vcommon.py`, which re-implements the claim rule and does not import
`claims_io.py`); all matched. Chart fixes from that pass: story 2 light segment moved to a ramp step that clears
2:1 contrast and the size gradient added to the note; story 3 headline and website bar redrawn as above; story 4
headline says "not found on" (recall unmeasured) and the thin MoHFW segment is labelled; story 5 gets an in-chart
key for filled vs hollow dots and a plainer headline for the claim-kind chart; story 6 stack reordered so the two
blues are not adjacent (validator normal-vision floor). Run from `viz/claims/verify/`:
`../../../.venv-viz/bin/python v1_longtail.py` (and so on).

## Not run

- No new hand check of any rate on this page; precision figures are quoted from the QA and matcher READMEs cited
  above.
- No gold-label evaluation of any of these features (the frozen test split was not touched).
- No Unity Catalog read: the notebook's config cell supports it, but it was run here from local files only.
- No map: no story needed geography beyond the PMNDP state comparison, which is a ranked dot plot.
