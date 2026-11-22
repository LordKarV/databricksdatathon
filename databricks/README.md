# Referral Saathi in Unity Catalog

The project's tables in Unity Catalog, so the planner dashboard, the Genie space and the app read one copy of
the data. Everything lives in schema `workspace.referral_saathi`. Nothing is written to the Marketplace catalog
`databricks_virtue_foundation_dataset_dais_2026`.

Loaded on 2026-11-21 from `derived/v1` (not v2), on warehouse `6a2f5637720a2c17`, profile `vf`. All 57
tables passed verification (results at the end).

Licence: tables built from Virtue Foundation records are for the team workspace only (Marketplace consumer
terms). Do not share the schema outside the team. The official lists NABH, NMC and MoHFW trauma are restricted:
only per-facility matched facts with a citation are loaded (`facility_list_facts`), never the lists.

## Files

| File | What |
|---|---|
| `tables.yaml` | Manifest: one entry per table with source file (or builder), primary key, spot column, table and column comments |
| `load_tables.py` | Loader: stage, upload to the volume, CREATE OR REPLACE TABLE from read_files, comments, verification |
| `build_staging.py` | Builders for tables with no ready parquet: services, pathways, test metrics, PMNDP state names, list facts. `python build_staging.py` runs its self-check |
| `../build/databricks_staging/` | Staged parquet (CSV conversions and builder output) and `verify_results.json`. Gitignored |

## Objects

- Schema `workspace.referral_saathi`, with a comment describing it.
- Volume `workspace.referral_saathi.uploads` (managed). One folder per table, holding `<table>/<table>.parquet`,
  the exact file each table was built from.
