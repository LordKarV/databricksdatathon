# Pattern discovery: what goes together in the facility records

Scope: the 9,959 usable Virtue Foundation records. Seven systematic searches (service co-occurrence, archetypes,
data-quality correlates, district supply vs need, public vs private, anomalies, year of establishment), each run
on a discovery split and re-measured on a holdout. Every number below comes from the scripts in this folder; the
full test table is `data/all_tests.csv`.

## How to read the numbers

- Split: duplicate groups (`derived/v1/facility_groups.dup_group_id`) are assigned whole to discovery (6,970
  records, 70%) or holdout (2,989, 30%) with seed 20261121. District analyses split the 704 districts 70/30 (492 /
  212) with the same seed instead, since the unit there is the district.
- Multiple comparisons: 613 tests were registered (465 service pairs, 72 regression coefficients, 24 district
  correlations, 23 public/private contrasts, 12 archetype contrasts, 7 time tests, 8 suspicious-profile tests, 2
  anomaly tests). Benjamini-Hochberg at q < 0.05 over all 613 declares 407 significant; the largest raw p that
  passes is 0.032. "q" below is the BH-adjusted p.
- Replicated means: significant on discovery, same direction on the holdout, and the holdout 95% interval
  excludes the null. 293 of the 407 replicated.
- Outcomes. Contaminated: the record has at least one claim sentence that the cleaning step attributes to another
  facility (2,487 of 9,959; broader than the 1,232 "places a service at another facility" count in
  viz/trust story 1, and the detector's sentence precision was 20 of 30 in the audit). Drift: the raw map pin is
  more than 50 km from the record's own PIN centroid (1,367 of 9,869). Claim breadth: number of the 36 taxonomy
  services claimed in the record's own positive text.
- Not used: gold labels of any split, and `facility_trust` scores (their location and service scores carry gold
  overrides).

## Findings, most important first

### 1. Public hospitals carry another facility's text in half their records, twice the private rate

Headline: 157 of 315 public hospitals in discovery (49.8%) contain a sentence attributed to another facility vs
1,061 of 3,297 private hospitals (32.2%); adjusted for stated beds, URL count and region the odds ratio is 2.34
(95% CI 1.79 to 3.07, q < 0.001). Holdout: 59.2% vs 32.8%, adjusted OR 2.76 (1.81 to 4.20). Replicated. Across all
facility types, with type, size, year, sources, web and region held fixed, public operator has OR 1.73 (1.29 to
2.32; holdout 2.16, 1.43 to 3.26). In the archetype view the "public hospitals" cluster is the most contaminated
of six (50.5% discovery, 61.1% holdout).

Chart: `charts/p5_public_private.png`, `charts/p2_archetypes.png`.

Why it matters: public hospitals are the default referral for the poorest patients, and their records are the
most likely to describe somewhere else. Generic institutional names ("District Hospital", "Civil Hospital") are
one mechanism (39% of the 467 public records carry such a name; viz/trust and the audit found generic names 75%
contaminated). Product: a public-hospital card should show "this record may mix text from other government
hospitals" and lean on official lists (LaQshya, MoHFW trauma, IPHS level) over record text. Model: an
`operator_public` x attribution interaction, or a lower prior on unanchored sentences in public records.

Caveat: operator comes from `operatorTypeId` (467 public, 687 not stated). Hospitals with a stated public operator
may differ from unlabelled government hospitals.

### 2. Public hospitals are invisible online, so web evidence penalises exactly the facilities poor patients use

Headline: a website answers for 94 of 315 public hospitals (29.8%) vs 2,197 of 3,297 private (66.6%), adjusted
OR 0.15 (0.11 to 0.20); the facility's own website confirms at least one service for 15.6% vs 49.3% (OR 0.15,
0.10 to 0.20); NABH list match 9.5% vs 36.3% (OR 0.13, 0.09 to 0.20). Yet public hospitals state PM-JAY
empanelment more often: 19.0% vs 10.9%, adjusted OR 1.96 (1.41 to 2.71; holdout 1.76, 1.02 to 3.03). All
replicated (q < 0.001).

