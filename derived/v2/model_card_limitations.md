# Model card v2: dataset limitations (addendum, #103)

This note goes with `model_card.json` (model_version `eed29abe...`). It is written by hand and not regenerated
into the JSON: `model/v2/final/export.py` hashes its own code into `model_version` and rewrites
`facility_service_scores.parquet` when it runs, so changing its caveats would change the frozen model's hash.

The dataset the model reads is much cleaner than the one we were given (`cleaning/geo_identity/summary.json`,
before -> after): duplicate records 9,970 -> 9,959; map points outside India 6 -> 0; listing points more than
50 km from their PIN code 1,405 of 9,672 -> 1,367 of 9,869 (against the repaired PIN centres); busy PIN centres
more than 25 km from their facilities' median point 78 -> 43 (of 1,051); records with a resolved state
9,877 -> 9,927. What remains is mostly claims nobody can verify from the web, plus phone and hours facts no listing
carries. That is why the app says "call first".

## Limitations

- **Service claims are mostly unverifiable.** On the sealed gold v3 TEST, 90 of 150 pairs (60%) are no_info:
  public facilities 64%, private 57%. On DEV, 166 of 300 (55%). P_S is therefore the chance that a web check
  which finds a decisive answer confirms the service; it says nothing about the 60% the web cannot decide.
  Sources: `model/gold/v3/test_eval/results.json`, `model/gold/v3/README.md`.
- **Public facilities: ranking is not shown.** TEST AUROC on 25 decided public pairs is 0.759 [0.491, 0.958].
  The interval includes 0.5, and DEV did not show ranking ability either (`public_note`). Private: 0.852
  [0.681, 0.970].
- **Listings omit services.** On TEST, 20 of 28 decided NO_SERVICE_TEXT pairs (no sentence of their own about the
  service) were confirmed, 0.714 [0.529, 0.847]. NO_SERVICE_TEXT means the listing is silent, not that the
  service is absent.
- **Phones are unverified.** 9,548 of 9,959 records (96%) list a number (`summary.json`,
  `trust.records_with_display_phone`). None has been checked to reach the facility.
- **Locations.** 1,680 map points are low-confidence (1,142) or disputed (538); 868 are placed at a postcode
  centre and 235 at a city centre (`summary.json`, `loc_conf`, `loc_src`).
- **No checked opening hours, 24x7 status or live capacity.** The provided table has no hours field. 4,320 of
  9,959 records say anything about hours, only in free text (`submission/referral_saathi.ipynb`, section 9), and
  OpenStreetMap adds 134 opening_hours facts (`kb/opendata/OPENDATA.md`); none is checked. Bed capacity is
  missing on 7,454 of 9,970 raw records (`REPORT.md`, claims-09). Nothing says whether a bed or a slot is free
  today.
- **Labels are agent-made.** Gold labels were made by agents from public web pages, not by phone calls or visits
  (`label_provenance.wording`). A human spot-check of 25 pairs is set up (PR #105,
  `model/gold/v3/human_check/`) and not yet done; no human agreement number exists yet.

## What the sealed TEST does and does not show (WS5, #140)

Numbers from [`independence.json`](../../model/gold/v3/test_eval/independence.json) (code: `model/gold/v3/test_eval/independence.py`, read-only on the
frozen predictions) and [`results.json`](../../model/gold/v3/test_eval/results.json). Decided TEST pairs only.

- **Lead number: Likely confirmed 25 of 28** (0.893 [0.728, 0.963]). AUROC 0.819 [0.686, 0.924] measures ranking
  within a list, not how often an answer is right. By band (confirmed / contradicted / no answer on the web):
  LIKELY 25 / 3 / 35, CALL_FIRST 0 / 0 / 11, NO_SERVICE_TEXT 20 / 8 / 44, UNLIKELY 2 / 2 / 0 (`bands`). The band
  itself ranks less well than p: AUROC 0.670 [0.509, 0.813]; LIKELY against the rest 0.651 [0.507, 0.778]
  (`band_as_score`).
- **Independence.** Where a facility's own website states the service, the model and the web check both see it
  (21 of 21 confirmed). Where it does not, the score still ranks above chance but weakly: AUROC 0.703 [0.521,
  0.864] on 39 pairs (`by_website_family`). Labels that cite the record's own source URL or domain: AUROC 0.894
  [0.768, 0.988] on 39 pairs; labels from an independent domain: 0.705 [0.400, 0.945] on 19
  (`by_label_evidence_source`).
- **No TEST negatives** for emergency_csection, nicu, emergency_24x7 and stemi_thrombolysis
  (`services_with_0_test_negatives`): TEST cannot show ranking within those services.
- **Exists and location are not tested.** TEST has no "no" label for either (114 yes, 36 unclear each). With the
  DEV rule (unclear after a search counts as 0) the existence score gets AUROC 0.617 [0.484, 0.749]
  (`existence_head`), which includes chance.
- **The c2 override.** UNLIKELY from p <= t_U (0.2) was right (contradicted) on 9 of 9 labelled pairs: DEV 7 of 7,
  TEST 2 of 2. UNLIKELY from the c2 rule with p > t_U was right on 3 of 10: DEV 3 of 8, TEST 0 of 2
  (`unlikely_by_route`; DEV is the fit set). A c2 Unlikely means the text names another facility, not that the
  service is absent.
- **Label agreement.** Cohen's kappa 0.834 on DEV (75 double-labelled pairs) and 0.624 on TEST (38); on TEST there
  is no confirmed-against-contradicted disagreement (`report.overlap` in
  [`dev_labels.json`](../../model/gold/v3/dev_labels.json) and
  [`test_labels.json`](../../model/gold/v3/test_labels.json)).
- **DEV Likely precision is how the threshold was set.** t_L is the lowest DEV threshold with out-of-fold precision
  at least 0.85, so 102 of 120 on DEV ([`model_card.json`](model_card.json), `thresholds.likely`) is not a test.
- **Simulation.** In the simulated referral world ([`submission/sim_results.csv`](../../submission/sim_results.csv),
  trauma, `minus_ncf`) the app is within 1 to 2 points of nearest listing plus a call ahead, and ahead only when
  the model is assumed right (S1, +1.0). The cause is the citation rule: the app offers only places with a quote
  from their own listing. In emergencies the score filters and explains, and the call decides. The multi-stop
  route is not evaluated in the simulation. Simulated, not a field result.

## Paths forward

- **Field reports:** the app's call-outcome reports (#65) are the path for phones, hours and turn-aways.
- **An official public-facility source** (for example, state health department lists) is future work.
