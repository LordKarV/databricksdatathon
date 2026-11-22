# Validation suite

Re-runnable data-quality checks for Bharosa. Each area folder holds one auditor's `checks.py`
(functions `check_<name>() -> dict(name, status, metric, threshold, detail, examples)`), its outputs and its
FINDINGS. `run_all.py` runs all of them and writes one scorecard.

## Run

```
.venv-viz/bin/python validation/run_all.py --skip-network          # everything, no warehouse or web calls
.venv-viz/bin/python validation/run_all.py --area integrity,labels  # some areas
.venv-viz/bin/python validation/contracts_v2.py --selftest          # contract code on a synthetic v2
```

Flags: `--area NAME` (repeatable or comma separated; folder names plus `contracts_v2`), `--skip-network`,
`--timeout S` per check (default 1200), `--jobs N` areas at once (default 2).

Outputs: `out/scorecard.json` (`meta` plus one row per check: area, check, status, metric, threshold,
detail, up to 5 examples, seconds), `out/scorecard.md`, and `out/logs/<area>.log` (whatever the checks
printed). Exit code 1 when any check fails, 0 otherwise.

## How it runs

- Discovery: every `validation/*/checks.py`, plus `validation/contracts_v2.py`. Every `check_*` function a
  module defines runs, in source order (a later check may read an earlier one's output file).
- Each area runs in its own worker process, from the repo root. Areas import sibling modules with the same
  names (`common`, `samples`), so they cannot share one interpreter.
- Timeout: the parent kills a worker whose check runs past `--timeout`, records that check as `not_run`
  ("timeout"), and starts a new worker at the next check. A worker that dies mid-check records `fail`.
- `--skip-network` blocks the network in the workers: subprocess calls to `sql.sh`, `gh`, `curl`, `wget` and
  `databricks` return exit code 1, outbound socket connects raise `OSError`, and retry sleeps are skipped
  after a block. The checks' own error handling then reports the network part as not run. Checks that read
  a saved fetch (labels `url_recheck`, web_facts `site_liveness`, labels `live_table_ids`) still run from
  their cached files.
- Status: `pass`, `warn`, `fail` or `not_run`. A result whose metric is "not run" is recorded as `not_run`
  even when the check returned `warn` (`reported_status` keeps the original). A crash is `fail`, except
  when the network block caused it (`not_run`).
- The privacy_licence checks call read-only `git` (`ls-files`, `cat-file`, `show`); nothing writes to git.
- Checks write their own side outputs into their area's `out/` folder, as they did when first run.

## derived/v2 contract (contracts_v2.py)

Every check returns `not_run` with the reason until `derived/v2/facility_service_scores.parquet` and
`derived/v2/model_card.json` both exist and parse. The module docstring states the contract; in short:

| check | rule |
|---|---|
| v2_keys_unique | (unique_id, service_id) non-null and unique |
| v2_coverage | every usable facility except the 12 exclude_review records x the 36 taxonomy services; no unknown service or id |
| v2_excluded_not_scored | no exclude_review (veterinary) record is scored |
| v2_probabilities | p, lo, hi, p_location, p_exists in [0, 1]; lo <= p <= hi |
| v2_logit_identity | base + sum(contributions.points) == logit to 1e-9 (sigmoid(logit) vs p reported as warn) |
| v2_evidence_ids_resolve | every cited id is a derived/v1 claim_id, a witness_id or evidence_id, or a claim_atoms atom_id of a known claim |
| v2_bands | band in likely / not_verified / unlikely; likely meets every likely threshold in model_card.json; unlikely has p <= the unlikely threshold unless band_reason names another rule |
| v2_not_observable_zero | contributions that are not_observable (by field, or because every cited witness is) have points exactly 0 |
| v2_operator | operator in public / private / unknown |
| v2_model_version | one non-null model_version equal to model_card.json's; as_of non-null |
| v2_witness_quotes | seeded sample (seed 20261121, up to 40 per source): quote verbatim in the claim, crawl page, raw record or list file it cites; witness_id unique |
| v2_restricted_lists | NABH, NMC and MoHFW trauma rows only on usable facilities, at most 50% of a list, and no other v2 file names 20+ list entries outside per-facility rows |

Contributions are read from a `contributions` column (list of structs with `term`, `points`,
`evidence_ids`) or from `derived/v2/contributions.parquet` in long form. If #11 publishes another shape, the
checks fail with the column names they found; change the reader, not the rule.

## Adding a check

Add a `check_<name>()` function to an area's `checks.py` that returns the dict above, with status one of
pass / warn / fail / not_run. `run_all.py` picks it up with no registration.
