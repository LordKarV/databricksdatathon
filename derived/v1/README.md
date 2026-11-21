# derived/v1: source reliability and data-point scores

One place for the app and the team to read from. It holds (a) a reliability score for every source domain
and source class, (b) a score in [0, 1] with an interval for every data point in the Virtue Foundation
facility records, keyed to the original `unique_id` and claim ids, and (c) copies of the canonical cleaned
tables. No original value is changed: every score sits next to a verbatim copy of what the record says.

Build: `pipelines/source_scoring/run_all.sh` (about 16 s; the live page fetch is opt-in with `FETCH=1`).
Build date 2026-11-21. Row counts, input hashes and script hashes are in `MANIFEST.json`; run statistics in
`build_stats.json`; held-out evaluation and page-check rates in `evaluation.json`.
Self-check: `pipelines/source_scoring/selfcheck.py` (verified-false scores below 0.1, scores in [0, 1],
every row joins to an original unique_id, original values copied unchanged, data/raw hashes unchanged).

## Tables

New tables (built by this pipeline):

| Table | Rows | Grain |
|---|---|---|
| data_point_scores.parquet | 518,191 | one data point (sentence, facility-service claim, location, existence, phone, email) |
| facility_trust.parquet / .csv | 9,959 | one record |
| source_domains.parquet / .csv | 10,951 | one registrable domain |
| source_classes.parquet / .csv | 16 | one source class |
| source_urls.parquet | 158,444 | one (record, URL) pair from source_urls |
| source_page_checks.parquet | 6,492 | one (fetched URL, claim sentence) test; URLs with no usable page have one row with claim_id null |
| evidence_rules.parquet | 20 | one evidence rule with its hand-check and gold-dev counts |
| gold_pairs.parquet | 176 | one gold facility-service pair with merged web verdicts and its frozen split |

Canonical cleaned tables (byte copies, see MANIFEST for the source path and hash):

| Table | Rows | Source |
|---|---|---|
| facility_location.parquet | 9,959 | cleaning/geo_identity (ranking point, radius, confidence, notes, district, NFHS key) |
| record_trust.parquet | 9,959 | cleaning/geo_identity (cleaned phones and emails, website class, trust flags) |
| facility_groups.parquet | 9,959 | cleaning/geo_identity (duplicate groups, soft links, co-located units) |
| pin_gazetteer.parquet | 19,713 | cleaning/geo_identity |
| place_gazetteer.parquet | 147,345 | cleaning/geo_identity |
| claims.parquet | 469,498 | cleaning/claims (one row per claim sentence; claim_id = uid8:field4:idx) |
| specialties.parquet | 117,964 | cleaning/claims |
| grades.parquet | 10,799 | cleaning/claims, grader v2, other-facility quarantine on (canonical) |
| grades_v1.parquet | 10,799 | cleaning/claims, grader v1 (reference) |

Why grades.parquet (v2) is canonical: it is the grade table REPORT.md section 3 reports and the product
plan reads. v2 was written after reading the 36 web verdicts, so it is in-sample on those; v1 was frozen
before them and is shipped as the honest reference. The pending grader-leak fix (department lists and
research protocols should fall to weak under G_nonspec) is not applied in either file. This pipeline never
changes a grade; it scores them.

## Columns

data_point_scores
- dp_id (string): `loc:<uid>`, `exist:<uid>`, `svc:<uid>:<service>`, `sent:<claim_id>`, `phone:<uid>`, `email:<uid>`.
- dp_type (string): location, existence, service_claim, claim_attribution, phone, email.
- unique_id (string): original record id. claim_id (string): claim sentence id (claim_attribution only).
- service (string): service for service_claim; pipe-joined services named by a sentence.
- field (string): source field of a sentence (procedure, capability, equipment, description).
- original_value (string): verbatim original. location = "lat,lon | city, state PIN" from the raw
  record; existence = "name | city"; service_claim = the cited claim sentences joined by " || ";
  sentence = its text; phone = raw officialPhone; email = raw email field.
