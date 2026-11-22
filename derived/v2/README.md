# derived/v2: model v2 service scores

`facility_service_scores.parquet` and `model_card.json` are written by `model/v2/final/export.py` (selected model
A_platt: the candidate A prior scorecard with one Platt step, a 0.5020, c 1.4983). The other parquet files here
(witnesses, claim_atoms, facility_features, facility_attributes, reader_scores) are model inputs built by
`model/v2/assemble/build.py`. The app reads only `facility_service_scores.parquet`.

`model_card_test.json` is the frozen model's result on the sealed gold v3 TEST (issue #66), written by
`model/gold/v3/test_eval/evaluate.py`. It is separate because `model_card.json` is hashed into model_version.

Contract check: `.venv-viz/bin/python validation/contracts_v2.py` (selftest: add `--selftest`).

## facility_service_scores.parquet

358,092 rows, one per (unique_id, service_id): 9,947 facilities x 36 services. The 12 `exclude_review` records in
derived/v1/record_trust are not scored at all; the export applies `common/eligibility.py eligible_facilities`, the
same rule the app uses.

| column | meaning |
| --- | --- |
| unique_id, service_id | key; service_id is a kb/taxonomy/services.json id |
| band | LIKELY, CALL_FIRST, NO_SERVICE_TEXT or UNLIKELY (see below) |
| overlays | list of flags: BORDERLINE (LIKELY with p - t_L < 0.05), PLACE_UNCLEAR, ON_A_PUBLIC_LIST:list:fetched_date |
| p | P_S, the chance that a web check which finds a decisive answer confirms the service. It is not the chance that a phone call finds it. |
| lo, hi | the score-bin record, see below |
| p_location, p_exists | location head P_L and existence head P_E |
| base, contributions | logit(p) = base + sum(points) / (20 / ln 2), to 1e-9. contributions is a JSON string: a list of {label, family, points, evidence_ids, card_phrase}. Every evidence id is a witnesses.evidence_id or a claim_atoms.atom_id. |
| operator | public, private or unknown |
| is_24x7, hours_text | from facility_attributes |
| as_of, model_version | build date; a single model_version, equal to model_card.json |

### lo and hi

lo/hi are the Wilson 95% interval of the observed confirmed rate among decided DEV pairs whose out-of-fold P_S
falls in the same score bin (width 0.2) as this row's p. They describe the bin's track record. They are not an
interval around p: every row of a bin carries the same lo/hi, and p need not lie inside it (22,363 rows have p
outside [lo, hi]). The five bins, with their DEV counts, are `calibration_by_score_bin` in model_card.json, and
`field_descriptions` there gives the same definition.

### Bands, and the mapping for the app

The thresholds are in model_card.json `band_thresholds` (t_L 0.3686, t_U 0.20). T is the own-text level, C the
contamination level.

- LIKELY: p >= t_L, P_L >= 0.7, P_E >= 0.7 and T >= 2 (the record describes the service as its own unit).
- UNLIKELY: p <= t_U, or C = 2 with T <= 1. The second rule shows as the c2 term in contributions (125 rows).
- CALL_FIRST: neither, and T >= 2.
- NO_SERVICE_TEXT: neither, and T < 2. The record has no sentence about the service as its own unit (at most a
  specialty tag or list mention), so p rests on context and prerequisites only. Show the band, not p: a district
  hospital with no service text can still have p near 0.6 from its level and IPHS terms.

`app/packs/build_packs.py` still accepts only likely / not_verified / unlikely. Until the app migrates (issue
#63), consumers map the bands as follows:

| model band | app band |
| --- | --- |
| LIKELY | likely |
| CALL_FIRST | not_verified |
| NO_SERVICE_TEXT | not_verified (the record has no sentence about the service) |
| UNLIKELY | unlikely |

The overlays are kept as flags beside the band. They are not bands.

## Freeze

The predictions for the 150 sealed v3 TEST pairs are in `model/v2/test_predictions.parquet`, and their sha256 is
in `model/v2/test_predictions.sha256`. Re-freeze record: `model/v2/final/REFREEZE.md`.
