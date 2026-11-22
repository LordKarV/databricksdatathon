# sim/: a simulated referral world (issue #92)

**Simulated. Not field results.** This folder builds a world in which the true answers are known, sends simulated
patients through it under several referral policies, and measures what happens. It answers one question: does the
app get more patients to care in time than sending them to the nearest listing, or to the "best" listing on paper?
Results appear only in the notebook appendix, `submission/02_simulation.ipynb`, labelled simulated. This README gives
the method, not results. Nothing here ships in the app runtime.

## Honesty rules (from #92)

1. **Policies never see the truth.** They see only what the app or a directory would show. Only the executor and the
   metrics read the truth tables. `sim/tests/test_policies.py` fails if a policy module imports `sim.truth`, names
   the truth tables, or is handed a truth object.
2. **More than one truth.** Every result is reported for each scenario. S1 is circular and is never shown alone.
3. **No TEST labels anywhere** (#51). Only `model/gold/v3/dev_labels.json` is read; a test checks that no module names
   the TEST files.
4. **Every output says "simulated":** a `label` column in every table, "SIMULATED" in every printed table and chart.
5. **Reproducible:** seeded; runs locally and as a Databricks notebook.

## Scenarios (`truth.py`)

One truth table per scenario and seed, `sim/out/truth/<scenario>_<seed>.parquet`, columns `unique_id, service,
exists, offers, phone_ok, open_now_p, accept_p, true_lat, true_lon`, one row per facility and app service.

| Scenario | P(offers) | Location |
| --- | --- | --- |
| S0 "text says nothing" | base rate by service x operator group (public by derived/v2 operator or by name, else private or unknown), from DEV labels; no text feature, no model p | map point |
| S1 "model is right" | derived/v2 `p` | map point |
| S2 "from labels" | DEV label rate by service x evidence grade (derived/v1 grades; `none` if unmentioned) x attribution (a sentence naming the service attributed to another facility, derived/v1 claims) | map point |
| S3 "data as bad as the audit says" | S2, but a pair whose only sentences are attributed elsewhere never offers, and one with its own sentences takes the rate of the same grade without the attribution | records flagged `coords_pin_conflict_gt50km` sit at `alt_lat/alt_lon` (else the PIN centroid) |

Rates from labels use decided DEV labels only (confirmed vs contradicted; `no_info` is missing), weighted
1 / `inclusion_prob` as in `model/gold/v3/merge_labels.py`. **Shrinkage:** a cell's weighted rate `r_c` with Kish
effective n `n_c` becomes `(n_c r_c + k_cell r_s) / (n_c + k_cell)`, where the service rate `r_s` is itself shrunk
toward the all-service rate with `k_service`; a cell with no label takes `r_s`. Unmentioned pairs outside the DEV
`no_mention` frame (not public by name, under 6 services claimed) have no label at all and take an assumed rate.
`test_truth.py` checks that S2's expected rates reproduce the weighted DEV label rate per service within two
standard errors.

All scenarios: `exists` ~ Bernoulli(derived/v1 `facility_trust.existence_score`); `phone_ok` is False with no
listed phone or a number shared by directories (`record_trust` flag `official_phone_is_directory`, or listed for 3+
records), else Bernoulli(`phone_ok_p`); `open_now_p` and `accept_p` as below. Every scenario uses the same uniform
draws per seed, so scenarios differ only in their rates.

**Caveat on S2 and S3 (#92 review):** they come from the DEV labels the v2 model's calibration step was fitted on,
and S3 penalises other-facility sentences the engine already drops. Both favour the app by construction. S0 is the
scenario where the app can lose.

## Policies

Every policy tries at most 3 facilities (`N_OPTIONS` in `app/facts/engine.py`), then escalates to 108.

| Policy | What it sees and does |
| --- | --- |
| `app` | the product as shipped: `Engine.plan` (derived/v2) with mobile data, the saved state pack without; phones every option first (the app says "We will phone before going" for every option); field reports off |
| `app_offline` | the state pack only, read as `app/static/pack.js` does (nearest PIN's list, sorted by straight-line km) |
| `nearest` | the 3 nearest listings naming the service, straight line, no call |
| `nearest_call_first` | the same, phoning each first: separates the ranking from calling ahead |
| `best_on_paper` | the 3 highest model p in the patient's state, ignoring distance, no call |
| `app_plus_reports` | future work: the app re-ranked with a Beta(p k, (1 - p) k) update from field reports (`reports.py`) |
| planner route | future work, after #77 |

`app_adapter.py` is the thin layer to the shipped app. It caches `Engine.plan` per (origin rounded to 1e-3 degree,
service), since plans do not depend on truth; `test_policies.py` checks it returns the engine's options unchanged.

## Metrics (`run.py`)

`sim/out/metrics.parquet`, one row per policy x scenario x state (and `ALL`) x service x urgency: treated within the
window (share), median minutes to care, wasted trips per case, calls per case, unsafe first stop (the first place
travelled to does not exist or does not offer the service), gave up. Each has a 90% seed-bootstrap interval
(`_lo`, `_hi`). `sim/out/sensitivity.parquet`: app minus `nearest_call_first`, treated in window, with each swept
assumption at low and high (others at the middle), and where the verdict changes.

Common random numbers: within a seed every policy and scenario meets the same patients and the same coin flips at
the same facility for the same patient (a hash of case, facility and purpose).

## Run

```bash
.venv-app/bin/python app/facts/build.py                                   # once; run.py builds it if missing
.venv-app/bin/python -m sim.run --seeds 20 --cases-per-seed 200           # S0-S3, Bihar + UP, dialysis + trauma
.venv-app/bin/python -m pytest sim/tests -q
.venv-app/bin/python submission/build_sim_notebook.py                     # writes and runs the appendix notebook
```

Options: `--scenarios`, `--states`, `--services`, `--out`, `--boot`, `--no-sweep`, `--with-reports` (network data:
`sim/out/network/facility_reports.parquet` and `district_summary.parquet`, future work), `--include-planner`.
`sim/out/` is git-ignored. On Databricks the notebook takes seeds and cases from widgets and writes to
`/Volumes/workspace/referral_saathi/uploads/sim`.

## Interface for sim/world.py, sim/execute.py, sim/policies_baseline.py

Types live in `interface.py` (`Case`, `Step`, `Truth`, `EVENT_COLUMNS`, the outcome vocabulary). `run.py` uses
these names when the modules exist, and the temporary stand-ins `_stub_execute.py` and `_stub_baselines.py` (with
a printed note) when they do not:

- `sim.world.generate_cases(seed, n, states, services, wave=1) -> list[Case]`
- `sim.execute.run_case(case, steps, truth, a: Assumptions) -> list[dict]` with keys `step, kind, facility_id,
  t_min, outcome`; `t_min` is minutes since the case started
- `sim.policies_baseline.POLICIES: dict[str, Policy]`, optional `make_context(states, services) -> dict`

## Assumptions (`assumptions.py`)

Every constant lives in `assumptions.py`. Each is an assumption unless the basis says otherwise.

| Name | Value | Basis |
| --- | --- | --- |
| `phone_ok_p` | 0.85 (swept 0.60 / 0.98) | assumption: own listed numbers that reach the facility |
| `phone_shared_min` | 3 | assumption; the app's shared-number warning threshold |
| `open_now_p` | 0.95 with a 24x7 claim (derived/v2 `is_24x7`), else 0.60 (swept 0.80/0.40 and 0.99/0.85) | assumption (#92) |
| `accept_p` | emergency 0.90, planned 0.75 (swept 0.70/0.50 and 0.98/0.95) | assumption |
| `exists` | Bernoulli(existence_score); 0.90 if missing | data; fallback assumed |
| `no_mention_outside_frame_p` | 0.05 | assumption: no DEV label covers these pairs |
| `k_cell`, `k_service` | 4, 4 (effective n) | assumption: Beta shrinkage of thin label cells |
| `wrong_yes_p` | 0.10 (swept 0.00 / 0.30): P(the phone says yes, given it cannot treat) | assumption |
| `wrong_no_p` | 0.05: P(the phone says no, given it could treat) | assumption |
| `call_minutes` | 5 | assumption |
| `give_up_minutes` | 480 | assumption |
| treatment window | trauma 60 min (kb/pathways `major_trauma` stabilise, itself assumed); dialysis 120 min (engine `WINDOW` for scheduled care) | stub world |
| `has_data_p`, `has_signal_p` | 0.80, 0.90 | assumption (stub world only) |
| `report_k` and report weights | 4; phone yes/no 0.5, arrival 1, closed or refused 0.25 | assumption (future work) |

## Files

| File | Owner | What |
| --- | --- | --- |
| `interface.py`, `assumptions.py` | shared | types, contract, every constant |
| `truth.py`, `policies_app.py`, `app_adapter.py`, `reports.py`, `run.py`, `tests/` | tm-AA2026 | truth, app policies, reports, runner |
| `world.py`, `execute.py`, `policies_baseline.py` | tm-Art4v or the lead | not yet written |
| `_stub_execute.py`, `_stub_baselines.py` | temporary | stand-ins until the three above land; delete then |
