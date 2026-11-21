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
| `data_v1.py` | Stub inputs from `derived/v1`: facility list and `capability_p` (needs pandas) |
| `app_contract.py` | `to_options(result)`: shapes plans for the app's `/api/plan` options |
| `__main__.py` | CLI that prints a plan for a coordinate (`--json`, `--osrm`, `--elapsed`) |
| `test_planner.py` | 14 tests with hand-built fixtures: `.venv/bin/python -m pytest planner/test_planner.py -q` |

## The swap point

`capability_p(facility_id, capability) -> (p, evidence_ids)` is the only source of probabilities.
`planner.core` never reads a data file. To use the model, pass a function backed by
`derived/v2/facility_service_scores.parquet`; nothing else changes.

The stub in `data_v1.py` is a placeholder, not a fitted model:

- Capability mapped to a graded service (6 tags): the `service_claim` score from
  `data_point_scores.parquet`, evidence = the claim ids `grades.parquet` cites.
- Proposed capability (20 tags): sentences in the facility's own record that contain one of the
  tag's evidence words. One sentence gets the median score of `weak` graded claims (0.715), two or
  more the median of `moderate` graded claims (0.783). Both medians are read from the data. That
  a keyword mention is as reliable as a weak or moderate graded claim is an untested assumption.
- No mention: 0.02 (assumption).

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
    expected minutes to definitive care. T1 is the stabilising stage window, else the add-stop
    threshold. T2 is the definitive stage window. Reaching definitive care counts as first care.
  - A stop plan is dropped unless it beats the best direct plan by 0.05 on the first measure, or
    matches it there and beats it by 0.05 on the second.
  - STEMI: after thrombolysis the PCI deadline becomes 24 hours from stabilisation (rule
    `pci_3_to_24h_after_lysis`); the MoHFW 30 minute reading is a `caution` line, not a rule.
- Scheduled pathways (dialysis): one facility per stage; fewest distinct sites first, then least
  travel over 12 weeks (one return trip per one-off stage, 3 a week for sessions).
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
    "vs_direct": {"direct_facility_id", "direct_minutes", "direct_p_objective", "plan_p_objective",
                  "gain", "text"}
  }],
  "abstain": null | {"text"},
  "instructions": [{"rule", "type", "when", "then", "basis", "source"}],
  "considered": {"plans", "stop_plans_dropped_below_margin"},
  "assumptions": {...}
}
```

`app_contract.to_options(result)` turns each plan into one `/api/plan` option for its definitive
facility (`rank, facility_id, name, town, district, state, lat, lon, travel, p, evidence, flags,
call_ahead, call_first`) plus a `route` object holding `type, stops, totals, window_checks,
vs_direct`. It does not fill `band, p_lo, p_hi, p_e, p_l, contributions, track_record, phone`:
those come from the model and the app's facts tables.

## What it does on real data (stub probabilities)

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

- Probabilities are the stub above. Every number that depends on them will change with the model.
- Snakebite abstains for all 40 queries: only 5 of 9,959 records mention anti-snake venom. The
  guideline answer (nearest public facility, call to confirm stock) needs a facility-type prior
  the stub does not have.
- Sparse tags make multi-requirement stages scarce: thrombolysis is mentioned by 48 records, SNCU
  by 19, burns dressing by 33, blood by 606. A definitive stage that needs four tags multiplies
  four stub probabilities, so near facilities with thin text lose to far ones with long text.
- One-stop plans never appear for STEMI or sick newborn in the benchmark. Whether that is because
  a definitive candidate was always within the threshold, or because no nearer stabilising
  candidate had evidence, was not broken down.
- Not wired into the app. `/api/plan` does not call the planner yet, and the app runs without
  pandas, so it needs a `capability_p` over its own facts export.
- Patient-specific rules (burn size, birth weight, prior stroke) are returned as `instructions`
  text; the planner does not evaluate them because the app collects no patient details.
- Windows are checked against the estimate; `met_at_high_estimate` shows when the range crosses
  the limit. `elapsed_minutes` shifts every check.
- Not run: no comparison of plans against real referral decisions; no clinician review.
