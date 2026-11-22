# sim/: a simulated referral world (issue #92)

**Simulated. Not field results.** This folder builds a world in which the true answers are known, sends simulated
patients through it under several referral policies, and measures what happens. It answers one question: does the
app get more patients to care in time than sending them to the nearest listing, or to the "best" listing on paper?
Results appear only in the notebook appendix, `submission/02_simulation.ipynb`, labelled simulated (owner's
decision on #92). This README gives the method, not results. Nothing here ships in the app runtime.

Two halves, one system:
- **World, truth, executor, baselines** (the lead): `world.py`, `execute.py`, `policies_baseline.py`.
- **App policies, runner, metrics, sweep, notebook, replay** (tm-AA2026): `policies_app.py`, `app_adapter.py`,
  `run.py`, `replay.py`, `submission/build_sim_notebook.py`.

## Run

```bash
.venv-app/bin/python app/facts/build.py                  # once; run.py builds facts and state packs if missing
.venv-app/bin/python -m sim.run --seeds 20 --cases-per-cell 200 --sweep   # S0-high, S0-low, S1-S3; Bihar + UP
.venv-app/bin/python -m sim.replay                       # sim/out/replay.html: one patient, policies side by side
.venv-app/bin/python -m pytest sim/tests -q
.venv-app/bin/python submission/build_sim_notebook.py    # writes and runs the appendix notebook
```

Options of `sim.run`: `--scenarios`, `--states`, `--services` (from `world.SERVICES`), `--cases-per-cell` (patients
per state x service x seed), `--out`, `--boot`, `--no-sweep`, `--with-reports` (network data only, future work).
`python -m sim.execute 1 2` is the world half's own smoke run (the three baselines only). Outputs go to `sim/out/`
(git-ignored); every parquet carries `simulated` in its file metadata. On Databricks the notebook takes seeds and
cases from widgets and writes to `/Volumes/workspace/referral_saathi/uploads/sim`.

## Honesty rules (#92)

1. **Policies never see the truth.** They see only what the app or a directory would show: the app policies get
   `AppAdapter` (the shipped engine and state packs), the baselines get `world.listing()` (listed point, state,
   operator, published v2 p). Only `execute.py` and the metrics read truth. `tests/test_policies.py` fails if a
   policy module imports the executor, names a truth function, or a policy's ctx holds truth columns.
2. **More than one truth.** Every result is reported for each scenario. S1 is circular and is never shown alone.
   S0 is two bounds, S0-high and S0-low, always reported together, never one alone.
3. **No TEST labels anywhere** (#51). Only `model/gold/v3/dev_labels.json` is read; tests check that no module
   names the TEST files.
4. **Every output says "simulated":** a `label` column in every table, "SIMULATED" in every printed table and
   chart, and the parquet file metadata.
5. **Reproducible:** seeded; runs locally and as a Databricks notebook.

## Scope (latest on #92)

Bihar and Uttar Pradesh; dialysis (planned) and trauma_emergency (emergency); S0-high, S0-low, S1, S2, S3; at most
3 places per policy (the app's N_OPTIONS); common random numbers. Cut from the first run: the planner route (still on
stub scores until #77) and "app + reports" (its reports would come from the simulation's own truth).

## Cases (`world.cases`)

`world.cases(seed, states, n)`: n patients per state x service, one row each: `case_id, seed, lat, lon, state,
district, service, urgency, window_min, t0_min, has_data, has_phone_signal`. Origins are PIN centroids drawn
uniformly within the state (no population table is in the repo). Windows: trauma 60 min (kb/pathways `major_trauma`
stabilise); dialysis 120 min (no deadline in kb/pathways, so the app's own window for the scheduled profile).
`sim.run` filters the rows to the requested services.

## Scenarios (`world.truth_table`)

`world.truth_table(scenario, seed, knobs)`: one row per facility x service (all 9,947 v2-scored facilities, so any
app pick is covered), columns `unique_id, service, exists, offers, phone_ok, open_now_p, accept_p, true_lat,
true_lon`. `sim.run` writes each to `sim/out/truth/<scenario>_<seed>.parquet`, which the replay reads.

| Scenario | offers | exists | map point |
| --- | --- | --- | --- |
| S0-high "text says nothing" | DEV confirmed / (confirmed + contradicted) by service x operator, weighted 1 / inclusion_prob | 0.984 (EXISTS_DEFAULT) | listed |
| S0-low | the same, with no_info counted as not offered | 0.984 | listed |
| S1 "model is right" | Bernoulli(v2 p) | Bernoulli(v2 p_exists) | listed |
| S2 "from labels" | DEV rate by service x stratum (strong / weak / suspect / no_mention, the gold v3 rule) | 0.984 | listed |
| S3 "claims as bad as the audit" | S2, and attributed_elsewhere claims are false | 0.984 | wrong at its class rate (below); truth 25 km away |

- **Why S0 is two bounds (lead, #92):** no_info means the labeller found nothing, which is not evidence either way,
  and the cells are thin (about 15 decided DEV pairs per service). `world.truth_table("S0", ...)` is S0-high.
- Small cells are pulled towards the pooled rate with 2 pseudo-counts (S2: the stratum over all 9 services; S0:
  the service).
- Uniforms are drawn once per seed and shared by the scenarios and knob levels, so scenarios differ only by their
  rates.
- **S3 map points (#103)** follow the cleaned data, not the raw coordinates the geo audit judged. Rates in
  `world.S3_LOC_WRONG`; unclear verdicts count as wrong:

  | Class (derived/v1 facility_location) | Points (v2-scored) | P(wrong) | Source |
  | --- | --- | --- | --- |
  | moved: `loc_src` is not `listing_coordinates` | 1,168 | 6/30 = 0.20 | validation/location/judgments/moved_30.csv: right 24, wrong 1, unclear 5 |
  | listing point kept, `loc_conf` low or disputed | 579 | 6/8 = 0.75 | audit/geo/hand_check_verdicts.csv rows of this class: no 3, unclear 3, yes 2 (3 of 5 decided) |
  | every other point | 8,200 | 0 (as S2) | the listed point is right |

  A wrong point's truth is 25 km from the listed point on a random bearing (`S3_WRONG_KM`, an assumption: the
  moved check measured no distance), never the rejected raw point. Any distance above `NOT_THERE_KM` gives the same
  events. The old rule applied the audit's 20 of 34 wrong, measured on the raw coordinates, to points the cleaning
  had already replaced. The 6/8 cell is thin, and the cleaning's own hand check found 12 of 12 `city_points_elsewhere`
  conflicts wrong (cleaning/geo_identity/handcheck_location.csv), so 0.75 may be low for those 195 disputed points.
- **S3 sensitivity (lead, #112):** S3 is the pessimistic scenario, so it counts unclear as wrong (6/8 = 0.75). The
  alternative is the audit's own decided-only count, 3 of 5 = 0.60 for `S3_LOC_WRONG["low_or_disputed"]`.
- **Caveat on S2 and S3 (#92 review):** they come from the DEV labels the v2 model's calibration step was fitted on,
  and S3 penalises other-facility sentences the engine already drops. Both favour the app by construction. S0 is
  the scenario where the app can lose.

## Policies

Every policy returns steps `{facility_id, call_first, note}`, at most 3, tried in order, then 108.

| Policy | What it sees and does |
| --- | --- |
| `app` | the product as shipped: `Engine.plan` (derived/v2) with mobile data, the saved state pack without; phones every option first (each option's text ends "We will phone before going"); field reports off |
| `app_offline` | the state pack only, read as `app/static/pack.js` does (nearest PIN's list, sorted by straight-line km) |
| `nearest` | the 3 listings naming the service (a derived/v1 claim, the app's own candidate pool) with the shortest travel estimate among the 15 nearest in a straight line; no call |
| `nearest_call_first` | the same places, phoning each first: separates the ranking from calling ahead |
| `best_on_paper` | the 3 highest published v2 p in the case's state among the same listings, ignoring distance; no call |
| `app_plus_reports` | future work: the app re-ranked with a Beta(p k, (1 - p) k) update from field reports (`reports.py`) |

`app_adapter.py` is the thin layer to the shipped app (`app/facts/engine.py`, unchanged). It caches `Engine.plan`
per (origin rounded to 1e-3 degree, service), since plans do not depend on truth.

**Ranking fix found by the simulation (#92, #101).** The first runs showed the app's emergency order, evidence
discounted by travel time (p x exp(-minutes / 45), best first), treating fewer simulated trauma patients in the
window than `nearest_call_first` in every scenario: a farther, better documented hospital came first, and a wasted
trip costs more than a "no" on the phone. PR #101 changed emergencies to the nearest plausible place first
(`NEAREST_FIRST` in `app/facts/engine.py`); planned care keeps the old order.

**`app_before_101` (diagnostic, opt-in)** keeps the old emergency order measurable. It uses
`AppAdapter(old_emergency_rank=True)`: the same engine, with the engine module's `NEAREST_FIRST` emptied only during
that adapter's calls (`app_adapter.rank_before_101`) and its own plan cache, so `app` is unaffected
(`tests/test_rank_before_101.py`). Planned care gets the same answers under both, so dialysis is the control. It
runs only when named: `python -m sim.run --no-sweep --policies app_before_101,app,nearest_call_first`. The
notebook's "Ranking fix" section reports both versions against `nearest_call_first`, trauma and dialysis, every
scenario.

## Execution (`execute.py`, the only reader of the truth)

- Call first: no signal is an `outage` and the worker goes anyway. A call costs 5 min. A number that does not reach
  the facility (`phone_ok` false, or no number listed) is `no_answer`, and the worker goes anyway. An answered call
  says "yes" when the facility would treat now, else a wrong "yes" at `wrong_yes`; "no" skips the trip.
- Travel: `geo.travel.estimate` (no network) from the current point to the listed point.
- Arrival: `not_there` (does not exist, or the true point is over 2 km from the listed one, or unknown), `closed`
  (`open_now_p`), `no_service`, `refused` (`accept_p`); each costs 15 min, then the next step from there. Else
  `treated`, outcome `in_window` or `late`.
- Gives up when the steps run out, or before a step once 240 min (emergency) or 480 min (planned) have passed.
- Per-visit draws (open, accept, wrong yes) are a hash of (seed, case, facility, purpose): the same patient at the
  same place gets the same answer under every policy (common random numbers).

`sim.run` calls `execute.run_case` once per case and policy, with the truth indexed once per table; steps are
computed once per policy and seed and reused for every scenario and knob level.

## Metrics (`run.py`)

`sim/out/metrics.parquet`, one row per policy x scenario x state (and `ALL`) x service x urgency: treated within the
window (share), median minutes to care, wasted trips per case, calls per case, unsafe first stop (the first place
travelled to does not exist or does not offer the service), gave up. Each has a 90% seed-bootstrap interval
(`_lo`, `_hi`). Events and cases: `sim/out/{events,cases}/<run_id>.parquet`.

`sim/out/sensitivity.parquet`: app minus `nearest_call_first`, treated in window, paired by seed, per scenario and
service, with each knob of `world.KNOBS` at low and high (the others at mid), and where the verdict changes.

## Assumptions

Every value below is assumed, not measured, unless the basis says otherwise.

| Name | Value | Where | Basis |
| --- | --- | --- | --- |
| `accept_p` | 0.8 (swept 0.6 / 0.95) | `world.KNOBS` | assumption: a facility that offers it takes this patient now |
| `phone_ok` | 0.5 (swept 0.3 / 0.8), and False with no listed number | `world.KNOBS` | PHONE_UNCHECKED q_ev 0.5 in derived/v1/evidence_rules |
| `wrong_yes` | 0.15 (swept 0.05 / 0.3) | `world.KNOBS` | assumption: a "yes" on the phone that is wrong |
| `open_now_p` | 0.9 (swept 0.7 / 0.98) | `world.KNOBS` | assumption: open and staffed on arrival |
| `P_HAS_DATA`, `P_PHONE_SIGNAL` | 0.8, 0.9 | `world.py` | assumption |
| `SMOOTH` | 2 pseudo-counts | `world.py` | assumption: shrinkage of thin label cells |
| `EXISTS_DEFAULT` | 0.984 | derived/v1 evidence_rules | data |
| `CALL_MIN` | 5 | `execute.py` | assumption |
| `TURN_AWAY_MIN` | 15 | `execute.py` | planner/core.py's figure |
| `NOT_THERE_KM` | 2 | `execute.py` | assumption |
| `S3_LOC_WRONG` | moved 0.20, low or disputed 0.75, other 0 | `world.py` | data: validation moved_30, audit/geo hand check (#103) |
| `S3_WRONG_KM` | 25 | `world.py` | assumption: distance of a wrong S3 point's truth |
| `GIVE_UP_MIN` | emergency 240, planned 480 | `execute.py` | assumption |
| `report_k` and report weights | 4; phone yes/no 0.5, arrival 1, closed or refused 0.25 | `assumptions.py` | assumption (future work) |

## Interface

`interface.py` documents the contract as it stands (`Case`, `Step`, the event columns and outcome vocabulary):

- `world.cases(seed, states, n)` rows have exactly the `Case` fields.
- Baselines: `policies_baseline.POLICIES[name](case_dict, ctx)` with `ctx = policies_baseline.context()`.
- App policies: `policies_app.POLICIES[name].choose(Case(**case_dict), {"app": AppAdapter()})` returns `Step`s;
  `run.app_steps` turns them into step dicts.
- `execute.run_case(case_dict, step_dicts, execute.index_truth(truth), listed, knobs)` returns the event rows;
  `execute.execute(cases, steps, truth, scenario=, policy=, run_id=, knobs=)` does the same for a whole case table.
- Event log columns: `run_id, scenario, seed, policy, case_id, step, kind, facility_id, t_min, outcome`; `t_min`
  is minutes since the case started.

## Files

| File | Owner | What |
| --- | --- | --- |
| `world.py` | lead | cases, truth per scenario (S0-high/S0-low, S1-S3), listing, knobs |
| `execute.py` | lead | the step loop, the only reader of the truth |
| `policies_baseline.py` | lead | nearest, nearest + call first, best on paper |
| `interface.py` | shared | the contract |
| `policies_app.py`, `app_adapter.py` | tm-AA2026 | the app as a policy, via the shipped engine and state packs |
| `run.py` | tm-AA2026 | runner, metrics, seed-bootstrap intervals, knob sweep |
| `replay.py`, `replay_template.html` | tm-AA2026 | one patient, the policies side by side (local HTML) |
| `reports.py`, `assumptions.py` | tm-AA2026 | field reports and their constants (future work) |
| `tests/` | both | world, executor, baselines, policies, runner, replay |