Chart: `charts/p5_public_private.png`.

Why it matters: any score that adds credit for website confirmation or NABH listing will rank public hospitals
down for lack of a web presence, not for lack of service. Model: treat web and NABH evidence as missing-not-negative
for public facilities (a "no website" state separate from "website silent"), and add public-sector evidence
sources (LaQshya, MoHFW lists, IPHS level) with their own weights. Product: PM-JAY text is a useful "accepts the
government scheme" line on a public card, labelled as the record's own claim.

Caveat: CGHS (2 public hospitals) gave an unstable fit; ignore that row.

### 3. Records with no website are more contaminated and more often misplaced, with breadth held fixed

Headline: no website (vs a website that answers) has adjusted OR 1.34 for contamination (1.12 to 1.59, q = 0.002;
holdout 1.89, 1.46 to 2.45) and 1.51 for drift (1.20 to 1.89, q = 0.001; holdout 1.80, 1.33 to 2.45), while
claiming fewer services (rate ratio 0.60, 0.55 to 0.66). Replicated. A website that exists but does not answer
is not worse than a live one (contamination OR 0.84 discovery, 1.09 holdout: not replicated).

Chart: `charts/p3_forest.png`.

Why it matters: "no website" is a cheap record-level risk feature that is independent of URL count and size.
Model feature: `web_state` in {alive, dead, none}, with "none" as a contamination and location prior.

### 4. Text that says PM-JAY goes with misplaced pins; a NABH list match goes with correct ones

Headline: records whose text says PM-JAY empanelled have adjusted drift OR 1.59 (1.20 to 2.10, q = 0.003; holdout
1.65, 1.04 to 2.61). A match to the NABH list halves the odds of drift: OR 0.49 (0.40 to 0.60, q < 0.001; holdout
0.52, 0.37 to 0.72). Both replicated. Saying "NABH" in text without a list match does not replicate (0.62
discovery, 0.77 holdout with CI crossing 1).

Chart: `charts/p3_forest.png`.

Why it matters: an independent list match is location evidence, a text claim is not. Model features:
`nabh_listed` as a location-confidence prior; PM-JAY text as a weak drift risk. Hypothesis, not tested here:
scheme pages list many hospitals at once, so PM-JAY text often arrives through a multi-hospital page that also
supplies a wrong geocode.

### 5. Record breadth is the largest driver of every quality problem, even with type and size fixed

Headline: each doubling of source URLs multiplies the odds of contamination by 2.58 (2.37 to 2.80) and of drift
by 2.45 (2.21 to 2.71), and the claimed-service rate by 1.28 (1.25 to 1.32), all q < 0.001 and replicated
(holdout 2.93, 2.84, 1.21). A higher aggregator share slightly lowers contamination (OR 0.94 per 10 points,
replicated); a higher social share raises drift (OR 1.20 per 10 points, 1.14 to 1.27, replicated).

Chart: `charts/p3_forest.png`.

Why it matters: this confirms PROV-02 and viz/sources story 2 under full adjustment, so breadth should stay a
penalty rather than count as evidence. It also explains several apparent patterns below (findings 8 and 10).

### 6. Six facility archetypes, from dental clinics (9% contaminated) to public hospitals (50%)

Headline: k-means on 30 standardised claim, size, type, operator, web and evidence features gives six
archetypes: flagship tertiary hospitals (770 discovery records, 9.2 services, 38% contaminated), mid-size
multispecialty hospitals (1,334; 34%), small hospitals with thin records (1,677; 27%), public hospitals (311;
50%), clinics with thin records (2,547; 14%) and dental clinics (331; 9%). 10 of 12 archetype-vs-rest
contamination and drift contrasts replicate; holdout re-clustering agrees with the discovery assignment at
ARI 0.89.

Chart: `charts/p2_archetypes.png`.

Why it matters: archetype is a compact stratum for calibration: a "strong" grade at a flagship hospital and at a
public hospital do not carry the same contamination risk. Model: report calibration per archetype.

