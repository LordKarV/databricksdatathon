# planner: multi-stop referral plans

Given an origin and a pathway from `kb/pathways/care_pathways.json`, returns the best plan
(direct, 1 stop, or up to 2 stops before a recurring site) and two alternatives, each with a
timeline, probabilities, evidence ids, window checks and a comparison against going direct.

```python
from planner import plan
result = plan((26.45, 85.95), pathway, facilities, capability_p, travel_fn=None, state="Bihar")
```

```
.venv/bin/python -m planner --list
.venv/bin/python -m planner --pathway major_trauma --lat 26.45 --lon 85.95 --state Bihar
.venv/bin/python -m planner --pathway dialysis_start --lat 26.6 --lon 85.48 --json
```

## Files

| File | What |
|---|---|
| `core.py` | The planner. Standard library only; data and probabilities are passed in |
| `export_v2.py` | Build step: writes `planner/out/planner_v2.json.gz` from model v2 (`derived/v2`; needs pandas, about 7 s) |
| `store.py` | Loads that file with the standard library: `facilities()`, `capability_p`, `band`, `state_near` |
| `data_v1.py` | The old derived/v1 stub, kept only for the stub-era stories in `viz/journeys` |
| `service.py` | `plan_for_service(service, lat, lon)`: the one call the app makes |
| `implied.py` | Wrapper around any `capability_p`: implied capabilities and blood from the blood-centre list |
| `eval_gold_dev.py`, `EVAL_GOLD_DEV.md` | The planner against the gold DEV labels, before and after |
| `eval_gold_dev_notebook.py` | The same evaluation as a Databricks-format notebook (local path run; Unity Catalog path not run) |
| `app_contract.py` | `to_options(result)`: shapes plans for the app's `/api/plan` options |
| `__main__.py` | CLI that prints a plan for a coordinate (`--json`, `--osrm`, `--elapsed`) |
| `test_planner.py` | 27 tests with hand-built fixtures: `.venv/bin/python -m pytest planner/test_planner.py -q` |

## Calling it from the app

```python
from planner.service import plan_for_service
out = plan_for_service("trauma_emergency", 26.45, 85.95)
# {"pathway": "major_trauma", "options": [...], "abstain": None, "thresholds": {...},
#  "instructions": [...], "considered": {...}, "assumptions": {...}, "meta": {"planner_data": {...}, ...}}
```

- `DATATHON_ROOT` moves the data root (where `derived/v1` and `data/external` live), `PLANNER_OUT` the
  export folder and `PLANNER_EVAL_OUT` the evaluation output, for machines where the code folder is
  read-only.
- Build the data once: `uv run --no-project --with pandas --with pyarrow python planner/export_v2.py` (about 0.9 MB, git-ignored). At run time
  nothing but the standard library is imported. Measured on this machine with system Python and no
  pandas installed: 0.1 s for the first call including the load, then 8 to 22 ms per plan.
- A service with no pathway returns `{"pathway": None}`: keep the single-destination ranking.
- Service ids: `emergency_csection -> obstetric_emergency`, `nicu -> sick_newborn`,
  `trauma_emergency -> major_trauma`, `burn_care -> burns`, `dialysis -> dialysis_start`, plus
  `stemi` and `snakebite` if tiles are added. `mri` and `cardiac_surgery` have no pathway.
- Pass `capability_p=` (and `facilities=`) to plan with other probabilities (tests do).
- `state=` (optional): the origin's state, e.g. from the app's PIN index. It selects the hill-road
  travel constants. When it is not passed, the state of the nearest PIN centroid in the export is
  used (near a border this can be the neighbouring state). `meta.origin_state`,
  `meta.origin_state_source` and `meta.terrain` say what was applied.
- If the export is missing, the call raises `RuntimeError` naming the build step.

## Implied capabilities and list evidence

`plan_for_service` wraps whatever `capability_p` it uses with `planner.implied.with_implications`
(pass `implications=False` to turn it off), so the model's scores get the same treatment.

- A capability takes `max(own p, strength x p of a source capability)` when the source is strongly
  evidenced (p at least 0.75). Rules, each with its reason, are in `IMPLIES`: a haemodialysis unit
  implies nephrology cover and a laboratory; comprehensive emergency obstetric care implies an
  operating theatre, the basic functions, a laboratory and (more weakly) blood; a NICU implies
  special newborn care and stabilisation; a burn unit implies dressings and IV fluids; and so on.
  One level only: an implied capability does not imply others.