- score (double): P(data point is true) after verification overrides. score_lo, score_hi (double): 90% interval.
- status (string): verified_true, verified_false, unverified.
- reason_codes (string, pipe-joined): evidence rule, GOLD_TRUE / GOLD_FALSE, SOURCES_ABOVE_AVERAGE /
  SOURCES_BELOW_AVERAGE (source term shifts the logit by more than 0.3), PAGE_CHECKED (attribution set by the
  Goal 3 page check).
- evidence_refs (string): gold label file(s) and evidence URLs, or the audit rule, its hand-check citation and script.
- rule (string): evidence rule (see evidence_rules). q_ev (double): evidence-only probability, no sources.
- source_support (double): weighted mean reliability of the sources the point is attributed to.
- score_model (double): model score before the gold override (used for the held-out evaluation).
- gold_split (string): dev or test when a gold verdict exists. grade (string): grade for service claims.
  attribution (string): own_anchored, unanchored, ambiguous, other_facility (sentences).

facility_trust
- existence_score, location_score (double) with location_lo, location_hi, and *_status, location_reason_codes.
- n_sentences, n_sentences_other_facility (int); attribution_score (double): mean sentence score.
- n_service_claims, n_service_verified_true, n_service_verified_false (int); service_score_mean (double).
- source_support (double): identity-profile weighted reliability of the record's sources.
- top_sources (JSON string): up to 3 domains with weight and reliability.
- overall_score (double) = existence_score x location_score x attribution_score; overall_lo uses the lower bounds.
- trust_level_cleaning (string): from record_trust. drivers (string): plain-English reasons.

source_domains
- domain (string), source_class (string: modal class of its URLs), class_mix (JSON: top 3 classes).
- reliability (double): posterior mean; ci05, ci95 (double): 90% credible interval; alpha, beta (double).
- credit, blame (double): effective true and false data-point mass assigned to the domain.
- class_prior_mean (double): mean of the Beta prior for its class.
- n_records, n_urls, n_distinct_urls (int); share_about, share_list (double).
- n_verified_true, n_verified_false (int): gold-dev and placeholder-email points in records citing the domain
  (the hard labels used in fitting). n_flagged_false (int): audit-flagged points (q_ev < 0.5) in those records.
  n_test_gold_points (int): held-out gold points touching it.
- top_blame_type (string), top_blame_share (double): data-point type that supplies most of its blame.
- page_urls_checked, page_urls_fetched, page_sentences_tested, page_sentences_supported: Goal 3 counts.
- reason (string): plain-English summary.

source_classes: source_class, n_domains, n_urls, n_records, reliability with ci05/ci95 (pooled Beta(1 +
credit, 1 + blame) of its domains), median and p10/p90 of domain reliabilities, verified counts, effective
true/false mass.

source_urls: unique_id, url_pos, url, host, domain, source_class, url_kind (about / list / unverified),
n_records_url, domain_reliability with ci05/ci95, page_fetch_status, page_sentences_tested,
page_sentences_supported.

source_page_checks: unique_id, url, domain, source_class, url_kind, stratum, fetch_status, page_chars,
claim_id, field, is_service_sentence, attribution, exact, partial_ratio, token_coverage, supported,
token_supported, snippet (at most 160 characters of normalised page text around the best match).

## How the scores are computed

Sources. Each URL gets a class from `audit/provenance/domains.py` and a kind from
`audit/provenance/q1_sources.py url_kind` (unchanged; totals reproduce q1_results.json: 158,444 URLs, about
44,434 / list 17,340 / unverified 96,670). A source is the registrable domain of the host.

Evidence-only truth q_ev. Every data point gets one evidence rule. Each rule has a Beta(a, b) built from
a hand check (true + 1, false + 1) and then updated with the gold DEV split where gold covers that rule:
`q_ev = a / (a + b)`. Gold TEST pairs never enter q_ev or the fit.

