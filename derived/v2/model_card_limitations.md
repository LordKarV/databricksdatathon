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

## Paths forward

- **Field reports:** the app's call-outcome reports (#65) are the path for phones, hours and turn-aways.
- **An official public-facility source** (for example, state health department lists) is future work.