- An implied capability has no evidence ids. The stop lists it under `capability_notes` as
  `{"capability", "basis": "implied", "implied_by", "text": "implied by a strongly evidenced ...",
  "p", "source_p", "strength", "reason"}`, so the card can show it as a named, weaker contribution.
- Blood: when the planner export was built on a machine that has
  `data/external/eraktkosh_blood_centres/` (not in git), `blood_transfusion` ignores record text:
  0.80 if the facility is matched to a listed blood centre (the matcher's hand-checked precision,
  16 of 20), 0.50 if a listed centre is within 5 km, else 0.02. The note's `basis` is `list`,
  `list_nearby` or `list_none`. Without those files blood comes from record text or from the
  caesarean implication, and `meta.implications.blood_from_list` is false.
- The strengths (0.6 to 0.9), the 0.75 cut, 0.50, 0.02 and 5 km are assumptions.

## Probabilities: model v2

`capability_p(facility_id, capability) -> (p, evidence_ids)` is the only source of probabilities;
`planner.core` never reads a data file. `export_v2.py` builds it from `derived/v2`:

- A tag with a `v2_service` in `kb/pathways/capabilities.json` (15 of 26: emergency, trauma care, ICU,
  CT, blood bank, C-section, NICU, dialysis, cath lab, ...) takes the v2 p of that facility and service.
  Only LIKELY and CALL_FIRST pairs are offered. NO_SERVICE_TEXT and UNLIKELY pairs get p 0, so they are
  never a stop, and implications never lift them: for these tags v2's band is final. A stop that rests
  on a CALL_FIRST pair carries `call_first: true` and the flag "Call first to check: ... is not
  confirmed in our data."
- The other 11 tags (operating theatre, ECG, laboratory, nephrology, fistula surgery, basic EmOC,
  newborn stabilisation, SNCU, IV fluids, burn dressings, plastic surgery) are support tags v2 does not
  score. They come from the record's own offer sentences that name them (0.7 for one sentence, 0.78 for
  two or more, 0.02 for none: assumptions), or from an implication (below).
- Facilities: only those v2 scores (so the 12 exclude_review records are gone) and no dental or eye
  clinic (2,190 records): none of the pathways is theirs to serve (validation H2; eye hospital as cath lab).