| Rule | Type | Hand check true / false | Dev true / false | q_ev | Points | Hand-check source |
|---|---|---|---|---|---|---|
| LOC_CITY_ELSEWHERE | location | 0 / 12 | 0 / 2 | 0.062 | 195 | cleaning/geo_identity/handcheck_location.csv |
| LOC_COORDS_FAR | location | 14 / 20 | 2 / 8 | 0.370 | 1,367 | audit/geo/hand_check_verdicts.csv |
| LOC_DISPUTED_OR_LOW | location | - | 1 / 1 | 0.500 | 186 | gold dev only |
| LOC_MEDIUM | location | - | 3 / 1 | 0.667 | 449 | gold dev only |
| LOC_HIGH | location | - | 37 / 1 | 0.950 | 7,762 | gold dev only |
| EXISTS_DEFAULT | existence | - | 60 / 0 | 0.984 | 9,959 | gold dev only |
| G_no (refers out / not offered) | service | 1 / 14 | 1 / 0 | 0.167 | 20 | cleaning/claims/out/handcheck.json D |
| G_else (about another facility) | service | 6 / 17 | 0 / 2 | 0.259 | 29 | handcheck.json A |
| G_scope (single-specialty name) | service | 67 / 44 | 0 / 0 | 0.602 | 341 | REPORT.md F4 |
| G_strong | service | - | 9 / 0 | 0.909 | 4,151 | gold dev only |
| G_mod | service | - | 10 / 2 | 0.786 | 4,663 | gold dev only |
| G_weak (G_nonspec, G_amb) | service | - | 2 / 0 | 0.750 | 382 | gold dev only |
| G_tag (specialty tag only) | service | - | 0 / 1 | 0.333 | 1,213 | gold dev only |
| ATTR_OTHER_FACILITY | sentence | 6 / 17 | - | 0.280 | 9,506 | handcheck.json A |
| ATTR_AMBIGUOUS | sentence | 4 / 7 | - | 0.385 | 5,922 | handcheck.json B |
| ATTR_UNFLAGGED | sentence | 18 / 0 | - | 0.950 | 454,070 | handcheck.json C |
| PHONE_DIRECTORY (held in 3+ cities) | phone | 12 / 33 | - | 0.277 | 292 | s5_trust.py docstring (ID5) |
| PHONE_UNCHECKED | phone | - | - | 0.500 | 9,172 | no check |
| EMAIL_PLACEHOLDER | email | deterministic | - | 0.010 | 360 | Cloudflare placeholder, not an address |
| EMAIL_UNCHECKED | email | - | - | 0.500 | 8,152 | no check |

Attribution weights (blame and credit). Sources are attached per record, not per claim, so a data point of
record r is attributed to all of r's domains with weight
`w_sd = sum over r's URLs in domain s of kind_weight(kind) x class_multiplier(profile, class)`, normalised
to sum to 1 per record and profile. Profiles: identity (location, existence), service (service claims),
attribution (sentences), contact (phone, email). Kind weights: about 1.0, list 0.5, unverified 0.3, except
for sentence attribution: about 0.7, list 2.0, unverified 1.0. Class multipliers (unlisted = 1.0):
identity: official, official_like, government 2; maps 1.5; social 0.7; research, news, docs 0.5.
service: official, official_like, government 1.5; research 1.2; business directory 0.7; social 0.7; maps 0.3.
attribution: research 2; docs, news, insurance/scheme lists, wikipedia 1.5; official 0.7; social 0.7; maps 0.3.
contact: aggregators and business directories 2; official 1.5; maps 1.5; research and wikipedia 0.2.
These are design choices, not fitted. Where the Goal 3 page check found a sentence on a fetched page, that
sentence (and any service claim citing it) is attributed to that page's domain only; where a fetched page
did not contain it, that domain is dropped from the sentence's weights (6,121 data points changed).

Fit (pipelines/source_scoring/s5_fit.py), iterated to convergence (12 iterations, max change below 1e-6):
1. Source support of a point: `sigma_d = sum_s w_sd rho_s`.
2. Truth of a point: `logit q_d = logit q_ev + GAMMA (logit sigma_d - mean logit sigma of its type)`, GAMMA = 1.
   Gold DEV verdicts are fixed at 0.97 (true) or 0.03 (false); placeholder emails at 0.01.
