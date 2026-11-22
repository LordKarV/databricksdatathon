# Offline state packs

One gzip JSON pack per state, for answers with no internet (spec section 3.2.3, issue #9).

```
.venv-app/bin/python app/packs/build_packs.py            # all states, writes SIZES.md and sizes.json
.venv-app/bin/python app/packs/build_packs.py --states BIHAR
```

Inputs are all from `derived/v1`: `facility_location` (ranking point, location confidence), `record_trust` (the
record's own first phone; directory numbers flagged), `data_point_scores` (service claims with score, 90% interval,
grade and cited sentences; sentence rows give the claim ids), and `pin_gazetteer` (PIN centroids, district).
Packs go to `app/packs/out/` and are git-ignored because they hold facility data. Build them at deploy time.

## What a pack holds

For every PIN in the state and each of the 7 app services: the 3 nearest candidate facilities, plus the nearest
"likely" one if it is not among them. Each row has name, phone, coordinates, band, score and interval, and the two
shortest cited sentences with their claim ids (`uid8:field4:idx`). The pack also has the state's PIN list with
centroids and districts for the offline picker, and the build date. Candidates come from all of India, so border
PINs see facilities in the next state.

Excluded: `icu` (no app tile), grades `attributed_elsewhere` and `counter_evidence`, and claims verified false.

## Layout (format v1)

| Key | Content |
| --- | --- |
| `fac` | columnar: `uid8`, `name`, `tel`, `tel_dir` (directory number), `loc_low` (location confidence not high), `lat`/`lon` as deltas of 1e-4 degree, sorted by latitude |
| `ev` | one row per (facility, service): `f` (facility index, delta), `s` (service index), `likely`, `p`/`lo`/`hi` (x100), `q1`/`q2` (quote index or -1) |
| `q` | quote table `[text, claim id suffix]`, shared by all rows |
| `lists` | distinct top lists (evidence row ids); neighbouring PINs share them |
| `index` | per service, one list id per PIN |
| `pins` | `pin`, `lat`, `lon` as deltas (1e-3 degree), `d` district index into `districts`, `not_centre` the PINs (ascending, not deltas) the area view names another district for after the LGD correction (facts/build.py not_centre), which offline.js districtCentre skips |

These three choices brought Uttar Pradesh from 228 KB in the prototype to about 80 KB: columnar arrays with delta
coordinates, dictionary-encoded quotes, and deduplicated top lists. Post-office names are not included; the picker
offers PIN and district only. Sizes for every state are in `SIZES.md`.

## Bands: model table or conservative placeholder

- When `derived/v2/facility_service_scores.parquet` exists (columns `unique_id, service_id, band, p, lo, hi, as_of`,
  published from #11), the builder takes band, p, lo and hi from it. `service_id` may be a derived/v1 name
  (`csection`) or an app key (`emergency_csection`). Pairs the model calls unlikely, and pairs it did not score,
  are left out of the pack.
- Until then the placeholder marks `likely` only for pairs verified true by the gold web checks (12 of 386 rows
  in the Bihar pack); every other candidate is not verified, with the derived/v1 score and interval.
- Each pack's `band_note` says which source was used.
- Ranking is still straight-line distance from the PIN centroid, not expected time to treatment.