- Evidence: own offer sentences only. Not another facility's sentence, not a non-offer, plan, camp,
  staff or list sentence (validation H3), and never a sentence that names a doctor (#86).

## Method

- A facility delivers a stage with probability = product of `requires_all`, times the best tag of
  each `requires_any` group. Capabilities and facilities are treated as independent.
- Emergency pathways: direct (origin to definitive facility D) or one stop (origin to S to D).
  - A stop is considered only when the pathway's `add_stop_only_if` rule holds for D, S is nearer
    than D, and S lies in a detour corridor (straight-line origin-S-D at most 1.6 times
    origin-D plus 10 km).
  - Timeline = travel (`geo.travel`) + dwell from the pathway. A facility that cannot deliver costs
    15 minutes, then the patient goes on: from S to D, from D to one fallback facility.
  - Ranking, in order: P(first care by T1 and definitive care by T2); P(first care by T1);
    expected minutes to definitive care. Differences under 0.05 (the margin) on the first two count as
    ties, so near-equal chances go to the plan with fewer expected minutes. T1 is the stabilising stage window, else the add-stop
    threshold. T2 is the definitive stage window. Reaching definitive care counts as first care.
  - A stop plan is dropped unless it beats the best direct plan by 0.05 on the first measure, or
    matches it there and beats it by 0.05 on the second.
  - STEMI: after thrombolysis the PCI deadline becomes 24 hours from stabilisation (rule
    `pci_3_to_24h_after_lysis`); the MoHFW 30 minute reading is a `caution` line, not a rule.
- Scheduled pathways (dialysis): one facility per stage; least travel over 12 weeks first (one
  return trip per one-off stage, 3 a week for sessions), then fewer distinct sites. The best
  one-site plan is always among the plans returned, for comparison.
- Travel defaults to the `geo.travel` estimate with no network calls. `--osrm` routes every leg
  live (about 15 requests for one plan).
- The planner constants (15 minute turn-away, 0.05 margin, 150 km radius, corridor, 12 weeks,
  one fallback) are assumptions. They are echoed under `assumptions` in every result.

## Output

```
{
  "pathway", "service", "urgency", "objective", "origin", "elapsed_minutes",
  "thresholds": {"first_care_minutes", "first_care_basis", "definitive_minutes", "definitive_basis",
                 "add_stop_only_if_definitive_beyond_minutes", "rule"},
  "plans": [{
    "type": "direct | one_stop | single_site | two_sites | three_sites",
    "stops": [{"facility_id", "name", "lat", "lon", "town", "district", "state", "stage",
               "purpose": "stabilise | definitive | assess | access | recurring",
               "eta_minutes", "eta_low", "eta_high", "dwell_minutes", "p",
               "weakest_capability", "weakest_capability_p", "evidence_ids",
               "leg": <geo.travel row>, "flags",
               "fallback_if_turned_away": {"facility_id", "name", "p", "eta_minutes", "leg", "evidence_ids"}}],
    "totals": {"minutes_to_definitive", "low", "high", "p_objective", "p_first_care", "p_treated",
               "expected_minutes", "minutes_if_treated"},
    "window_checks": [{"check", "limit_minutes", "basis", "at_facility_id", "eta_minutes", "met",
                       "met_at_high_estimate"}],
    "vs_direct": {"direct_facility_id", "direct_name", "direct_minutes", "direct_p_objective",
                  "direct_p_first_care", "plan_p_objective", "plan_p_first_care", "gain", "text",
                  "text_numbers": {<every number quoted in text, rounded as printed>},
                  "what_would_change", "what_would_change_facility_id"}}
  }],
  "abstain": null | {"text"},
  "instructions": [{"rule", "type", "when", "then", "basis", "source"}],
  "considered": {"plans", "stop_plans_dropped_below_margin"},
  "assumptions": {...}
}
```

`vs_direct.text` is one plain sentence in minutes ("Going straight to X takes 84 min and misses the
60-minute window; stopping first at Y gives first care in about 34 min."); the probabilities stay in the
fields. `what_would_change` (from `service.py`, model v2 store only) names the nearer facility a phone
"yes" would bring in: v2 rules out none of the first stop's stage tags there.

`app_contract.to_options(result)` turns each plan into one `/api/plan` option for its definitive
facility (`rank, facility_id, name, town, district, state, lat, lon, travel, p, evidence, flags,
call_ahead, call_first`) plus a `route` object holding `type, stops, totals, window_checks,
vs_direct`. It does not fill `band, p_lo, p_hi, p_e, p_l, contributions, track_record, phone`:
those come from the model and the app's facts tables.

## What it did on real data before model v2 (stub probabilities, history)

Rural Madhubani, Bihar, major trauma: stabilise at Madhubani Medical College (25 min), then
Rajeshwar Hospital, Patna (180 min, range 154 to 247). Chance of first care in time 0.91; going
direct takes 129 min, past the 60 min threshold.

Best plan type for the 40 benchmark queries in `model/gold/queries.json`, each run against every
pathway (9,959 facilities, estimate travel):

| Pathway | Direct | One stop | Abstain |
|---|---|---|---|
| stemi | 39 | 0 | 1 |
| major_trauma | 18 | 18 | 4 |
| obstetric_emergency | 15 | 11 | 14 |
| burns | 36 | 1 | 3 |
| sick_newborn | 38 | 0 | 2 |
| snakebite | 0 | 0 | 40 |
| dialysis_start | 15 one site, 17 two sites, 2 three sites | | 6 |

## Limits

- Support tags without a v2 service rest on text mentions with assumed probabilities (above).
- Snakebite abstains for all 40 queries: only 5 of 9,959 records mention anti-snake venom. The
  guideline answer (nearest public facility, call to confirm stock) needs a facility-type prior
  the stub does not have.
- Sparse tags make multi-requirement stages scarce: thrombolysis is mentioned by 48 records, SNCU
  by 19, burns dressing by 33, blood by 606. A definitive stage that needs four tags multiplies
  four stub probabilities, so near facilities with thin text lose to far ones with long text.
- One-stop plans never appear for STEMI or sick newborn in the benchmark. Whether that is because
  a definitive candidate was always within the threshold, or because no nearer stabilising
  candidate had evidence, was not broken down.
- The planner side of the app wiring is in place (`service.py`, `store.py`). `/api/plan` does not
  call it yet; that change and the faithfulness markers are in `app/` (#47).
- Patient-specific rules (burn size, birth weight, prior stroke) are returned as `instructions`
  text; the planner does not evaluate them because the app collects no patient details.
- Windows are checked against the estimate; `met_at_high_estimate` shows when the range crosses
  the limit. `elapsed_minutes` shifts every check.
- Not run: no comparison of plans against real referral decisions; no clinician review.