3. Credit and blame: with fitting weight `strength_d` (gold 1.0; location, service, phone, email rules 0.3;
   all sentences of one record share 1.0; existence and unchecked phone/email 0), each domain gets
   `credit_s = sum_d strength_d q_d w_sd` and `blame_s = sum_d strength_d (1 - q_d) w_sd`.
4. Reliability: `rho_s = (KAPPA m_c + credit_s) / (KAPPA + credit_s + blame_s)`, KAPPA = 10, where the class
   prior mean is `m_c = (1 + class credit) / (2 + class credit + class blame)`. Domains seen in few records
   stay near their class mean. The 90% interval is the 5th to 95th percentile of
   Beta(KAPPA m_c + credit_s, KAPPA (1 - m_c) + blame_s).
The full EM split (by w x rho) was tried first and is not identifiable here: facebook.com, cited by 8,840
records, absorbed all credit and reached 0.999. The weight-only split above is what the challenge text
describes: a true or false point updates all sources of its record, weighted by kind and class.

Final data-point score. Unverified: `score = expit(logit q_ev + GAMMA (logit sigma_d - mean logit sigma))`,
90% interval `expit(s +- 1.645 sqrt(1/a + 1/b + GAMMA^2 sum_s w_sd^2 (1/alpha_s + 1/beta_s)))`.
Verified by gold (dev or test): true 0.97 [0.90, 0.995], false 0.03 [0.005, 0.10]. Placeholder email: 0.01
[0.001, 0.03]. Audit rules never set `verified_*`: they only move q_ev, by their measured precision.

## Results (from evaluation.json and the tables above)

- Domain reliabilities are tightly spread: mean 0.869, sd 0.018, range 0.773 to 0.927. 10,212 of 10,951
  domains appear in fewer than 5 records, so their score is mostly the class prior.
- Held-out test (gold TEST split, not used in the fit): service claims n = 29 (23 true, 6 false): AUC
  baseline without sources 0.826 (90% 0.689-0.946), model 0.819 (0.666-0.944), sources only 0.493
  (0.282-0.694). Locations n = 56 (46 true, 10 false): baseline 0.770 (0.624-0.905), model 0.802
  (0.643-0.934), sources only 0.696 (0.547-0.828); true rate by source-support tercile 13/19, 15/18, 18/19.
  Source reliability adds a little for location and nothing measurable for service claims.
- Goal 3 page check (385 distinct URLs, 258 with text, 6,364 sentence tests): share of tested sentences found
  on the page they are attributed to (exact or partial_ratio >= 90): official about pages 9.6%
  (277 / 2,891), aggregator about pages 4.9% (38 / 783), list pages 1.5%, government 1.2%, research 0.8%;
  35 of 88 government URLs were unreachable from this machine (recorded as unreachable, not as false).

## Limitations

- Gold is small: 176 pairs, of which only 29 test service pairs and 56 test locations are informative.
  The 90% intervals on the AUCs are 26 to 41 points wide.
- Record-level attribution confounds source quality with record breadth. Records with few URLs are cleaner
  (PROV-02: 6.9% vs 49.7% contamination), and social pages dominate small records, so social scores highest.
  Read a domain's score as "records citing this source tend to be right", not "this page is accurate".
- Kind weights and class multipliers are hand-set; GAMMA = 1 assumes sources and evidence are independent.
- Sentences in the record are model paraphrases of the pages, so exact and fuzzy matching under-counts
  support; token coverage (>= 70% of content words) is reported as a looser second measure (24.2% overall).
- Phones and emails other than directory numbers and placeholders have no check; their score is 0.5
  moved by sources.
- Hand-check counts behind each rule are 11 to 111 items; the rule q_ev intervals reflect that.
- The grade table carries the known G_nonspec leaks; scores inherit them.

## Licence

The facility data comes from the Virtue Foundation share on the Databricks Marketplace and is used under the
Marketplace consumer terms: team use only, keep the repository private, do not publish these tables. The
India Post PIN directory and NFHS-5 district indicators are under the Government Open Data Licence - India
(GODL-India).