Caveat: the structure is weak. Silhouette is below 0.15 for every k from 3 to 10 (0.142 at k = 6); k = 6 and
k = 4 tie and k = 3 is the most stable (bootstrap ARI 0.97 vs 0.68 at k = 6). We kept k = 6 because it is the
only k that isolates public hospitals. Treat archetypes as a segmentation, not natural kinds.

### 7. Services co-occur along care pathways, plus one tertiary bundle

Headline: of 465 service pairs with at least 30 claiming facilities each, 301 have lift different from 1 after
BH, and 215 replicate. All 25 highest-lift pairs replicate; 15 of them are on a care-pathway list written before
looking (18 share a taxonomy category). Examples: chemotherapy with radiotherapy lift 8.2 (7.4 to 9.1; holdout
8.6), psychiatric care with de-addiction 8.9 (6.9 to 11.3), cataract surgery with eye emergency 6.9 (6.3 to 7.5),
dialysis with kidney transplant 3.2 (2.9 to 3.5; holdout 2.9). Most of the remaining strong pairs bind cardiac
surgery, cath lab, kidney transplant, cancer, MRI and blood bank into one tertiary bundle (cardiac surgery with
radiotherapy lift 3.3, 2.9 to 3.8). The clearest anti-associations are eye services with acute care: 49 of the 73
pair slots with a lift upper bound below 1 involve cataract surgery or eye emergency (for example 24x7 emergency
with cataract surgery, lift 0.56, 0.49 to 0.63; holdout 0.67).

Chart: `charts/p1_network.png`.

Why it matters: pathway pairs are a sanity check the grader can use (a cath lab claim with no cardiology context
is weaker), and the tertiary bundle is the profile of both real flagship hospitals and merged records, which is
why flagship hospitals are 38% contaminated. Model feature: "claims a pathway partner" (for example dialysis plus
nephrology context) as corroboration within the record, never as independent evidence.

Caveat: my pathway list missed obstetric pairs that are clinically sensible (C-section with MTP, lift 7.2).
Pairs from one record are not independent sources: they come from the same extraction.

### 8. Off-focus claims (an eye or dental name claiming acute care) are a symptom of breadth, not a separate signal

Headline: among 2,370 single-focus names in discovery (eye, dental, IVF, skin, ENT, physiotherapy, AYUSH,
diagnostic centre), the 208 that claim an acute service outside their focus contain another facility's text 23.1%
of the time vs 13.6% (difference 9.5 points, 4.1 to 15.8, q < 0.001; holdout 28.1% vs 14.9%, replicated). With
claim breadth, URL count and type held fixed the effect disappears: OR 0.89 (0.55 to 1.43, q = 0.70; holdout
0.88). The data-driven version (claims an anti-associated pair) also fails to replicate once adjusted (1.52
discovery, 1.05 holdout).

Chart: `charts/p1_suspicious.png`.

Why it matters: keep the "name suggests an eye hospital" card (it explains the risk to a user), but do not add an
off-focus feature to the model on top of breadth: it would double count. The existing scope-conflict cap in the
grader overlaps (138 of the 297 off-focus records already have a scope conflict).

### 9. District supply follows institutional births, not insurance; dialysis evidence tracks high blood pressure

Headline: across 492 discovery districts, records per million people correlate with the institutional birth rate
(Spearman rho 0.43, 0.35 to 0.50; holdout 0.40) and C-section rate (0.45, 0.38 to 0.52), but not with household
insurance coverage (0.01, -0.08 to 0.09; holdout -0.01). Corroborated dialysis units per million track women's
high blood pressure with the urban share held fixed (partial rho 0.22, 0.13 to 0.30; holdout 0.24, replicated),
while the link to high blood sugar does not survive the urban adjustment (0.13 discovery, 0.08 holdout, not
replicated). 531 of 704 districts have no corroborated dialysis record at all.

Chart: `charts/p4_district.png`.

Ecological fallacy warning: these are district aggregates. A district where more births happen in institutions
and more facilities appear in the dataset says nothing about whether any one facility performs deliveries, or
whether any one mother can reach one. The dataset is a web-visibility sample, so records per million partly
measures how online a district is.