- 57 managed Delta tables, listed below. Each has a table comment that names its source file and primary
  key; 104 columns carry comments taken from the READMEs (derived/v1/README.md, kb/*/*.md,
  viz/dashboard/DASHBOARD_SPEC.md). Primary keys are documented and verified, not declared as constraints.

## How it loads

For each manifest entry, `load_tables.py`:

1. Stages the source. A parquet file is uploaded as is. A CSV is converted to parquet with duckdb first, so
   types are fixed locally and not re-inferred by Spark. A `build` entry calls the function of that name in
   `build_staging.py`, which always rebuilds from the current local files.
2. Uploads it with `databricks fs cp --overwrite` to `/Volumes/workspace/referral_saathi/uploads/<table>/<table>.parquet`.
3. Runs `CREATE OR REPLACE TABLE workspace.referral_saathi.<table> COMMENT ... AS SELECT * EXCEPT (_rescued_data)
   FROM read_files(<that file>, format => 'parquet')` through the SQL Statement API (`/api/2.0/sql/statements`).
4. Sets column comments in one `ALTER TABLE ... ALTER COLUMN a COMMENT ..., b COMMENT ...` statement.
5. Verifies: the row count equals the local file, the primary key has no duplicates and no nulls (columns in
   `nullable_key` may be null), and the value of the spot column equals the local file on 3 rows (first,
   middle and last by key). Results are merged into `build/databricks_staging/verify_results.json`.

Every step overwrites, so a re-run gives the same tables. One failing table is reported and the rest still load;
the exit code is 1 if any table failed.

## How to reload

Run from the project root. pyyaml is not in `.venv`, so uv adds it on top (offline, from its cache):

```
export DATABRICKS_CONFIG_PROFILE=vf
L="uv run --offline --with pyyaml --python .venv/bin/python python databricks/load_tables.py"
$L                                   # all 57 tables
$L --only claims,facility_trust      # named tables
$L --only kb                         # a group: derived, kb, dashboard or lists
$L --local-only                      # stage and check keys locally, send nothing
```

When `derived/v2` is finished, one command reloads every derived table from it under the same names:

```
$L --only derived --derived derived/v2
```

A table that is new in v2 needs one manifest entry (`file: "{derived}/<name>.parquet"`, a key and a
description), then `$L --only <name> --derived derived/v2`. If a v2 file is missing, that table fails and the
others still load.

## Choices worth knowing

- Names follow DASHBOARD_SPEC where it names a table (`facility_location`, `pair_scores`, `geo_facility`,
  `facility_list_facts`, `model_test_metrics` ...), so its SQL runs with bare names and
  `--dataset-catalog workspace --dataset-schema referral_saathi`.
- Service ids: `grades` uses the cleaning/claims tags (trauma, csection, burns), `pair_scores`,
  `claims_funnel_pairs` and `facility_list_facts` use the dashboard ids (trauma_emergency, emergency_csection,
  burn_care), and the kb tables use taxonomy v1.1 ids. `services.aliases` maps between them.
- `pmndp_state` keeps the published lower-case `state` and adds `state_lgd` (LGD spelling, joins all 36 states
  to `geo_state_density.stname`), as DASHBOARD_SPEC asks.
- `model_test_metrics` is every leaf of the two JSON files as (source_file, path, value_num, value_text). It is
  quoted, not recomputed; the dashboard picks the paths it needs.
- `facility_list_facts`: NABH rows are facility-level (service null). LaQshya gives one row per certified
  department with `valid_to`, and `status` says valid or expired as of 2026-11-21. NMC gives one facility-level
  row per matched college plus one row per service label from its approved courses. MoHFW trauma (20),
  e-RaktKosh (388) and Goa PMNDP (1) are one row each.
- Known data quirks, kept as is: `open_data_facts` has one exact duplicate row in the source (an OSM speciality
  tag repeats "Bone and Joints"), so its key has 1 duplicate locally and in UC. `specialty_map` has one row
  with a null specialty (the empty specialties value). `geo_district`, `dialysis_burden_district` and
  `nfhs_lgd_crosswalk` have `dist_lgd = 0` for Muzaffarabad and Mirpur, so their key includes the district name.

Not loaded, on purpose: the CSV copies in derived/v1 (same rows as the parquet), the JSON stats files, crawl
page text (`kb/crawl/pages.parquet`), the full OSM and Wikidata dumps and `opendata_not_in_vf`, the LLM hour
candidate tables in web_evidence and vf_details, the taxonomy hand-check samples, and the full official lists.
Add any of them with one manifest entry.

## Checks against DASHBOARD_SPEC

Run on the loaded tables on 2026-11-21, all equal to the numbers the spec quotes: records with any stated
hours 6,074; mentioned pairs in the funnel 7,969; hot dialysis districts 69; high-confidence locations 7,762;
directory phones 292; Bihar records per million 1.948; `pmndp_state.state_lgd` joins 36 of 36 states.

## Tables

### Derived v1 tables (group derived)

- `data_point_scores`: 518,191 rows, key (dp_id), from `{derived}/data_point_scores.parquet`. One row per data point in the Virtue Foundation records (location, existence, facility-service claim, claim sentence attribution, phone, email) with a score in [0, 1] that it is true, a 90% interval and the evidence behind it.
  Columns: dp_id, dp_type, unique_id, claim_id, service, field, original_value, score, score_lo, score_hi, status, reason_codes, evidence_refs, rule, ... (20 columns).
- `facility_trust`: 9,959 rows, key (unique_id), from `{derived}/facility_trust.parquet`. One row per facility record: existence, location and attribution scores, service claim counts, source support and plain-English drivers. overall_score = existence x location x attribution.
  Columns: unique_id, name, existence_score, existence_status, location_score, location_lo, location_hi, location_status, location_reason_codes, n_sentences, attribution_score, n_sentences_other_facility, n_service_claims, service_score_mean, ... (22 columns).
- `source_domains`: 10,951 rows, key (domain), from `{derived}/source_domains.parquet`. One row per registrable source domain cited by the records, with a reliability posterior (records citing this source tend to be right), its 90% credible interval and the counts behind it.
  Columns: domain, source_class, alpha, beta, reliability, ci05, ci95, credit, blame, class_prior_mean, n_records, n_urls, n_distinct_urls, share_about, ... (27 columns).
- `source_classes`: 16 rows, key (source_class), from `{derived}/source_classes.parquet`. One row per source class (official, government, social, maps ...): pooled reliability with 90% interval, domain reliability spread and verified counts.
  Columns: source_class, n_domains, n_urls, n_records, reliability, ci05, ci95, median_domain_reliability, domain_reliability_p10, domain_reliability_p90, n_verified_true, n_verified_false, effective_true, effective_false (14 columns).
- `source_urls`: 158,444 rows, key (unique_id, url_pos), from `{derived}/source_urls.parquet`. One row per (record, URL) from the records' source_urls, with host, domain, class, kind (about, list, unverified), domain reliability and the page-check result.
  Columns: unique_id, url_pos, url, host, domain, source_class, url_kind, n_records_url, domain_reliability, ci05, ci95, page_fetch_status, page_sentences_tested, page_sentences_supported (14 columns).
- `source_page_checks`: 6,492 rows, key (unique_id, url, claim_id), from `{derived}/source_page_checks.parquet`. One row per (fetched URL, claim sentence) test: was the sentence found on the page it is attributed to. URLs with no usable page have one row with claim_id null.
  Columns: unique_id, url, domain, source_class, url_kind, stratum, fetch_status, page_chars, claim_id, field, is_service_sentence, attribution, exact, partial_ratio, ... (18 columns).
- `evidence_rules`: 20 rows, key (rule), from `{derived}/evidence_rules.parquet`. One row per evidence rule with its hand-check and gold-dev counts, Beta(a, b) and q_ev = a / (a + b).
  Columns: rule, dp_type, handcheck_true, handcheck_false, dev_true, dev_false, a, b, q_ev, citation, n_points (11 columns).
- `gold_pairs`: 176 rows, key (pair_id), from `{derived}/gold_pairs.parquet`. One row per gold facility-service pair (176) with merged web verdicts and its frozen dev or test split.
  Columns: pair_id, unique_id, service, stratum, split, n_labels, exists, location_ok, service_verdict, confidence, evidence_urls, label_files (12 columns).
- `facility_location`: 9,959 rows, key (unique_id), from `{derived}/facility_location.parquet`. One row per facility record: cleaned ranking point, radius, location confidence and notes, LGD district and NFHS key.
  Columns: unique_id, name, address_city, address_stateOrRegion, pin, raw_lat, raw_lon, raw_coords_to_pin_km, p_src, loc_src, loc_lat, loc_lon, loc_radius, loc_conf, ... (27 columns).
- `record_trust`: 9,959 rows, key (unique_id), from `{derived}/record_trust.parquet`. One row per facility record: cleaned phones and emails, website class, trust flags and trust level. trust_flags and scale_flags are arrays (use array_contains).
  Columns: unique_id, name, display_phones, chain_helplines, emails_clean, email_issue, website_domain, website_class, trust_flags, trust_reasons, scale_flags, n_services_claimed, trust_level (13 columns).
- `facility_groups`: 9,959 rows, key (unique_id), from `{derived}/facility_groups.parquet`. One row per facility record: duplicate group, canonical flag, possible same-site links and co-located units.
  Columns: unique_id, name, dup_group_id, is_canonical, group_size, possible_same_site, co_located_with, group_location_disagrees (8 columns).
- `pin_gazetteer`: 19,713 rows, key (pin), from `{derived}/pin_gazetteer.parquet`. One row per India Post PIN: state, district, centroid and radius.
  Columns: pin, state, district, districts, lat, lon, src, radius_km, n_used, n_fac, dir_lat, dir_lon, d_consensus_km (13 columns).
- `place_gazetteer`: 147,345 rows, key (state, name, kind), from `{derived}/place_gazetteer.parquet`. One row per (state, place name, kind) with a centroid and spread.
  Columns: state, name, lat, lon, spread_km, n_points, kind (7 columns).
- `claims`: 469,498 rows, key (claim_id), from `{derived}/claims.parquet`. One row per claim sentence from the records' procedure, capability, equipment and description fields, with attribution (own, other facility ...), services named and non-offer cues. claim_id = uid8:field4:idx.
  Columns: claim_id, unique_id, field, idx, text, attribution, foreign_names, sibling_names, self_names, places_other_state, places_other_district, context, dup_in_record, services, ... (27 columns).
- `specialties`: 117,964 rows, key (unique_id, spec), from `{derived}/specialties.parquet`. One row per (record, specialty value) from the records' specialties field.
  Columns: unique_id, spec, n_raw (3 columns).
- `grades`: 10,799 rows, key (unique_id, service), from `{derived}/grades.parquet`. Canonical grade table (grader v2, other-facility quarantine on): one row per (record, service) the text mentions, with grade, rule, counts, corroboration and risk flags and cited claim ids. Service keys are the cleaning/claims tags (trauma, csection, burns ...).
  Columns: unique_id, service, name, facilityTypeId, grade, rule, rank, n_mentions, n_own, n_own_distinct, n_specific, n_ambiguous, n_other_facility, n_nonoffer, ... (51 columns).
- `grades_v1`: 10,799 rows, key (unique_id, service), from `{derived}/grades_v1.parquet`. Grader v1 reference grades (frozen before the web verdicts), same columns as grades.
  Columns: unique_id, service, name, facilityTypeId, grade, rule, rank, n_mentions, n_own, n_own_distinct, n_specific, n_ambiguous, n_other_facility, n_nonoffer, ... (51 columns).

### Knowledge base tables (group kb)

- `services`: 37 rows, key (service_id), from `build_staging.services()`. Canonical referral service taxonomy v1.1: 36 services in 11 categories plus 1 candidate, with names, definition, urgency, required capabilities, evidence, IPHS 2022 levels, phrase routing and answer_mode. Nested values are JSON strings.
  Columns: service_id, category_id, category_name, name_en, urgency_profile, urgency_window, aliases, alias_note, names, definition, urgency, required_capabilities, supporting_evidence, contradicting_evidence, ... (29 columns).
- `service_coverage`: 37 rows, key (service), from `kb/taxonomy/out/coverage.csv`. Per-service facility counts over the 9,959 usable records: any mention, text positive, 2+ fields, specialty only, states, sentences, low_coverage flag.
  Columns: service, in_taxonomy, sentences, facilities_any, facilities_2plus_fields, states_any, facilities_text, facilities_specialty_only, facilities_text_positive, facilities_text_2plus_fields, sentences_nonoffer_cue, sentences_other_facility, sentences_with_quantity, low_coverage (14 columns).
- `specialty_map`: 2,933 rows, key (specialty), from `kb/taxonomy/specialty_map.csv`. All 2,933 distinct raw specialties strings mapped to a service id (or a ; list), too_general, out_of_scope or not_a_service, with method, confidence, facility count and prereq_for.
  Columns: specialty, normalized, service_id, method, confidence, n_facilities, n_facilities_all_rows, prereq_for, basis (9 columns).
- `specialty_evidence_weights`: 1,346 rows, key (specialty, service), from `kb/taxonomy/specialty_evidence_weights.csv`. 1,346 (specialty value, service) pairs with the measured share of tagged facilities that have positive text for the service, shrunk toward the group rate; use instead of a 0/1 specialty label.
  Columns: specialty, service, kind, k_text_positive, n_facilities, pooled_rate, weight, k_fit_half, n_fit_half, weight_fit_half, k_test_half, n_test_half (12 columns).
- `claim_service_matches`: 64,670 rows, key (claim_id, service), from `kb/taxonomy/out/lexicon_matches.parquet`. One row per (claim sentence, taxonomy service) lexicon match (v1.1), with attribution, sentence kind and non-offer cue.
  Columns: claim_id, unique_id, field, service, attribution, kind, dup_in_record, nonoffer_cue, negation_extra, quantity_text (10 columns).
- `web_site_identity`: 6,770 rows, key (target_id, unique_id), from `kb/web_evidence/out/site_identity.parquet`. One row per (crawl target, record): does the website belong to the facility. Name, PIN and locality evidence with quote and URL, conflicts, confidence (high, medium, low, none) and attributable.
  Columns: target_id, unique_id, kind, site, site_status, site_spam_injected, n_pages, has_services_page, name_how, name_quote, name_field, name_url, pin_found, pin_quote, ... (29 columns).
- `web_page_identity`: 30,517 rows, key (page_id, unique_id), from `kb/web_evidence/out/page_identity.parquet`. Site identity evidence per (crawled page, record).
  Columns: page_id, path, unique_id, parked, name_how, name_quote, name_field, pin_quote, pin_field, loc_quote, loc_field, other_pins, target_id, final_url, ... (15 columns).
- `web_services`: 153,160 rows, key (unique_id, page_id, seg_start, service_id, field), from `kb/web_evidence/out/web_services.parquet`. One row per (record, page, line, service) a facility website states, with an exact quote, URL and fetch time. Use only rows with attributable and positive; prefer strength = strong.
  Columns: unique_id, service_id, quote, url, final_url, fetched_at, role, field, line_kind, negated, nonoffer_cue, weak_cue, kind, edu, ... (28 columns).
- `web_service_summary`: 20,886 rows, key (unique_id, service_id), from `kb/web_evidence/out/web_service_summary.parquet`. One row per (record, service) over attributable website rows: web_positive, web_positive_strong, counts and the best quote and URL.
  Columns: unique_id, service_id, web_positive, web_positive_strong, n_positive_rows, n_positive_quotes, n_pages_positive, n_negated_rows, n_rows, positive_on_services_page, positive_sentence, best_quote, best_url, best_field, ... (18 columns).
- `web_hours`: 43,540 rows, key (fact_id), from `kb/web_evidence/out/web_hours.parquet`. Hours facts from facility websites: 24x7 statements by scope, OPD and other schedules, dialysis shifts, 24x7 doctor. vf_details schema plus page columns. Use when attributable, status in (ok, flagged) and polarity = positive.
  Columns: fact_id, unique_id, segment_id, fact_type, attribute, value_num, value_text, polarity, status, flags, quote, match, source_text, kind, ... (28 columns).
- `web_facts`: 41,191 rows, key (fact_id), from `kb/web_evidence/out/web_details.parquet`. Detail facts from facility websites: beds by unit, equipment counts, accreditation, empanelment, ambulance, blood centre, free or government care, staffing, emergency phone listed. Each with an exact quote and URL. Use when attributable, status in (ok, flagged) and polarity = positive.
  Columns: fact_id, unique_id, segment_id, fact_type, attribute, value_num, value_text, polarity, status, flags, quote, match, source_text, kind, ... (28 columns).
- `web_facility_details`: 17,908 rows, key (unique_id, fact_type, attribute), from `kb/web_evidence/out/web_facility_details.parquet`. One row per (record, fact_type, attribute) from website hours and details, same columns as facility_details plus best_url.
  Columns: unique_id, fact_type, attribute, n_ok, n_flagged, n_excluded, n_usable, n_negative, n_neutral, value_num, n_distinct_values, value_text, page_fields, methods, ... (19 columns).
- `open_data_matches`: 17,662 rows, key (unique_id, source), from `kb/opendata/vf_opendata_match.parquet`. Best OpenStreetMap and best Wikidata candidate for each facility record, with match features, tier (high, medium, conflict, none), match_conf, source_url and the source's own fields. OSM data is ODbL.
  Columns: unique_id, vf_name, vf_type, vf_city, vf_district, vf_state, vf_pin, vf_loc_conf, vf_address, source, source_id, cand_name, cand_kind, cand_place, ... (73 columns).
- `open_data_facts`: 6,001 rows, key (unique_id, source, field, value), from `kb/opendata/vf_opendata_facts.parquet`. Long table of facts from matched OSM and Wikidata features (high and medium matches only): field, value, evidence, source_url, match tier and confidence, licence, observed_at.
  Columns: unique_id, source, source_id, source_url, match_tier, match_conf, licence, field, value, evidence, observed_at (11 columns).
- `facility_details`: 26,046 rows, key (unique_id, fact_type, attribute), from `kb/vf_details/out/facility_details.parquet`. One row per facility x (fact_type, attribute) from the provided records' text: support counts, the value stated most often and the best quote (hours, unit beds, equipment, staffing, accreditation, empanelment, ambulance, blood centre).
  Columns: unique_id, fact_type, attribute, n_ok, n_flagged, n_excluded, n_usable, n_negative, n_neutral, value_num, n_distinct_values, value_text, fields, methods, ... (19 columns).
- `vf_facts`: 42,036 rows, key (fact_id), from `kb/vf_details/out/facts.parquet`. One row per quote-backed fact from the provided records (regex, LLM or typed field). Use a fact only when status is ok or flagged and polarity is positive.
  Columns: fact_id, unique_id, claim_id, field, fact_type, attribute, value_num, value_text, polarity, status, flags, quote, match, source_text, ... (19 columns).
- `crawl_sites`: 9,405 rows, key (target_id), from `kb/crawl/sites.parquet`. One row per crawl target website: status (ok, dns_fail, hijacked_spam, parked ...), pages stored, redirects and quality flags. No page text.
  Columns: target_id, site, domain, kind, shared, unique_ids, site_status, finished_at, n_pages_stored, n_page_attempts, site_home_final_url, site_http_fallback, site_redirect_same_org, site_tls_invalid, ... (20 columns).
- `care_pathways`: 7 rows, key (pathway_id), from `build_staging.care_pathways()`. The 7 referral care pathways (stemi, major_trauma, obstetric_emergency, burns, sick_newborn, snakebite, dialysis_start): urgency, objective, clock start, sources, open questions. Facility-level routing only, not clinical advice.
  Columns: pathway_id, n_stages, n_rules, name, service, urgency, objective, clock_start, sources, open_questions, decisions (11 columns).
- `pathway_stages`: 14 rows, key (pathway_id, stage_id), from `build_staging.pathway_stages()`. One row per pathway stage in order (the last is definitive): required capability tags (requires_all, and one from each requires_any group), facility levels, time window and dwell minutes with their basis (guideline or assumption).
  Columns: pathway_id, stage_order, stage_id, is_last_stage, window_minutes, window_from, window_basis, dwell_typical_minutes, dwell_basis, name, purpose, actions, requires_all, requires_any, ... (21 columns).
- `pathway_rules`: 52 rows, key (pathway_id, rule_id), from `build_staging.pathway_rules()`. One row per pathway rule: add_stop_only_if, skip_stop_if, never_delay, before_transfer, refer_if or caution, with condition thresholds, basis, source and quote.
  Columns: pathway_id, rule_id, definitive_travel_minutes_gt, type, stage, when, then, condition, basis, source, quote, why (12 columns).
- `pathway_capabilities`: 26 rows, key (capability_id), from `build_staging.pathway_capabilities()`. The 26 capability tags the pathway stages need, with meaning, evidence words and the taxonomy service they map to.
  Columns: capability_id, meaning, evidence_words, used_by, used_by_rules, kb_status, kb_service (7 columns).

### Dashboard inputs (group dashboard)

- `pair_scores`: 69,713 rows, key (unique_id, service), from `model/proto/fusion/pair_scores.parquet`. One row per (record, service) for the 7 gold services from the fusion prototype: p_s with range, band (Likely, Unverified, Unlikely), text level T, location and existence scores.
  Columns: unique_id, service, name, z_raw, z_cal, p_s, p_s_lo, p_s_hi, band, band_reason, p_s_without_cited, T, C, N, ... (20 columns).
- `pair_features`: 69,713 rows, key (unique_id, service), from `model/proto/evidence/pair_features.parquet`. Evidence features per (record, service) behind pair_scores.
  Columns: unique_id, service, T, C, N, n_atoms, n_units_own, n_fields_own, n_rejected, n_rejected_ownership, n_tagged_sentences, cited_atom_ids, rejected_atom_ids, t_without_cited, ... (38 columns).
- `facility_scores`: 9,959 rows, key (unique_id), from `model/proto/fusion/facility_scores.parquet`. Location and existence scores per record from the fusion prototype.
  Columns: unique_id, p1_lat, p1_lon, p2_lat, p2_lon, loc_radius_km, p_l, p_l_lo, p_l_hi, z_cal_location, p_e, p_e_lo, p_e_hi, z_cal_existence, ... (15 columns).
- `geo_facility`: 9,959 rows, key (unique_id), from `viz/geography/data/_cache/facilities.parquet`. One row per record with the LGD state (stname) and district (dtname) of its cleaned point, settlement class (degurba) and per-service claimed and corroborated flags. Dashboard state and district filters come from here.
  Columns: unique_id, name, state_final, district, loc_lat, loc_lon, loc_conf, nfhs_state_ut, nfhs_district_name, is_canonical, operatorTypeId, facilityTypeId, row, col, ... (43 columns).
- `geo_facility_site`: 9,959 rows, key (unique_id), from `viz/geography/verify/out/records.parquet`. One row per record with the crawl's own-site flag (own_site) and per-service evidence flags (dashboard tile 6.4).
  Columns: unique_id, loc_lat, loc_lon, state_final, operatorTypeId, dtname, stname, dist_lgd, trauma_claim, trauma_web, trauma_osm, trauma_tcf, trauma_lq, trauma_conf, ... (27 columns).
- `geo_state_density`: 36 rows, key (stname), from `viz/geography/data/s1_state.csv`. Records per million people by state or UT with a 95% Poisson interval (geography story 1). Aggregate.
  Columns: stname, label, pop, n_districts, records, per_m, per_m_lo, per_m_hi, child_u5_who_are_stunted_height_for_age_18_pct, hh_member_covered_health_insurance_pct (10 columns).
- `geo_state_access`: 36 rows, key (stname), from `viz/geography/data/s4_state.csv`. Share of people within 60 minutes of confirmed trauma care, any record and any clinic, by state (geography story 4). Columns any and map are reserved words: backtick them.
  Columns: stname, any, claim, corr, corr_hi, corr_lo, map, pop, n_corr, n_claim, median_min_map, median_min_corr, label, people_outside_corr (14 columns).
- `geo_district`: 784 rows, key (dist_lgd, dtname), from `viz/geography/data/s1_district.csv`. One row per LGD district (784): population, records, records per million (geography story 1).
  Columns: dist_lgd, dtname, stname, nfhs_state, nfhs_district, pop, records, per_m, cx, cy (10 columns).
- `geo_dialysis_district`: 704 rows, key (nfhs_state, nfhs_district), from `viz/geography/data/s2_district.csv`. One row per NFHS district: dialysis need proxy (ncd, in percent), confirmed dialysis per million, share within 60 minutes and the hot flag (geography story 2).
  Columns: nfhs_state, nfhs_district, pop, ncd, w15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct, m15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct, w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct, m15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct, burden_q, n_claim, n_corr, corr_per_m, corr_per_m_lo, corr_per_m_hi, ... (20 columns).
- `geo_csection_district`: 704 rows, key (nfhs_state, nfhs_district), from `viz/geography/data/s3_district.csv`. One row per NFHS district: caesarean rate band against claimed, corroborated and LaQshya facilities (geography story 3).
  Columns: nfhs_state, nfhs_district, pop, wra, births_delivered_by_csection_5y_pct, births_in_a_public_fac_that_were_delivered_by_csection_5y_pct, births_in_a_public_fac_that_were_delivered_by_csection_5y_pct_flag, births_in_a_private_fac_that_were_delivered_by_csection_5y_pct, births_in_a_private_fac_that_were_delivered_by_csection_5y_pct_flag, institutional_birth_5y_pct, band, n_claimed, n_corroborated, n_laqshya, ... (16 columns).
- `geo_settlement`: 3 rows, key (code), from `viz/geography/data/s5_classes.csv`. Within an hour of confirmed care, by settlement class (3 rows, geography story 5).
  Columns: code, cls, pop, records, trauma_corr, dialysis_corr, csection_corr, pop_share, records_share, trauma_corr_share, dialysis_corr_share, csection_corr_share, trauma_within60, trauma_median_min, ... (18 columns).
- `dialysis_burden_district`: 784 rows, key (dist_lgd, district), from `viz/journeys/data/s5_district_dialysis.csv`. Weekly road km and hours for three dialysis sessions, by district and evidence tier (journeys story 5).
  Columns: state, district, dist_lgd, population, lat, lon, median_weekly_km_claimed, median_weekly_hours_claimed, median_weekly_km_graded, median_weekly_hours_graded, median_weekly_km_corroborated, median_weekly_hours_corroborated, road_estimate_valid (13 columns).
- `claims_funnel_pairs`: 9,244 rows, key (unique_id, service), from `viz/claims/data/s3_pairs.csv`. One row per (record, service) with any mention or outside evidence: mentioned, fields2, prereq, has_site, web, listed (claims story 3 evidence ladder).
  Columns: unique_id, service, T, P, mentioned, fields2, prereq, has_site, web, listed (10 columns).
- `facility_hours`: 9,959 rows, key (unique_id), from `viz/claims/data/s6_facility_hours.csv`. One row per record: any stated hours, 24x7 emergency and clock schedule from the dataset, the website and OSM (claims story 6).
  Columns: unique_id, dataset_any_hours, dataset_any24, dataset_emerg24, dataset_schedule, web_any_hours, web_any24, web_emerg24, web_schedule, osm_any_hours, osm_any24, osm_emerg24, osm_schedule, has_site (14 columns).
- `pmndp_state`: 36 rows, key (state), from `build_staging.pmndp_state()`. Public dialysis centres (PMNDP, NHSRC state counts) against records that mention dialysis, by state (claims story 4). state is lower case as published; state_lgd is the LGD upper-case spelling for the state filter.
  Columns: nhsrc_functional_districts, nhsrc_functional_centres, state, vf_records, vf_dialysis, vf_public_dialysis, state_lgd (7 columns).
- `planner_plans`: 3,430 rows, key (origin_set, origin_id, pathway), from `viz/journeys/data/plans_best.csv`. Best referral plan per (sampled origin, pathway) from the planner with stub probabilities (journeys stories 1, 2, 6): 150 PIN origins per state in Bihar, Uttar Pradesh and Maharashtra plus benchmark points.
  Columns: origin_set, origin_id, lat, lon, label, state, pathway, best_type, n_plans, first_name, first_eta, first_low, first_high, first_km, ... (36 columns).
- `nfhs_lgd_crosswalk`: 785 rows, key (dist_lgd, dtname), from `data/external/lgd_district_polygons/nfhs_lgd_crosswalk.csv`. LGD district to NFHS-5 district key, so NFHS-keyed tables filter by LGD district.
  Columns: dist_lgd, dtname, stname, nfhs_district, score, nfhs_by_post_offices, po_majority_share, nfhs_final, nfhs_how (9 columns).
- `model_test_metrics`: 2,615 rows, key (source_file, path), from `build_staging.model_test_metrics()`. Every value in the two published sealed-test files (model/review/stats/results.json and model/proto/fusion/test_metrics.json) as (source_file, JSON path, value). Quoted, never recomputed. Example path: pair_level_test.primary_target_all.auroc.WL_shipped.raw.
  Columns: source_file, path, value_num, value_text (4 columns).

### Official list facts (group lists)

- `facility_list_facts`: 3,062 rows, key (fact_id), from `build_staging.facility_list_facts()`. One row per (facility, official list, service) matched fact with its citation: NABH, LaQshya, NMC, MoHFW trauma care facilities, e-RaktKosh and Goa PMNDP. Per-facility matched facts only; the full lists (NABH, NMC, MoHFW trauma) are restricted and are not loaded. Service null = a facility-level fact (for example NABH).
  Columns: fact_id, list_slug, list_name, unique_id, service, status, list_record_id, listed_name, valid_to, match_method, match_score, citation_url, detail, licence_note, ... (15 columns).

## Verification results

| Table | Local rows | UC rows | Duplicate keys | Null keys | Spot column | Spots equal | Result |
|---|---|---|---|---|---|---|---|
| data_point_scores | 518,191 | 518,191 | 0 | 0 | score | 3/3 | pass |
| facility_trust | 9,959 | 9,959 | 0 | 0 | overall_score | 3/3 | pass |
| source_domains | 10,951 | 10,951 | 0 | 0 | reliability | 3/3 | pass |
| source_classes | 16 | 16 | 0 | 0 | reliability | 3/3 | pass |
| source_urls | 158,444 | 158,444 | 0 | 0 | domain | 3/3 | pass |
| source_page_checks | 6,492 | 6,492 | 0 | 0 | fetch_status | 3/3 | pass |
| evidence_rules | 20 | 20 | 0 | 0 | q_ev | 3/3 | pass |
| gold_pairs | 176 | 176 | 0 | 0 | service_verdict | 3/3 | pass |
| facility_location | 9,959 | 9,959 | 0 | 0 | loc_lat | 3/3 | pass |
| record_trust | 9,959 | 9,959 | 0 | 0 | trust_level | 3/3 | pass |
| facility_groups | 9,959 | 9,959 | 0 | 0 | dup_group_id | 3/3 | pass |
| pin_gazetteer | 19,713 | 19,713 | 0 | 0 | district | 3/3 | pass |
| place_gazetteer | 147,345 | 147,345 | 0 | 0 | lat | 3/3 | pass |
| claims | 469,498 | 469,498 | 0 | 0 | text | 3/3 | pass |
| specialties | 117,964 | 117,964 | 0 | 0 | n_raw | 3/3 | pass |
| grades | 10,799 | 10,799 | 0 | 0 | grade | 3/3 | pass |
| grades_v1 | 10,799 | 10,799 | 0 | 0 | grade | 3/3 | pass |
| services | 37 | 37 | 0 | 0 | category_id | 3/3 | pass |
| service_coverage | 37 | 37 | 0 | 0 | facilities_any | 3/3 | pass |
| specialty_map | 2,933 | 2,933 | 0 | 0 | service_id | 3/3 | pass |
| specialty_evidence_weights | 1,346 | 1,346 | 0 | 0 | weight | 3/3 | pass |
| claim_service_matches | 64,670 | 64,670 | 0 | 0 | kind | 3/3 | pass |
| web_site_identity | 6,770 | 6,770 | 0 | 0 | confidence | 3/3 | pass |
| web_page_identity | 30,517 | 30,517 | 0 | 0 | name_how | 3/3 | pass |
| web_services | 153,160 | 153,160 | 0 | 0 | quote | 3/3 | pass |
| web_service_summary | 20,886 | 20,886 | 0 | 0 | web_positive | 3/3 | pass |
| web_hours | 43,540 | 43,540 | 0 | 0 | value_text | 3/3 | pass |
| web_facts | 41,191 | 41,191 | 0 | 0 | attribute | 3/3 | pass |
| web_facility_details | 17,908 | 17,908 | 0 | 0 | value_text | 3/3 | pass |
| open_data_matches | 17,662 | 17,662 | 0 | 0 | tier | 3/3 | pass |
| open_data_facts | 6,001 | 6,001 | 1 | 0 | value | 3/3 | pass |
| facility_details | 26,046 | 26,046 | 0 | 0 | value_text | 3/3 | pass |
| vf_facts | 42,036 | 42,036 | 0 | 0 | value_text | 3/3 | pass |
| crawl_sites | 9,405 | 9,405 | 0 | 0 | site_status | 3/3 | pass |
| care_pathways | 7 | 7 | 0 | 0 | service | 3/3 | pass |
| pathway_stages | 14 | 14 | 0 | 0 | stage_order | 3/3 | pass |
| pathway_rules | 52 | 52 | 0 | 0 | type | 3/3 | pass |
| pathway_capabilities | 26 | 26 | 0 | 0 | kb_status | 3/3 | pass |
| pair_scores | 69,713 | 69,713 | 0 | 0 | p_s | 3/3 | pass |
| pair_features | 69,713 | 69,713 | 0 | 0 | T | 3/3 | pass |
| facility_scores | 9,959 | 9,959 | 0 | 0 | p_l | 3/3 | pass |
| geo_facility | 9,959 | 9,959 | 0 | 0 | stname | 3/3 | pass |
| geo_facility_site | 9,959 | 9,959 | 0 | 0 | own_site | 3/3 | pass |
| geo_state_density | 36 | 36 | 0 | 0 | per_m | 3/3 | pass |
| geo_state_access | 36 | 36 | 0 | 0 | corr | 3/3 | pass |
| geo_district | 784 | 784 | 0 | 0 | records | 3/3 | pass |
| geo_dialysis_district | 704 | 704 | 0 | 0 | share60 | 3/3 | pass |
| geo_csection_district | 704 | 704 | 0 | 0 | band | 3/3 | pass |
| geo_settlement | 3 | 3 | 0 | 0 | cls | 3/3 | pass |
| dialysis_burden_district | 784 | 784 | 0 | 0 | median_weekly_km_corroborated | 3/3 | pass |
| claims_funnel_pairs | 9,244 | 9,244 | 0 | 0 | mentioned | 3/3 | pass |
| facility_hours | 9,959 | 9,959 | 0 | 0 | dataset_any_hours | 3/3 | pass |
| pmndp_state | 36 | 36 | 0 | 0 | nhsrc_functional_centres | 3/3 | pass |
| planner_plans | 3,430 | 3,430 | 0 | 0 | best_type | 3/3 | pass |
| nfhs_lgd_crosswalk | 785 | 785 | 0 | 0 | nfhs_final | 3/3 | pass |
| model_test_metrics | 2,615 | 2,615 | 0 | 0 | value_text | 3/3 | pass |
| facility_list_facts | 3,062 | 3,062 | 0 | 0 | status | 3/3 | pass |
