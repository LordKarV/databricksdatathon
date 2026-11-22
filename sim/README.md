# sim: simulated referral world (#92)

SIMULATED. Nothing here is a field result. A synthetic world with known truth, to compare referral policies
against "nearest" and "best on paper". Build-time only; nothing here goes into the app runtime. Results belong in
the notebook appendix only, labelled "simulated" (#92, owner's decision).

This file covers the world half (world.py, execute.py, policies_baseline.py). The app policy, run.py, metrics and
the notebook are tm-AA2026's.

```
python -m sim.execute 1 2          # smoke run: 3 baselines x S0-S3 x 2 seeds, prints a SIMULATED summary
python -m pytest sim/tests -q      # 21 tests, about 1 s
```

Needs pandas, numpy, pyarrow (and pytest for the tests). 20 seeds of the three baselines take about 30 s on a
laptop. Outputs go to `sim/out/` (git-ignored); every parquet carries `simulated` in its file metadata.

## Interface (as agreed on #92)

- `world.cases(seed)`: one row per patient: `case_id, seed, lat, lon, state, district, service, urgency,
  window_min, t0_min, has_data, has_phone_signal`.
- `world.truth_table(scenario, seed, knobs)`: `unique_id, service, exists, offers, phone_ok, open_now_p, accept_p,
  true_lat, true_lon`, one row per facility x service (all 9,947 v2-scored facilities, so any app pick is covered).
  `world.write_truth` writes `sim/out/truth/<scenario>_<seed>.parquet`.
- `world.listing(service)`: what a policy may see (listed point, state, operator, published v2 p). No truth.
- Policy: `choose(case, ctx) -> [{facility_id, call_first, note}, ...]`. `policies_baseline.POLICIES` has
  `nearest`, `nearest_call_first`, `best_on_paper`; `policies_baseline.context()` builds their ctx.
- `execute.execute(cases, steps, truth, scenario=, policy=, run_id=, knobs=)`: the event log, columns
  `run_id, scenario, seed, policy, case_id, step, kind, facility_id, t_min, outcome`. Steps are computed once per
  policy and seed (they never depend on the truth) and reused for every scenario and knob level.
- Knobs for the sensitivity sweep: `world.KNOBS` (`accept_p, phone_ok, wrong_yes, open_now_p`, each low/mid/high).
  `truth_table` takes the first, second and fourth; `execute` takes `wrong_yes`.

## Scope (latest on #92)

Bihar and UP; dialysis (planned) and trauma_emergency (emergency); S0 to S3; at most 3 places per policy (the
app's N_OPTIONS); common random numbers. Cut: the planner route and "app + reports".

## Scenarios

| | offers | exists | map point |
|---|---|---|---|
| S0 "text says nothing" | DEV rate by service x operator, weighted by 1 / inclusion_prob | 0.984 (EXISTS_DEFAULT) | listed |
| S1 "model is right" | Bernoulli(v2 p) | Bernoulli(v2 p_exists) | listed |
| S2 "from labels" | DEV rate by service x stratum (strong / weak / suspect / no_mention, the gold v3 rule) | 0.984 | listed |
| S3 "data as bad as the audit" | S2, and attributed_elsewhere claims are false | 0.984 | wrong at 1 - q_ev of its LOC rule; truth = alt point |

- DEV rates are confirmed / (confirmed + contradicted), the gold v3 headline; no_info pairs are left out. Small
  cells are pulled towards the pooled rate with 2 pseudo-counts (S2: the stratum over all 9 services; S0: the
  service). The cells are thin: dialysis has 15 decided DEV pairs, trauma 14, so S0 is high (dialysis about
  0.98, trauma about 0.83).
- Only `model/gold/v3/dev_labels.json` is read. No TEST label file is opened anywhere (a test checks the sources).
- Uniforms are drawn once per seed and shared by the scenarios, so scenarios differ only by their rates.

## Execution (execute.py, the only reader of the truth)

- Call first: no signal is an `outage` and the worker goes anyway. A call costs 5 min. A number that does not reach
  the facility (`phone_ok` false, or no number listed) is `no_answer`, and the worker goes anyway. An answered
  call says "yes" when the facility would treat now, else a wrong "yes" at `wrong_yes`; "no" skips the trip.
- Travel: `geo.travel.estimate` (no network) from the current point to the listed point, with the origin state for
  the hill-road constants (Bihar and UP are plain).
- Arrival: `not_there` (does not exist, or the true point is over 2 km from the listed one, or unknown), `closed`
  (`open_now_p`), `no_service`, `refused` (`accept_p`); each costs 15 min (the planner's figure), then the next step
  from there. Else `treated`, outcome `in_window` or `late`.
- Gives up when the steps run out, or before a step once 240 min (emergency) or 480 min (planned) have passed.
- Per-visit draws (open, accept, wrong yes) are a hash of (seed, case, facility, purpose): the same patient at the
  same place gets the same answer under every policy.
- `t_min` is minutes since the case started; `t0_min` (minute of the day) is informational.
- `has_data` is logged as an `outage` (`no_data`); only the app policy acts on it (offline pack).

## Choices made where #92 was open

- Truth tables live in world.py (lead's assignment), not in a separate truth.py.
- "Listing names the service" = a derived/v1 service claim (grades.parquet), the app's own candidate pool. Best on
  paper ranks the same pool by v2 p within the case's state.
- Dialysis has no deadline in kb/pathways (60480 min is a wait before first fistula use), so its window is the
  app's 120 min for the scheduled profile. Trauma uses the pathway's 60 min stabilise window.
- Origins are PIN centroids drawn uniformly per state: no NFHS population table is in the repo.
- Duplicate listings are not merged into sites (the app merges them); truth covers every member.
- Assumed, not measured: `P_HAS_DATA` 0.8, `P_PHONE_SIGNAL` 0.9, the knob values, call 5 min, 2 km, the give-up
  limits, 200 cases per state x service x seed. Travel time is the estimate's middle value, with no spread.