Why it matters: the planner view can show NFHS need beside supply, but only as district context; and the
dialysis-hypertension link suggests NCD need is visible in where units are documented. Not a model feature for
facility-level ranking.

### 10. Older facilities look more contaminated only because the web says more about them

Headline: records of facilities founded before 1970 contain another facility's text 39.7% of the time vs 19.6%
for those founded in 2020 or later (unadjusted OR 1.10 per decade older, 1.06 to 1.13, replicated). Holding URL
count, type and beds fixed, the effect shrinks to 1.04 (1.00 to 1.08, q = 0.08, not significant); older records
cite 24 URLs on average vs 13. Year of establishment has no replicated association with drift or website
liveness, and after adjustment older facilities claim slightly fewer services (rate ratio 0.98 per decade, 0.97
to 0.99, replicated).

Chart: `charts/p7_time.png`.

Why it matters: do not use yearEstablished as a trust feature; it is stated for only 4,754 of 9,959 records, is
usually read from the record's own description, and shows mild heaping on years ending in 0 or 5 (+2.4 points
over the expected 20%, not replicated).

### 11. The most anomalous records are either data errors or unusually complete flagships

Headline: an isolation forest over 12 record features (fitted on discovery) puts 12 data errors and 8 genuinely
unusual hospitals in its top 20, classified by hand from the record text: 2,860 doctors for 200 beds (Narhari,
Vadodara), pins 177 and 242 km from their PIN, society-wide bed counts on one site, a Goa hospital described as a
Panipat cashless hospital. The top 5% by score is somewhat more contaminated (33.8% vs 24.5%, q < 0.001) but this
did not replicate (holdout 31.4% vs 24.6%, CI crossing 0).

Chart: `charts/p6_anomalies.png`; verdicts in `data/p6_top20_classified.csv`.

Why it matters: the forest mostly finds completeness (records that state beds, doctors and a year are rare), so
an anomaly score is not a usable trust feature. The errors it surfaces are already caught by explicit rules
(doctors_exceed_beds, coordinate drift); keep the rules.

## Suggested model and product changes

- New features: `operator_public` (contamination prior), `web_state` (alive / dead / none), `nabh_listed`
  (location prior), PM-JAY text (weak drift risk), archetype id (calibration stratum).
- Treat missing web and NABH evidence as missing, not negative, for public facilities; add public-sector list
  evidence with its own weight.
- Do not add: off-focus claim flag (redundant with breadth), year established, isolation-forest score.
- Warning cards: "public record may mix text from other government hospitals"; "no website found: location and
  services are less certain".

## Files

- Scripts (run in order, or `notebook.py`): `p0_build.py` (facility table and split), `p1_cooccurrence.py`,
  `p2_archetypes.py`, `p3_quality.py`, `p4_district.py`, `p5_public_private.py`, `p6_anomalies.py`,
  `p7_time.py`, `p9_multiple.py`; shared helpers in `common.py` (self-check: `python common.py`).
- Charts: `charts/p1_network`, `p1_suspicious`, `p2_archetypes`, `p3_forest`, `p4_district`,
  `p5_public_private`, `p6_anomalies`, `p7_time` (each .png at 2x, .svg, .txt alt text).
- Data: `data/all_tests.csv` (every test with q and replication), `data/multiple_summary.json`, per-analysis CSVs.

## Not run

- k-prototypes: k-means on one-hot and standardised features was used instead (no extra package installed).
- The co-occurrence network layout is a hand-placed circle by taxonomy category, not a force layout (networkx is
  not installed).
- The notebook was run locally as a script (about 60 s); it has not been run on Databricks. The UC_TABLES mapping
  in its config cell assumes tables under `workspace.parchi` that may not exist yet; the district step reads the
  viz/geography population cache from files.
- The top-20 anomaly verdicts were made by one reader from the record text, not checked on the web.
- No web or phone verification of any pattern; all outcomes are the cleaning pipeline's flags, which have their
  own error rates (contamination sentence precision 20 of 30 in the audit).
